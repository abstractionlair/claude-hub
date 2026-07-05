"""GitHub API client for file operations."""

import base64
import json
import os
import urllib.request
import urllib.error
from typing import Optional


class GitHubError(Exception):
    """Base exception for GitHub operations."""
    pass


class GitHubClient:
    """
    Client for GitHub API operations using urllib (no extra dependencies).

    Uses a Personal Access Token (PAT) from GITHUB_PAT env var for auth.
    """

    API_BASE = "https://api.github.com"

    def __init__(self, pat: Optional[str] = None):
        self.pat = pat or os.environ.get("GITHUB_PAT", "")

    def _make_request(self, url: str) -> dict:
        """
        Make an authenticated GET request to the GitHub API.

        Args:
            url: Full URL to request.

        Returns:
            Parsed JSON response as dict.

        Raises:
            GitHubError: On any request failure.
        """
        headers = {
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "claude-hub",
        }

        if self.pat:
            headers["Authorization"] = f"Bearer {self.pat}"

        req = urllib.request.Request(url, headers=headers)

        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            if e.code == 404:
                raise GitHubError(f"Not found: {url}")
            elif e.code == 401:
                raise GitHubError("Authentication failed. Check GITHUB_PAT.")
            elif e.code == 403:
                raise GitHubError(f"Access denied (rate limit or permissions): {body}")
            else:
                raise GitHubError(f"GitHub API error {e.code}: {body}")
        except urllib.error.URLError as e:
            raise GitHubError(f"Network error: {e.reason}")
        except Exception as e:
            raise GitHubError(f"Unexpected error: {e}")

    def read_file(
        self,
        owner: str,
        repo: str,
        path: str,
        ref: str = "main",
    ) -> dict:
        """
        Read a file from a GitHub repository.

        Args:
            owner: Repository owner (user or org).
            repo: Repository name.
            path: File path within the repository.
            ref: Git ref (branch, tag, or commit SHA).

        Returns:
            Dict with content, path, sha, size keys.

        Raises:
            GitHubError: On any failure.
        """
        url = f"{self.API_BASE}/repos/{owner}/{repo}/contents/{path}?ref={ref}"
        data = self._make_request(url)

        if data.get("type") != "file":
            raise GitHubError(
                f"Path is not a file (type: {data.get('type')}): {path}"
            )

        # Decode base64 content
        encoded = data.get("content", "")
        try:
            content = base64.b64decode(encoded).decode("utf-8")
        except Exception as e:
            raise GitHubError(f"Error decoding file content: {e}")

        return {
            "content": content,
            "path": data.get("path", path),
            "sha": data.get("sha", ""),
            "size": data.get("size", 0),
        }
