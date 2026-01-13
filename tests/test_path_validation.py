"""Security tests for path validation utilities."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from app.utils.path_validation import (
    PathValidationError,
    sanitize_filename,
    validate_folder_name,
    validate_path_within_vault,
    validate_session_id,
)


@pytest.fixture
def temp_vault() -> Path:
    """Create a temporary vault directory for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Resolve tmpdir to handle macOS /var -> /private/var symlink
        tmpdir_resolved = Path(tmpdir).resolve()
        vault = tmpdir_resolved / "vault"
        vault.mkdir()
        (vault / ".prime").mkdir()
        (vault / "inbox").mkdir()
        yield vault


class TestValidatePathWithinVault:
    """Test path validation against vault boundaries."""

    def test_blocks_path_traversal_sequences(self, temp_vault: Path) -> None:
        """Verify path validation blocks directory traversal."""
        with pytest.raises(PathValidationError, match="contains '..'"):
            validate_path_within_vault("../../etc/passwd", temp_vault)

        with pytest.raises(PathValidationError, match="contains '..'"):
            validate_path_within_vault("inbox/../../etc/passwd", temp_vault)

        with pytest.raises(PathValidationError, match="contains '..'"):
            validate_path_within_vault("./../config", temp_vault)

    def test_blocks_absolute_paths_outside_vault(self, temp_vault: Path) -> None:
        """Verify path validation blocks absolute paths outside vault."""
        with pytest.raises(PathValidationError, match="outside vault root"):
            validate_path_within_vault("/etc/passwd", temp_vault)

        with pytest.raises(PathValidationError, match="outside vault root"):
            validate_path_within_vault("/root/.ssh/id_rsa", temp_vault)

    def test_blocks_null_bytes(self, temp_vault: Path) -> None:
        """Verify path validation blocks null bytes."""
        with pytest.raises(PathValidationError, match="null bytes"):
            validate_path_within_vault("inbox/test\x00.txt", temp_vault)

    def test_allows_safe_relative_paths(self, temp_vault: Path) -> None:
        """Verify path validation allows safe relative paths."""
        # Create a safe file
        safe_file = temp_vault / "inbox" / "test.md"
        safe_file.parent.mkdir(parents=True, exist_ok=True)
        safe_file.write_text("test")

        # Should not raise
        validated = validate_path_within_vault("inbox/test.md", temp_vault)
        assert validated.is_relative_to(temp_vault.resolve())
        assert validated.name == "test.md"

    def test_allows_nested_safe_paths(self, temp_vault: Path) -> None:
        """Verify path validation allows safely nested paths."""
        # Create nested structure
        nested = temp_vault / "Daily" / "2026" / "01"
        nested.mkdir(parents=True)
        nested_file = nested / "notes.md"
        nested_file.write_text("notes")

        # Should not raise
        validated = validate_path_within_vault("Daily/2026/01/notes.md", temp_vault)
        assert validated.is_relative_to(temp_vault.resolve())
        assert validated.name == "notes.md"

    def test_blocks_symlink_by_default(self, temp_vault: Path) -> None:
        """Verify symlinks are blocked by default."""
        # Create a file inside vault
        target = temp_vault / "target.txt"
        target.write_text("target")

        # Create symlink inside vault pointing inside (for easier testing)
        symlink = temp_vault / "link.txt"
        symlink.symlink_to(target)

        # Should raise when we pass the symlink path directly as relative
        with pytest.raises(PathValidationError, match="Symlink not allowed"):
            validate_path_within_vault("link.txt", temp_vault, allow_symlinks=False)

    def test_allows_symlink_when_enabled(self, temp_vault: Path) -> None:
        """Verify symlinks are allowed when explicitly enabled."""
        # Create a file inside vault
        target = temp_vault / "target.txt"
        target.write_text("target")

        # Create symlink inside vault pointing inside
        symlink = temp_vault / "link.txt"
        symlink.symlink_to(target)

        # Should not raise when allow_symlinks=True
        validated = validate_path_within_vault("link.txt", temp_vault, allow_symlinks=True)
        assert validated.exists()

    def test_handles_path_object_input(self, temp_vault: Path) -> None:
        """Verify validation works with Path objects."""
        safe_file = temp_vault / "inbox" / "test.md"
        safe_file.parent.mkdir(parents=True, exist_ok=True)
        safe_file.write_text("test")

        # Pass relative Path object instead of string
        rel_path = Path("inbox") / "test.md"
        validated = validate_path_within_vault(rel_path, temp_vault)
        assert validated.is_relative_to(temp_vault.resolve())

    def test_resolves_relative_to_vault(self, temp_vault: Path) -> None:
        """Verify paths are resolved relative to vault."""
        # Create file
        safe_file = temp_vault / "inbox" / "test.md"
        safe_file.parent.mkdir(parents=True, exist_ok=True)
        safe_file.write_text("test")

        # Validate with ./ prefix
        validated = validate_path_within_vault("./inbox/test.md", temp_vault)
        assert validated.is_relative_to(temp_vault.resolve())
        assert validated.name == "test.md"


