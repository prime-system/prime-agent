"""Read-only vault browser API endpoints."""

from __future__ import annotations

import logging
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response, status

from app.dependencies import get_vault_browser_service, verify_token
from app.exceptions import ValidationError, VaultError
from app.models.vault_browser import FileItem, FileMetadata, FolderListingResponse, Item
from app.services.vault_browser import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE, VaultBrowserService
from app.utils.error_handling import format_exception_for_response
from app.utils.pagination import PaginationError, paginate_items

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/vault", tags=["vault"], dependencies=[Depends(verify_token)])

SortField = Literal["name", "modifiedAt", "size"]
SortOrder = Literal["asc", "desc"]


class RangeNotSatisfiableError(ValueError):
    """Raised when a Range header is invalid or unsatisfiable."""


def parse_include_types(include: str) -> set[Literal["file", "folder"]]:
    """Parse include types query parameter."""
    parts = {part.strip().lower() for part in include.split(",") if part.strip()}
    if not parts:
        msg = "Include parameter must specify at least one type"
        raise ValidationError(msg, context={"include": include})

    mapping: dict[str, Literal["file", "folder"]] = {"files": "file", "folders": "folder"}
    invalid = sorted(part for part in parts if part not in mapping)
    if invalid:
        msg = "Include parameter contains invalid values"
        raise ValidationError(msg, context={"include": include, "invalid": invalid})

    return {mapping[part] for part in parts}


def normalize_sort_field(sort_field: str) -> SortField:
    """Normalize the sort field string."""
    normalized = sort_field.strip()
    if normalized in {"modified_at", "modifiedAt"}:
        return "modifiedAt"
    if normalized == "name":
        return "name"
    if normalized == "size":
        return "size"
    msg = "Sort field must be one of name, modifiedAt, size"
    raise ValidationError(msg, context={"sort": sort_field})


def parse_range_header(range_header: str, file_size: int) -> tuple[int, int]:
    """Parse a single HTTP Range header into start/end bytes."""
    if file_size <= 0:
        msg = "File is empty"
        raise RangeNotSatisfiableError(msg)

    if not range_header.startswith("bytes="):
        msg = "Range unit must be bytes"
        raise RangeNotSatisfiableError(msg)

    raw_range = range_header.removeprefix("bytes=").strip()
    if "," in raw_range:
        msg = "Multiple ranges are not supported"
        raise RangeNotSatisfiableError(msg)

    start_str, end_str = raw_range.split("-", 1)

    if start_str == "":
        if not end_str:
            msg = "Range suffix is missing"
            raise RangeNotSatisfiableError(msg)
        try:
            suffix_length = int(end_str)
        except ValueError as exc:
            msg = "Range suffix must be an integer"
            raise RangeNotSatisfiableError(msg) from exc
        if suffix_length <= 0:
            msg = "Range suffix must be positive"
            raise RangeNotSatisfiableError(msg)
        if suffix_length >= file_size:
            return 0, file_size - 1
        return file_size - suffix_length, file_size - 1

    try:
        start = int(start_str)
    except ValueError as exc:
        msg = "Range start must be an integer"
        raise RangeNotSatisfiableError(msg) from exc
    if start < 0:
        msg = "Range start must be non-negative"
        raise RangeNotSatisfiableError(msg)
    if start >= file_size:
        msg = "Range start out of bounds"
        raise RangeNotSatisfiableError(msg)

    if end_str == "":
        return start, file_size - 1

    try:
        end = int(end_str)
    except ValueError as exc:
        msg = "Range end must be an integer"
        raise RangeNotSatisfiableError(msg) from exc
    if end < start:
        msg = "Range end must be >= start"
        raise RangeNotSatisfiableError(msg)

    if end >= file_size:
        end = file_size - 1

    return start, end


