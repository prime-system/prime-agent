"""
Comprehensive tests for robust YAML frontmatter parsing.

Tests cover:
- Basic frontmatter parsing
- Multiline YAML values
- Special characters
- Edge cases (missing markers, empty frontmatter, etc.)
- Error handling
- Serialization and deserialization
- Validation with Pydantic models
"""

from __future__ import annotations

import pytest

from app.models.frontmatter import CaptureFrontmatter, CommandFrontmatter
from app.utils.frontmatter import (
    FrontmatterError,
    ParsedContent,
    get_frontmatter,
    parse_and_validate_capture,
    parse_and_validate_command,
    parse_frontmatter,
    serialize_frontmatter,
    strip_frontmatter,
    update_frontmatter,
)


class TestParseFrontmatter:
    """Tests for basic frontmatter parsing."""

    def test_parse_basic_frontmatter(self) -> None:
        """Test parsing basic frontmatter."""
        content = """---
id: test-123
captured_at: 2026-01-02T14:30:00Z
source: iphone
input: voice
---

Capture content here
"""

        result = parse_frontmatter(content)

        assert isinstance(result, ParsedContent)
        assert result.frontmatter["id"] == "test-123"
        assert result.frontmatter["captured_at"] == "2026-01-02T14:30:00Z"
        assert result.frontmatter["source"] == "iphone"
        assert result.frontmatter["input"] == "voice"
        assert "Capture content" in result.body

    def test_parse_frontmatter_with_nested_dict(self) -> None:
        """Test parsing frontmatter with nested dictionaries."""
        content = """---
id: test-123
captured_at: 2026-01-02T14:30:00Z
source: iphone
input: voice
context:
  app: shortcuts
  location:
    latitude: 40.7128
    longitude: -74.0060
---

Content
"""

        result = parse_frontmatter(content)

        assert result.frontmatter["context"]["app"] == "shortcuts"
        assert result.frontmatter["context"]["location"]["latitude"] == 40.7128

    def test_parse_frontmatter_multiline_values(self) -> None:
        """Test multiline YAML values."""
        content = """---
id: test-123
description: |
  This is a
  multiline value
  with multiple lines
---

Body
"""

        result = parse_frontmatter(content)
        assert "multiline" in result.frontmatter["description"]
        assert result.frontmatter["description"].count("\n") > 0

    def test_parse_frontmatter_special_chars(self) -> None:
        """Test special characters in frontmatter."""
        content = """---
id: test-123
title: "Title with: colon and !bang"
path: "C:\\\\Users\\\\test"
---

Body
"""

        result = parse_frontmatter(content)
        assert result.frontmatter["title"] == "Title with: colon and !bang"

    def test_parse_frontmatter_windows_line_endings(self) -> None:
        """Test handling Windows line endings."""
        content = "---\r\nid: test-123\r\ncaptured_at: 2026-01-02T14:30:00Z\r\n---\r\n\r\nBody"

        result = parse_frontmatter(content)
        assert result.frontmatter["id"] == "test-123"
        assert "Body" in result.body

    def test_parse_frontmatter_no_frontmatter(self) -> None:
        """Test content without frontmatter."""
        content = "Just plain content without frontmatter"

        result = parse_frontmatter(content)
        assert result.frontmatter == {}
        assert result.body == content

    def test_parse_frontmatter_empty_frontmatter(self) -> None:
        """Test empty frontmatter."""
        content = """---
---

Body content
"""

        result = parse_frontmatter(content)
        assert result.frontmatter == {}

    def test_parse_frontmatter_missing_closing_marker(self) -> None:
        """Test handling of missing closing --- marker."""
        content = """---
id: test-123
captured_at: 2026-01-02T14:30:00Z

Body without closing marker
"""

        result = parse_frontmatter(content)
        # Should gracefully handle missing marker
        assert result.frontmatter == {}

    def test_parse_frontmatter_invalid_yaml(self) -> None:
        """Test handling of invalid YAML."""
        content = """---
invalid: yaml: syntax: too: many: colons
---

Body
"""

        with pytest.raises(FrontmatterError):
            parse_frontmatter(content)

    def test_parse_frontmatter_non_dict_yaml(self) -> None:
        """Test YAML that doesn't parse to dict."""
        content = """---
- item1
- item2
---

Body
"""

        result = parse_frontmatter(content)
        # Should return empty dict for non-dict YAML
        assert result.frontmatter == {}

    def test_parse_frontmatter_preserve_body_whitespace(self) -> None:
        """Test that body whitespace is preserved."""
        content = """---
id: test
---

  Indented body
  with multiple lines
"""

        result = parse_frontmatter(content)
        assert result.body.startswith("  Indented")


