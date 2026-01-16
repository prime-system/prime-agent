"""Models for vault search API."""

from __future__ import annotations

from pydantic import BaseModel, Field


class SearchRequest(BaseModel):
    """Request body for vault search."""

    query: str = Field(..., description="Search query")
    regex: bool = Field(False, description="Treat query as regex")
    case_sensitive: bool = Field(False, description="Use case-sensitive matching")
    folder: str | None = Field(None, description="Vault API folder prefix")
    globs: list[str] | None = Field(None, description="Ripgrep glob filters")
    max_results: int = Field(200, description="Maximum matches to return")
    context_lines: int = Field(0, description="Context lines around matches")


class SearchMatch(BaseModel):
    """Single search result match."""

    path: str = Field(..., description="Vault-relative file path")
    line: int = Field(..., description="Line number of match")
    column: int = Field(..., description="Column number of match")
    text: str = Field(..., description="Matched line text")
    context_before: list[str] = Field(default_factory=list, description="Context lines before")
    context_after: list[str] = Field(default_factory=list, description="Context lines after")


class SearchResponse(BaseModel):
    """Response payload for vault search."""

    query: str = Field(..., description="Search query")
    results: list[SearchMatch] = Field(..., description="Search results")
    total_matches: int = Field(..., description="Total matches returned")
    truncated: bool = Field(..., description="Whether results were truncated")
    duration_ms: int = Field(..., description="Search duration in milliseconds")
