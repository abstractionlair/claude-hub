"""Async CLI entrypoint for the multi-model review engine.

Calls review_engine functions directly via Python imports — no HTTP, no OAuth.
Blocks until all reviews + synthesis complete, writes results to a file.

Usage:
  python -m claude_hub.review_cli --prompt "Review for correctness"
  python -m claude_hub.review_cli --files src/foo.py --prompt "Security review"
  python -m claude_hub.review_cli --intent-ref docs/design/spec.md --models claude gemini
  python -m claude_hub.review_cli --output docs/design/reviews/my-review.md --prompt "Review"
  python -m claude_hub.review_cli get <job-id>
"""

import argparse
import asyncio
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from claude_hub import database
from claude_hub import review_engine


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------

async def _init_pool(needs_registry: bool = True):
    """Create the asyncpg pool and optionally load the model registry."""
    dsn = os.environ.get("CLAUDE_HUB_PG_DSN")
    if not dsn:
        print("Error: CLAUDE_HUB_PG_DSN not set", file=sys.stderr)
        sys.exit(1)
    project_dir = Path(
        os.environ.get("CLAUDE_HUB_PROJECT_DIR", str(Path.home() / "claude-hub"))
    )
    pool = await database.create_pool(dsn)
    database.set_pool(pool)
    if needs_registry:
        review_engine.load_model_registry(project_dir / "config" / "review_models.yaml")
    return pool


# ---------------------------------------------------------------------------
# Git auto-detect
# ---------------------------------------------------------------------------

def _detect_git_changes() -> list[str]:
    """Detect changed files via git diff (unstaged + staged, deduplicated)."""
    files = set()
    for cmd in (
        ["git", "diff", "--name-only", "HEAD"],
        ["git", "diff", "--name-only", "--cached"],
    ):
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            for line in result.stdout.strip().splitlines():
                if line:
                    files.add(line)
    return sorted(files)


# ---------------------------------------------------------------------------
# Output file
# ---------------------------------------------------------------------------

def _default_output_path(slug: str | None = None) -> Path:
    """Generate a default output path in docs/design/reviews/."""
    project_dir = Path(
        os.environ.get("CLAUDE_HUB_PROJECT_DIR", str(Path.home() / "claude-hub"))
    )
    reviews_dir = project_dir / "docs" / "design" / "reviews"
    reviews_dir.mkdir(parents=True, exist_ok=True)
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    name = f"review-{date_str}"
    if slug:
        name += f"-{slug}"
    # Avoid collisions
    path = reviews_dir / f"{name}.md"
    counter = 1
    while path.exists():
        counter += 1
        path = reviews_dir / f"{name}-{counter}.md"
    return path