def sort_items(items: list[Item], sort_field: SortField, order: SortOrder) -> list[Item]:
    """Sort folder items by the requested field."""
    reverse = order == "desc"

    if sort_field == "name":
        return sorted(items, key=lambda item: item.name.lower(), reverse=reverse)

    if sort_field == "modifiedAt":
        return sorted(items, key=lambda item: item.modified_at, reverse=reverse)

    def size_key(item: Item) -> int:
        if isinstance(item, FileItem):
            return item.size
        return 0

    return sorted(items, key=size_key, reverse=reverse)


@router.get("/folders", response_model=FolderListingResponse)
async def list_folder_children(
    path: Annotated[str, Query(description="Canonical API path of folder")],
    response: Response,
    limit: Annotated[
        int,
        Query(
            description="Items per page",
            ge=1,
            le=MAX_PAGE_SIZE,
        ),
    ] = DEFAULT_PAGE_SIZE,
    cursor: Annotated[str | None, Query(description="Opaque pagination cursor")] = None,
    sort: Annotated[str, Query(description="Sort field")] = "name",
    order: Annotated[SortOrder, Query(description="Sort order")] = "asc",
    include: Annotated[
        str,
        Query(description="Item types to include (folders,files)"),
    ] = "folders,files",
    show_hidden: Annotated[
        bool,
        Query(description="Include dotfiles", alias="showHidden"),
    ] = False,
    if_none_match: Annotated[str | None, Header(alias="If-None-Match")] = None,
    vault_browser: VaultBrowserService = Depends(get_vault_browser_service),
) -> FolderListingResponse | Response:
    """List contents of a folder with pagination and filtering."""
    try:
        include_types = parse_include_types(include)
        sort_field = normalize_sort_field(sort)

        items = await vault_browser.list_folder(
            api_path=path,
            show_hidden=show_hidden,
            include_types=include_types,
        )

        etag = vault_browser.generate_folder_etag(path, items, show_hidden)
        if if_none_match == etag:
            return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers={"ETag": etag})

        items = sort_items(items, sort_field, order)
        page_items, next_cursor = paginate_items(items, limit, cursor)

        response.headers["ETag"] = etag

        return FolderListingResponse.model_validate(
            {
                "path": vault_browser.normalize_api_path(path),
                "items": page_items,
                "next_cursor": next_cursor,
                "has_more": next_cursor is not None,
            }
        )
    except ValidationError as exc:
        logger.warning(
            "Invalid vault folder listing request",
            extra={
                "path": path,
                **exc.context,
            },
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=format_exception_for_response(exc),
        ) from exc
    except VaultError as exc:
        status_code = status.HTTP_404_NOT_FOUND
        if exc.context.get("reason") == "symlink_not_allowed":
            status_code = status.HTTP_404_NOT_FOUND
        logger.warning(
            "Vault folder listing blocked",
            extra=exc.context,
        )
        raise HTTPException(
            status_code=status_code,
            detail=format_exception_for_response(exc),
        ) from exc
    except PaginationError as exc:
        logger.warning(
            "Invalid pagination cursor",
            extra={
                "path": path,
                "cursor": cursor,
                "error": str(exc),
            },
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "InvalidCursor", "message": str(exc)},
        ) from exc
    except FileNotFoundError as exc:
        logger.info(
            "Folder not found",
            extra={
                "path": path,
                "error": str(exc),
            },
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Folder not found",
        ) from exc
    except NotADirectoryError as exc:
        logger.info(
            "Path is not a folder",
            extra={
                "path": path,
                "error": str(exc),
            },
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Path is not a folder",
        ) from exc
    except Exception as exc:
        logger.exception(
            "Unexpected error listing folder",
            extra={
                "path": path,
                "error_type": type(exc).__name__,
            },
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unexpected error listing folder",
        ) from exc


