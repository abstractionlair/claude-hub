"""
Observation Store for Claude Hub

Persistent storage for observations that accumulate across sessions.
Unlike window files (point-in-time snapshots), this is a stream of learnings.

Usage:
    store = ObservationStore(dsn="postgresql://...")

    # Record an observation
    store.record(
        category="belief",
        content="Session middleware requires X-Auth-Token header",
        tags=["auth", "session", "middleware"],
        confidence=0.8
    )

    # Get relevant observations for current context
    observations = store.get_relevant(tags=["auth"], limit=10)

    # Confirm an observation was accurate
    store.confirm(observation_id)

    # Refute an observation
    store.refute(observation_id, reason="Actually uses Bearer token")
"""

import json
import psycopg2
import psycopg2.extras
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Optional


@dataclass
class Observation:
    """A single observation that persists across sessions."""
    id: str
    created_at: str  # ISO format
    last_referenced: str  # ISO format
    category: str  # belief | preference | anti-pattern | codebase-fact | meta-calibration
    confidence: float  # 0.0 to 1.0
    content: str
    tags: list[str]
    source_session: Optional[str] = None
    confirmations: int = 0
    refutations: int = 0

    def effective_confidence(self) -> float:
        """Calculate confidence with time-based decay."""
        last_ref = datetime.fromisoformat(self.last_referenced)
        # Make naive for comparison if needed
        now = datetime.now(timezone.utc)
        if last_ref.tzinfo is None:
            last_ref = last_ref.replace(tzinfo=timezone.utc)
        days_since = (now - last_ref).days
        decay_factor = 0.95 ** (days_since / 7)  # ~5% decay per week
        return self.confidence * decay_factor

    def to_context_string(self) -> str:
        """Format for injection into context."""
        conf_pct = int(self.effective_confidence() * 100)
        return f"[{self.category}] {self.content} (confidence: {conf_pct}%)"


