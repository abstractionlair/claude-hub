"""Core review engine for the multi-model review system.

Dispatches review jobs across multiple AI models, collects results,
and synthesizes consensus findings.  All functions take an asyncpg pool
as their first argument and use parameterized queries with positional
``$N`` placeholders.

Depends on:
    - ``database.py``        -- ``get_pool()`` for asyncpg pool access
    - ``artifact_store.py``  -- ``store_artifact()`` for persisting reviews
    - ``review_models.py``   -- Pydantic response models
"""

import asyncio
import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
import uuid
import yaml
from datetime import datetime, timezone
from pathlib import Path

import asyncpg

from claude_hub import artifact_store as artifact_store_module

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Environment variables to strip from review subprocesses.
# CLAUDECODE: prevents Claude CLI from refusing to run inside Claude Code.
# GEMINI_API_KEY: forces gemini CLI to use subscription auth instead of
#   pay-per-use API key (the key, if present, takes precedence).
# ---------------------------------------------------------------------------
_STRIP_ENV_VARS = {"CLAUDECODE", "GEMINI_API_KEY"}

# ---------------------------------------------------------------------------
# Module-level model registry (loaded once at startup)
# ---------------------------------------------------------------------------

_model_registry: dict | None = None
_synthesis_config: dict | None = None


def get_synthesis_config() -> dict:
    """Return the synthesis configuration from the registry."""
    if _synthesis_config is None:
        return {"model": "claude", "timeout_seconds": 120}  # defaults
    return _synthesis_config


