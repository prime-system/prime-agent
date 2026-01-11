from datetime import datetime

from app.services.vault import VaultService


def test_ensure_structure_creates_folders(temp_vault):
    """Ensure structure creates base directory only."""
    service = VaultService(str(temp_vault))
    service.ensure_structure()

    # .prime directory should be created
    assert (temp_vault / ".prime").exists()
    assert (temp_vault / ".prime").is_dir()

    # All other folders should NOT be auto-created (created on-demand)
    assert not (temp_vault / ".claude").exists()
    assert not (temp_vault / "Daily").exists()
    assert not (temp_vault / "Notes").exists()
    assert not (temp_vault / "Inbox").exists()
    assert not (temp_vault / "Logs").exists()


def test_inbox_path(temp_vault):
    """Inbox path returns correct default path."""
    service = VaultService(str(temp_vault))
    inbox = service.inbox_path()
    assert inbox == temp_vault / ".prime" / "inbox"


def test_get_capture_file(temp_vault):
    """Capture file path uses timestamp and source with weekly subfolders by default."""
    service = VaultService(str(temp_vault))

    dt = datetime(2025, 12, 21, 14, 30, 0)
    file_path = service.get_capture_file(dt, "iphone")

    assert file_path.name == "2025-12-21_14-30-00_iphone.md"
    assert file_path.parent.name == "2025-W51"
    assert file_path.parent.parent == temp_vault / ".prime" / "inbox"


def test_get_capture_file_different_sources(temp_vault):
    """Capture file includes source in filename."""
    service = VaultService(str(temp_vault))

    dt = datetime(2025, 12, 21, 14, 30, 0)

    iphone_file = service.get_capture_file(dt, "iphone")
    ipad_file = service.get_capture_file(dt, "ipad")
    mac_file = service.get_capture_file(dt, "mac")

    assert iphone_file.name == "2025-12-21_14-30-00_iphone.md"
    assert ipad_file.name == "2025-12-21_14-30-00_ipad.md"
    assert mac_file.name == "2025-12-21_14-30-00_mac.md"
    # All files should be in the same weekly subfolder
    assert iphone_file.parent == ipad_file.parent == mac_file.parent


def test_get_relative_path(temp_vault):
    """Relative path calculation is correct."""
    service = VaultService(str(temp_vault))
    absolute_path = temp_vault / ".prime" / "inbox" / "brain-dump-2025-W51.md"

    relative = service.get_relative_path(absolute_path)
    assert relative == ".prime/inbox/brain-dump-2025-W51.md"