class ObservationStore:
    """PostgreSQL-backed store for observations."""

    def __init__(self, dsn: Optional[str] = None):
        if dsn is None:
            import os
            dsn = os.environ.get("CLAUDE_HUB_PG_DSN", "")
        self.dsn = dsn
        self._ensure_schema()

    @contextmanager
    def _get_conn(self):
        conn = psycopg2.connect(self.dsn)
        try:
            yield conn
        finally:
            conn.close()

    def _ensure_schema(self):
        """Ensure database schema exists."""
        with self._get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS observations (
                        id TEXT PRIMARY KEY,
                        created_at TIMESTAMPTZ NOT NULL,
                        last_referenced TIMESTAMPTZ NOT NULL,
                        category TEXT NOT NULL,
                        confidence REAL NOT NULL,
                        content TEXT NOT NULL,
                        tags JSONB NOT NULL,
                        source_session TEXT,
                        confirmations INTEGER DEFAULT 0,
                        refutations INTEGER DEFAULT 0
                    )
                """)
                cur.execute("CREATE INDEX IF NOT EXISTS idx_observations_category ON observations(category)")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_observations_last_referenced ON observations(last_referenced)")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_observations_confidence ON observations(confidence)")
            conn.commit()

    def record(
        self,
        category: str,
        content: str,
        tags: list[str],
        confidence: float = 0.7,
        source_session: Optional[str] = None
    ) -> Observation:
        """Record a new observation."""
        now = datetime.now(timezone.utc)
        now_iso = now.isoformat()
        obs = Observation(
            id=str(uuid.uuid4()),
            created_at=now_iso,
            last_referenced=now_iso,
            category=category,
            confidence=confidence,
            content=content,
            tags=tags,
            source_session=source_session,
            confirmations=0,
            refutations=0
        )

        with self._get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO observations
                    (id, created_at, last_referenced, category, confidence, content, tags, source_session, confirmations, refutations)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (
                    obs.id, now, now, obs.category,
                    obs.confidence, obs.content, json.dumps(obs.tags),
                    obs.source_session, obs.confirmations, obs.refutations
                ))
            conn.commit()

        return obs

    def get_by_id(self, observation_id: str) -> Optional[Observation]:
        """Get a single observation by ID."""
        with self._get_conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    "SELECT * FROM observations WHERE id = %s",
                    (observation_id,)
                )
                row = cur.fetchone()

                if row:
                    return self._row_to_observation(row)
        return None

    def get_recent(self, days: int = 30, limit: int = 20, min_confidence: float = 0.3) -> list[Observation]:
        """Get recent observations above confidence threshold."""
        with self._get_conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("""
                    SELECT * FROM observations
                    WHERE confidence >= %s
                    ORDER BY last_referenced DESC
                    LIMIT %s
                """, (min_confidence, limit))
                rows = cur.fetchall()

                observations = [self._row_to_observation(row) for row in rows]
                # Filter by effective confidence and sort
                return sorted(
                    [o for o in observations if o.effective_confidence() >= min_confidence],
                    key=lambda o: o.effective_confidence(),
                    reverse=True
                )

    def get_relevant(self, tags: list[str], limit: int = 10, min_confidence: float = 0.3) -> list[Observation]:
        """Get observations matching given tags, scored by relevance."""
        # Get all observations above threshold
        with self._get_conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("""
                    SELECT * FROM observations
                    WHERE confidence >= %s
                """, (min_confidence,))
                rows = cur.fetchall()

                observations = [self._row_to_observation(row) for row in rows]

        # Score by tag overlap and effective confidence
        def score(obs: Observation) -> float:
            tag_overlap = len(set(obs.tags) & set(tags))
            if tag_overlap == 0:
                return 0.0
            return tag_overlap * obs.effective_confidence()

        scored = [(obs, score(obs)) for obs in observations]
        scored = [(obs, s) for obs, s in scored if s > 0]
        scored.sort(key=lambda x: x[1], reverse=True)

        return [obs for obs, _ in scored[:limit]]

    def confirm(self, observation_id: str) -> bool:
        """Confirm an observation was accurate. Boosts confidence slightly."""
        with self._get_conn() as conn:
            with conn.cursor() as cur:
                now = datetime.now(timezone.utc)
                cur.execute("""
                    UPDATE observations
                    SET confirmations = confirmations + 1,
                        last_referenced = %s,
                        confidence = LEAST(1.0, confidence + 0.05)
                    WHERE id = %s
                """, (now, observation_id))
            conn.commit()
            return cur.rowcount > 0

    def refute(self, observation_id: str, reason: Optional[str] = None) -> bool:
        """Refute an observation. Reduces confidence."""
        with self._get_conn() as conn:
            with conn.cursor() as cur:
                now = datetime.now(timezone.utc)
                cur.execute("""
                    UPDATE observations
                    SET refutations = refutations + 1,
                        last_referenced = %s,
                        confidence = GREATEST(0.0, confidence - 0.2)
                    WHERE id = %s
                """, (now, observation_id))
            conn.commit()
            return cur.rowcount > 0

    def get_stats(self) -> dict:
        """Get statistics about the observation store."""
        with self._get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM observations")
                total = cur.fetchone()[0]
                cur.execute("""
                    SELECT category, COUNT(*) FROM observations GROUP BY category
                """)
                by_category = dict(cur.fetchall())
                cur.execute(
                    "SELECT AVG(confidence) FROM observations"
                )
                avg_confidence = cur.fetchone()[0] or 0.0

                return {
                    "total_observations": total,
                    "by_category": by_category,
                    "average_confidence": round(avg_confidence, 2)
                }

    def format_for_context(self, observations: list[Observation]) -> str:
        """Format observations for injection into Claude's context."""
        if not observations:
            return ""

        lines = ["## Loaded Observations", ""]
        for obs in observations:
            lines.append(f"- {obs.to_context_string()}")
        lines.append("")
        return "\n".join(lines)

    def _row_to_observation(self, row: dict) -> Observation:
        """Convert a database row to an Observation."""
        tags_raw = row["tags"]
        if isinstance(tags_raw, list):
            tags = tags_raw
        elif isinstance(tags_raw, str):
            tags = json.loads(tags_raw)
        else:
            tags = []

        created_at = row["created_at"]
        last_referenced = row["last_referenced"]
        # Convert datetime objects to ISO strings
        if isinstance(created_at, datetime):
            created_at = created_at.isoformat()
        if isinstance(last_referenced, datetime):
            last_referenced = last_referenced.isoformat()

        return Observation(
            id=row["id"],
            created_at=created_at,
            last_referenced=last_referenced,
            category=row["category"],
            confidence=row["confidence"],
            content=row["content"],
            tags=tags,
            source_session=row["source_session"],
            confirmations=row["confirmations"],
            refutations=row["refutations"]
        )


