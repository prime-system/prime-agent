"""Utilities for encoding file paths to Claude Code format."""

from pathlib import Path


def encode_project_path(project_path: str | Path) -> str:
    """
    Encode a project path into Claude Code's format.

    Claude Code stores project-specific data using an encoded path format where
    directory separators (/) are replaced with hyphens (-).

    Example:
        "/Users/michael/Workspace/freiwald/Prime" → "-Users-michael-Workspace-freiwald-Prime"
        "/home/prime/vault" → "-home-prime-vault"

    Args:
        project_path: Absolute path to project directory

    Returns:
        Encoded path string suitable for use in Claude Code directory names
    """
    path = Path(project_path).absolute()
    return str(path).replace("/", "-")


def get_claude_projects_dir(claude_home: str | Path = "/home/prime/.claude") -> Path:
    """
    Get the Claude Code projects directory path.

    Args:
        claude_home: Path to Claude Code home directory
                    (default: /home/prime/.claude for Prime container)

    Returns:
        Path to projects directory
    """
    return Path(claude_home) / "projects"


def get_project_sessions_dir(
    project_path: str | Path,
    claude_home: str | Path = "/home/prime/.claude",
) -> Path:
    """
    Get the directory containing session files for a specific project.

    Args:
        project_path: Absolute path to project directory
        claude_home: Path to Claude Code home directory

    Returns:
        Path to project's session directory

    Example:
        >>> get_project_sessions_dir("/Users/michael/Workspace/freiwald/Prime")
        Path('/home/prime/.claude/projects/-Users-michael-Workspace-freiwald-Prime')
    """
    encoded = encode_project_path(project_path)
    return get_claude_projects_dir(claude_home) / encoded