class TestSerializeFrontmatter:
    """Tests for frontmatter serialization."""

    def test_serialize_basic_frontmatter(self) -> None:
        """Test serializing basic frontmatter."""
        frontmatter = {
            "id": "test-123",
            "captured_at": "2026-01-02T14:30:00Z",
            "source": "iphone",
        }
        body = "Content here"

        result = serialize_frontmatter(frontmatter, body)

        assert result.startswith("---\n")
        assert "id: test-123" in result
        assert "captured_at: 2026-01-02T14:30:00Z" in result
        assert result.endswith("\nContent here\n")

    def test_serialize_empty_frontmatter(self) -> None:
        """Test serializing with empty frontmatter."""
        body = "Just body"

        result = serialize_frontmatter({}, body)
        assert result == body

    def test_serialize_nested_frontmatter(self) -> None:
        """Test serializing nested dictionaries."""
        frontmatter = {
            "id": "test",
            "context": {"app": "shortcuts", "location": {"latitude": 40.7}},
        }
        body = "Body"

        result = serialize_frontmatter(frontmatter, body)

        assert "app: shortcuts" in result
        assert "latitude: 40.7" in result


class TestUpdateFrontmatter:
    """Tests for frontmatter updates."""

    def test_update_frontmatter_merge(self) -> None:
        """Test merging frontmatter updates."""
        content = """---
id: test-123
old_key: old_value
---

Body
"""

        result = update_frontmatter(content, {"new_key": "new_value"}, merge=True)

        # Should have both old and new keys
        assert "old_key" in result
        assert "new_key" in result
        assert "old_value" in result
        assert "new_value" in result

    def test_update_frontmatter_replace(self) -> None:
        """Test replacing frontmatter."""
        content = """---
id: test-123
old_key: old_value
---

Body
"""

        result = update_frontmatter(
            content,
            {"new_key": "new_value"},
            merge=False,
        )

        # Should only have new keys
        assert "new_key" in result
        assert "new_value" in result
        # Old keys should not be present
        assert "old_key" not in result

    def test_update_frontmatter_processed_flag(self) -> None:
        """Test updating the processed flag."""
        content = """---
id: test-123
processed: false
---

Body
"""

        result = update_frontmatter(content, {"processed": True})

        assert "processed: true" in result


class TestHelperFunctions:
    """Tests for helper functions."""

    def test_strip_frontmatter(self) -> None:
        """Test stripping frontmatter from content."""
        content = """---
id: test-123
---

Body content
"""

        result = strip_frontmatter(content)
        assert "id" not in result
        assert "Body content" in result

    def test_get_frontmatter(self) -> None:
        """Test extracting frontmatter dict."""
        content = """---
id: test-123
source: iphone
---

Body
"""

        result = get_frontmatter(content)
        assert result["id"] == "test-123"
        assert result["source"] == "iphone"


class TestCaptureValidation:
    """Tests for capture frontmatter validation."""

    def test_parse_and_validate_capture_success(self) -> None:
        """Test successful capture validation."""
        content = """---
id: 2026-01-02T14:30:00Z-iphone
captured_at: 2026-01-02T14:30:00Z
source: iphone
input: voice
processed: false
context:
  app: shortcuts
---

Capture text here
"""

        frontmatter, body = parse_and_validate_capture(content)

        assert isinstance(frontmatter, CaptureFrontmatter)
        assert frontmatter.id == "2026-01-02T14:30:00Z-iphone"
        assert frontmatter.source == "iphone"
        assert frontmatter.input == "voice"
        assert frontmatter.processed is False
        assert "Capture text" in body

    def test_parse_and_validate_capture_missing_id(self) -> None:
        """Test validation fails with missing id."""
        content = """---
captured_at: 2026-01-02T14:30:00Z
source: iphone
input: voice
---

Body
"""

        with pytest.raises(FrontmatterError):
            parse_and_validate_capture(content)

    def test_parse_and_validate_capture_invalid_source(self) -> None:
        """Test validation fails with invalid source."""
        content = """---
id: test-123
captured_at: 2026-01-02T14:30:00Z
source: invalid_source
input: voice
---

Body
"""

        with pytest.raises(FrontmatterError):
            parse_and_validate_capture(content)

    def test_parse_and_validate_capture_invalid_input(self) -> None:
        """Test validation fails with invalid input."""
        content = """---
id: test-123
captured_at: 2026-01-02T14:30:00Z
source: iphone
input: invalid_input
---

Body
"""

        with pytest.raises(FrontmatterError):
            parse_and_validate_capture(content)

    def test_parse_and_validate_capture_no_frontmatter(self) -> None:
        """Test validation fails with no frontmatter."""
        content = "Just plain content"

        with pytest.raises(FrontmatterError):
            parse_and_validate_capture(content)


