"""Workspace management for agent delegation and isolation."""

import os
import json
from pathlib import Path
from typing import Optional, List, Dict
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class ResourceConstraints:
    """Resource constraints for delegated agents."""
    deadline: Optional[datetime] = None
    max_memory_mb: Optional[int] = None
    max_agents: Optional[int] = None
    max_iterations: Optional[int] = None

    def merge_child(self, child_estimate: 'ResourceConstraints') -> 'ResourceConstraints':
        """
        Create child constraints using min() for tightening.

        Implements deadline propagation pattern:
        - If parent has deadline and child estimates duration, take min()
        - If parent has resource limits, child can't exceed them
        """
        return ResourceConstraints(
            deadline=min(
                filter(None, [self.deadline, child_estimate.deadline]),
                default=None
            ) if (self.deadline or child_estimate.deadline) else None,
            max_memory_mb=min(
                filter(None, [self.max_memory_mb, child_estimate.max_memory_mb]),
                default=None
            ) if (self.max_memory_mb or child_estimate.max_memory_mb) else None,
            max_agents=min(
                filter(None, [self.max_agents, child_estimate.max_agents]),
                default=None
            ) if (self.max_agents or child_estimate.max_agents) else None,
            max_iterations=min(
                filter(None, [self.max_iterations, child_estimate.max_iterations]),
                default=None
            ) if (self.max_iterations or child_estimate.max_iterations) else None,
        )

    def to_dict(self) -> Dict:
        """Serialize to dict for storage."""
        return {
            'deadline': self.deadline.isoformat() if self.deadline else None,
            'max_memory_mb': self.max_memory_mb,
            'max_agents': self.max_agents,
            'max_iterations': self.max_iterations,
        }

    @classmethod
    def from_dict(cls, data: Dict) -> 'ResourceConstraints':
        """Deserialize from dict."""
        return cls(
            deadline=datetime.fromisoformat(data['deadline']) if data.get('deadline') else None,
            max_memory_mb=data.get('max_memory_mb'),
            max_agents=data.get('max_agents'),
            max_iterations=data.get('max_iterations'),
        )


@dataclass
class WorkspaceMetadata:
    """Metadata about a workspace."""
    agent_id: str
    parent_id: Optional[str]
    created_at: datetime
    created_by: str  # Directory path of creator
    constraints: ResourceConstraints
    writers: List[str] = field(default_factory=list)  # Directories allowed to write


