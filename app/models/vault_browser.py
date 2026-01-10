"""Models for vault browser API responses."""

from __future__ import annotations

from datetime import datetime  # noqa: TC003
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class BaseItem(BaseModel):
    """Common fields for vault items."""

    name: str = Field(..., description="Item name")
    path: str = Field(..., description="Canonical API path")
    modified_at: datetime = Field(..., alias="modifiedAt", description="Last modified timestamp")

    model_config = ConfigDict(populate_by_name=True)


class FileMetadata(BaseItem):
    """Metadata for a file."""

    size: int = Field(..., description="Size in bytes")
    mime_type: str | None = Field(None, alias="mimeType", description="MIME type")
    etag: str = Field(..., description="ETag for file content")


class FileItem(FileMetadata):
    """File item returned in folder listings."""

    type: Literal["file"] = Field("file", description="Item type")


class FolderItem(BaseItem):
    """Folder item returned in folder listings."""

    type: Literal["folder"] = Field("folder", description="Item type")
    child_count: int | None = Field(None, alias="childCount", description="Child item count")


Item = FileItem | FolderItem


class FolderListingResponse(BaseModel):
    """Response for folder listing endpoints."""

    path: str = Field(..., description="Canonical API path")
    items: list[Item] = Field(..., description="Child items")
    next_cursor: str | None = Field(
        None,
        alias="nextCursor",
        description="Opaque cursor for the next page (if any)",
    )
    has_more: bool = Field(..., alias="hasMore", description="Whether more items exist")

    model_config = ConfigDict(populate_by_name=True)