def load_model_registry(config_path: Path) -> dict:
    """Load the model registry from a YAML configuration file.

    Reads the YAML file, validates that each model entry has the required
    ``invoke`` and ``timeout_seconds`` fields, and stores the registry
    module-level for later access via :func:`get_registry`.

    Args:
        config_path: Path to the YAML config (e.g. ``config/review_models.yaml``).

    Returns:
        A dict mapping model names to their configuration dicts.

    Raises:
        FileNotFoundError: If *config_path* does not exist.
        ValueError: If a model entry is missing required fields.
    """
    global _model_registry, _synthesis_config

    if not config_path.exists():
        raise FileNotFoundError(f"Model registry config not found: {config_path}")

    with open(config_path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    models = raw.get("models", {})
    if not models:
        raise ValueError(f"No models defined in {config_path}")

    required_fields = {"invoke", "timeout_seconds", "mode"}
    for name, cfg in models.items():
        missing = required_fields - set(cfg.keys())
        if missing:
            raise ValueError(
                f"Model '{name}' is missing required fields: {missing}"
            )

    _model_registry = models
    _synthesis_config = raw.get("synthesis", {"model": "claude", "timeout_seconds": 120})
    logger.info("Loaded %d review models from %s", len(models), config_path)
    return models


def get_registry() -> dict:
    """Return the module-level model registry.

    Raises:
        RuntimeError: If :func:`load_model_registry` has not been called.
    """
    if _model_registry is None:
        raise RuntimeError(
            "Review model registry not loaded — call load_model_registry() first"
        )
    return _model_registry


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

# Default paths to exclude from reviewer access (opinion isolation, R2.6)
# .claude/ contains harness config, not relevant to code review.
# CLAUDE.md contains project instructions that carry editorial opinions.
# thoughts/ is no longer excluded: ledgers decommissioned, window files
# moved to ~/roles/, remaining content is prediction-markets data (fine to read).
DEFAULT_EXCLUDE_PATHS = [
    ".claude/",
    "CLAUDE.md",
    ".review-external/",
]


def build_review_prompt(
    *,
    files: list[str] | None = None,
    intent: str = "",
    prompt: str = "",
    context_files: list[str] | None = None,
    exclude_paths: list[str] | None = None,
    include_paths: list[str] | None = None,
) -> str:
    """Construct the task prompt for a review.

    Assembles the prompt from: files list, intent text, context_files,
    review instructions, exclude/include paths, and output format.
    Uses the template from Spec Section 6.2.

    Args:
        files: List of file paths to review (changed files).
        intent: What the code is supposed to do — spec references,
                requirements, acceptance criteria.
        prompt: Additional review instructions (what to look for).
        context_files: Additional files the reviewer should read
                       for conventions and patterns.
        exclude_paths: Paths reviewers should not read.
                       Defaults to DEFAULT_EXCLUDE_PATHS.
        include_paths: Paths to explicitly include even if under
                       an exclude prefix. Include wins over exclude.

    Returns:
        The fully assembled review prompt string.
    """
    parts = []

    parts.append(
        "You are reviewing code for correctness, completeness, "
        "and alignment with requirements."
    )

    # Files section
    if files:
        parts.append("\n## Files to Review")
        for f in files:
            parts.append(f"- {f}")

    # Intent section
    if intent:
        parts.append("\n## Intent")
        parts.append(intent)

    # Additional review instructions
    if prompt:
        parts.append("\n## Review Instructions")
        parts.append(prompt)

    # Context files section
    if context_files:
        parts.append("\n## Suggested Context")
        parts.append("Read these files for conventions and patterns:")
        for f in context_files:
            parts.append(f"- {f}")

    # Boundaries section
    effective_excludes = exclude_paths if exclude_paths is not None else list(DEFAULT_EXCLUDE_PATHS)

    # Remove any excludes that are overridden by include_paths
    if include_paths and effective_excludes:
        filtered_excludes = []
        for exc in effective_excludes:
            # Keep the exclude unless an include_path starts with it or matches it
            override = False
            for inc in include_paths:
                if inc.startswith(exc) or exc.startswith(inc):
                    override = True
                    break
            if not override:
                filtered_excludes.append(exc)
        effective_excludes = filtered_excludes

    if effective_excludes:
        parts.append("\n## Boundaries")
        parts.append(
            "Please do NOT read the following paths — they contain "
            "process preferences and editorial opinions that could "
            "anchor your review:"
        )
        for p in effective_excludes:
            parts.append(f"- {p}")
        if include_paths:
            parts.append("\nException — you MAY read these specific paths:")
            for p in include_paths:
                parts.append(f"- {p}")

    parts.append(
        "\nFocus on the code and its alignment with the intent above. "
        "Form your own opinions."
    )

    # Review approach
    parts.append("\n## Review Approach")
    parts.append(
        "Start by reading the files listed above, then explore "
        "adjacent code for context (imports, callers, tests). "
        "Report which files you read beyond the review targets."
    )
    parts.append(
        "\nWrite your review as prose. For each finding, note where "
        "in the code it occurs and how severe you think it is. "
        "Organize however makes sense for what you found — there is "
        "no required format. The synthesis model will read your output directly."
    )

    return "\n".join(parts)


def _review_task_done(task: asyncio.Task) -> None:
    """Log unhandled exceptions from review background tasks."""
    if task.cancelled():
        return
    exc = task.exception()
    if exc:
        logger.error("Review background task failed: %s", exc, exc_info=exc)


# Concurrency limiter for VPS protection (4GB server)
_review_semaphore = asyncio.Semaphore(3)


async def dispatch_review(
    pool: asyncpg.Pool,
    *,
    files: list[str] | None = None,
    content: str | None = None,
    prompt: str = "",
    intent: str | None = None,
    intent_ref: str | None = None,
    context_files: list[str] | None = None,
    models: list[str] | None = None,
    clean_room: bool = True,
    exclude_paths: list[str] | None = None,
    include_paths: list[str] | None = None,
    artifact_id: str | None = None,
    review_type: str = "general",
) -> dict:
    """Dispatch a multi-model review job.

    At least one of *files*, *content*, or *artifact_id* must be provided
    to specify the material being reviewed.

    For each selected model a ``reviews`` row is created with
    ``status='pending'`` and an async task is spawned to run the review.

    Args:
        pool: asyncpg connection pool.
        files: List of file paths to review (agentic mode).
        content: Raw text to review (bundled mode fallback).
        prompt: Review instructions / prompt.
        intent: What the code is supposed to do (inline text).
        intent_ref: File path or artifact ID for intent. Takes precedence
                    over *intent*. If a file path, reads the file. If a UUID,
                    fetches from artifact store.
        context_files: Additional files for reviewer context.
        models: Model names from the registry. None means all models.
        clean_room: Whether to invoke in clean-room mode (default True).
        exclude_paths: Paths reviewers should not read.
        include_paths: Paths to explicitly include (overrides excludes).
        artifact_id: UUID of an existing artifact to review.
        review_type: Category for quality grading (e.g. "spec", "code",
                     "requirements"). Defaults to "general".

    Returns:
        A dict with ``job_id`` and ``models_dispatched``.

    Raises:
        ValueError: If no content source or if artifact is sensitive.
    """
    # --- Validate at least one source ---
    sources_provided = sum(
        x is not None for x in (files, content, artifact_id)
    )
    if sources_provided == 0:
        raise ValueError(
            "At least one of files, content, or artifact_id must be provided"
        )

    resolved_artifact_id: str | None = artifact_id
    resolved_content: str | None = content

    # --- Resolve artifact_id ---
    if artifact_id is not None:
        artifact = await artifact_store_module.get_artifact(pool, artifact_id)
        if artifact is None:
            raise ValueError(f"Artifact not found: {artifact_id}")
        # Sensitive artifact check (R2, Spec Draft 5)
        if artifact.get("sensitive"):
            raise ValueError(
                f"Cannot review sensitive artifact {artifact_id} — "
                "sensitive artifacts must not be sent to third-party models"
            )
        resolved_content = artifact["content"]

    # --- Resolve intent_ref ---
    resolved_intent = intent or ""
    if intent_ref is not None:
        ref_path = Path(intent_ref)
        # Security: reject absolute paths and traversal
        if ref_path.is_absolute():
            raise ValueError(f"intent_ref must be a relative path, got: {intent_ref}")
        resolved = (Path.cwd() / ref_path).resolve()
        repo_root = Path.cwd().resolve()
        if not resolved.is_relative_to(repo_root):
            raise ValueError(f"intent_ref path traversal detected: {intent_ref}")
        if resolved.exists():
            resolved_intent = resolved.read_text(encoding="utf-8")
        else:
            # Try as artifact UUID
            try:
                uuid.UUID(intent_ref)
                intent_artifact = await artifact_store_module.get_artifact(
                    pool, intent_ref
                )
                if intent_artifact is not None:
                    resolved_intent = intent_artifact["content"]
                else:
                    raise ValueError(f"Intent reference not found: {intent_ref}")
            except (ValueError,) as e:
                if "Intent reference not found" in str(e):
                    raise
                raise ValueError(
                    f"Intent ref '{intent_ref}' is neither a valid file path "
                    "nor a valid artifact UUID"
                ) from e

    # --- Determine models ---
    registry = get_registry()
    if models is not None:
        unknown = set(models) - set(registry.keys())
        if unknown:
            raise ValueError(f"Unknown model(s): {unknown}")
        selected_models = {k: registry[k] for k in models}
    else:
        selected_models = dict(registry)

    # --- Internalize external files ---
    # Some models (Codex, Gemini) sandbox to the project directory. Copy external
    # files (include_paths, context_files) into a temp dir within the project
    # so all models can read them.
    internalized_dir: Path | None = None
    effective_include = list(include_paths) if include_paths else []
    effective_context = list(context_files) if context_files else []
    effective_files = list(files) if files else []

    project_dir = Path.cwd().resolve()
    external_paths = []
    for path_list in (effective_include, effective_context, effective_files):
        for p in path_list:
            resolved = Path(p).expanduser().resolve()
            if not resolved.is_relative_to(project_dir) and resolved.exists():
                external_paths.append((path_list, p, resolved))

    if external_paths:
        internalized_dir = project_dir / ".review-external"
        internalized_dir.mkdir(exist_ok=True)
        for path_list, original, resolved in external_paths:
            dest = internalized_dir / resolved.name
            # Handle name collisions
            counter = 1
            while dest.exists():
                dest = internalized_dir / f"{resolved.stem}-{counter}{resolved.suffix}"
                counter += 1
            shutil.copy2(resolved, dest)
            # Replace the original path in the list with the project-relative path
            idx = path_list.index(original)
            path_list[idx] = str(dest.relative_to(project_dir))
            logger.info("Internalized external file: %s -> %s", original, path_list[idx])

    # --- Build prompt and check per-model limits ---
    task_prompt = build_review_prompt(
        files=effective_files or None,
        intent=resolved_intent,
        prompt=prompt,
        context_files=effective_context or None,
        exclude_paths=exclude_paths,
        include_paths=effective_include or None,
    )

    # Check max_input_chars per model, skip models that exceed
    models_to_run: dict[str, dict] = {}
    skipped_models: list[str] = []
    for model_name, model_config in selected_models.items():
        max_chars = model_config.get("max_input_chars")
        if max_chars and len(task_prompt) > max_chars:
            logger.warning(
                "Skipping model %s: prompt (%d chars) exceeds limit (%d chars)",
                model_name,
                len(task_prompt),
                max_chars,
            )
            skipped_models.append(model_name)
        else:
            models_to_run[model_name] = model_config

    if not models_to_run:
        raise ValueError(
            f"Prompt exceeds all models' limits. "
            f"Skipped: {skipped_models}. Reduce scope or use higher-capacity models."
        )

    # --- Create job and review rows ---
    job_id = uuid.uuid4()

    review_rows: list[tuple[uuid.UUID, str, dict]] = []
    async with pool.acquire() as conn:
        for model_name, model_config in models_to_run.items():
            review_id = await conn.fetchval(
                """
                INSERT INTO reviews (
                    job_id, artifact_id, model, prompt, clean_room,
                    status, invocation_mode
                )
                VALUES ($1, $2, $3, $4, $5, 'pending', $6)
                RETURNING id
                """,
                job_id,
                uuid.UUID(artifact_id) if artifact_id else None,
                model_name,
                task_prompt,
                clean_room,
                model_config.get("mode", "agentic"),
            )
            review_rows.append((review_id, model_name, model_config))

    # Collect all file paths referenced in the prompt so _run_single_review
    # can copy them into the sandbox temp dir for sandboxed models.
    review_file_paths = list(effective_files) + list(effective_context)
    if effective_include:
        review_file_paths.extend(effective_include)

    # --- Spawn background tasks ---
    tasks: list[asyncio.Task] = []
    for review_id, model_name, model_config in review_rows:
        task = asyncio.create_task(
            _run_single_review(
                pool=pool,
                review_id=review_id,
                job_id=job_id,
                model_name=model_name,
                model_config=model_config,
                task_prompt=task_prompt,
                content=resolved_content,
                clean_room=clean_room,
                artifact_id=resolved_artifact_id,
                review_type=review_type,
                review_file_paths=review_file_paths,
                source_dir=project_dir,
            )
        )
        task.add_done_callback(_review_task_done)
        tasks.append(task)

    model_names = list(models_to_run.keys())
    logger.info(
        "Dispatched review job %s to %d models: %s",
        job_id,
        len(model_names),
        ", ".join(model_names),
    )

    result = {
        "job_id": str(job_id),
        "models_dispatched": model_names,
        "tasks": tasks,
    }
    if skipped_models:
        result["models_skipped"] = skipped_models
    return result


async def check_review_status(pool: asyncpg.Pool, job_id: str) -> dict:
    """Check the status of a review job.

    Args:
        pool: asyncpg connection pool.
        job_id: The review job UUID string.

    Returns:
        A dict with ``status``, ``models`` (list of per-model status dicts),
        and ``completion_pct``.
    """
    try:
        job_uuid = uuid.UUID(job_id)
    except (ValueError, AttributeError):
        raise ValueError(f"Invalid job_id: {job_id}")

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, model, status, completed_at
            FROM reviews
            WHERE job_id = $1
            ORDER BY created_at ASC
            """,
            job_uuid,
        )

        # Check for synthesis
        synthesis_exists = await conn.fetchval(
            "SELECT 1 FROM review_syntheses WHERE job_id = $1",
            job_uuid,
        )

    if not rows:
        return {
            "status": "not_found",
            "models": [],
            "completion_pct": 0.0,
        }

    model_statuses = []
    total = len(rows)
    done = 0
    all_failed = True

    for row in rows:
        status = row["status"]
        completed_at = (
            row["completed_at"].isoformat() if row["completed_at"] else None
        )
        model_statuses.append({
            "name": row["model"],
            "status": status,
            "completed_at": completed_at,
        })
        if status in ("complete", "failed", "timeout"):
            done += 1
        if status not in ("failed",):
            all_failed = False

    completion_pct = (done / total * 100.0) if total > 0 else 0.0

    if synthesis_exists:
        overall_status = "complete"
    elif all_failed and done == total:
        overall_status = "failed"
    elif done < total:
        overall_status = "running"
    else:
        # All done but synthesis not yet created (race window)
        overall_status = "running"

    return {
        "status": overall_status,
        "models": model_statuses,
        "completion_pct": completion_pct,
    }


async def get_review_results(
    pool: asyncpg.Pool,
    job_id: str,
    include_individual: bool = True,
) -> dict:
    """Retrieve full review results for a job.

    Args:
        pool: asyncpg connection pool.
        job_id: The review job UUID string.
        include_individual: Whether to include individual model reviews.

    Returns:
        A dict matching :class:`ReviewGetResponse` fields.
    """
    try:
        job_uuid = uuid.UUID(job_id)
    except (ValueError, AttributeError):
        raise ValueError(f"Invalid job_id: {job_id}")

    async with pool.acquire() as conn:
        # Get synthesis
        synth_row = await conn.fetchrow(
            """
            SELECT artifact_id, synthesis_artifact_id, review_ids,
                   consensus, unique_findings, contradictions,
                   models_requested, models_responded, review_modes
            FROM review_syntheses
            WHERE job_id = $1
            """,
            job_uuid,
        )

        # Get individual reviews
        review_rows = await conn.fetch(
            """
            SELECT id, model, status, findings, clean_room,
                   started_at, completed_at, invocation_mode,
                   raw_content
            FROM reviews
            WHERE job_id = $1
            ORDER BY created_at ASC
            """,
            job_uuid,
        )

    if not review_rows:
        return {
            "job_id": job_id,
            "artifact_id": None,
            "synthesis": None,
            "reviews": None,
            "status": "not_found",
        }

    # Determine overall status
    all_done = all(
        r["status"] in ("complete", "failed", "timeout") for r in review_rows
    )
    all_failed = all(r["status"] in ("failed",) for r in review_rows)

    if synth_row:
        overall_status = "complete"
    elif all_failed:
        overall_status = "failed"
    elif all_done:
        overall_status = "running"  # synthesis pending
    else:
        overall_status = "running"

    # Build synthesis dict
    synthesis = None
    artifact_id_str = None
    if synth_row:
        artifact_id_str = (
            str(synth_row["artifact_id"]) if synth_row["artifact_id"] else None
        )
        # Deprecated structured fields — kept for backward compatibility
        consensus = (
            json.loads(synth_row["consensus"])
            if isinstance(synth_row["consensus"], str)
            else synth_row["consensus"]
        )
        unique_findings = (
            json.loads(synth_row["unique_findings"])
            if isinstance(synth_row["unique_findings"], str)
            else synth_row["unique_findings"]
        )
        contradictions = (
            json.loads(synth_row["contradictions"])
            if isinstance(synth_row["contradictions"], str)
            else synth_row["contradictions"]
        )
        review_modes = (
            json.loads(synth_row["review_modes"])
            if isinstance(synth_row["review_modes"], str)
            else synth_row["review_modes"]
        )

        # Fetch synthesis prose from artifact store
        synthesis_prose = None
        if synth_row["synthesis_artifact_id"]:
            async with pool.acquire() as conn:
                art_row = await conn.fetchval(
                    "SELECT content FROM artifacts WHERE id = $1::uuid",
                    str(synth_row["synthesis_artifact_id"]),
                )
                if art_row:
                    synthesis_prose = art_row

        synthesis = {
            "consensus": consensus,
            "unique_findings": unique_findings,
            "contradictions": contradictions,
            "models_requested": list(synth_row["models_requested"]),
            "models_responded": list(synth_row["models_responded"]),
            "review_modes": review_modes,
            "synthesis_prose": synthesis_prose,
        }
    else:
        # No synthesis yet — artifact_id not available from synthesis row.
        # Individual reviews have artifact_id but it's not in the SELECT
        # (lightweight status query). Leave as None.
        pass

    # Build individual reviews
    reviews = None
    if include_individual:
        reviews = []
        for row in review_rows:
            # findings is deprecated (NULL for new reviews) — kept for backward compat
            findings = row["findings"]
            if findings is not None and isinstance(findings, str):
                findings = json.loads(findings)
            reviews.append({
                "id": str(row["id"]),
                "model": row["model"],
                "status": row["status"],
                "findings": findings,
                "raw_content": row.get("raw_content"),
                "clean_room": row["clean_room"],
                "started_at": (
                    row["started_at"].isoformat()
                    if row["started_at"]
                    else None
                ),
                "completed_at": (
                    row["completed_at"].isoformat()
                    if row["completed_at"]
                    else None
                ),
                "invocation_mode": row.get("invocation_mode", "agentic"),
            })

    return {
        "job_id": job_id,
        "artifact_id": artifact_id_str,
        "synthesis": synthesis,
        "reviews": reviews,
        "status": overall_status,
    }


# ---------------------------------------------------------------------------
# Internal: per-model review execution
# ---------------------------------------------------------------------------


async def _run_single_review(
    pool: asyncpg.Pool,
    review_id: uuid.UUID,
    job_id: uuid.UUID,
    model_name: str,
    model_config: dict,
    task_prompt: str,
    content: str | None,
    clean_room: bool,
    artifact_id: str | None = None,
    review_type: str = "general",
    review_file_paths: list[str] | None = None,
    source_dir: Path | None = None,
) -> None:
    """Execute a single model review as a background task.

    Mode-aware invocation:
    - **agentic**: substitutes {prompt} or writes to {prompt_file} in the
      invoke template. No content temp file needed.
    - **bundled**: writes content to a temp file and substitutes {file}
      and {prompt_file} in the invoke template.

    When *review_file_paths* and *source_dir* are provided, referenced
    files are copied into the temp dir so sandboxed models (Codex,
    Gemini) can access them via relative paths.

    After completion, checks whether all reviews for the job are done and
    triggers synthesis if so.
    """
    tmp_dir = None
    mode = model_config.get("mode", "agentic")

    try:
        # Mark as running
        now = datetime.now(timezone.utc)
        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE reviews
                SET status = 'running', started_at = $1
                WHERE id = $2
                """,
                now,
                review_id,
            )

        # Create secure temp directory
        tmp_dir = tempfile.mkdtemp(prefix="review_")

        # Copy referenced files into temp dir so sandboxed models
        # (Codex, Gemini) can access them via the same relative paths
        # that appear in the prompt.
        if review_file_paths and source_dir:
            for rel_path in review_file_paths:
                src = source_dir / rel_path
                if src.exists():
                    dest = Path(tmp_dir) / rel_path
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, dest)

        # Agentic models can't see API-passed content — write to accessible file
        if mode != "bundled" and content is not None:
            content_path = os.path.join(tmp_dir, "review_subject.md")
            with open(content_path, "w", encoding="utf-8") as f:
                f.write(content)
            task_prompt = f"NOTE: The content to review has been written to: {content_path}\n\n{task_prompt}"

        # Build command based on mode
        if mode == "bundled" and content is not None:
            # Bundled mode: write content and prompt to temp files
            content_path = os.path.join(tmp_dir, "content.md")
            with open(content_path, "w", encoding="utf-8") as f:
                f.write(content)

            prompt_path = os.path.join(tmp_dir, "prompt.md")
            with open(prompt_path, "w", encoding="utf-8") as f:
                f.write(task_prompt)

            cmd = []
            for arg in model_config["invoke"]:
                cmd.append(
                    arg.replace("{file}", content_path)
                    .replace("{prompt_file}", prompt_path)
                    .replace("{prompt}", task_prompt)
                )
        else:
            # Agentic mode: prompt only (model reads files itself)
            prompt_path = os.path.join(tmp_dir, "prompt.md")
            with open(prompt_path, "w", encoding="utf-8") as f:
                f.write(task_prompt)

            cmd = []
            for arg in model_config["invoke"]:
                cmd.append(
                    arg.replace("{prompt_file}", prompt_path)
                    .replace("{prompt}", task_prompt)
                )

        # Append clean-room flags if applicable
        if clean_room and model_config.get("clean_room_flags"):
            cmd.extend(model_config["clean_room_flags"])

        timeout = model_config.get("timeout_seconds", 300)

        logger.info(
            "Running review %s with model %s (mode=%s, timeout=%ds)",
            review_id,
            model_name,
            mode,
            timeout,
        )

        # Use semaphore to limit concurrent reviews
        subprocess_env = {k: v for k, v in os.environ.items() if k not in _STRIP_ENV_VARS}

        run_kwargs: dict = dict(
            capture_output=True,
            text=True,
            timeout=timeout,
            env=subprocess_env,
            cwd=tmp_dir,  # sandboxed models see review files; avoids project snapshotting
        )
        if model_config.get("stdin_prompt", False):
            run_kwargs["input"] = task_prompt

        async with _review_semaphore:
            result = await asyncio.to_thread(
                subprocess.run,
                cmd,
                **run_kwargs,
            )

        if result.returncode != 0:
            logger.warning(
                "Model %s returned non-zero exit code %d for review %s: %s",
                model_name,
                result.returncode,
                review_id,
                result.stderr[:500] if result.stderr else "(no stderr)",
            )
            # Mark as failed, not complete
            completed_at = datetime.now(timezone.utc)
            async with pool.acquire() as conn:
                await conn.execute(
                    "UPDATE reviews SET status = 'failed', raw_content = $1, completed_at = $2 WHERE id = $3",
                    result.stdout + "\n\nSTDERR:\n" + (result.stderr or ""),
                    completed_at,
                    review_id,
                )
            # finally block triggers _check_and_synthesize
            return

        # Strip ANSI escape codes from output (Codex/Gemini emit them)
        raw_output = re.sub(r'\x1b\[[0-9;]*m', '', result.stdout).strip()

        if not raw_output:
            # Model exited 0 but produced no output — treat as failure
            logger.warning(
                "Model %s returned exit 0 but empty stdout for review %s. stderr: %s",
                model_name,
                review_id,
                result.stderr[:500] if result.stderr else "(no stderr)",
            )
            completed_at = datetime.now(timezone.utc)
            async with pool.acquire() as conn:
                await conn.execute(
                    "UPDATE reviews SET status = 'failed', raw_content = $1, completed_at = $2 WHERE id = $3",
                    "EXIT 0 BUT EMPTY OUTPUT\n\nSTDERR:\n" + (result.stderr or "(none)"),
                    completed_at,
                    review_id,
                )
            # finally block triggers _check_and_synthesize
            return

        # Extract session ID and review text from JSON output
        session_id_format = model_config.get("session_id_format")
        session_id, review_text = _extract_session_and_text(raw_output, session_id_format)

        if session_id:
            logger.info(
                "Captured session ID for review %s (model=%s): %s",
                review_id, model_name, session_id,
            )

        # Store review text — synthesis model reads this directly
        completed_at = datetime.now(timezone.utc)
        if result.stderr:
            logger.debug(
                "Review %s (model=%s) stderr: %s",
                review_id,
                model_name,
                result.stderr[:300],
            )
        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE reviews
                SET status = 'complete',
                    findings = NULL,
                    raw_content = $1,
                    completed_at = $2,
                    invocation_mode = $3,
                    session_id = $4
                WHERE id = $5
                """,
                review_text,
                completed_at,
                mode,
                session_id,
                review_id,
            )

        logger.info(
            "Review %s (model=%s, mode=%s) completed (%d chars)",
            review_id,
            model_name,
            mode,
            len(review_text),
        )

    except subprocess.TimeoutExpired:
        completed_at = datetime.now(timezone.utc)
        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE reviews
                SET status = 'timeout', completed_at = $1
                WHERE id = $2
                """,
                completed_at,
                review_id,
            )
        logger.warning(
            "Review %s (model=%s) timed out after %ds",
            review_id,
            model_name,
            model_config.get("timeout_seconds", 300),
        )

    except FileNotFoundError as exc:
        completed_at = datetime.now(timezone.utc)
        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE reviews
                SET status = 'failed', completed_at = $1
                WHERE id = $2
                """,
                completed_at,
                review_id,
            )
        logger.error(
            "Review %s (model=%s) failed — binary not found: %s",
            review_id,
            model_name,
            exc,
        )

    except Exception as exc:
        completed_at = datetime.now(timezone.utc)
        try:
            async with pool.acquire() as conn:
                await conn.execute(
                    """
                    UPDATE reviews
                    SET status = 'failed', completed_at = $1
                    WHERE id = $2
                    """,
                    completed_at,
                    review_id,
                )
        except Exception:
            logger.exception(
                "Failed to update review %s status after error", review_id
            )
        logger.error(
            "Review %s (model=%s) failed: %s", review_id, model_name, exc
        )

    finally:
        # Clean up temp directory
        if tmp_dir is not None:
            try:
                shutil.rmtree(tmp_dir, ignore_errors=True)
            except Exception:
                pass

        # Check if all reviews for this job are done
        try:
            await _check_and_synthesize(pool, job_id, review_type=review_type)
        except Exception:
            logger.exception(
                "Error checking/triggering synthesis for job %s", job_id
            )


# ---------------------------------------------------------------------------
# Internal: synthesis
# ---------------------------------------------------------------------------


async def _check_and_synthesize(
    pool: asyncpg.Pool, job_id: uuid.UUID, *, review_type: str = "general"
) -> None:
    """Check if all reviews for a job are done and trigger synthesis.

    Uses the UNIQUE(job_id) constraint on review_syntheses to prevent
    duplicate synthesis (race condition fix).
    """
    # Use a single transaction for atomic check-then-act
    async with pool.acquire() as conn:
        async with conn.transaction():
            pending_count = await conn.fetchval(
                """
                SELECT count(*)
                FROM reviews
                WHERE job_id = $1 AND status IN ('pending', 'running')
                """,
                job_id,
            )

            if pending_count > 0:
                return

            already_synthesized = await conn.fetchval(
                "SELECT 1 FROM review_syntheses WHERE job_id = $1",
                job_id,
            )
            if already_synthesized:
                return

            completed_rows = await conn.fetch(
                """
                SELECT id, model, findings, raw_content, artifact_id,
                       invocation_mode, session_id
                FROM reviews
                WHERE job_id = $1 AND status = 'complete'
                ORDER BY created_at ASC
                """,
                job_id,
            )

    if not completed_rows:
        # All reviews failed/timed out — create empty synthesis
        logger.warning(
            "All reviews for job %s failed — creating empty synthesis", job_id
        )
        try:
            async with pool.acquire() as conn:
                all_models = await conn.fetch(
                    "SELECT DISTINCT model FROM reviews WHERE job_id = $1",
                    job_id,
                )
                models_requested = [r["model"] for r in all_models]

                await conn.execute(
                    """
                    INSERT INTO review_syntheses (
                        job_id, review_ids, consensus, unique_findings,
                        contradictions, models_requested, models_responded
                    )
                    VALUES ($1, $2, '[]'::jsonb, '{}'::jsonb, '[]'::jsonb, $3, $4)
                    """,
                    job_id,
                    [],
                    models_requested,
                    [],
                )
        except asyncpg.UniqueViolationError:
            logger.info("Synthesis already exists for job %s (race resolved)", job_id)
        return

    await _synthesize_reviews(pool, job_id, completed_rows, review_type=review_type)


async def _synthesize_reviews(
    pool: asyncpg.Pool,
    job_id: uuid.UUID,
    reviews: list,
    *,
    review_type: str = "general",
) -> None:
    """Synthesize findings across multiple model reviews.

    Uses the synthesis model configured in review_models.yaml.
    Writes the synthesis prompt to a temp file (prevents ARG_MAX overflow).
    Records per-review invocation mode in the synthesis.
    After synthesis, invokes a second grading pass to rate each reviewer.
    """
    n_models = len(reviews)
    models_responded = [row["model"] for row in reviews]

    # Get all models that were requested (including failed ones)
    async with pool.acquire() as conn:
        all_model_rows = await conn.fetch(
            "SELECT DISTINCT model FROM reviews WHERE job_id = $1",
            job_id,
        )
    models_requested = [r["model"] for r in all_model_rows]

    # Get the artifact_id from the reviews (they all share the same one)
    source_artifact_id = None
    for row in reviews:
        if row["artifact_id"] is not None:
            source_artifact_id = str(row["artifact_id"])
            break

    # Collect per-review mode information
    review_modes = {}
    for row in reviews:
        mode = row.get("invocation_mode", "agentic")
        review_modes[row["model"]] = mode

    bundled_only_models = [m for m, mode in review_modes.items() if mode == "bundled"]

    # Build synthesis prompt
    mode_note = ""
    if bundled_only_models:
        mode_note = (
            f"\nNote: The following models reviewed in bundled mode (limited context, "
            f"no codebase exploration): {', '.join(bundled_only_models)}. "
            f"Flag any findings that came exclusively from bundled reviewers.\n"
        )

    synthesis_prompt = (
        f"Here are {n_models} model reviews of the same code. "
        "Read them and produce a synthesis:\n\n"
        "- What do multiple reviewers agree on? (high confidence)\n"
        "- What did only one reviewer catch? (note which model)\n"
        "- Where do they contradict each other?\n"
        "- Note the severity of each finding.\n"
        f"{mode_note}\n"
        "Write your synthesis as prose.\n\n"
        "Reviews:\n"
    )

    for row in reviews:
        mode = review_modes.get(row["model"], "agentic")
        synthesis_prompt += f"\n--- {row['model']} (mode: {mode}) ---\n"
        synthesis_prompt += row["raw_content"] or "(no output)"
        synthesis_prompt += "\n"

    # Get synthesis config
    synth_config = get_synthesis_config()
    synth_model = synth_config.get("model", "claude")
    synth_timeout = synth_config.get("timeout_seconds", 120)

    # Get the invoke command for the synthesis model
    registry = get_registry()
    synth_model_config = registry.get(synth_model)

    # Invoke synthesis
    synthesis_prose = ""
    tmp_dir = None

    try:
        # Write prompt to temp file (prevents ARG_MAX overflow)
        tmp_dir = tempfile.mkdtemp(prefix="synthesis_")
        prompt_path = os.path.join(tmp_dir, "synthesis_prompt.md")
        with open(prompt_path, "w", encoding="utf-8") as f:
            f.write(synthesis_prompt)

        if synth_model_config is None:
            raise RuntimeError(
                f"Synthesis model '{synth_model}' not found in registry — "
                "ensure review_models.yaml defines it"
            )

        # Use the configured model's invoke template
        cmd = []
        for arg in synth_model_config["invoke"]:
            cmd.append(
                arg.replace("{prompt_file}", prompt_path)
                .replace("{prompt}", synthesis_prompt)
            )
        # NOTE: Do NOT append clean_room_flags for synthesis — synthesis
        # summarizes already-collected reviews, it doesn't explore the codebase.

        subprocess_env = {k: v for k, v in os.environ.items() if k not in _STRIP_ENV_VARS}

        synth_run_kwargs: dict = dict(
            capture_output=True,
            text=True,
            timeout=synth_timeout,
            env=subprocess_env,
        )
        if synth_model_config.get("stdin_prompt", False):
            synth_run_kwargs["input"] = synthesis_prompt

        result = await asyncio.to_thread(
            subprocess.run,
            cmd,
            **synth_run_kwargs,
        )

        if result.returncode == 0 and result.stdout.strip():
            raw_synth = re.sub(r'\x1b\[[0-9;]*m', '', result.stdout).strip()
            synth_session_id_format = synth_model_config.get("session_id_format")
            _, synthesis_prose = _extract_session_and_text(raw_synth, synth_session_id_format)
        else:
            logger.warning(
                "Synthesis CLI returned non-zero or empty for job %s: %s",
                job_id,
                result.stderr[:500] if result.stderr else "(no stderr)",
            )

    except subprocess.TimeoutExpired:
        logger.error("Synthesis timed out for job %s", job_id)
    except FileNotFoundError:
        logger.error(
            "Synthesis CLI not found — cannot synthesize reviews for job %s",
            job_id,
        )
    except Exception:
        logger.exception("Synthesis failed for job %s", job_id)
    finally:
        if tmp_dir is not None:
            try:
                shutil.rmtree(tmp_dir, ignore_errors=True)
            except Exception:
                pass

    # --- Peer-disagreement follow-up (best-effort) ---
    # Identify contradictions in the synthesis and resume reviewer sessions.
    peer_disagreements: list[dict] = []
    if synthesis_prose:
        try:
            peer_disagreements = await _peer_followup(
                pool=pool,
                job_id=job_id,
                reviews=reviews,
                synthesis_prose=synthesis_prose,
            )
        except Exception:
            logger.warning("Peer follow-up failed for job %s, continuing", job_id, exc_info=True)

    # --- Quality grading (best-effort) ---
    # After synthesis, invoke a second model call to grade each reviewer.
    # This is supplementary signal — failures here must not crash the review.
    if synthesis_prose and synth_model_config is not None:
        await _grade_reviewers(
            pool=pool,
            job_id=job_id,
            reviews=reviews,
            review_modes=review_modes,
            synthesis_prose=synthesis_prose,
            synth_model_config=synth_model_config,
            synth_timeout=synth_timeout,
            review_type=review_type,
            peer_disagreements=peer_disagreements,
        )

    # Store individual reviews as artifacts
    review_ids: list[uuid.UUID] = []
    for row in reviews:
        review_ids.append(row["id"])

        try:
            review_artifact = await artifact_store_module.store_artifact(
                pool,
                content=row["raw_content"] or "",
                artifact_type="review",
                tags=["review", row["model"]],
                source_ref=f"review:{job_id}",
            )
            review_artifact_id = review_artifact["artifact_id"]

            # Update review row with artifact reference
            async with pool.acquire() as conn:
                await conn.execute(
                    """
                    UPDATE reviews
                    SET review_artifact_id = $1::uuid
                    WHERE id = $2
                    """,
                    review_artifact_id,
                    row["id"],
                )
        except Exception:
            logger.exception(
                "Failed to store review artifact for review %s", row["id"]
            )

    # Store synthesis as artifact (prose, not structured JSON)
    synthesis_artifact_id: str | None = None

    try:
        synth_artifact = await artifact_store_module.store_artifact(
            pool,
            content=synthesis_prose,
            artifact_type="review-synthesis",
            tags=["review-synthesis"],
            source_ref=f"review-synthesis:{job_id}",
        )
        synthesis_artifact_id = synth_artifact["artifact_id"]
    except Exception:
        logger.exception(
            "Failed to store synthesis artifact for job %s", job_id
        )

    # Insert review_syntheses row (UNIQUE(job_id) prevents duplicates)
    # consensus/unique_findings deprecated — contradictions populated from peer-disagreement
    contradictions_json = json.dumps(peer_disagreements) if peer_disagreements else '[]'
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO review_syntheses (
                    job_id, artifact_id, synthesis_artifact_id,
                    review_ids, consensus, unique_findings,
                    contradictions, models_requested, models_responded,
                    review_modes
                )
                VALUES ($1, $2, $3, $4, $5::jsonb, $6::jsonb, $7::jsonb, $8, $9, $10::jsonb)
                """,
                job_id,
                uuid.UUID(source_artifact_id) if source_artifact_id else None,
                uuid.UUID(synthesis_artifact_id) if synthesis_artifact_id else None,
                review_ids,
                '[]',
                '{}',
                contradictions_json,
                models_requested,
                models_responded,
                json.dumps(review_modes),
            )
    except asyncpg.UniqueViolationError:
        logger.info("Synthesis already exists for job %s (race resolved)", job_id)
    except Exception:
        logger.exception(
            "Failed to insert review_syntheses row for job %s", job_id
        )

    logger.info(
        "Synthesis complete for job %s (%d models, %d chars prose)",
        job_id,
        n_models,
        len(synthesis_prose),
    )