@router.get("/files/meta", response_model=FileMetadata)
async def get_file_metadata(
    path: Annotated[str, Query(description="Canonical API path of file")],
    response: Response,
    if_none_match: Annotated[str | None, Header(alias="If-None-Match")] = None,
    vault_browser: VaultBrowserService = Depends(get_vault_browser_service),
) -> FileMetadata | Response:
    """Get metadata for a file."""
    try:
        metadata = await vault_browser.get_file_metadata(path)
        if if_none_match == metadata.etag:
            return Response(
                status_code=status.HTTP_304_NOT_MODIFIED,
                headers={"ETag": metadata.etag},
            )

        response.headers["ETag"] = metadata.etag

        return metadata
    except ValidationError as exc:
        logger.warning(
            "Invalid file metadata request",
            extra={
                "path": path,
                **exc.context,
            },
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=format_exception_for_response(exc),
        ) from exc
    except VaultError as exc:
        logger.warning(
            "File metadata access blocked",
            extra=exc.context,
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=format_exception_for_response(exc),
        ) from exc
    except FileNotFoundError as exc:
        logger.info(
            "File not found",
            extra={
                "path": path,
                "error": str(exc),
            },
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="File not found",
        ) from exc
    except IsADirectoryError as exc:
        logger.info(
            "Path is a folder",
            extra={
                "path": path,
                "error": str(exc),
            },
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Path is a folder",
        ) from exc
    except Exception as exc:
        logger.exception(
            "Unexpected error retrieving file metadata",
            extra={
                "path": path,
                "error_type": type(exc).__name__,
            },
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unexpected error retrieving file metadata",
        ) from exc


@router.get("/files/content")
async def get_file_content(
    path: Annotated[str, Query(description="Canonical API path of file")],
    range_header: Annotated[str | None, Header(alias="Range")] = None,
    if_range: Annotated[str | None, Header(alias="If-Range")] = None,
    if_none_match: Annotated[str | None, Header(alias="If-None-Match")] = None,
    vault_browser: VaultBrowserService = Depends(get_vault_browser_service),
) -> Response:
    """Get file content with Range request support."""
    try:
        fs_path, metadata = await vault_browser.get_file_info(path)
        etag = metadata.etag

        if if_none_match == etag:
            return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers={"ETag": etag})

        if range_header and if_range and if_range != etag:
            range_header = None

        file_size = metadata.size
        media_type = metadata.mime_type or "application/octet-stream"

        if range_header:
            start, end = parse_range_header(range_header, file_size)
            length = end - start + 1
            content = await vault_browser.read_file_range(fs_path, start, length)

            headers = {
                "Content-Range": f"bytes {start}-{end}/{file_size}",
                "Accept-Ranges": "bytes",
                "ETag": etag,
                "Content-Length": str(length),
            }
            return Response(
                content=content,
                status_code=status.HTTP_206_PARTIAL_CONTENT,
                headers=headers,
                media_type=media_type,
            )

        content = await vault_browser.read_file_range(fs_path, 0, file_size)
        headers = {
            "Accept-Ranges": "bytes",
            "ETag": etag,
            "Content-Length": str(file_size),
        }
        return Response(content=content, headers=headers, media_type=media_type)
    except RangeNotSatisfiableError as exc:
        logger.info(
            "Range request not satisfiable",
            extra={
                "path": path,
                "range": range_header,
                "error": str(exc),
            },
        )
        return Response(
            status_code=status.HTTP_416_RANGE_NOT_SATISFIABLE,
            headers={"Content-Range": f"bytes */{metadata.size}"},
        )
    except ValidationError as exc:
        logger.warning(
            "Invalid file content request",
            extra={
                "path": path,
                **exc.context,
            },
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=format_exception_for_response(exc),
        ) from exc
    except VaultError as exc:
        logger.warning(
            "File content access blocked",
            extra=exc.context,
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=format_exception_for_response(exc),
        ) from exc
    except FileNotFoundError as exc:
        logger.info(
            "File not found",
            extra={
                "path": path,
                "error": str(exc),
            },
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="File not found",
        ) from exc
    except IsADirectoryError as exc:
        logger.info(
            "Path is a folder",
            extra={
                "path": path,
                "error": str(exc),
            },
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Path is a folder",
        ) from exc
    except Exception as exc:
        logger.exception(
            "Unexpected error reading file content",
            extra={
                "path": path,
                "error_type": type(exc).__name__,
            },
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unexpected error reading file content",
        ) from exc
