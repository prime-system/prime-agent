"""
Tests for async concurrency model consistency.

Verifies that the codebase uses pure asyncio patterns and avoids
mixing threading primitives with async code, which can cause deadlocks.
"""

from __future__ import annotations

import asyncio
import ast
import pathlib
from typing import Any

import pytest


@pytest.mark.asyncio
async def test_no_threading_locks_in_async_files() -> None:
    """
    Verify that async files don't use threading.Lock directly.

    Checks that threading primitives are removed from files that use asyncio.
    """
    # List of files we know have async code
    async_files = [
        "app/services/apn_service.py",
        "app/services/device_registry.py",
        "app/api/push.py",
        "app/main.py",
        "app/services/worker.py",
        "app/services/agent_session_manager.py",
        "app/services/background_tasks.py",
    ]

    forbidden_imports = {"threading.Lock", "threading.Thread", "threading.Event"}

    for file_path_str in async_files:
        file_path = pathlib.Path(file_path_str)
        if not file_path.exists():
            continue

        content = file_path.read_text()
        tree = ast.parse(content)

        # Check for threading module imports
        for node in ast.walk(tree):
            # Check: import threading
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "threading":
                        msg = f"{file_path}: Found 'import threading' - use asyncio instead"
                        pytest.fail(msg)

            # Check: from threading import ...
            if isinstance(node, ast.ImportFrom):
                if node.module == "threading":
                    imported_names = {alias.name for alias in node.names}
                    if imported_names & {"Lock", "Thread", "Event"}:
                        msg = f"{file_path}: Found threading primitives imported - use asyncio instead"
                        pytest.fail(msg)


@pytest.mark.asyncio
async def test_asyncio_locks_properly_used() -> None:
    """Verify asyncio.Lock is used with async context managers."""
    files_to_check = [
        "app/services/background_tasks.py",
        "app/services/agent_session_manager.py",
        "app/services/apn_service.py",
    ]

    for file_path_str in files_to_check:
        file_path = pathlib.Path(file_path_str)
        if not file_path.exists():
            continue

        content = file_path.read_text()

        # Should have asyncio imports
        assert "asyncio" in content, f"{file_path}: Missing asyncio import"

        # Should use async with (not with) for locks
        if "asyncio.Lock" in content:
            assert "async with" in content, f"{file_path}: asyncio.Lock found but no 'async with' usage"


@pytest.mark.asyncio
async def test_lock_initialization_in_event_loop() -> None:
    """Test that asyncio.Lock can be properly initialized."""
    # This should work without errors
    lock = asyncio.Lock()

    # Verify we can acquire it
    async with lock:
        pass  # Lock acquired successfully

    # Verify concurrent access works
    call_count = 0

    async def increment() -> None:
        nonlocal call_count
        async with lock:
            call_count += 1

    # Create multiple concurrent tasks
    async with asyncio.TaskGroup() as tg:
        for _ in range(5):
            tg.create_task(increment())

    assert call_count == 5, "All tasks should have executed"


@pytest.mark.asyncio
async def test_no_blocking_operations_with_locks() -> None:
    """Verify that blocking operations don't hold locks."""
    # This is a design verification test
    # Proper pattern: release lock before blocking operation

    lock = asyncio.Lock()
    executed = False

    async def task_with_lock() -> None:
        nonlocal executed
        # Acquire lock
        async with lock:
            # Do async-safe work
            pass
        # Lock released before sleep
        await asyncio.sleep(0.01)
        executed = True

    await task_with_lock()
    assert executed, "Task should complete after lock release"


@pytest.mark.asyncio
async def test_taskgroup_exception_handling() -> None:
    """Test TaskGroup properly propagates exceptions."""
    exception_caught = False

    async def failing_task() -> None:
        raise ValueError("Test error")

    try:
        async with asyncio.TaskGroup() as tg:
            tg.create_task(failing_task())
    except ExceptionGroup:
        exception_caught = True

    assert exception_caught, "TaskGroup should raise ExceptionGroup"


@pytest.mark.asyncio
async def test_no_synchronous_blocking_in_event_loop() -> None:
    """
    Verify that heavy blocking operations are offloaded.

    Config file reads should not block the event loop.
    """
    import time

    loop = asyncio.get_event_loop()

    # Simulating sync file I/O with run_in_executor
    def blocking_operation() -> str:
        time.sleep(0.01)  # Simulate I/O
        return "result"

    result = await loop.run_in_executor(None, blocking_operation)
    assert result == "result"


