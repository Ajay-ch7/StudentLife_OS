from pathlib import Path
from app.core.config import DATA_DIR
from app.schemas.tools import ToolAccessLevel


class PermissionDeniedError(Exception):
    """Raised when an agent attempts an unauthorized action."""
    pass


class ApprovalRequiredError(Exception):
    """Raised when an action requires explicit user approval."""
    pass


class PermissionService:
    """Enforces safety, permissions, and human approval constraints on tool calls."""

    @staticmethod
    def check_tool_permission(
        tool_name: str,
        access_level: ToolAccessLevel,
        requires_approval: bool,
        is_approved: bool = False,
    ) -> None:
        """Verify whether a tool is allowed to execute."""
        if requires_approval and not is_approved:
            raise ApprovalRequiredError(
                f"Action '{tool_name}' has high impact and requires explicit user approval."
            )

    @staticmethod
    def validate_file_path(file_path_str: str) -> Path:
        """Ensure file path is strictly within the allowed data directories to prevent path traversal."""
        path = Path(file_path_str).resolve()
        allowed_root = DATA_DIR.resolve()
        
        try:
            path.relative_to(allowed_root)
        except ValueError:
            raise PermissionDeniedError(
                f"Access denied: File path '{file_path_str}' is outside allowed data directory."
            )
        
        return path