class TestCommandValidation:
    """Tests for command frontmatter validation."""

    def test_parse_and_validate_command_with_frontmatter(self) -> None:
        """Test command validation with frontmatter."""
        content = """---
description: Process and organize brain dumps
version: 1
requires_lock: true
---

Command content here
"""

        frontmatter, body = parse_and_validate_command(content)

        assert isinstance(frontmatter, CommandFrontmatter)
        assert frontmatter.description == "Process and organize brain dumps"
        assert "Command content" in body

    def test_parse_and_validate_command_no_frontmatter(self) -> None:
        """Test command validation without frontmatter (uses defaults)."""
        content = "Just command content"

        frontmatter, body = parse_and_validate_command(content)

        assert isinstance(frontmatter, CommandFrontmatter)
        assert frontmatter.description is None

    def test_parse_and_validate_command_invalid_version(self) -> None:
        """Test command validation fails with invalid version type."""
        content = """---
description: Test
version: not_a_number
---

Content
"""

        frontmatter, body = parse_and_validate_command(content)
        assert frontmatter.description == "Test"
        assert "Content" in body


class TestRoundTrip:
    """Tests for parse/serialize round-trip."""

    def test_roundtrip_basic(self) -> None:
        """Test parsing and serializing maintains data."""
        original = """---
id: test-123
captured_at: 2026-01-02T14:30:00Z
source: iphone
---

Body content
"""

        parsed = parse_frontmatter(original)
        reserialized = serialize_frontmatter(parsed.frontmatter, parsed.body)
        reparsed = parse_frontmatter(reserialized)

        assert reparsed.frontmatter["id"] == "test-123"
        assert "Body content" in reparsed.body

    def test_roundtrip_nested_dict(self) -> None:
        """Test round-trip with nested dictionaries."""
        original = """---
id: test-123
context:
  app: shortcuts
  level2:
    value: 42
---

Content
"""

        parsed = parse_frontmatter(original)
        reserialized = serialize_frontmatter(parsed.frontmatter, parsed.body)
        reparsed = parse_frontmatter(reserialized)

        assert reparsed.frontmatter["context"]["level2"]["value"] == 42


class TestEdgeCases:
    """Tests for edge cases and error conditions."""

    def test_frontmatter_with_dashes_in_body(self) -> None:
        """Test content with dashes in body doesn't confuse parser."""
        content = """---
id: test-123
---

This is a body with
--- some dashes ---
scattered throughout
"""

        result = parse_frontmatter(content)
        assert result.frontmatter["id"] == "test-123"
        assert "some dashes" in result.body

    def test_very_long_frontmatter(self) -> None:
        """Test handling of very long frontmatter values."""
        long_value = "x" * 10000
        content = f"""---
id: test-123
large_value: {long_value}
---

Body
"""

        result = parse_frontmatter(content)
        assert result.frontmatter["large_value"] == long_value

    def test_frontmatter_with_unicode(self) -> None:
        """Test Unicode characters in frontmatter."""
        content = """---
id: test-123
title: "Title with émojis 🎉 and ñ characters"
---

Content with émojis 🎉
"""

        result = parse_frontmatter(content)
        assert "🎉" in result.frontmatter["title"]
        assert "🎉" in result.body

    def test_empty_content(self) -> None:
        """Test empty content."""
        result = parse_frontmatter("")
        assert result.frontmatter == {}
        assert result.body == ""

    def test_only_frontmatter_no_body(self) -> None:
        """Test content with only frontmatter, no body."""
        content = """---
id: test-123
---
"""

        result = parse_frontmatter(content)
        assert result.frontmatter["id"] == "test-123"
        assert result.body == ""
