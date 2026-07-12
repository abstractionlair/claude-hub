"""Window-file continuity system for claude-hub.

Manages context window files that form a linked tree via YAML frontmatter.
Each window file represents one context window's narrative, linked to
parent/child windows for continuity across sessions.

Usage as CLI:
    python3 -m claude_hub.continuity load-chain <path> [--depth N]
"""

from __future__ import annotations

import argparse
import asyncio
import fcntl
import json
import os
import re
import sys
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


def _windows_dir(harness: str = "claude-code") -> Path:
    """Resolve the windows directory, preferring role-scoped path.

    Primary: ~/roles/{CURRENT_ROLE}/windows/ (if role is active and dir exists)
    Fallback: {project}/thoughts/windows/{harness}/
    """
    role = os.environ.get("CURRENT_ROLE", "")
    if role:
        role_dir = Path.home() / "roles" / role / "windows"
        if role_dir.is_dir():
            return role_dir
    project_dir = Path(os.environ.get("CLAUDE_PROJECT_DIR", Path.cwd()))
    return project_dir / "thoughts" / "windows" / harness


def _timestamp_filename() -> str:
    """Generate a timestamp-based filename (ISO 8601, colons replaced with hyphens)."""
    now = datetime.now(timezone.utc)
    # e.g. 2026-03-07T14-30-00Z.md
    ts = now.strftime("%Y-%m-%dT%H-%M-%SZ")
    return f"{ts}.md"