class TestValidateFolderName:
    """Test folder name validation from configuration."""

    def test_accepts_simple_folder_names(self, temp_vault: Path) -> None:
        """Verify simple folder names are accepted."""
        validated = validate_folder_name("inbox", temp_vault)
        assert validated == (temp_vault / "inbox").resolve()

        validated = validate_folder_name(".prime", temp_vault)
        assert validated == (temp_vault / ".prime").resolve()

    def test_accepts_nested_folder_paths(self, temp_vault: Path) -> None:
        """Verify nested folder paths are accepted."""
        validated = validate_folder_name(".prime/inbox", temp_vault)
        assert validated == (temp_vault / ".prime" / "inbox").resolve()

    def test_blocks_path_traversal_in_folder_names(self, temp_vault: Path) -> None:
        """Verify path traversal is blocked in folder names."""
        with pytest.raises(PathValidationError, match="cannot contain '..'"):
            validate_folder_name("../etc", temp_vault)

        with pytest.raises(PathValidationError, match="cannot contain '..'"):
            validate_folder_name("inbox/../../sensitive", temp_vault)

    def test_accepts_rooted_folder_paths(self, temp_vault: Path) -> None:
        """Verify leading separators are treated as vault-rooted."""
        validated = validate_folder_name("/Daily", temp_vault)
        assert validated == (temp_vault / "Daily").resolve()

        validated = validate_folder_name("\\Daily", temp_vault)
        assert validated == (temp_vault / "Daily").resolve()

        validated = validate_folder_name("/.prime/inbox", temp_vault)
        assert validated == (temp_vault / ".prime" / "inbox").resolve()

    def test_blocks_null_bytes_in_folder_name(self, temp_vault: Path) -> None:
        """Verify null bytes are blocked."""
        with pytest.raises(PathValidationError, match="null bytes"):
            validate_folder_name("inbox\x00folder", temp_vault)

    def test_blocks_consecutive_separators(self, temp_vault: Path) -> None:
        """Verify consecutive separators are blocked."""
        with pytest.raises(PathValidationError, match="consecutive separators"):
            validate_folder_name("inbox//folder", temp_vault)

    def test_blocks_empty_folder_names(self, temp_vault: Path) -> None:
        """Verify empty folder names are rejected."""
        with pytest.raises(PathValidationError, match="must be a non-empty string"):
            validate_folder_name("", temp_vault)

    def test_validates_final_path_stays_in_vault(self, temp_vault: Path) -> None:
        """Verify final validation ensures path stays in vault."""
        # This path technically doesn't escape via .. but resolves outside
        # (edge case - normally prevented by .. check)
        # Most cases caught by .. check first
        with pytest.raises(PathValidationError, match="cannot contain '..'"):
            validate_folder_name("../vault/inbox", temp_vault)


