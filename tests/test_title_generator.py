"""Tests for title generation service."""

from unittest.mock import MagicMock, patch

import pytest

from app.services.title_generator import TitleGenerator


@pytest.fixture
def mock_query():
    """Mock the claude_agent_sdk.query function."""
    with patch("app.services.title_generator.query") as mock:
        yield mock


class TestTitleGenerator:
    """Tests for TitleGenerator service."""

    def test_generate_title_basic(self, mock_query):
        """Generate title from simple text."""
        mock_query.return_value = "meeting-notes-with-team"

        generator = TitleGenerator()
        title = generator.generate_title("We had a great meeting with the team today")

        assert title == "meeting-notes-with-team"
        assert mock_query.called

    def test_generate_title_sanitizes_output(self, mock_query):
        """Title is sanitized to be filesystem-safe."""
        mock_query.return_value = "My Meeting Notes!!!"

        generator = TitleGenerator()
        title = generator.generate_title("Some text")

        # Should be lowercase, no special chars, hyphens instead of spaces
        assert title == "my-meeting-notes"

    def test_generate_title_removes_quotes(self, mock_query):
        """Quotes are removed from title."""
        mock_query.return_value = '"shopping-list"'

        generator = TitleGenerator()
        title = generator.generate_title("Need to buy groceries")

        assert title == "shopping-list"

    def test_generate_title_max_length(self, mock_query):
        """Title is truncated to max length."""
        mock_query.return_value = "this-is-a-very-long-title-that-should-be-truncated"

        generator = TitleGenerator()
        title = generator.generate_title("Some text", max_length=20)

        assert len(title) <= 20
        assert not title.endswith("-")  # No trailing hyphens

    def test_generate_title_fallback_on_error(self, mock_query):
        """Fallback to simple title on API error."""
        mock_query.side_effect = Exception("API error")

        generator = TitleGenerator()
        title = generator.generate_title("Meeting with the development team tomorrow")

        # Should use fallback (first few words)
        assert title  # Not empty
        assert len(title) <= 50  # Within max length
        assert "-" in title  # Words separated by hyphens

    def test_generate_title_empty_response(self, mock_query):
        """Handle empty response from API."""
        mock_query.return_value = ""

        generator = TitleGenerator()
        title = generator.generate_title("Some text")

        # Should use fallback
        assert title == "untitled" or title.startswith("some-text")

    def test_generate_title_too_short_response(self, mock_query):
        """Handle very short response from API."""
        mock_query.return_value = "ab"

        generator = TitleGenerator()
        title = generator.generate_title("Some text")

        # Should use fallback since < 3 chars
        assert title == "untitled" or len(title) >= 3

    def test_sanitize_title_removes_special_chars(self):
        """Special characters are removed from title."""
        generator = TitleGenerator()

        assert generator._sanitize_title("hello@world!") == "helloworld"
        assert generator._sanitize_title("test#123") == "test123"
        assert generator._sanitize_title("foo/bar\\baz") == "foobarbaz"

    def test_sanitize_title_consolidates_hyphens(self):
        """Multiple hyphens are consolidated."""
        generator = TitleGenerator()

        assert generator._sanitize_title("foo---bar") == "foo-bar"
        assert generator._sanitize_title("a--b--c") == "a-b-c"

    def test_sanitize_title_removes_leading_trailing_hyphens(self):
        """Leading and trailing hyphens are removed."""
        generator = TitleGenerator()

        assert generator._sanitize_title("-foo-") == "foo"
        assert generator._sanitize_title("--bar--") == "bar"

    def test_fallback_title_basic(self):
        """Fallback title uses first few words."""
        generator = TitleGenerator()

        title = generator._fallback_title("Meeting with the development team", 50)
        assert title == "meeting-with-the-development"

    def test_fallback_title_truncates(self):
        """Fallback title respects max length."""
        generator = TitleGenerator()

        title = generator._fallback_title(
            "This is a very long text with many words that should be truncated", 20
        )
        assert len(title) <= 20

    def test_fallback_title_empty_input(self):
        """Fallback title handles empty input."""
        generator = TitleGenerator()

        title = generator._fallback_title("", 50)
        assert title == "untitled"
