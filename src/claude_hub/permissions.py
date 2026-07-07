"""Permission checking for workspace operations.

NOTE: PermissionChecker implements the workspace permission rules but is
not wired into the server's file-write path. Workspace permissions are
currently a convention for cooperating agents, not an enforced boundary —
see docs/delegation-system.md.
"""

from pathlib import Path
from typing import Optional
from .workspace import WorkspaceManager


class PermissionChecker:
    """
    Checks permission rules for workspace access.

    Rules:
    1. Own directory: full control
    2. Parent -> child: read + write
    3. Child -> parent: read-only
    4. Siblings: no direct access (unless via shared/)
    5. Shared resources: metadata-based control
    """

    def __init__(self, workspace_manager: WorkspaceManager):
        self.workspace_manager = workspace_manager

    def check_file_access(
        self,
        file_path: Path,
        requester_dir: str,
        operation: str,  # "read" or "write"
        project: str,
    ) -> tuple[bool, Optional[str]]:
        """
        Check if requester can access a file.

        Args:
            file_path: Absolute path to the file
            requester_dir: Requester's workspace directory (e.g., "work/main/")
            operation: "read" or "write"
            project: Project name

        Returns:
            (allowed: bool, reason: Optional[str])
        """
        project_dir = self.workspace_manager.projects_dir / project

        # Convert file_path to relative within project
        try:
            rel_path = file_path.relative_to(project_dir)
        except ValueError:
            return False, "File outside project directory"

        # Check if file is in requester's workspace
        requester_workspace = project_dir / requester_dir
        if self._is_under_directory(file_path, requester_workspace):
            return True, None  # Own workspace - full control

        # Check if file is in work/ (agent workspace)
        if rel_path.parts[0] == "work":
            target_workspace = project_dir / "work" / rel_path.parts[1]

            if operation == "read":
                # Can read parent or child workspaces
                if self._is_parent_child_relationship(requester_dir, str(rel_path)):
                    return True, None

            elif operation == "write":
                # Can only write to child workspaces (parent -> child)
                if self._is_parent_of(requester_dir, str(rel_path)):
                    return True, None
                return False, "Cannot write to non-child workspace"

            return False, "No access to sibling workspace"

        # Check if file is in shared/
        if rel_path.parts[0] == "shared":
            if operation == "read":
                return True, None  # Anyone can read shared

            # Check write permission for shared resource
            shared_rel_path = "/".join(rel_path.parts[1:])  # Remove "shared/" prefix
            can_write = self.workspace_manager.can_write_shared(
                project, shared_rel_path, requester_dir
            )
            if can_write:
                return True, None
            return False, "Not in writers list for shared resource"

        # Unknown location
        return False, "File not in work/ or shared/"

    def _is_under_directory(self, file_path: Path, directory: Path) -> bool:
        """Check if file_path is under directory."""
        try:
            file_path.relative_to(directory)
            return True
        except ValueError:
            return False

    def _is_parent_child_relationship(self, requester_dir: str, target_path: str) -> bool:
        """Check if requester and target have parent-child relationship."""
        # Extract workspace names
        # requester_dir format: "work/main/" or "work/main.research/"
        # target_path format: "work/main.research/..." or "work/main/..."

        requester_workspace = requester_dir.rstrip("/").split("/")[-1]
        target_workspace = target_path.split("/")[1]

        # Check if one is parent of the other
        return (
            target_workspace.startswith(requester_workspace + ".")
            or requester_workspace.startswith(target_workspace + ".")
        )

    def _is_parent_of(self, requester_dir: str, target_path: str) -> bool:
        """Check if requester is parent of target."""
        requester_workspace = requester_dir.rstrip("/").split("/")[-1]
        target_workspace = target_path.split("/")[1]

        # Target must start with requester's name followed by "."
        return target_workspace.startswith(requester_workspace + ".")