async def _peer_followup(
    pool: asyncpg.Pool,
    job_id: uuid.UUID,
    reviews: list,
    synthesis_prose: str,
) -> list[dict]:
    """Identify contradictions in synthesis and resume reviewer sessions for follow-up.

    Asks the synthesis model to identify contradictions, then resumes each
    contradicted reviewer's session with an anonymous follow-up prompt.

    Returns a list of contradiction dicts with resolutions, or empty list
    if no contradictions or if follow-up fails.
    """
    registry = get_registry()
    synth_config = get_synthesis_config()
    synth_model_config = registry.get(synth_config.get("model", "claude"))
    synth_timeout = synth_config.get("timeout_seconds", 120)

    if synth_model_config is None:
        return []

    # --- Step 1: Ask synthesizer to identify contradictions as structured data ---
    contradiction_prompt = (
        "Review this synthesis and identify any contradictions between reviewers.\n\n"
        "A contradiction is where two or more reviewers reached CONFLICTING assessments "
        "of the same code location or topic. Unique findings (only one reviewer mentions it) "
        "are NOT contradictions. Different detail levels on the same finding are NOT contradictions.\n\n"
        f"## Synthesis\n{synthesis_prose}\n\n"
        "Output ONLY a JSON array (no markdown fences, no extra text). "
        "Each entry: {\"topic\": \"...\", \"location\": \"file:line or null\", "
        "\"positions\": [{\"reviewer\": \"model_name\", \"assessment\": \"...\"}]}\n"
        "If no contradictions, output: []"
    )

    tmp_dir = None
    contradictions = []

    try:
        tmp_dir = tempfile.mkdtemp(prefix="contradiction_")
        prompt_path = os.path.join(tmp_dir, "contradiction_prompt.md")
        with open(prompt_path, "w", encoding="utf-8") as f:
            f.write(contradiction_prompt)

        cmd = []
        for arg in synth_model_config["invoke"]:
            cmd.append(
                arg.replace("{prompt_file}", prompt_path)
                .replace("{prompt}", contradiction_prompt)
            )

        subprocess_env = {k: v for k, v in os.environ.items() if k not in _STRIP_ENV_VARS}
        run_kwargs: dict = dict(
            capture_output=True, text=True, timeout=synth_timeout, env=subprocess_env,
        )
        if synth_model_config.get("stdin_prompt", False):
            run_kwargs["input"] = contradiction_prompt

        result = await asyncio.to_thread(subprocess.run, cmd, **run_kwargs)

        if result.returncode != 0 or not result.stdout.strip():
            logger.warning("Contradiction detection failed for job %s", job_id)
            return []

        raw = re.sub(r'\x1b\[[0-9;]*m', '', result.stdout).strip()
        # Extract text from JSON wrapper if needed
        _, text = _extract_session_and_text(raw, synth_model_config.get("session_id_format"))

        parsed = _parse_grades_json(text)  # reuse JSON array parser
        if not parsed:
            # Try direct parse of the text
            try:
                parsed = json.loads(text)
            except (json.JSONDecodeError, ValueError):
                pass

        if not isinstance(parsed, list) or len(parsed) == 0:
            logger.info("No contradictions found for job %s", job_id)
            return []

        contradictions = parsed
        logger.info("Found %d contradictions for job %s", len(contradictions), job_id)

    except (subprocess.TimeoutExpired, Exception) as exc:
        logger.warning("Contradiction detection failed for job %s: %s", job_id, exc)
        return []
    finally:
        if tmp_dir:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    # --- Step 2: Resume reviewer sessions for each contradiction ---
    # Build session_id map from reviews
    session_map: dict[str, tuple[str, dict]] = {}  # model -> (session_id, model_config)
    for row in reviews:
        sid = row.get("session_id")
        model = row["model"]
        mcfg = registry.get(model)
        if sid and mcfg and mcfg.get("resume_cmd"):
            session_map[model] = (sid, mcfg)

    for contradiction in contradictions:
        positions = contradiction.get("positions", [])
        resolutions = []

        for position in positions:
            reviewer = position.get("reviewer", "")
            if reviewer not in session_map:
                resolutions.append({
                    "reviewer": reviewer,
                    "stance": "unresolved",
                    "reason": "no session ID or no resume support",
                })
                continue

            session_id, mcfg = session_map[reviewer]
            other_positions = [p for p in positions if p["reviewer"] != reviewer]
            if not other_positions:
                continue

            # Build anonymous follow-up prompt
            other_desc = "; ".join(
                f"Another reviewer's assessment: {p['assessment']}"
                for p in other_positions
            )
            followup_prompt = (
                f"A peer reviewer assessed \"{contradiction.get('topic', 'this area')}\" "
                f"differently from you.\n\n"
                f"{other_desc}\n\n"
                f"Your assessment: {position.get('assessment', '(not captured)')}\n\n"
                "Please respond:\n"
                "1. Do you CONCEDE (they're right)?\n"
                "2. Do you DEFEND your position (cite specific evidence)?\n\n"
                "Output a JSON object: {\"stance\": \"conceded\" or \"defended\", "
                "\"evidence\": \"your reasoning\"}"
            )

            # Build resume command
            resume_cmd_template = mcfg["resume_cmd"]
            resume_cmd = [
                arg.replace("{session_id}", session_id)
                for arg in resume_cmd_template
            ]

            try:
                subprocess_env = {k: v for k, v in os.environ.items() if k not in _STRIP_ENV_VARS}
                run_kwargs = dict(
                    capture_output=True, text=True,
                    timeout=mcfg.get("timeout_seconds", 300),
                    env=subprocess_env,
                    input=followup_prompt,
                )

                followup_result = await asyncio.to_thread(
                    subprocess.run, resume_cmd, **run_kwargs,
                )

                if followup_result.returncode == 0 and followup_result.stdout.strip():
                    raw_resp = re.sub(r'\x1b\[[0-9;]*m', '', followup_result.stdout).strip()
                    _, resp_text = _extract_session_and_text(
                        raw_resp, mcfg.get("session_id_format")
                    )
                    # Try to parse stance from response
                    try:
                        resp_data = json.loads(resp_text)
                        stance = resp_data.get("stance", "defended")
                        evidence = resp_data.get("evidence", resp_text)
                    except (json.JSONDecodeError, ValueError):
                        # Model didn't output JSON — infer from text
                        lower = resp_text.lower()
                        if "concede" in lower or "you're right" in lower or "i was wrong" in lower:
                            stance = "conceded"
                        else:
                            stance = "defended"
                        evidence = resp_text

                    resolutions.append({
                        "reviewer": reviewer,
                        "stance": stance,
                        "evidence": evidence[:500],
                    })
                    logger.info(
                        "Peer follow-up for %s on '%s': %s",
                        reviewer, contradiction.get("topic", "?"), stance,
                    )
                else:
                    resolutions.append({
                        "reviewer": reviewer,
                        "stance": "unresolved",
                        "reason": "session resume failed or empty response",
                    })
            except subprocess.TimeoutExpired:
                resolutions.append({
                    "reviewer": reviewer,
                    "stance": "unresolved",
                    "reason": "session resume timed out",
                })
            except Exception as exc:
                resolutions.append({
                    "reviewer": reviewer,
                    "stance": "unresolved",
                    "reason": str(exc)[:200],
                })
                logger.warning("Peer follow-up failed for %s: %s", reviewer, exc)

        contradiction["resolutions"] = resolutions

    return contradictions