# Marker parsing for extracting observations from Claude's responses
import re

OBSERVE_PATTERN = re.compile(
    r'\[OBSERVE:\s*category=(\w+),\s*confidence=([\d.]+),\s*tags=([^\]]+)\]\s*\n(.+?)\n\[/OBSERVE\]',
    re.DOTALL
)

CONFIRM_PATTERN = re.compile(r'\[CONFIRM:\s*([a-f0-9-]+)\]')
REFUTE_PATTERN = re.compile(r'\[REFUTE:\s*([a-f0-9-]+)(?:,\s*reason="([^"]*)")?\]')


def parse_observation_markers(text: str, store: ObservationStore, session_id: Optional[str] = None) -> list[Observation]:
    """Parse observation markers from text and record them."""
    recorded = []

    # Parse [OBSERVE:...] blocks
    for match in OBSERVE_PATTERN.finditer(text):
        category = match.group(1)
        confidence = float(match.group(2))
        tags = [t.strip() for t in match.group(3).split(",")]
        content = match.group(4).strip()

        obs = store.record(
            category=category,
            content=content,
            tags=tags,
            confidence=confidence,
            source_session=session_id
        )
        recorded.append(obs)

    # Parse [CONFIRM:...] markers
    for match in CONFIRM_PATTERN.finditer(text):
        store.confirm(match.group(1))

    # Parse [REFUTE:...] markers
    for match in REFUTE_PATTERN.finditer(text):
        store.refute(match.group(1), match.group(2))

    return recorded


def extract_keywords(text: str) -> list[str]:
    """Extract potential tag keywords from text for retrieval."""
    # Simple keyword extraction - skip common words
    stopwords = {
        'the', 'a', 'an', 'is', 'are', 'was', 'were', 'be', 'been', 'being',
        'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would', 'could',
        'should', 'may', 'might', 'can', 'this', 'that', 'these', 'those',
        'i', 'you', 'he', 'she', 'it', 'we', 'they', 'what', 'which', 'who',
        'when', 'where', 'why', 'how', 'all', 'each', 'every', 'both', 'few',
        'more', 'most', 'other', 'some', 'such', 'no', 'not', 'only', 'own',
        'same', 'so', 'than', 'too', 'very', 'just', 'and', 'but', 'or', 'if',
        'because', 'as', 'until', 'while', 'of', 'at', 'by', 'for', 'with',
        'about', 'against', 'between', 'into', 'through', 'during', 'before',
        'after', 'above', 'below', 'to', 'from', 'up', 'down', 'in', 'out',
        'on', 'off', 'over', 'under', 'again', 'further', 'then', 'once',
        'here', 'there', 'any', 'let', 'me', 'my', 'your', 'our', 'their',
        'please', 'thanks', 'thank', 'hello', 'hi', 'hey'
    }

    # Extract words, lowercase, filter
    words = re.findall(r'\b[a-zA-Z]{3,}\b', text.lower())
    keywords = [w for w in words if w not in stopwords]

    # Return unique keywords, preserving order
    seen = set()
    result = []
    for w in keywords:
        if w not in seen:
            seen.add(w)
            result.append(w)

    return result[:20]  # Limit to top 20