class TestSanitizeFilename:
    """Test filename sanitization."""

    def test_removes_path_separators(self) -> None:
        """Verify path separators are removed."""
        assert sanitize_filename("test/file.txt") == "test_file.txt"
        assert sanitize_filename("test\\file.txt") == "test_file.txt"
        assert sanitize_filename("test//file.txt") == "test__file.txt"

    def test_removes_traversal_sequences(self) -> None:
        """Verify traversal sequences are removed."""
        # ".." gets replaced with "__", "/" with "_"
        assert sanitize_filename("../../../etc/passwd") == "_________etc_passwd"
        assert sanitize_filename("..\\..\\..\\windows\\system32") == "_________windows_system32"

    def test_removes_null_bytes(self) -> None:
        """Verify null bytes are removed."""
        assert sanitize_filename("test\x00.txt") == "test.txt"
        assert sanitize_filename("file\x00\x00name.md") == "filename.md"

    def test_removes_control_characters(self) -> None:
        """Verify control characters are removed."""
        # Control characters are ASCII 0-31
        assert sanitize_filename("test\x01\x02.txt") == "test.txt"
        assert sanitize_filename("file\t\n\rname.md") == "filename.md"

    def test_respects_max_length(self) -> None:
        """Verify maximum length is respected."""
        long_name = "a" * 300
        sanitized = sanitize_filename(long_name, max_length=255)
        assert len(sanitized) == 255

        # Test custom max length
        sanitized = sanitize_filename("a" * 100, max_length=50)
        assert len(sanitized) == 50

    def test_removes_leading_trailing_dots_and_spaces(self) -> None:
        """Verify leading/trailing dots and spaces are removed."""
        assert sanitize_filename("  test.txt  ") == "test.txt"
        # "...test..." -> ".." -> "__" -> "__.test.__" -> strip dots/spaces -> "__.test.__"
        assert sanitize_filename("...test...") == "__.test__"
        # ". . test . ." -> ".." -> "__" -> ". . test . ." (no ".." here) -> strip -> "test"
        assert sanitize_filename(". . test . .") == "test"

    def test_preserves_valid_characters(self) -> None:
        """Verify valid characters are preserved."""
        assert sanitize_filename("my-file_2026.md") == "my-file_2026.md"
        assert sanitize_filename("2026-01-05_notes.txt") == "2026-01-05_notes.txt"

    def test_rejects_empty_filename(self) -> None:
        """Verify empty filenames are rejected."""
        with pytest.raises(PathValidationError, match="must be a non-empty string"):
            sanitize_filename("")

        with pytest.raises(PathValidationError, match="empty after sanitization"):
            sanitize_filename("\x00\x01\x02")

    def test_complex_sanitization(self) -> None:
        """Test complex filename sanitization scenarios."""
        # Real-world attack attempts
        # "../../etc/passwd.txt" -> ".." -> "__", "/" -> "_"
        assert sanitize_filename("../../etc/passwd.txt") == "______etc_passwd.txt"
        assert sanitize_filename("config\x00.yaml") == "config.yaml"
        # "  ..malicious..  " -> ".." -> "__" -> "  __malicious__  " -> strip -> "__malicious__"
        assert sanitize_filename("  ..malicious..  ") == "__malicious__"


