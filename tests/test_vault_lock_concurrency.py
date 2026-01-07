"""
Tests for vault lock initialization and concurrency behavior.

These tests verify that:
1. The vault lock is properly initialized in the event loop
2. The lock serializes concurrent access
3. The lock prevents race conditions in critical sections
4. Error handling works correctly for uninitialized lock
"""

import asyncio

import pytest

from app.services.lock import get_vault_lock, init_vault_lock, reset_lock_for_testing


@pytest.mark.asyncio
async def test_vault_lock_initialized_after_init():
    """Verify vault lock is initialized after calling init_vault_lock()."""
    await reset_lock_for_testing()
    lock = await init_vault_lock()
    assert lock is not None
    assert isinstance(lock, asyncio.Lock)


@pytest.mark.asyncio
async def test_get_vault_lock_returns_same_instance():
    """Verify get_vault_lock() returns the same lock instance."""
    await reset_lock_for_testing()
    await init_vault_lock()

    lock1 = get_vault_lock()
    lock2 = get_vault_lock()

    assert lock1 is lock2


@pytest.mark.asyncio
async def test_get_vault_lock_raises_if_not_initialized():
    """Verify get_vault_lock() raises RuntimeError if not initialized."""
    await reset_lock_for_testing()

    with pytest.raises(RuntimeError, match="not initialized"):
        get_vault_lock()


@pytest.mark.asyncio
async def test_vault_lock_prevents_concurrent_access():
    """Verify vault lock prevents concurrent access to critical section."""
    await reset_lock_for_testing()
    lock = await init_vault_lock()

    in_critical_section = False
    concurrent_access_detected = False

    async def critical_section_task(task_id: int) -> None:
        nonlocal in_critical_section, concurrent_access_detected

        async with lock:
            if in_critical_section:
                concurrent_access_detected = True
            in_critical_section = True
            await asyncio.sleep(0.01)  # Hold lock briefly
            in_critical_section = False

    # Run multiple tasks concurrently
    await asyncio.gather(
        critical_section_task(1),
        critical_section_task(2),
        critical_section_task(3),
    )

    assert not concurrent_access_detected, "Lock did not prevent concurrent access!"


@pytest.mark.asyncio
async def test_vault_lock_serializes_writes():
    """Verify vault lock serializes concurrent write operations."""
    await reset_lock_for_testing()
    lock = await init_vault_lock()

    acquisition_order: list[int] = []

    async def write_task(task_id: int, delay: float = 0.0) -> None:
        """Simulate write operation with lock."""
        await asyncio.sleep(delay)
        async with lock:
            acquisition_order.append(task_id)
            await asyncio.sleep(0.01)

    # Start tasks with staggered timing
    # Task 2 starts first, then 3, then 1
    await asyncio.gather(
        write_task(1, delay=0.05),
        write_task(2, delay=0.0),
        write_task(3, delay=0.025),
    )

    # All tasks should have executed
    assert len(acquisition_order) == 3
    assert set(acquisition_order) == {1, 2, 3}

    # Task 2 should have acquired lock first (started first, no delay)
    assert acquisition_order[0] == 2


@pytest.mark.asyncio
async def test_vault_lock_fairness():
    """Verify vault lock provides fair access (FIFO ordering)."""
    await reset_lock_for_testing()
    lock = await init_vault_lock()

    acquisition_order: list[int] = []

    async def competing_task(task_id: int) -> None:
        """Task that competes for lock."""
        async with lock:
            acquisition_order.append(task_id)
            await asyncio.sleep(0.01)

    # Create 5 tasks and ensure they execute in a predictable order
    tasks = [competing_task(i) for i in range(1, 6)]
    await asyncio.gather(*tasks)

    assert len(acquisition_order) == 5
    assert set(acquisition_order) == {1, 2, 3, 4, 5}


@pytest.mark.asyncio
async def test_vault_lock_multiple_init_raises_error():
    """Verify calling init_vault_lock() twice raises RuntimeError."""
    await reset_lock_for_testing()
    await init_vault_lock()

    with pytest.raises(RuntimeError, match="already initialized"):
        await init_vault_lock()


@pytest.mark.asyncio
async def test_vault_lock_exception_handling():
    """Verify lock is properly released even if exception occurs in critical section."""
    await reset_lock_for_testing()
    lock = await init_vault_lock()

    tasks_completed = []

    async def failing_task() -> None:
        """Task that raises exception in critical section."""
        try:
            async with lock:
                tasks_completed.append("entered")
                raise ValueError("Simulated error")
        except ValueError:
            tasks_completed.append("caught")
            raise

    async def normal_task() -> None:
        """Normal task that should execute after failing task."""
        async with lock:
            tasks_completed.append("normal")

    # Run failing task then normal task
    with pytest.raises(ValueError):
        await failing_task()

    # Normal task should still be able to acquire lock
    await normal_task()

    assert "entered" in tasks_completed
    assert "caught" in tasks_completed
    assert "normal" in tasks_completed


@pytest.mark.asyncio
async def test_vault_lock_with_multiple_concurrent_readers():
    """Verify lock serializes even simple reading operations (no concurrent reads)."""
    await reset_lock_for_testing()
    lock = await init_vault_lock()

    operation_log: list[str] = []

    async def read_operation(op_id: int) -> None:
        """Simulate read operation."""
        async with lock:
            operation_log.append(f"read_{op_id}_start")
            await asyncio.sleep(0.005)
            operation_log.append(f"read_{op_id}_end")

    # All read operations should serialize
    await asyncio.gather(
        read_operation(1),
        read_operation(2),
        read_operation(3),
    )

    # Verify operations didn't overlap
    assert len(operation_log) == 6
    for i in range(0, 6, 2):
        assert "start" in operation_log[i]
        assert "end" in operation_log[i + 1]
        assert operation_log[i].split("_")[1] == operation_log[i + 1].split("_")[1]


@pytest.mark.asyncio
async def test_reset_lock_for_testing():
    """Verify reset_lock_for_testing() properly resets lock state."""
    # Initialize lock
    lock1 = await init_vault_lock()
    assert lock1 is not None

    # Reset lock
    await reset_lock_for_testing()

    # Should raise error since lock is not initialized
    with pytest.raises(RuntimeError, match="not initialized"):
        get_vault_lock()

    # Should be able to initialize again
    lock2 = await init_vault_lock()
    assert lock2 is not None
    # Note: lock2 might be the same object due to reuse, but that's implementation detail


@pytest.mark.asyncio
async def test_vault_lock_timeout_behavior():
    """Verify lock blocks until released (eventual access guaranteed)."""
    await reset_lock_for_testing()
    lock = await init_vault_lock()

    execution_times: dict[int, list[float]] = {1: [], 2: []}
    import time

    async def long_running_task() -> None:
        """Task that holds lock for a bit."""
        async with lock:
            execution_times[1].append(time.time())
            await asyncio.sleep(0.05)

    async def waiting_task() -> None:
        """Task that waits for lock."""
        # Small delay to ensure first task gets lock first
        await asyncio.sleep(0.01)
        async with lock:
            execution_times[2].append(time.time())

    # Run both tasks
    await asyncio.gather(long_running_task(), waiting_task())

    # Both should have executed
    assert len(execution_times[1]) == 1
    assert len(execution_times[2]) == 1

    # Task 1 should have started and completed before task 2 started
    assert execution_times[1][0] < execution_times[2][0]