async def _grade_reviewers(
    *,
    pool: asyncpg.Pool,
    job_id: uuid.UUID,
    reviews: list,
    review_modes: dict[str, str],
    synthesis_prose: str,
    synth_model_config: dict,
    synth_timeout: int,
    review_type: str,
    peer_disagreements: list[dict] | None = None,
) -> None:
    """Grade each reviewer's quality, potentially with cross-model grading.

    Cross-grading policy:
    - First 20 review cycles: every grader grades every review (N×N matrix)
    - After 20 cycles: synthesizer-only grading, unless contradictions found
      or cycle count mod 5 == 0 (then full cross-grading)

    Best-effort: failures are logged, not raised.
    """
    # Determine cross-grading policy
    async with pool.acquire() as conn:
        cross_grade_count = await conn.fetchval(
            "SELECT COUNT(DISTINCT job_id) FROM review_grades WHERE grader_model IS NOT NULL"
        ) or 0

    has_contradictions = bool(peer_disagreements)
    do_full_cross_grading = (
        cross_grade_count < 20
        or has_contradictions
        or (cross_grade_count % 5 == 0)
    )

    peer_json = json.dumps(peer_disagreements) if peer_disagreements else None

    # Determine which models will grade
    registry = get_registry()
    if do_full_cross_grading:
        # Each reviewer model grades all reviews
        grader_configs = []
        for row in reviews:
            mcfg = registry.get(row["model"])
            if mcfg:
                grader_configs.append((row["model"], mcfg))
        # Also include synthesizer if not already a reviewer
        synth_name = get_synthesis_config().get("model", "claude")
        if synth_name not in [g[0] for g in grader_configs]:
            grader_configs.append((synth_name, synth_model_config))
        logger.info(
            "Full cross-grading for job %s: %d graders (cycle %d, contradictions=%s)",
            job_id, len(grader_configs), cross_grade_count, has_contradictions,
        )
    else:
        # Synthesizer-only grading
        synth_name = get_synthesis_config().get("model", "claude")
        grader_configs = [(synth_name, synth_model_config)]
        logger.info("Synthesizer-only grading for job %s (cycle %d)", job_id, cross_grade_count)

    # Guard: skip if grades already exist for this job
    async with pool.acquire() as conn:
        existing = await conn.fetchval(
            "SELECT COUNT(*) FROM review_grades WHERE job_id = $1", job_id,
        )
        if existing > 0:
            logger.info("Grades already exist for job %s (%d rows), skipping", job_id, existing)
            return

    # Run grading for each grader model
    for grader_name, grader_config in grader_configs:
        await _run_single_grading(
            pool=pool,
            job_id=job_id,
            reviews=reviews,
            review_modes=review_modes,
            synthesis_prose=synthesis_prose,
            grader_name=grader_name,
            grader_config=grader_config,
            grader_timeout=grader_config.get("timeout_seconds", synth_timeout),
            review_type=review_type,
            peer_json=peer_json,
        )