def _write_results(path: Path, result: dict, prompt: str, files: list[str] | None) -> None:
    """Write review results to a markdown file."""
    lines = []

    # Header
    lines.append(f"# Review: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    lines.append("")
    lines.append(f"**Prompt:** {prompt}")
    if files:
        lines.append(f"**Files:** {', '.join(files)}")
    lines.append(f"**Job ID:** {result.get('job_id', 'unknown')}")
    lines.append("")

    # Synthesis
    synthesis = result.get("synthesis")
    if synthesis:
        prose = synthesis.get("synthesis_prose")
        if prose:
            lines.append("## Synthesis")
            lines.append("")
            lines.append(prose)
            lines.append("")

        models_responded = synthesis.get("models_responded", [])
        modes = synthesis.get("review_modes", {})
        responded_parts = []
        for m in models_responded:
            mode = modes.get(m, "")
            responded_parts.append(f"{m} ({mode})" if mode else m)
        lines.append(f"**Models responded:** {', '.join(responded_parts)}")

        skipped = set(synthesis.get("models_requested", [])) - set(models_responded)
        if skipped:
            lines.append(f"**Models skipped/failed:** {', '.join(sorted(skipped))}")
        lines.append("")

    # Individual reviews
    reviews = result.get("reviews") or []
    if reviews:
        lines.append("## Individual Reviews")
        lines.append("")
        for r in reviews:
            model = r.get("model", "unknown")
            status = r.get("status", "unknown")
            raw = r.get("raw_content") or ""
            lines.append(f"### {model} ({status})")
            lines.append("")
            if raw:
                lines.append(raw)
            else:
                lines.append(f"*No output (status: {status})*")
            lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")


# ---------------------------------------------------------------------------
# File resolution
# ---------------------------------------------------------------------------

def _resolve_files(args) -> list[str] | None:
    """Resolve files from args or git auto-detect.

    Returns None if --content or --artifact-id were provided instead.
    """
    content = getattr(args, "content", None)
    artifact_id = getattr(args, "artifact_id", None)
    files = getattr(args, "files", None)

    if files:
        return files
    if content or artifact_id:
        return None

    # Auto-detect from git
    detected = _detect_git_changes()
    if not detected:
        print(
            "Error: No files specified and no git changes detected.\n"
            "Use --files, --content, or --artifact-id, or make changes first.",
            file=sys.stderr,
        )
        sys.exit(1)
    print(f"Auto-detected {len(detected)} changed file(s): {', '.join(detected)}", file=sys.stderr)
    return detected


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

async def _cmd_review(pool, args) -> None:
    """Main review command: dispatch, await tasks, write results to file."""
    files = _resolve_files(args)

    dispatch_result = await review_engine.dispatch_review(
        pool,
        files=files,
        content=getattr(args, "content", None),
        prompt=args.prompt,
        intent=getattr(args, "intent", None),
        intent_ref=getattr(args, "intent_ref", None),
        context_files=getattr(args, "context_files", None),
        models=getattr(args, "models", None),
        clean_room=getattr(args, "clean_room", True),
        exclude_paths=getattr(args, "exclude_paths", None),
        include_paths=getattr(args, "include_paths", None),
        artifact_id=getattr(args, "artifact_id", None),
        review_type=getattr(args, "review_type", "general"),
    )

    job_id = dispatch_result["job_id"]
    dispatched = dispatch_result["models_dispatched"]
    tasks = dispatch_result.get("tasks", [])
    skipped = dispatch_result.get("models_skipped")

    print(f"Dispatched to {len(dispatched)} model(s): {', '.join(dispatched)}", file=sys.stderr)
    if skipped:
        print(f"Skipped (prompt too large): {', '.join(skipped)}", file=sys.stderr)
    print(f"Job ID: {job_id}", file=sys.stderr)
    print("Waiting for reviews + synthesis...", file=sys.stderr)

    # Await all review tasks — synthesis auto-triggers when last review completes
    try:
        await asyncio.gather(*tasks, return_exceptions=True)
    except KeyboardInterrupt:
        print(f"\nInterrupted. Job ID: {job_id}", file=sys.stderr)
        print(f"  python -m claude_hub.review_cli get {job_id}", file=sys.stderr)
        sys.exit(130)

    # Fetch results from DB
    result = await review_engine.get_review_results(pool, job_id, include_individual=True)

    # Clean up internalized external files
    review_external = Path.cwd() / ".review-external"
    if review_external.exists():
        import shutil
        shutil.rmtree(review_external, ignore_errors=True)

    # Write to file
    output_path = Path(args.output) if getattr(args, "output", None) else _default_output_path()
    _write_results(output_path, result, args.prompt, files)
    print(f"Results written to: {output_path}", file=sys.stderr)


async def _cmd_get(pool, args) -> None:
    """Retrieve and write results for a previous review job."""
    result = await review_engine.get_review_results(pool, args.job_id, include_individual=True)

    if result.get("status") == "not_found":
        print(f"Job not found: {args.job_id}", file=sys.stderr)
        sys.exit(1)

    output_path = Path(args.output) if getattr(args, "output", None) else _default_output_path()
    _write_results(output_path, result, "(retrieved)", None)
    print(f"Results written to: {output_path}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

def _add_review_args(parser: argparse.ArgumentParser) -> None:
    """Add review dispatch arguments to a parser."""
    parser.add_argument("--files", nargs="+", metavar="FILE", help="File paths to review")
    parser.add_argument("--content", metavar="TEXT", help="Raw content to review (alternative to --files)")
    parser.add_argument("--prompt", help="Review instructions")
    parser.add_argument("--intent", metavar="TEXT", help="What the code should do")
    parser.add_argument("--intent-ref", metavar="PATH", help="File path or artifact UUID for intent")
    parser.add_argument("--context-files", nargs="+", metavar="FILE", help="Additional context files")
    parser.add_argument("--models", nargs="+", metavar="MODEL", help="Specific models (default: all)")
    parser.add_argument("--no-clean-room", dest="clean_room", action="store_false", help="Disable opinion isolation")
    parser.add_argument("--exclude-paths", nargs="+", metavar="PATH", help="Paths reviewers shouldn't read")
    parser.add_argument("--include-paths", nargs="+", metavar="PATH", help="Override excluded paths")
    parser.add_argument("--artifact-id", metavar="UUID", help="Review an existing artifact by UUID")
    parser.add_argument("--review-type", metavar="TYPE", default="general",
                        help="Review type for quality grading (default: general)")
    parser.add_argument("--output", "-o", metavar="PATH", help="Output file (default: docs/design/reviews/review-DATE.md)")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(
        prog="python -m claude_hub.review_cli",
        description="Multi-model code review CLI — blocks until complete, writes results to file",
    )
    subparsers = parser.add_subparsers(dest="command")

    # --- Default mode (review) ---
    _add_review_args(parser)

    # --- get subcommand (retrieve previous results) ---
    get_parser = subparsers.add_parser("get", help="Retrieve results from a previous review job")
    get_parser.add_argument("job_id", help="Review job UUID")
    get_parser.add_argument("--output", "-o", metavar="PATH", help="Output file path")

    args = parser.parse_args(argv)

    # Validate: default mode requires --prompt
    if args.command is None and not getattr(args, "prompt", None):
        parser.error("--prompt is required")

    return args


# ---------------------------------------------------------------------------
# Async main
# ---------------------------------------------------------------------------

async def _async_main(args: argparse.Namespace) -> None:
    """Async entrypoint: init pool, run command, cleanup."""
    needs_registry = args.command != "get"
    pool = await _init_pool(needs_registry=needs_registry)
    try:
        if args.command == "get":
            await _cmd_get(pool, args)
        else:
            await _cmd_review(pool, args)
    finally:
        await database.close_pool()


def main():
    args = parse_args()
    asyncio.run(_async_main(args))


if __name__ == "__main__":
    main()
