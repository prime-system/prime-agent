from datetime import datetime

from app.models.capture import (
    AppContext,
    CaptureContext,
    CaptureRequest,
    InputType,
    Location,
    Source,
)
from app.services.inbox import InboxService


def test_generate_dump_id():
    """Dump ID format is correct."""
    service = InboxService()
    dt = datetime(2025, 12, 21, 14, 30, 0)
    dump_id = service.generate_dump_id(dt, "iphone")
    assert dump_id == "2025-12-21T14:30:00Z-iphone"


def test_generate_dump_id_different_sources():
    """Dump ID includes source correctly."""
    service = InboxService()
    dt = datetime(2025, 12, 21, 14, 30, 0)

    assert service.generate_dump_id(dt, "ipad") == "2025-12-21T14:30:00Z-ipad"
    assert service.generate_dump_id(dt, "mac") == "2025-12-21T14:30:00Z-mac"


def test_format_capture_file_basic():
    """Capture file formatting uses frontmatter."""
    service = InboxService()
    request = CaptureRequest(
        text="Test thought",
        source=Source.IPHONE,
        input=InputType.VOICE,
        captured_at=datetime(2025, 12, 21, 14, 30, 0),
        context=CaptureContext(app=AppContext.SHORTCUTS),
    )
    dump_id = "2025-12-21T14:30:00Z-iphone"

    content = service.format_capture_file(request, dump_id)

    # Uses standard frontmatter
    assert content.startswith("---\n")
    assert "id: 2025-12-21T14:30:00Z-iphone" in content
    assert "source: iphone" in content
    assert "input: voice" in content
    assert "app: shortcuts" in content
    assert "Test thought" in content


def test_format_capture_file_with_location():
    """Capture file includes location when provided."""
    service = InboxService()
    request = CaptureRequest(
        text="Test thought with location",
        source=Source.IPHONE,
        input=InputType.VOICE,
        captured_at=datetime(2025, 12, 21, 14, 30, 0),
        context=CaptureContext(
            app=AppContext.PRIME,
            location=Location(latitude=37.7749, longitude=-122.4194),
        ),
    )
    dump_id = "2025-12-21T14:30:00Z-iphone"

    content = service.format_capture_file(request, dump_id)

    assert "latitude: 37.7749" in content
    assert "longitude: -122.4194" in content


def test_write_capture_creates_file(temp_vault):
    """Write capture creates file with content."""
    service = InboxService()
    file_path = temp_vault / "Inbox" / "test.md"
    file_path.parent.mkdir(parents=True, exist_ok=True)

    service.write_capture(file_path, "---\nid: test\n---\n\nTest content\n")

    assert file_path.exists()
    content = file_path.read_text()
    assert "---" in content
    assert "Test content" in content


def test_write_capture_creates_directories(temp_vault):
    """Write capture creates parent directories if needed."""
    service = InboxService()
    file_path = temp_vault / "Inbox" / "2026-W01" / "test.md"

    service.write_capture(file_path, "---\nid: test\n---\n\nTest\n")

    assert file_path.exists()


def test_write_capture_overwrites_existing(temp_vault):
    """Write capture overwrites existing file."""
    service = InboxService()
    file_path = temp_vault / "Inbox" / "test.md"
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text("Old content\n")

    service.write_capture(file_path, "New content\n")

    assert file_path.read_text() == "New content\n"