async def _run_single_grading(
    *,
    pool: asyncpg.Pool,
    job_id: uuid.UUID,
    reviews: list,
    review_modes: dict[str, str],
    synthesis_prose: str,
    grader_name: str,
    grader_config: dict,
    grader_timeout: int,
    review_type: str,
    peer_json: str | None = None,
) -> None:
    """Run a single grading session — one grader model grades all reviews.

    Best-effort: failures are logged, not raised.
    """
    valid_grades = {"EXCELLENT", "ADEQUATE", "INADEQUATE", "HARMFUL"}
    valid_failure_modes = {
        "no_output", "false_positive", "false_negative",
        "wrong_severity", "hallucinated_evidence", "credulous", "shallow",
    }

    grading_prompt_parts = [
        "You are grading the quality of code reviews. "
        "The synthesis below represents the merged consensus — use it as an approximate answer key.\n\n",
        "## Synthesis\n",
        synthesis_prose,
        "\n\n## Individual Reviews\n",
    ]
    for row in reviews:
        mode = review_modes.get(row["model"], "agentic")
        grading_prompt_parts.append(f"\n--- {row['model']} (mode: {mode}) ---\n")
        grading_prompt_parts.append(row["raw_content"] or "(no output)")
        grading_prompt_parts.append("\n")

    grading_prompt_parts.append(
        "\n## Instructions\n"
        "For each reviewer model, provide a quality grade.\n\n"
        "**Grade:** EXCELLENT | ADEQUATE | INADEQUATE | HARMFUL\n"
        "**Failure mode** (required if INADEQUATE or HARMFUL): "
        "no_output | false_positive | false_negative | wrong_severity | "
        "hallucinated_evidence | credulous | shallow\n"
        "**Note:** 2-3 sentence justification\n\n"
        "Output ONLY a JSON array (no markdown fences, no extra text):\n"
        '[{"model": "model_name", "grade": "GRADE", '
        '"failure_mode": null, "note": "brief reasoning"}]\n'
    )
    grading_prompt = "".join(grading_prompt_parts)

    tmp_dir = None
    try:
        tmp_dir = tempfile.mkdtemp(prefix="grading_")
        prompt_path = os.path.join(tmp_dir, "grading_prompt.md")
        with open(prompt_path, "w", encoding="utf-8") as f:
            f.write(grading_prompt)

        # Build grading command. Grading is text-in/JSON-out — no tool access
        # needed. Use grading_cmd if defined, otherwise fall back to invoke.
        grading_cmd_template = grader_config.get("grading_cmd") or grader_config["invoke"]
        cmd = []
        for arg in grading_cmd_template:
            cmd.append(
                arg.replace("{prompt_file}", prompt_path)
                .replace("{prompt}", grading_prompt)
            )

        subprocess_env = {k: v for k, v in os.environ.items() if k not in _STRIP_ENV_VARS}

        run_kwargs: dict = dict(
            capture_output=True, text=True, timeout=grader_timeout, env=subprocess_env,
        )
        if grader_config.get("stdin_prompt", False):
            run_kwargs["input"] = grading_prompt

        result = await asyncio.to_thread(subprocess.run, cmd, **run_kwargs)

        if result.returncode != 0 or not result.stdout.strip():
            logger.warning(
                "Grader %s returned non-zero or empty for job %s: rc=%d",
                grader_name, job_id, result.returncode,
            )
            return

        raw_output = re.sub(r'\x1b\[[0-9;]*m', '', result.stdout).strip()

        # Extract text from JSON wrapper if needed
        _, grade_text = _extract_session_and_text(raw_output, grader_config.get("session_id_format"))

        parsed_grades = _parse_grades_json(grade_text)
        if parsed_grades is None:
            logger.warning(
                "Could not parse grading JSON from %s for job %s. Raw: %.300s",
                grader_name, job_id, grade_text,
            )
            return

        inserted = 0
        async with pool.acquire() as conn:
            for entry in parsed_grades:
                if not isinstance(entry, dict):
                    continue
                model_name = entry.get("model", "")
                grade = entry.get("grade", "")
                note = entry.get("note", "")
                failure_mode = entry.get("failure_mode")

                if grade not in valid_grades:
                    logger.warning(
                        "Skipping invalid grade '%s' for model '%s' from grader %s",
                        grade, model_name, grader_name,
                    )
                    continue

                # Validate failure_mode
                if failure_mode and failure_mode not in valid_failure_modes:
                    failure_mode = None
                if grade in ("EXCELLENT", "ADEQUATE"):
                    failure_mode = None

                await conn.execute(
                    """
                    INSERT INTO review_grades (
                        job_id, model_name, review_type, grade, note,
                        grader_model, failure_mode, review_target, peer_disagreement
                    )
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9::jsonb)
                    """,
                    job_id,
                    model_name,
                    review_type,
                    grade,
                    note,
                    grader_name,
                    failure_mode,
                    review_type,  # review_target = review_type for now
                    peer_json,
                )
                inserted += 1

        logger.info(
            "Grading by %s for job %s: %d grades inserted",
            grader_name, job_id, inserted,
        )

    except subprocess.TimeoutExpired:
        logger.warning("Grading by %s timed out for job %s", grader_name, job_id)
    except Exception:
        logger.warning("Grading by %s failed for job %s", grader_name, job_id, exc_info=True)
    finally:
        if tmp_dir:
            shutil.rmtree(tmp_dir, ignore_errors=True)


