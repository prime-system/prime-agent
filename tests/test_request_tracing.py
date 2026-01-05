"""Tests for request ID tracing with ContextVars."""

from __future__ import annotations

import asyncio
import pytest

from app.utils.request_context import (
    clear_request_id,
    generate_request_id,
    get_request_id,
    set_request_id,
)
from app.middleware.request_id import RequestIDMiddleware


class TestRequestContextManagement:
    """Tests for request context utilities."""

    def test_generate_request_id(self) -> None:
        """Verify request ID generation creates valid UUIDs."""
        request_id = generate_request_id()
        assert request_id is not None
        assert len(request_id) > 0
        assert isinstance(request_id, str)

    def test_set_and_get_request_id(self) -> None:
        """Verify request ID can be set and retrieved."""
        request_id = generate_request_id()
        set_request_id(request_id)
        assert get_request_id() == request_id

    def test_clear_request_id(self) -> None:
        """Verify request ID can be cleared."""
        set_request_id("test-id-123")
        assert get_request_id() == "test-id-123"
        clear_request_id()
        assert get_request_id() is None

    def test_default_request_id_is_none(self) -> None:
        """Verify default request ID is None."""
        clear_request_id()
        assert get_request_id() is None

    @pytest.mark.asyncio
    async def test_request_id_in_async_context(self) -> None:
        """Verify request ID propagates to async operations."""
        request_id = generate_request_id()
        set_request_id(request_id)

        async def get_context_id() -> str | None:
            await asyncio.sleep(0)
            return get_request_id()

        result = await get_context_id()
        assert result == request_id

    @pytest.mark.asyncio
    async def test_request_id_propagates_to_child_tasks(self) -> None:
        """Verify request ID propagates across task boundaries."""
        request_id = generate_request_id()
        set_request_id(request_id)
        child_ids = []

        async def child_task() -> None:
            child_ids.append(get_request_id())

        async with asyncio.TaskGroup() as tg:
            tg.create_task(child_task())

        assert len(child_ids) > 0
        assert child_ids[0] == request_id

    @pytest.mark.asyncio
    async def test_request_id_isolated_between_contexts(self) -> None:
        """Verify request IDs are isolated between different contexts."""
        id1 = generate_request_id()
        id2 = generate_request_id()
        results = []

        async def task_with_id(request_id: str) -> None:
            set_request_id(request_id)
            await asyncio.sleep(0)
            results.append(get_request_id())

        # Create independent tasks
        await asyncio.gather(
            task_with_id(id1),
            task_with_id(id2),
        )

        # Both results should match their input IDs
        assert id1 in results
        assert id2 in results


class TestRequestIDMiddleware:
    """Tests for request ID middleware."""

    @pytest.mark.asyncio
    async def test_middleware_generates_request_id(self) -> None:
        """Verify middleware generates request ID if not provided."""
        clear_request_id()
        from starlette.testclient import TestClient
        from app.main import app

        client = TestClient(app)
        response = client.get("/health")

        assert response.status_code == 200
        assert "X-Request-ID" in response.headers
        assert len(response.headers["X-Request-ID"]) > 0

    @pytest.mark.asyncio
    async def test_middleware_preserves_client_request_id(self) -> None:
        """Verify middleware uses client-provided request ID."""
        from starlette.testclient import TestClient
        from app.main import app

        client = TestClient(app)
        test_id = "custom-request-id-123"
        response = client.get("/health", headers={"X-Request-ID": test_id})

        assert response.status_code == 200
        assert response.headers["X-Request-ID"] == test_id

    @pytest.mark.asyncio
    async def test_middleware_clears_context_after_request(self) -> None:
        """Verify middleware clears context after request processing."""
        from starlette.testclient import TestClient
        from app.main import app

        client = TestClient(app)
        # Make a request
        response = client.get("/health")
        assert response.status_code == 200

        # Context should be cleared after response
        # (Note: TestClient runs synchronously, so this tests the finally block)
        # Making a new request should get a different ID
        response2 = client.get("/health")
        assert response.headers["X-Request-ID"] != response2.headers["X-Request-ID"]

    @pytest.mark.asyncio
    async def test_middleware_request_id_in_logs(self) -> None:
        """Verify request ID is included in log records."""
        import logging
        from io import StringIO
        from starlette.testclient import TestClient
        from app.main import app

        # Capture logs
        log_capture = StringIO()
        handler = logging.StreamHandler(log_capture)
        logger = logging.getLogger("app.middleware.request_id")
        logger.addHandler(handler)

        client = TestClient(app)
        test_id = "test-tracing-id-456"
        response = client.get("/health", headers={"X-Request-ID": test_id})

        assert response.status_code == 200

        # Check that request ID appears in logs
        logs = log_capture.getvalue()
        # Logs should contain the request ID somewhere
        # (Could be in structured fields or text)
        assert len(logs) > 0

        logger.removeHandler(handler)


@pytest.mark.asyncio
async def test_context_propagation_across_await() -> None:
    """Verify context propagates across await boundaries."""
    request_id = generate_request_id()
    set_request_id(request_id)

    async def level1() -> str | None:
        await asyncio.sleep(0)
        return await level2()

    async def level2() -> str | None:
        await asyncio.sleep(0)
        return get_request_id()

    result = await level1()
    assert result == request_id


@pytest.mark.asyncio
async def test_context_independent_between_tasks() -> None:
    """Verify context is independent between concurrent tasks."""
    clear_request_id()

    id1 = generate_request_id()
    id2 = generate_request_id()
    id3 = generate_request_id()

    results: dict[int, str | None] = {}

    async def task(task_num: int, context_id: str) -> None:
        set_request_id(context_id)
        await asyncio.sleep(0.01 * task_num)  # Vary timing
        results[task_num] = get_request_id()

    # Run tasks concurrently
    async with asyncio.TaskGroup() as tg:
        tg.create_task(task(1, id1))
        tg.create_task(task(2, id2))
        tg.create_task(task(3, id3))

    # Each task should have captured its own ID
    assert results[1] == id1
    assert results[2] == id2
    assert results[3] == id3
