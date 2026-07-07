"""File storage manager for persistent storage operations."""

import os
import re
import subprocess
from pathlib import Path
from typing import List, Dict, Optional
from datetime import datetime


class StorageError(Exception):
    """Base exception for storage operations."""
    pass


class PathTraversalError(StorageError):
    """Raised when a path attempts to escape the storage root."""
    pass


class StorageManager:
    """
    Manages file operations within a sandboxed storage root.

    All paths are resolved relative to the storage root. Any attempt
    to access paths outside the root (via .., symlinks, etc.) is rejected.
    """

    def __init__(self, storage_root: Optional[str] = None):
        root = storage_root or os.environ.get("STORAGE_ROOT", "/storage")
        self.storage_root = Path(root).resolve()
        self.storage_root.mkdir(parents=True, exist_ok=True)

    def _resolve_path(self, path: str) -> Path:
        """
        Resolve a relative path against the storage root.

        Raises PathTraversalError if the resolved path is outside the storage root.
        """
        # Reject paths with .. components before resolution
        if ".." in Path(path).parts:
            raise PathTraversalError(
                f"Path contains '..': {path}"
            )

        resolved = (self.storage_root / path).resolve()

        # Verify the resolved path is within the storage root
        try:
            resolved.relative_to(self.storage_root)
        except ValueError:
            raise PathTraversalError(
                f"Path resolves outside storage root: {path}"
            )

        return resolved

    def read_file(self, path: str) -> str:
        """
        Read file contents.

        Args:
            path: Path relative to storage root.

        Returns:
            File contents as string.

        Raises:
            PathTraversalError: If path escapes storage root.
            StorageError: If file doesn't exist or can't be read.
        """
        resolved = self._resolve_path(path)

        if not resolved.exists():
            raise StorageError(f"File not found: {path}")
        if not resolved.is_file():
            raise StorageError(f"Not a file: {path}")

        try:
            return resolved.read_text(encoding="utf-8")
        except Exception as e:
            raise StorageError(f"Error reading file: {e}")

    def write_file(self, path: str, content: str) -> str:
        """
        Write or create a file.

        Creates parent directories as needed.

        Args:
            path: Path relative to storage root.
            content: Content to write.

        Returns:
            Absolute path of the written file.

        Raises:
            PathTraversalError: If path escapes storage root.
            StorageError: If file can't be written.
        """
        resolved = self._resolve_path(path)

        try:
            resolved.parent.mkdir(parents=True, exist_ok=True)
            resolved.write_text(content, encoding="utf-8")
            return str(resolved)
        except PathTraversalError:
            raise
        except Exception as e:
            raise StorageError(f"Error writing file: {e}")

    def list_files(
        self, path: str = "", recursive: bool = False
    ) -> List[Dict]:
        """
        List directory contents.

        Args:
            path: Directory path relative to storage root (default: root).
            recursive: Whether to list recursively.

        Returns:
            List of dicts with name, type, size, modified fields.

        Raises:
            PathTraversalError: If path escapes storage root.
            StorageError: If directory doesn't exist.
        """
        resolved = self._resolve_path(path)

        if not resolved.exists():
            raise StorageError(f"Directory not found: {path}")
        if not resolved.is_dir():
            raise StorageError(f"Not a directory: {path}")

        entries = []

        if recursive:
            iterator = resolved.rglob("*")
        else:
            iterator = resolved.iterdir()

        for item in sorted(iterator, key=lambda p: p.name):
            try:
                stat = item.stat()
                # Make path relative to the resolved dir for recursive,
                # or just use name for non-recursive
                if recursive:
                    display_name = str(item.relative_to(resolved))
                else:
                    display_name = item.name

                entries.append({
                    "name": display_name,
                    "type": "dir" if item.is_dir() else "file",
                    "size": stat.st_size if item.is_file() else 0,
                    "modified": datetime.fromtimestamp(
                        stat.st_mtime
                    ).isoformat(),
                })
            except (OSError, ValueError):
                # Skip entries we can't stat
                continue

        return entries

    def append_file(self, path: str, content: str) -> str:
        """
        Append content to a file, creating it if it doesn't exist.

        Args:
            path: Path relative to storage root.
            content: Content to append.

        Returns:
            Absolute path of the file.

        Raises:
            PathTraversalError: If path escapes storage root.
            StorageError: If file can't be written.
        """
        resolved = self._resolve_path(path)

        try:
            resolved.parent.mkdir(parents=True, exist_ok=True)
            with open(resolved, "a", encoding="utf-8") as f:
                f.write(content)
            return str(resolved)
        except PathTraversalError:
            raise
        except Exception as e:
            raise StorageError(f"Error appending to file: {e}")

    # Directories excluded from search by default (FUSE mounts, large mail archives)
    SEARCH_EXCLUDE_DIRS = ["google", "onedrive", "pcloud", "mail"]

    def search_files(
        self,
        query: str,
        path: str = "",
        glob_pattern: str = "*.md",
    ) -> List[Dict]:
        """
        Search for text in files using grep.

        Args:
            query: Text to search for.
            path: Directory to search in (relative to storage root).
            glob_pattern: Glob pattern to filter files (default: *.md).

        Returns:
            List of dicts with file, line, content fields.

        Raises:
            PathTraversalError: If path escapes storage root.
            StorageError: If search fails.
        """
        resolved = self._resolve_path(path)

        if not resolved.exists():
            raise StorageError(f"Directory not found: {path}")
        if not resolved.is_dir():
            raise StorageError(f"Not a directory: {path}")

        results = []

        # Use grep for efficiency
        try:
            cmd = [
                "grep", "-rn", "--include", glob_pattern,
            ]
            # Exclude FUSE mounts and large directories when searching from root
            if not path:
                for exclude_dir in self.SEARCH_EXCLUDE_DIRS:
                    cmd.extend(["--exclude-dir", exclude_dir])
            # -e marks the query as a pattern and -- ends option parsing, so a
            # query starting with "-" can't be interpreted as a grep flag.
            cmd.extend(["-e", query, "--", str(resolved)])
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30,
            )

            for line in proc.stdout.splitlines():
                # grep output: filepath:linenum:content
                match = re.match(r"^(.+?):(\d+):(.*)$", line)
                if match:
                    filepath, linenum, content = match.groups()
                    # Make path relative to storage root
                    try:
                        rel_path = str(
                            Path(filepath).relative_to(self.storage_root)
                        )
                    except ValueError:
                        rel_path = filepath

                    results.append({
                        "file": rel_path,
                        "line": int(linenum),
                        "content": content.strip(),
                    })
        except subprocess.TimeoutExpired:
            raise StorageError("Search timed out")
        except FileNotFoundError:
            # grep not available, fall back to Python
            for file_path in resolved.rglob(glob_pattern):
                if not file_path.is_file():
                    continue
                # Skip excluded directories when searching from root
                if not path:
                    rel_parts = file_path.relative_to(resolved).parts
                    if rel_parts and rel_parts[0] in self.SEARCH_EXCLUDE_DIRS:
                        continue
                try:
                    with open(file_path, "r", encoding="utf-8") as f:
                        for i, file_line in enumerate(f, 1):
                            if query in file_line:
                                rel_path = str(
                                    file_path.relative_to(self.storage_root)
                                )
                                results.append({
                                    "file": rel_path,
                                    "line": i,
                                    "content": file_line.strip(),
                                })
                except (OSError, UnicodeDecodeError):
                    continue

        return results