def _extract_session_and_text(raw_output: str, session_id_format: str | None) -> tuple[str | None, str]:
    """Extract session ID and review text from CLI JSON output.

    Different CLIs embed the review text and session ID differently:
    - claude: JSON with "result" (text) and "session_id"
    - gemini: JSON with "response" or "text" and "session_id"
    - codex: JSONL where first line has "thread_id", agent messages have content

    If session_id_format is None, returns (None, raw_output) unchanged.

    Returns:
        (session_id, review_text) — session_id may be None if not parseable.
    """
    if not session_id_format:
        return None, raw_output

    session_id = None
    review_text = raw_output  # fallback

    try:
        if session_id_format == "claude":
            data = json.loads(raw_output)
            session_id = data.get("session_id")
            review_text = data.get("result", raw_output)

        elif session_id_format == "gemini":
            data = json.loads(raw_output)
            session_id = data.get("session_id")
            # Gemini may use "response", "text", or "content"
            review_text = data.get("response") or data.get("text") or data.get("content") or raw_output

        elif session_id_format == "codex":
            # JSONL: first line has thread_id, agent messages have content
            lines = raw_output.strip().split("\n")
            text_parts = []
            for line in lines:
                try:
                    obj = json.loads(line)
                except (json.JSONDecodeError, ValueError):
                    continue
                if obj.get("thread_id") and not session_id:
                    session_id = obj["thread_id"]
                # Extract text from agent messages
                if obj.get("type") == "item.completed":
                    item = obj.get("item", {})
                    if item.get("type") == "agent_message":
                        content = item.get("content", [])
                        for block in content:
                            if isinstance(block, dict) and block.get("text"):
                                text_parts.append(block["text"])
            if text_parts:
                review_text = "\n\n".join(text_parts)

    except (json.JSONDecodeError, ValueError, TypeError) as exc:
        logger.warning("Failed to parse %s JSON output: %s", session_id_format, exc)

    return session_id, review_text