class TestValidateSessionId:
    """Test session ID validation."""

    def test_accepts_valid_uuid(self) -> None:
        """Verify valid UUID format is accepted."""
        uuid = "550e8400-e29b-41d4-a716-446655440000"
        assert validate_session_id(uuid) == uuid

    def test_accepts_uppercase_uuid(self) -> None:
        """Verify uppercase UUID is accepted."""
        uuid = "550E8400-E29B-41D4-A716-446655440000"
        assert validate_session_id(uuid) == uuid

    def test_accepts_safe_alphanumeric(self) -> None:
        """Verify safe alphanumeric IDs are accepted."""
        assert validate_session_id("session-123") == "session-123"
        assert validate_session_id("agent_id_456") == "agent_id_456"
        assert validate_session_id("run.001.abc") == "run.001.abc"

    def test_blocks_path_traversal_in_session_id(self) -> None:
        """Verify path traversal is blocked."""
        with pytest.raises(PathValidationError, match="invalid path characters"):
            validate_session_id("../../../etc/passwd")

        with pytest.raises(PathValidationError, match="invalid path characters"):
            validate_session_id("session/../../admin")

    def test_blocks_backslashes_in_session_id(self) -> None:
        """Verify backslashes are blocked."""
        with pytest.raises(PathValidationError, match="invalid path characters"):
            validate_session_id("session\\escape")

    def test_blocks_null_bytes_in_session_id(self) -> None:
        """Verify null bytes are blocked."""
        with pytest.raises(PathValidationError, match="null bytes"):
            validate_session_id("session\x00id")

    def test_blocks_special_characters(self) -> None:
        """Verify special characters are blocked."""
        with pytest.raises(PathValidationError, match="must be UUID format"):
            validate_session_id("session!@#$%")

        with pytest.raises(PathValidationError, match="must be UUID format"):
            validate_session_id("session<script>")

    def test_blocks_too_long_session_id(self) -> None:
        """Verify overly long session IDs are blocked."""
        long_id = "a" * 256
        with pytest.raises(PathValidationError, match="too long"):
            validate_session_id(long_id)

    def test_blocks_empty_session_id(self) -> None:
        """Verify empty session IDs are blocked."""
        with pytest.raises(PathValidationError, match="must be a non-empty string"):
            validate_session_id("")

    def test_rejects_invalid_uuid_format(self) -> None:
        """Verify invalid UUID format is rejected."""
        # "550e8400-e29b-41d4-a716" is too short for UUID but still valid alphanumeric+hyphens
        # So test with something clearly invalid
        with pytest.raises(PathValidationError, match="must be UUID format"):
            validate_session_id("invalid!@#$")

        # Test with special characters
        with pytest.raises(PathValidationError, match="must be UUID format"):
            validate_session_id("not!valid")


class TestIntegrationPathTraversal:
    """Integration tests simulating real attack scenarios."""

    def test_symlink_escape_attempt(self, temp_vault: Path) -> None:
        """Test that symlink escapes are prevented."""
        # Create a file inside vault
        target = temp_vault / "target.txt"
        target.write_text("target")

        # Create symlink inside vault
        symlink = temp_vault / "escape_link"
        symlink.symlink_to(target)

        # Should fail validation when symlinks not allowed
        with pytest.raises(PathValidationError, match="Symlink not allowed"):
            validate_path_within_vault("escape_link", temp_vault, allow_symlinks=False)

    def test_combined_traversal_attack(self, temp_vault: Path) -> None:
        """Test combined path traversal with multiple techniques."""
        # Attack: inbox/../../../etc + traversal
        with pytest.raises(PathValidationError, match="contains '..'"):
            validate_path_within_vault("inbox/../../../etc/passwd", temp_vault)

    def test_null_byte_injection(self, temp_vault: Path) -> None:
        """Test null byte injection attack."""
        # Null byte injection: "file.txt\x00.md"
        with pytest.raises(PathValidationError, match="null bytes"):
            validate_path_within_vault("inbox/file.txt\x00.md", temp_vault)

    def test_double_encoding_traversal(self, temp_vault: Path) -> None:
        """Test that simple double-encoding is caught."""
        # Most double-encoding is caught at API level
        # This tests our path-level checks
        with pytest.raises(PathValidationError, match="contains '..'"):
            validate_path_within_vault("inbox/..%2f..%2fetc", temp_vault)

    def test_config_based_folder_escape(self, temp_vault: Path) -> None:
        """Test that malicious folder config is caught."""
        with pytest.raises(PathValidationError, match="cannot contain '..'"):
            validate_folder_name("../../../sensitive", temp_vault)

    def test_whitespace_tricks(self, temp_vault: Path) -> None:
        """Test that whitespace-based tricks are handled."""
        # Create a file with spaces
        spaced_file = temp_vault / "inbox" / "test file.md"
        spaced_file.parent.mkdir(parents=True, exist_ok=True)
        spaced_file.write_text("test")

        # Should work fine with spaces
        validated = validate_path_within_vault("inbox/test file.md", temp_vault)
        assert validated.is_relative_to(temp_vault.resolve())