class WorkspaceManager:
    """
    Manages agent workspaces for delegation.

    Directory structure:
    thoughts/projects/{project}/
        work/
            main/                           # Main Claude's workspace
            main.research-abc123/           # Child of main
            main.research-abc123.analysis/  # Grandchild
        shared/
            ontologies/
            data/
    """

    def __init__(self, base_dir: Path):
        self.base_dir = base_dir
        self.projects_dir = base_dir / "thoughts" / "projects"
        self.projects_dir.mkdir(parents=True, exist_ok=True)

    def create_workspace(
        self,
        project: str,
        agent_id: str,
        parent_id: Optional[str] = None,
        constraints: Optional[ResourceConstraints] = None
    ) -> Path:
        """
        Create a workspace directory for an agent.

        Args:
            project: Project name
            agent_id: Agent identifier (e.g., "main", "research-abc123")
            parent_id: Parent agent ID if this is a child
            constraints: Resource constraints for this agent

        Returns:
            Path to the workspace directory
        """
        project_dir = self.projects_dir / project
        work_dir = project_dir / "work"

        # Construct agent directory name
        if parent_id:
            agent_dir_name = f"{parent_id}.{agent_id}"
        else:
            agent_dir_name = agent_id

        workspace = work_dir / agent_dir_name
        workspace.mkdir(parents=True, exist_ok=True)

        # Create shared directory if it doesn't exist
        shared_dir = project_dir / "shared"
        (shared_dir / "ontologies").mkdir(parents=True, exist_ok=True)
        (shared_dir / "data").mkdir(parents=True, exist_ok=True)

        # Write workspace metadata
        metadata = WorkspaceMetadata(
            agent_id=agent_id,
            parent_id=parent_id,
            created_at=datetime.utcnow(),
            created_by=f"work/{agent_dir_name}",
            constraints=constraints or ResourceConstraints(),
            writers=[f"work/{agent_dir_name}"],  # Creator can always write
        )

        metadata_path = workspace / ".workspace.json"
        with open(metadata_path, 'w') as f:
            json.dump({
                'agent_id': metadata.agent_id,
                'parent_id': metadata.parent_id,
                'created_at': metadata.created_at.isoformat(),
                'created_by': metadata.created_by,
                'constraints': metadata.constraints.to_dict(),
                'writers': metadata.writers,
            }, f, indent=2)

        return workspace

    def get_workspace(self, project: str, agent_id: str, parent_id: Optional[str] = None) -> Optional[Path]:
        """Get path to existing workspace."""
        if parent_id:
            agent_dir_name = f"{parent_id}.{agent_id}"
        else:
            agent_dir_name = agent_id

        workspace = self.projects_dir / project / "work" / agent_dir_name
        return workspace if workspace.exists() else None

    def load_metadata(self, workspace: Path) -> Optional[WorkspaceMetadata]:
        """Load workspace metadata."""
        metadata_path = workspace / ".workspace.json"
        if not metadata_path.exists():
            return None

        with open(metadata_path, 'r') as f:
            data = json.load(f)

        return WorkspaceMetadata(
            agent_id=data['agent_id'],
            parent_id=data.get('parent_id'),
            created_at=datetime.fromisoformat(data['created_at']),
            created_by=data['created_by'],
            constraints=ResourceConstraints.from_dict(data['constraints']),
            writers=data.get('writers', [data['created_by']]),
        )

    def can_write(self, workspace: Path, requester_dir: str) -> bool:
        """
        Check if requester can write to workspace.

        Rules:
        - Own directory: always yes
        - Parent -> child: yes
        - Child -> parent: no
        - Sibling -> sibling: no
        """
        metadata = self.load_metadata(workspace)
        if not metadata:
            return False

        # Own directory
        if metadata.created_by == requester_dir:
            return True

        # Parent -> child: parent dir is prefix of child dir
        # e.g., parent="work/main", child="work/main.research"
        child_dir = metadata.created_by
        if child_dir.startswith(requester_dir + "."):
            return True

        return False

    def list_children(self, project: str, parent_agent_id: str) -> List[str]:
        """List all child workspaces of a parent."""
        work_dir = self.projects_dir / project / "work"
        if not work_dir.exists():
            return []

        children = []
        prefix = f"{parent_agent_id}."
        for item in work_dir.iterdir():
            if item.is_dir() and item.name.startswith(prefix):
                children.append(item.name)

        return children

    def get_shared_resource_metadata(self, project: str, resource_path: str) -> Optional[Dict]:
        """
        Extract metadata from shared resource.

        Looks for metadata block at start of file:
        <!-- PERMISSIONS
        created_by: work/main/
        writers: [work/main/, work/main.research/]
        -->
        """
        full_path = self.projects_dir / project / "shared" / resource_path
        if not full_path.exists():
            return None

        try:
            with open(full_path, 'r') as f:
                content = f.read(1000)  # Read first 1000 chars

            # Extract metadata block
            if content.startswith('<!-- PERMISSIONS'):
                end = content.find('-->')
                if end > 0:
                    metadata_text = content[len('<!-- PERMISSIONS'):end]
                    metadata = {}
                    for line in metadata_text.strip().split('\n'):
                        if ':' in line:
                            key, value = line.split(':', 1)
                            key = key.strip()
                            value = value.strip()
                            if key == 'writers' and value.startswith('['):
                                # Parse list
                                value = [v.strip().strip(',') for v in value.strip('[]').split()]
                            metadata[key] = value
                    return metadata
        except Exception:
            pass

        return None

    def can_write_shared(self, project: str, resource_path: str, requester_dir: str) -> bool:
        """Check if requester can write to shared resource."""
        metadata = self.get_shared_resource_metadata(project, resource_path)
        if not metadata:
            # No metadata = anyone can write (for now)
            return True

        # Check if requester is creator
        if metadata.get('created_by') == requester_dir:
            return True

        # Check if requester is in writers list
        writers = metadata.get('writers', [])
        if isinstance(writers, list) and requester_dir in writers:
            return True

        return False