def _parse_grades_json(raw: str) -> list[dict] | None:
    """Extract and parse a JSON array from model output.

    Tries direct parse first, then looks for a JSON array within the text.
    Returns None if parsing fails entirely.
    """
    # Try direct parse
    try:
        result = json.loads(raw)
        if isinstance(result, list):
            return result
    except (json.JSONDecodeError, ValueError):
        pass

    # Try to find a JSON array in the output (model may wrap in markdown fences)
    match = re.search(r'\[.*\]', raw, re.DOTALL)
    if match:
        try:
            result = json.loads(match.group(0))
            if isinstance(result, list):
                return result
        except (json.JSONDecodeError, ValueError):
            pass

    return None


# ---------------------------------------------------------------------------
# Public API: review quality
# ---------------------------------------------------------------------------


async def get_review_quality(
    pool: asyncpg.Pool,
    model_name: str,
    review_type: str | None = None,
) -> list[dict]:
    """Query review quality grades for a specific model.

    Args:
        pool: asyncpg connection pool.
        model_name: The model name to filter by.
        review_type: Optional review type filter (e.g. "spec", "code").
                     If None, returns grades across all review types.

    Returns:
        A list of dicts with keys: job_id, grade, note, review_type, created_at.
    """
    async with pool.acquire() as conn:
        if review_type is not None:
            rows = await conn.fetch(
                """
                SELECT job_id, grade, note, review_type, created_at
                FROM review_grades
                WHERE model_name = $1 AND review_type = $2
                ORDER BY created_at DESC
                """,
                model_name,
                review_type,
            )
        else:
            rows = await conn.fetch(
                """
                SELECT job_id, grade, note, review_type, created_at
                FROM review_grades
                WHERE model_name = $1
                ORDER BY created_at DESC
                """,
                model_name,
            )

    return [
        {
            "job_id": str(row["job_id"]),
            "grade": row["grade"],
            "note": row["note"],
            "review_type": row["review_type"],
            "created_at": row["created_at"].isoformat() if row["created_at"] else None,
        }
        for row in rows
    ]