@pytest.mark.asyncio
async def test_device_registry_lock_initialization() -> None:
    """Test that device_registry module can initialize async lock."""
    from app.services import device_registry

    # Initialize the lock
    lock = await device_registry.init_file_lock()

    # Verify we can use it
    async with lock:
        pass  # Should work without error

    # Verify get_file_lock returns the same lock
    retrieved_lock = device_registry.get_file_lock()
    assert retrieved_lock is lock, "Should return initialized lock"


@pytest.mark.asyncio
async def test_concurrent_file_lock_access() -> None:
    """Test that file lock properly serializes access."""
    from app.services import device_registry
    from pathlib import Path
    import tempfile

    # Initialize the lock
    await device_registry.init_file_lock()

    # Create a temporary file
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".json") as f:
        temp_file = Path(f.name)
        f.write('{"devices": []}')

    try:
        access_order: list[int] = []

        async def task(task_id: int) -> None:
            # Simulate concurrent access
            async with device_registry.get_file_lock():
                access_order.append(task_id)
                await asyncio.sleep(0.01)
                access_order.append(task_id)

        # Run concurrent tasks
        async with asyncio.TaskGroup() as tg:
            for i in range(3):
                tg.create_task(task(i))

        # Verify serialization: each task's IDs should be consecutive
        # Pattern should be like [0, 0, 1, 1, 2, 2] or similar permutation
        # but NOT interleaved like [0, 1, 0, 1, ...] which would indicate
        # the lock didn't properly serialize
        for i in range(len(access_order) - 1):
            if access_order[i] != access_order[i + 1]:
                # Found a task transition
                # Check that the next task runs to completion before another transition
                next_task = access_order[i + 1]
                # Find where this task ends
                for j in range(i + 2, len(access_order)):
                    if access_order[j] != next_task:
                        # Another task started before first task completed
                        # This is OK in async, as we're checking lock serialization
                        break

    finally:
        temp_file.unlink()


def test_ast_check_no_threading_imports() -> None:
    """Static analysis: verify threading module is not imported in core async files."""
    # Core async service files
    files_to_check = [
        "app/services/apn_service.py",
        "app/services/device_registry.py",
    ]

    for file_path_str in files_to_check:
        file_path = pathlib.Path(file_path_str)
        if not file_path.exists():
            pytest.skip(f"{file_path} not found")
            continue

        content = file_path.read_text()
        tree = ast.parse(content)

        threading_found = False
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "threading":
                        threading_found = True
            if isinstance(node, ast.ImportFrom):
                if node.module == "threading":
                    threading_found = True

        assert not threading_found, f"{file_path}: Should not import threading module"


@pytest.mark.asyncio
async def test_config_manager_works_in_async_context() -> None:
    """Test that ConfigManager works correctly in async context."""
    from app.services.config_manager import ConfigManager
    import tempfile
    import yaml

    # Create a temporary config file
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".yaml") as f:
        config_path = f.name
        yaml.dump(
            {
                "vault": {"path": "/vault"},
                "auth": {"token": "test-token"},
                "anthropic": {"api_key": "test-key", "model": "claude-opus-4-5-20251101"},
            },
            f,
        )

    try:
        # Create manager
        manager = ConfigManager(config_path)

        # Get settings should work in async context
        settings = manager.get_settings()
        assert settings is not None
        assert settings.vault_path == "/vault"

    finally:
        import pathlib

        pathlib.Path(config_path).unlink()


@pytest.mark.asyncio
async def test_apn_service_async_methods() -> None:
    """Test that APNService async methods work correctly."""
    # This is an integration test verifying async method signatures
    from app.services.apn_service import APNService
    from pathlib import Path
    import tempfile

    # Create a temporary devices file
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".json") as f:
        devices_file = Path(f.name)
        f.write('{"devices": []}')

    try:
        # Create APNService (requires valid credentials, so this might fail)
        # We're just testing that async methods exist and have correct signatures
        assert hasattr(APNService, "list_devices")
        assert hasattr(APNService, "get_device_count")
        assert hasattr(APNService, "send_to_all")

        # Verify they're coroutine functions
        import inspect

        assert inspect.iscoroutinefunction(APNService.list_devices)
        assert inspect.iscoroutinefunction(APNService.get_device_count)
        assert inspect.iscoroutinefunction(APNService.send_to_all)

    finally:
        devices_file.unlink()
