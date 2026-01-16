"""Vault search API endpoints."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.dependencies import get_vault_search_service, verify_token
from app.exceptions import SearchError, ValidationError
from app.models.vault_search import SearchRequest, SearchResponse
from app.utils.error_handling import format_exception_for_response

if TYPE_CHECKING:
    from app.services.vault_search import VaultSearchService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/vault", tags=["vault"], dependencies=[Depends(verify_token)])


@router.post("/search", response_model=SearchResponse)
async def search_vault(
    request: SearchRequest,
    show_hidden: Annotated[
        bool,
        Query(description="Include dotfiles", alias="showHidden"),
    ] = False,
    vault_search: VaultSearchService = Depends(get_vault_search_service),
) -> SearchResponse:
    """Search vault contents using ripgrep."""
    query_length = len(request.query) if isinstance(request.query, str) else 0

    try:
        return await vault_search.search(request, show_hidden=show_hidden)
    except ValidationError as exc:
        logger.warning(
            "Invalid vault search request",
            extra={
                "query_length": query_length,
                "folder": request.folder,
                "show_hidden": show_hidden,
                "reason": exc.context.get("reason"),
            },
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=format_exception_for_response(exc),
        ) from exc
    except FileNotFoundError as exc:
        logger.info(
            "Search folder not found",
            extra={
                "query_length": query_length,
                "folder": request.folder,
                "error": str(exc),
            },
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Folder not found",
        ) from exc
    except SearchError as exc:
        logger.exception(
            "Vault search failed",
            extra={
                "query_length": query_length,
                "folder": request.folder,
                **exc.context,
            },
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=format_exception_for_response(exc),
        ) from exc
    except Exception as exc:
        logger.exception(
            "Unexpected error searching vault",
            extra={
                "query_length": query_length,
                "folder": request.folder,
                "error_type": type(exc).__name__,
            },
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unexpected error searching vault",
        ) from exc
