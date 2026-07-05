"""Pydantic models for file storage and GitHub API endpoints."""

from pydantic import BaseModel
from typing import Optional, List


# -----------------------------------------------------------------------------
# File Storage Models
# -----------------------------------------------------------------------------


class FilesReadParams(BaseModel):
    """Parameters for reading a file."""
    path: str


class FilesReadResponse(BaseModel):
    """Response from reading a file."""
    content: str
    path: str


class FilesWriteParams(BaseModel):
    """Parameters for writing a file."""
    path: str
    content: str


class FilesWriteResponse(BaseModel):
    """Response from writing a file."""
    path: str
    size: int


class FilesListParams(BaseModel):
    """Parameters for listing files."""
    path: str = ""
    recursive: bool = False


class FileEntry(BaseModel):
    """A single file/directory entry."""
    name: str
    type: str  # "file" or "dir"
    size: int
    modified: str


class FilesListResponse(BaseModel):
    """Response from listing files."""
    entries: List[FileEntry]
    path: str


class FilesAppendParams(BaseModel):
    """Parameters for appending to a file."""
    path: str
    content: str


class FilesAppendResponse(BaseModel):
    """Response from appending to a file."""
    path: str


class FilesSearchParams(BaseModel):
    """Parameters for searching files."""
    query: str
    path: str = ""
    glob_pattern: str = "*.md"


class SearchResult(BaseModel):
    """A single search result."""
    file: str
    line: int
    content: str


class FilesSearchResponse(BaseModel):
    """Response from searching files."""
    results: List[SearchResult]
    query: str


# -----------------------------------------------------------------------------
# GitHub Models
# -----------------------------------------------------------------------------


class GitHubFileReadParams(BaseModel):
    """Parameters for reading a file from GitHub."""
    owner: str
    repo: str
    path: str
    ref: str = "main"


class GitHubFileReadResponse(BaseModel):
    """Response from reading a GitHub file."""
    content: str
    path: str
    sha: str
    size: int
