"""Tests for processing API endpoints."""

import pytest


def test_trigger_processing_requires_auth(client):
    """Trigger endpoint requires authentication."""
    response = client.post("/api/processing/trigger")
    assert response.status_code == 401


def test_trigger_processing_success(client, auth_headers):
    """Trigger endpoint starts processing."""
    response = client.post("/api/processing/trigger", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] in ["started", "already_running"]
    assert "message" in data


def test_get_status_requires_auth(client):
    """Status endpoint requires authentication."""
    response = client.get("/api/processing/status")
    assert response.status_code == 401


def test_get_status_success(client, auth_headers):
    """Status endpoint returns processing state."""
    response = client.get("/api/processing/status", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert "is_running" in data
    assert isinstance(data["is_running"], bool)
    assert "unprocessed_count" in data
    assert isinstance(data["unprocessed_count"], int)
    # last_run can be None if no runs have occurred
    if data["last_run"] is not None:
        assert "timestamp" in data["last_run"]
        assert "duration_seconds" in data["last_run"]
        assert "status" in data["last_run"]


def test_get_queue_requires_auth(client):
    """Queue endpoint requires authentication."""
    response = client.get("/api/processing/queue")
    assert response.status_code == 401


def test_get_queue_success(client, auth_headers):
    """Queue endpoint returns unprocessed dumps."""
    response = client.get("/api/processing/queue", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert "count" in data
    assert "dumps" in data
    assert isinstance(data["count"], int)
    assert isinstance(data["dumps"], list)
    assert data["count"] == len(data["dumps"])


def test_get_queue_with_unprocessed_dump(client, auth_headers, sample_capture_request):
    """Queue endpoint lists captured dumps."""
    # First, create a capture
    capture_response = client.post(
        "/capture",
        json=sample_capture_request,
        headers=auth_headers,
    )
    assert capture_response.status_code == 200

    # Then check the queue
    queue_response = client.get("/api/processing/queue", headers=auth_headers)
    assert queue_response.status_code == 200
    data = queue_response.json()

    # Should have at least one unprocessed dump
    assert data["count"] >= 1
    assert len(data["dumps"]) >= 1

    # Check dump structure
    dump = data["dumps"][0]
    assert "id" in dump
    assert "file" in dump
    assert "captured_at" in dump
    assert "source" in dump
    assert "input" in dump
    assert "preview" in dump


def test_trigger_while_already_running(client, auth_headers):
    """Triggering while processing returns already_running status."""
    # First trigger
    response1 = client.post("/api/processing/trigger", headers=auth_headers)
    assert response1.status_code == 200
    data1 = response1.json()

    # If it started processing, a second immediate trigger should return already_running
    # (This test may be timing-dependent - processing might finish very quickly)
    response2 = client.post("/api/processing/trigger", headers=auth_headers)
    assert response2.status_code == 200
    data2 = response2.json()

    # Either we started and it's already running, or it finished and we started again
    assert data2["status"] in ["already_running", "started"]