def _parse_frontmatter(text: str) -> tuple[dict[str, object], str]:
    """Parse YAML frontmatter from a markdown file.

    Returns (metadata_dict, body_text). If no frontmatter found,
    returns (empty dict, full text).
    """
    if not text.startswith("---"):
        return {}, text

    # Find closing ---
    end_match = re.search(r"\n---\s*\n", text[3:])
    if end_match is None:
        # Check for --- at very end of file
        end_match = re.search(r"\n---\s*$", text[3:])
        if end_match is None:
            return {}, text

    fm_text = text[3 : 3 + end_match.start()]
    body = text[3 + end_match.end() :]

    metadata: dict[str, object] = {}
    for line in fm_text.strip().split("\n"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue

        colon_pos = line.find(":")
        if colon_pos == -1:
            continue

        key = line[:colon_pos].strip()
        value_str = line[colon_pos + 1 :].strip()

        # Parse value
        if value_str == "null" or value_str == "~" or value_str == "":
            metadata[key] = None
        elif value_str.startswith("[") and value_str.endswith("]"):
            # Simple list parsing
            inner = value_str[1:-1].strip()
            if not inner:
                metadata[key] = []
            else:
                items = [item.strip().strip('"').strip("'") for item in inner.split(",")]
                metadata[key] = items
        elif value_str.startswith('"') and value_str.endswith('"'):
            metadata[key] = value_str[1:-1]
        elif value_str.startswith("'") and value_str.endswith("'"):
            metadata[key] = value_str[1:-1]
        else:
            metadata[key] = value_str

    return metadata, body


def _serialize_frontmatter(metadata: dict[str, object]) -> str:
    """Serialize metadata dict to YAML frontmatter string (including --- delimiters)."""
    lines = ["---"]
    for key, value in metadata.items():
        if value is None:
            lines.append(f"{key}: null")
        elif isinstance(value, list):
            if not value:
                lines.append(f"{key}: []")
            else:
                items = ", ".join(f'"{item}"' for item in value)
                lines.append(f"{key}: [{items}]")
        else:
            lines.append(f'{key}: "{value}"')
    lines.append("---")
    return "\n".join(lines) + "\n"


def _atomic_write(path: Path, content: str) -> None:
    """Write content to path atomically via temp file + rename."""
    tmp_fd, tmp_path = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(tmp_path, path)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


@contextmanager
def _file_lock(path: Path):
    """Advisory file lock using fcntl.flock.

    The lockfile is deliberately left in place after release. Unlinking it
    while other processes are blocked in flock() on the same path is a
    classic race: waiters wake holding a lock on the orphaned inode while
    the next caller creates (and locks) a fresh file at the same path,
    letting two holders into the critical section simultaneously.
    """
    lock_path = path.with_suffix(path.suffix + ".lock")
    fd = os.open(str(lock_path), os.O_CREAT | os.O_WRONLY)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def create_window(
    session_id: str,
    harness: str = "claude-code",
    parent: str | None = None,
    projects: list[str] | None = None,
) -> Path:
    """Create a new window file with YAML frontmatter.

    Args:
        session_id: The session identifier.
        harness: Harness name (used for fallback path under thoughts/windows/).
        parent: Parent window filename or relative path, or None for root windows.
        projects: Project tags to record in the new window.

    Returns:
        Path to the created window file.
    """
    directory = _windows_dir(harness)
    directory.mkdir(parents=True, exist_ok=True)

    filename = _timestamp_filename()
    filepath = directory / filename
    counter = 1
    while filepath.exists():
        base = filename.removesuffix(".md")
        filepath = directory / f"{base}-{counter}.md"
        counter += 1

    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    metadata: dict[str, object] = {
        "parent": parent,
        "children": [],
        "session_id": session_id,
        "harness": harness,
        "role": os.environ.get("CURRENT_ROLE", ""),
        "projects": projects or [],
        "workstream": "",
        "component": "",
        "service": "",
        "finalized": "false",
        "created": now_iso,
        "updated": now_iso,
    }

    _atomic_write(filepath, _serialize_frontmatter(metadata) + "\n")

    # Create .current-{session_id} pointer file
    pointer = directory / f".current-{session_id}"
    _atomic_write(pointer, filepath.name + "\n")

    # Link to parent if provided
    if parent is not None:
        # Resolve parent path
        if "/" in parent:
            # Cross-harness relative path
            parent_path = (directory / parent).resolve()
        else:
            parent_path = directory / parent
        if parent_path.exists():
            link_child(parent_path, filepath)

    return filepath


def link_child(parent_path: Path, child_path: Path) -> None:
    """Add a child reference to a parent window file's frontmatter.

    Updates the parent's children list and updated timestamp.
    Handles cross-harness relative paths.

    Args:
        parent_path: Path to the parent window file.
        child_path: Path to the child window file.
    """
    with _file_lock(parent_path):
        text = parent_path.read_text()
        metadata, body = _parse_frontmatter(text)

        children = metadata.get("children", [])
        if not isinstance(children, list):
            children = []

        # Determine child reference: filename if same directory, relative path if cross-harness
        if parent_path.parent == child_path.parent:
            child_ref = child_path.name
        else:
            # Compute relative path from parent's directory to child
            try:
                child_ref = os.path.relpath(child_path, parent_path.parent)
            except ValueError:
                # Different drives on Windows, use absolute
                child_ref = str(child_path)

        if child_ref not in children:
            children.append(child_ref)

        metadata["children"] = children
        metadata["updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        _atomic_write(parent_path, _serialize_frontmatter(metadata) + body)


def append_window(path: Path, content: str) -> bool:
    """Append narrative content to an active window atomically.

    Finalized windows are immutable: returning ``False`` lets lifecycle hooks
    tolerate a late Stop event without writing into the preceding context
    epoch after compaction has already advanced its pointer.
    """
    if not path.is_file() or not content.strip():
        return False

    with _file_lock(path):
        text = path.read_text()
        metadata, body = _parse_frontmatter(text)
        if str(metadata.get("finalized", "false")).lower() == "true":
            return False

        metadata["updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        separator = "" if not body.strip() else "\n\n"
        updated_body = body.rstrip() + separator + content.strip() + "\n"
        _atomic_write(path, _serialize_frontmatter(metadata) + updated_body)
    return True


def find_current_window(
    session_id: str,
    harness: str = "claude-code",
) -> Path | None:
    """Find the current window file for a session by reading its pointer.

    Args:
        session_id: The session identifier.
        harness: Harness name.

    Returns:
        Path to the current window file, or None if no pointer exists
        or the target file doesn't exist.
    """
    directory = _windows_dir(harness)
    pointer = directory / f".current-{session_id}"

    if not pointer.exists():
        return None

    filename = pointer.read_text().strip()
    filepath = directory / filename

    if not filepath.exists():
        return None

    return filepath


def find_latest_window(
    session_id: str | None = None,
    harness: str = "claude-code",
) -> Path | None:
    """Find the most recent window file by timestamp filename.

    Args:
        session_id: If provided, filter to windows matching this session_id
            in frontmatter.
        harness: Harness name.

    Returns:
        Path to the latest window file, or None if no windows exist.
    """
    directory = _windows_dir(harness)

    if not directory.exists():
        return None

    md_files = sorted(directory.glob("*.md"), reverse=True)

    if session_id is None:
        return md_files[0] if md_files else None

    # Filter by session_id in frontmatter
    for filepath in md_files:
        text = filepath.read_text()
        metadata, _ = _parse_frontmatter(text)
        if metadata.get("session_id") == session_id:
            return filepath

    return None


def load_window_chain(path: Path, depth: int = 3) -> str:
    """Load a chain of window files by following parent links.

    Reads the given window file, then follows parent references up to
    `depth` levels. Returns concatenated content in chronological order
    (oldest parent first).

    Args:
        path: Path to the starting (most recent) window file.
        depth: Maximum number of parent levels to traverse.

    Returns:
        Concatenated content of the window chain with separators.
    """
    chain: list[tuple[str, str, str]] = []  # (filename, full_text, body)

    current = path
    for _ in range(depth + 1):  # +1 to include the starting file
        if not current.exists():
            break

        text = current.read_text()
        metadata, body = _parse_frontmatter(text)

        chain.append((current.name, text, body))

        parent_ref = metadata.get("parent")
        if parent_ref is None:
            break

        # Resolve parent path
        parent_ref_str = str(parent_ref)
        if "/" in parent_ref_str:
            # Relative path (cross-harness)
            current = (current.parent / parent_ref_str).resolve()
        else:
            current = current.parent / parent_ref_str

    # Reverse to chronological order (oldest first)
    chain.reverse()

    parts = []
    for i, (filename, full_text, body) in enumerate(chain):
        is_leaf = (i == len(chain) - 1)
        content = full_text if is_leaf else body.lstrip("\n")
        parts.append(f"<!-- window: {filename} -->\n{content}")

    return "\n---\n\n".join(parts)


def extract_sections(body: str, sections: list[str]) -> str:
    """Extract named sections (## headers) from a window file body.

    Args:
        body: The body text (after frontmatter).
        sections: List of section names to extract (e.g. ["Open Threads"]).
            Matches against ## headers case-insensitively.

    Returns:
        Extracted sections concatenated, or empty string if none found.
    """
    lines = body.split("\n")
    result_lines: list[str] = []
    capturing = False
    section_lower = [s.lower() for s in sections]

    for line in lines:
        if line.startswith("## "):
            header_text = line[3:].strip().lower()
            if any(s in header_text for s in section_lower):
                capturing = True
                result_lines.append(line)
                continue
            else:
                capturing = False
        if capturing:
            result_lines.append(line)

    return "\n".join(result_lines).strip()


def extract_title(body: str) -> str:
    """Extract the first # heading from a window file body."""
    for line in body.split("\n"):
        if line.startswith("# ") and not line.startswith("## "):
            return line
    return ""


def load_selective_chain(
    path: Path,
    depth: int = 3,
    full_depth: int = 1,
) -> str:
    """Load a chain of window files with selective extraction for older windows.

    Recent windows (within full_depth) are loaded fully. Older windows
    are reduced to their title and Open Threads section — the parts that
    remain relevant across sessions.

    Args:
        path: Path to the starting (most recent) window file.
        depth: Maximum number of parent levels to traverse.
        full_depth: Number of parent levels to load fully (0 = only current
            window is full, 1 = current + immediate parent, etc.)

    Returns:
        Concatenated content with separators.
    """
    chain: list[tuple[str, str, dict, str]] = []  # (filename, full_text, metadata, body)

    current = path
    for _ in range(depth + 1):
        if not current.exists():
            break

        text = current.read_text()
        metadata, body = _parse_frontmatter(text)
        chain.append((current.name, text, metadata, body))

        parent_ref = metadata.get("parent")
        if parent_ref is None:
            break

        parent_ref_str = str(parent_ref)
        if "/" in parent_ref_str:
            current = (current.parent / parent_ref_str).resolve()
        else:
            current = current.parent / parent_ref_str

    # Reverse to chronological order (oldest first)
    chain.reverse()

    # The leaf (most recent) is now at the end
    # full_depth=1 means: leaf + 1 parent get full content
    # So items at index >= (len(chain) - 1 - full_depth) get full content
    full_cutoff = len(chain) - 1 - full_depth

    parts = []
    for i, (filename, full_text, metadata, body) in enumerate(chain):
        if i >= full_cutoff:
            # Recent window: full content
            is_leaf = (i == len(chain) - 1)
            content = full_text if is_leaf else body.lstrip("\n")
        else:
            # Older window: title + Open Threads only
            title = extract_title(body)
            threads = extract_sections(body, ["Open Threads"])
            summary_parts = [f"[older window — selective extract]"]
            if title:
                summary_parts.append(title)
            if threads:
                summary_parts.append(threads)
            if not title and not threads:
                # Nothing useful to extract, include a one-liner
                first_line = body.strip().split("\n")[0] if body.strip() else "(empty)"
                summary_parts.append(first_line)
            content = "\n\n".join(summary_parts)

        parts.append(f"<!-- window: {filename} -->\n{content}")

    return "\n---\n\n".join(parts)


def finalize_window(path: Path) -> bool:
    """Set finalized: true in a window file's frontmatter.

    Returns True if the file was updated, False if already finalized or not found.
    """
    if not path.exists():
        return False

    with _file_lock(path):
        text = path.read_text()
        metadata, body = _parse_frontmatter(text)

        if metadata.get("finalized") == "true":
            return False

        metadata["finalized"] = "true"
        metadata["updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        _atomic_write(path, _serialize_frontmatter(metadata) + body)
    return True


def main() -> None:
    """CLI entrypoint for the continuity module."""
    parser = argparse.ArgumentParser(
        prog="python3 -m claude_hub.continuity",
        description="Window-file continuity system",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # create command
    create_parser = subparsers.add_parser("create", help="Create a window file")
    create_parser.add_argument("--session-id", required=True, help="Session identifier")
    create_parser.add_argument(
        "--harness",
        default="claude-code",
        help="Harness name (default: claude-code)",
    )
    create_parser.add_argument(
        "--parent",
        default=None,
        help="Known originating window filename or relative path",
    )
    create_parser.add_argument(
        "--project",
        action="append",
        default=[],
        help="Project tag to record (repeatable)",
    )

    # append command
    append_parser = subparsers.add_parser(
        "append", help="Append stdin to an active window file"
    )
    append_parser.add_argument("--file", required=True, help="Window file path")

    # load-chain command
    chain_parser = subparsers.add_parser("load-chain", help="Load a window file chain")
    chain_parser.add_argument("path", type=str, help="Path to the window file")
    chain_parser.add_argument(
        "--depth", type=int, default=3, help="Maximum parent depth to traverse (default: 3)"
    )
    chain_parser.add_argument(
        "--selective", action="store_true",
        help="Selective mode: full content for recent windows, extracts for older ones",
    )
    chain_parser.add_argument(
        "--full-depth", type=int, default=1,
        help="Parent levels to load fully in selective mode (default: 1)",
    )

    # find-latest command
    latest_parser = subparsers.add_parser("find-latest", help="Find the most recent window file")
    latest_parser.add_argument(
        "--session-id",
        type=str,
        default=None,
        help="Filter to windows matching this session_id",
    )
    latest_parser.add_argument(
        "--harness",
        type=str,
        default="claude-code",
        help="Harness name (default: claude-code)",
    )

    # finalize command
    finalize_parser = subparsers.add_parser("finalize", help="Set finalized: true on a window file")
    finalize_parser.add_argument("path", type=str, help="Path to the window file")

    # ingest command (requires Postgres)
    ingest_parser = subparsers.add_parser("ingest", help="Ingest a window file into the artifact store")
    ingest_parser.add_argument("--file", type=str, required=True, help="Path to the window file")

    # ingest-all command (requires Postgres)
    ingest_all_parser = subparsers.add_parser("ingest-all", help="Bulk ingest all window files")
    ingest_all_parser.add_argument(
        "--harness", type=str, default="claude-code", help="Harness name (default: claude-code)"
    )

    # search command (requires Postgres)
    search_parser = subparsers.add_parser("search", help="Semantic search across window files")
    search_parser.add_argument("--topic", type=str, required=True, help="Search topic")
    search_parser.add_argument("--limit", type=int, default=5, help="Max results (default: 5)")
    search_parser.add_argument(
        "--format", type=str, default="json", choices=["json", "brief"],
        help="Output format (default: json)",
    )

    args = parser.parse_args()

    if args.command == "create":
        result = create_window(
            session_id=args.session_id,
            harness=args.harness,
            parent=args.parent,
            projects=args.project,
        )
        print(result)
    elif args.command == "append":
        success = append_window(Path(args.file), sys.stdin.read())
        if not success:
            sys.exit(1)
    elif args.command == "load-chain":
        if args.selective:
            result = load_selective_chain(
                Path(args.path), depth=args.depth, full_depth=args.full_depth
            )
        else:
            result = load_window_chain(Path(args.path), depth=args.depth)
        print(result)
    elif args.command == "find-latest":
        result = find_latest_window(
            session_id=args.session_id,
            harness=args.harness,
        )
        if result is not None:
            print(result)
        else:
            sys.exit(1)
    elif args.command == "finalize":
        success = finalize_window(Path(args.path))
        if success:
            print(f"Finalized: {args.path}")
        else:
            print(f"No change: {args.path} (already finalized or not found)")
            sys.exit(1)
    elif args.command in ("ingest", "ingest-all", "search"):
        asyncio.run(_async_main(args))
    else:
        parser.print_help()
        sys.exit(1)


async def _async_main(args: argparse.Namespace) -> None:
    """Async dispatch for commands that need the artifact store."""
    from claude_hub import database
    from claude_hub import continuity_ingest
    from claude_hub.embedding import configure_gemini

    dsn = os.environ.get("CLAUDE_HUB_PG_DSN")
    if not dsn:
        print("Error: CLAUDE_HUB_PG_DSN not set", file=sys.stderr)
        sys.exit(1)

    configure_gemini()
    try:
        pool = await database.create_pool(dsn)
    except Exception as e:
        print(f"Error: Cannot connect to database: {e}", file=sys.stderr)
        sys.exit(1)
    database.set_pool(pool)
    try:
        if args.command == "ingest":
            result = await continuity_ingest.ingest_window(pool, Path(args.file))
            print(json.dumps(result, indent=2))
        elif args.command == "ingest-all":
            result = await continuity_ingest.ingest_all_windows(pool, harness=args.harness)
            print(f"Created: {result['created']}")
            print(f"Updated: {result['updated']}")
            print(f"Skipped: {result['skipped']}")
            print(f"Errors: {result['errors']}")
            for detail in result["details"]:
                print(f"  {detail}")
        elif args.command == "search":
            if args.format == "brief":
                output = await continuity_ingest.get_semantic_context(
                    pool, args.topic, limit=args.limit
                )
                print(output)
            else:
                results = await continuity_ingest.search_windows(
                    pool, args.topic, limit=args.limit
                )
                print(json.dumps(results, indent=2, default=str))

        # Let fire-and-forget embedding tasks complete before pool closes
        pending = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
    finally:
        await database.close_pool()


if __name__ == "__main__":
    main()
