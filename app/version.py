"""Version information for PrimeAgent server."""

import tomllib
from pathlib import Path

_VERSION: str | None = None


def get_version() -> str:
    """
    Get the server version from pyproject.toml.

    Returns:
        Version string (e.g., "0.1.0")
    """
    global _VERSION

    # Cache the version after first read
    if _VERSION is not None:
        return _VERSION

    # Read version from pyproject.toml
    pyproject_path = Path(__file__).parent.parent / "pyproject.toml"

    try:
        with open(pyproject_path, "rb") as f:
            pyproject_data = tomllib.load(f)

        _VERSION = pyproject_data.get("project", {}).get("version", "unknown")
        return _VERSION
    except Exception:
        # Fallback if pyproject.toml can't be read
        return "unknown"
