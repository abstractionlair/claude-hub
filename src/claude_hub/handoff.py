"""Handoff protocol for agent delegation."""

import json
from pathlib import Path
from typing import Optional, List, Dict
from dataclasses import dataclass, asdict
from datetime import datetime


@dataclass
class HandoffDoc:
    """Structured handoff document from delegatee to parent."""
    status: str  # "complete" | "in_progress" | "blocked" | "failed"
    summary: str
    started_at: datetime
    last_updated: datetime
    findings: List[str] = None
    files_changed: List[str] = None
    questions: List[str] = None
    recommendations: str = None

    def to_dict(self) -> Dict:
        """Convert to dict for serialization."""
        data = asdict(self)
        data['started_at'] = self.started_at.isoformat()
        data['last_updated'] = self.last_updated.isoformat()
        return data

    @classmethod
    def from_dict(cls, data: Dict) -> 'HandoffDoc':
        """Create from dict."""
        data = data.copy()
        data['started_at'] = datetime.fromisoformat(data['started_at'])
        data['last_updated'] = datetime.fromisoformat(data['last_updated'])
        return cls(**data)

    def to_markdown(self) -> str:
        """Render as markdown."""
        md = f"""# Handoff

**Status:** {self.status}
**Started:** {self.started_at.strftime('%Y-%m-%d %H:%M')}
**Last Updated:** {self.last_updated.strftime('%Y-%m-%d %H:%M')}

## Summary
{self.summary}
"""

        if self.findings:
            md += "\n## Key Findings\n"
            for finding in self.findings:
                md += f"- {finding}\n"

        if self.files_changed:
            md += "\n## Files Changed\n"
            for file in self.files_changed:
                md += f"- `{file}`\n"

        if self.questions:
            md += "\n## Open Questions\n"
            for question in self.questions:
                md += f"- {question}\n"

        if self.recommendations:
            md += f"\n## Recommendations\n{self.recommendations}\n"

        md += "\n## Details Available On Request\n"
        md += "If parent needs more detail, resume session and ask.\n"

        return md


class HandoffManager:
    """Manages handoff documents for agent delegation."""

    HANDOFF_FILENAME = "HANDOFF.md"
    HANDOFF_JSON_FILENAME = ".handoff.json"

    def __init__(self):
        pass

    def write_handoff(
        self,
        workspace: Path,
        summary: str,
        status: str,
        started_at: Optional[datetime] = None,
        findings: Optional[List[str]] = None,
        files_changed: Optional[List[str]] = None,
        questions: Optional[List[str]] = None,
        recommendations: Optional[str] = None
    ) -> Path:
        """
        Write handoff document to workspace.

        Creates both markdown (human-readable) and JSON (machine-readable) versions.

        Args:
            workspace: Agent's workspace directory
            summary: Brief summary of work
            status: "complete" | "in_progress" | "blocked" | "failed"
            started_at: When work started (defaults to now if first write)
            findings: Key findings
            files_changed: Files that were modified
            questions: Open questions for parent
            recommendations: What should happen next

        Returns:
            Path to the handoff markdown file
        """
        # Load existing handoff if it exists to preserve started_at
        existing = self.read_handoff(workspace)
        if existing and started_at is None:
            started_at = existing.started_at
        elif started_at is None:
            started_at = datetime.utcnow()

        handoff = HandoffDoc(
            status=status,
            summary=summary,
            started_at=started_at,
            last_updated=datetime.utcnow(),
            findings=findings or [],
            files_changed=files_changed or [],
            questions=questions or [],
            recommendations=recommendations
        )

        # Write markdown version (human-readable)
        md_path = workspace / self.HANDOFF_FILENAME
        with open(md_path, 'w') as f:
            f.write(handoff.to_markdown())

        # Write JSON version (machine-readable)
        json_path = workspace / self.HANDOFF_JSON_FILENAME
        with open(json_path, 'w') as f:
            json.dump(handoff.to_dict(), f, indent=2)

        return md_path

    def read_handoff(self, workspace: Path) -> Optional[HandoffDoc]:
        """
        Read handoff document from workspace.

        Returns:
            HandoffDoc if exists, None otherwise
        """
        json_path = workspace / self.HANDOFF_JSON_FILENAME
        if not json_path.exists():
            return None

        with open(json_path, 'r') as f:
            data = json.load(f)

        return HandoffDoc.from_dict(data)

    def read_handoff_markdown(self, workspace: Path) -> Optional[str]:
        """
        Read handoff markdown content.

        Returns:
            Markdown string if exists, None otherwise
        """
        md_path = workspace / self.HANDOFF_FILENAME
        if not md_path.exists():
            return None

        with open(md_path, 'r') as f:
            return f.read()

    def update_status(self, workspace: Path, status: str) -> bool:
        """
        Update just the status of an existing handoff.

        Returns:
            True if handoff exists and was updated, False otherwise
        """
        handoff = self.read_handoff(workspace)
        if not handoff:
            return False

        handoff.status = status
        handoff.last_updated = datetime.utcnow()

        # Rewrite both files
        md_path = workspace / self.HANDOFF_FILENAME
        with open(md_path, 'w') as f:
            f.write(handoff.to_markdown())

        json_path = workspace / self.HANDOFF_JSON_FILENAME
        with open(json_path, 'w') as f:
            json.dump(handoff.to_dict(), f, indent=2)

        return True

    def list_handoffs(self, project_work_dir: Path) -> Dict[str, HandoffDoc]:
        """
        List all handoffs in a project's work directory.

        Args:
            project_work_dir: Path to thoughts/projects/{project}/work/

        Returns:
            Dict mapping agent_dir_name -> HandoffDoc
        """
        handoffs = {}
        if not project_work_dir.exists():
            return handoffs

        for agent_dir in project_work_dir.iterdir():
            if not agent_dir.is_dir():
                continue

            handoff = self.read_handoff(agent_dir)
            if handoff:
                handoffs[agent_dir.name] = handoff

        return handoffs
