"""Scheduling facility for periodic agent wake-ups."""

import psycopg2
import psycopg2.extras
import json
import threading
import time
import uuid
from contextlib import contextmanager
from typing import Optional, List, Callable
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta


@dataclass
class Schedule:
    """A scheduled wake-up."""
    schedule_id: str
    session_id: str
    next_wake: datetime
    interval: Optional[timedelta]  # None for one-time, timedelta for recurring
    prompt: str
    constraints_json: str  # JSON-serialized ResourceConstraints
    end_time: Optional[datetime] = None
    created_at: datetime = None


class Scheduler:
    """
    Cron-like scheduling for agent wake-ups.

    Runs a background thread that checks for due schedules every 30 seconds.
    When a schedule is due, calls the wake_callback with (session_id, prompt, constraints).
    """

    def __init__(self, dsn: str, wake_callback: Callable):
        """
        Initialize scheduler.

        Args:
            dsn: PostgreSQL connection DSN
            wake_callback: Function to call when schedule is due
                          Signature: wake_callback(session_id: str, prompt: str, constraints: dict)
        """
        self.dsn = dsn
        self.wake_callback = wake_callback
        self._running = False
        self._thread: Optional[threading.Thread] = None
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
                    CREATE TABLE IF NOT EXISTS schedules (
                        schedule_id TEXT PRIMARY KEY,
                        session_id TEXT NOT NULL,
                        next_wake TIMESTAMPTZ NOT NULL,
                        interval_seconds INTEGER,
                        prompt TEXT NOT NULL,
                        constraints_json JSONB,
                        end_time TIMESTAMPTZ,
                        created_at TIMESTAMPTZ NOT NULL
                    )
                """)
                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_schedules_next_wake ON schedules(next_wake)
                """)
            conn.commit()

    def start(self):
        """Start the scheduler background thread."""
        if self._running:
            return

        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def stop(self):
        """Stop the scheduler background thread."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)

    def _run_loop(self):
        """Background loop that checks for due schedules."""
        while self._running:
            try:
                self._check_due_schedules()
            except Exception as e:
                print(f"[Scheduler] Error checking schedules: {e}")

            # Sleep for 30 seconds, but check _running every second for fast shutdown
            for _ in range(30):
                if not self._running:
                    break
                time.sleep(1)

    def _check_due_schedules(self):
        """Check for and execute due schedules."""
        now = datetime.now(timezone.utc)

        with self._get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT schedule_id, session_id, next_wake, interval_seconds, prompt, constraints_json, end_time "
                    "FROM schedules WHERE next_wake <= %s",
                    (now,)
                )
                due_schedules = cur.fetchall()

        for row in due_schedules:
            schedule_id, session_id, next_wake, interval_seconds, prompt, constraints_json_raw, end_time = row

            try:
                # Parse constraints
                if isinstance(constraints_json_raw, dict):
                    constraints = constraints_json_raw
                elif isinstance(constraints_json_raw, str):
                    constraints = json.loads(constraints_json_raw)
                else:
                    constraints = {}

                # Execute wake-up
                self.wake_callback(session_id, prompt, constraints)

                # Update schedule for next execution
                if interval_seconds:
                    # Recurring - calculate next wake time
                    new_next_wake = next_wake + timedelta(seconds=interval_seconds)

                    # Check if we've passed end_time
                    if end_time and new_next_wake > end_time:
                        # Schedule expired - delete it
                        self._delete_schedule(schedule_id)
                    else:
                        # Update next wake time
                        with self._get_conn() as conn:
                            with conn.cursor() as cur:
                                cur.execute(
                                    "UPDATE schedules SET next_wake = %s WHERE schedule_id = %s",
                                    (new_next_wake, schedule_id)
                                )
                            conn.commit()
                else:
                    # One-time - delete after execution
                    self._delete_schedule(schedule_id)

            except Exception as e:
                print(f"[Scheduler] Error executing schedule {schedule_id}: {e}")

    def _delete_schedule(self, schedule_id: str):
        """Delete a schedule."""
        with self._get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM schedules WHERE schedule_id = %s", (schedule_id,))
            conn.commit()

    def schedule_wake_at(
        self,
        session_id: str,
        time: datetime,
        prompt: str,
        constraints: Optional[dict] = None
    ) -> str:
        """
        Schedule a one-time wake-up.

        Args:
            session_id: Session to wake
            time: When to wake (datetime)
            prompt: Prompt to provide at wake-up
            constraints: Optional resource constraints dict

        Returns:
            schedule_id
        """
        schedule_id = str(uuid.uuid4())
        constraints_json = json.dumps(constraints) if constraints else None

        with self._get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO schedules
                       (schedule_id, session_id, next_wake, interval_seconds, prompt, constraints_json, end_time, created_at)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                    (
                        schedule_id,
                        session_id,
                        time,
                        None,  # No interval for one-time
                        prompt,
                        constraints_json,
                        None,  # No end time for one-time
                        datetime.now(timezone.utc)
                    )
                )
            conn.commit()

        return schedule_id

    def schedule_wake_every(
        self,
        session_id: str,
        interval: timedelta,
        prompt: str,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        constraints: Optional[dict] = None
    ) -> str:
        """
        Schedule a recurring wake-up.

        Args:
            session_id: Session to wake
            interval: How often to wake (timedelta)
            prompt: Prompt to provide at wake-up
            start_time: When to start (defaults to now + interval)
            end_time: When to stop (None = never)
            constraints: Optional resource constraints dict

        Returns:
            schedule_id
        """
        schedule_id = str(uuid.uuid4())
        constraints_json = json.dumps(constraints) if constraints else None
        next_wake = start_time or (datetime.now(timezone.utc) + interval)

        with self._get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO schedules
                       (schedule_id, session_id, next_wake, interval_seconds, prompt, constraints_json, end_time, created_at)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                    (
                        schedule_id,
                        session_id,
                        next_wake,
                        int(interval.total_seconds()),
                        prompt,
                        constraints_json,
                        end_time,
                        datetime.now(timezone.utc)
                    )
                )
            conn.commit()

        return schedule_id

    def list_schedules(self, session_id: Optional[str] = None) -> List[Schedule]:
        """
        List scheduled wake-ups.

        Args:
            session_id: Filter by session (None = all sessions)

        Returns:
            List of Schedule objects
        """
        with self._get_conn() as conn:
            with conn.cursor() as cur:
                if session_id:
                    cur.execute(
                        "SELECT schedule_id, session_id, next_wake, interval_seconds, prompt, constraints_json, end_time, created_at "
                        "FROM schedules WHERE session_id = %s ORDER BY next_wake",
                        (session_id,)
                    )
                else:
                    cur.execute(
                        "SELECT schedule_id, session_id, next_wake, interval_seconds, prompt, constraints_json, end_time, created_at "
                        "FROM schedules ORDER BY next_wake"
                    )

                schedules = []
                for row in cur.fetchall():
                    schedule_id, session_id, next_wake, interval_seconds, prompt, constraints_json_raw, end_time, created_at = row
                    # Handle JSONB auto-deserialization
                    if isinstance(constraints_json_raw, dict):
                        constraints_json = json.dumps(constraints_json_raw)
                    else:
                        constraints_json = constraints_json_raw
                    schedules.append(Schedule(
                        schedule_id=schedule_id,
                        session_id=session_id,
                        next_wake=next_wake,
                        interval=timedelta(seconds=interval_seconds) if interval_seconds else None,
                        prompt=prompt,
                        constraints_json=constraints_json,
                        end_time=end_time,
                        created_at=created_at
                    ))

                return schedules

    def cancel_schedule(self, schedule_id: str) -> bool:
        """
        Cancel a scheduled wake-up.

        Returns:
            True if schedule was found and cancelled, False otherwise
        """
        with self._get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM schedules WHERE schedule_id = %s",
                    (schedule_id,)
                )
            conn.commit()
            return cur.rowcount > 0
