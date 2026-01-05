def test_health_check(client):
    """Health endpoint returns ok status."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_capture_requires_auth(client, sample_capture_request):
    """Capture endpoint requires authentication."""
    response = client.post("/capture", json=sample_capture_request)
    assert response.status_code == 401  # HTTPBearer returns 401 when no credentials provided


def test_capture_rejects_invalid_token(client, sample_capture_request):
    """Capture endpoint rejects invalid token."""
    response = client.post(
        "/capture",
        json=sample_capture_request,
        headers={"Authorization": "Bearer invalid"},
    )
    assert response.status_code == 401


def test_capture_validates_request(client, auth_headers):
    """Capture endpoint validates request body."""
    response = client.post(
        "/capture",
        json={"text": ""},
        headers=auth_headers,
    )
    assert response.status_code == 422


def test_capture_validates_empty_text(client, auth_headers):
    """Capture endpoint rejects empty text."""
    response = client.post(
        "/capture",
        json={
            "text": "",
            "source": "iphone",
            "input": "voice",
            "captured_at": "2025-12-21T14:30:00Z",
            "context": {"app": "shortcuts"},
        },
        headers=auth_headers,
    )
    assert response.status_code == 422


def test_capture_validates_invalid_source(client, auth_headers):
    """Capture endpoint rejects invalid source."""
    response = client.post(
        "/capture",
        json={
            "text": "Test thought",
            "source": "invalid",
            "input": "voice",
            "captured_at": "2025-12-21T14:30:00Z",
            "context": {"app": "shortcuts"},
        },
        headers=auth_headers,
    )
    assert response.status_code == 422


def test_capture_success(client, auth_headers, sample_capture_request):
    """Capture endpoint accepts valid request (per-capture file mode with subfolders)."""
    response = client.post(
        "/capture",
        json=sample_capture_request,
        headers=auth_headers,
    )

    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert "inbox_file" in data
    assert "dump_id" in data
    # Per-capture mode with weekly subfolders: Inbox/YYYY-Www/YYYY-MM-DD_HH-MM-SS_source.md
    assert data["inbox_file"] == "Inbox/2025-W51/2025-12-21_14-30-00_iphone.md"
    assert data["dump_id"] == "2025-12-21T14:30:00Z-iphone"


def test_capture_with_location(client, auth_headers):
    """Capture endpoint accepts request with location."""
    response = client.post(
        "/capture",
        json={
            "text": "Test thought with location",
            "source": "iphone",
            "input": "voice",
            "captured_at": "2025-12-21T14:30:00Z",
            "context": {
                "app": "prime",
                "location": {"latitude": 37.7749, "longitude": -122.4194},
            },
        },
        headers=auth_headers,
    )

    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True


def test_capture_different_sources(client, auth_headers):
    """Capture endpoint accepts all valid sources."""
    for source in ["iphone", "ipad", "mac"]:
        response = client.post(
            "/capture",
            json={
                "text": f"Test from {source}",
                "source": source,
                "input": "text",
                "captured_at": "2025-12-21T14:30:00Z",
                "context": {"app": "cli"},
            },
            headers=auth_headers,
        )
        assert response.status_code == 200


def test_capture_different_input_types(client, auth_headers):
    """Capture endpoint accepts all valid input types."""
    for input_type in ["voice", "text"]:
        response = client.post(
            "/capture",
            json={
                "text": f"Test {input_type} input",
                "source": "mac",
                "input": input_type,
                "captured_at": "2025-12-21T14:30:00Z",
                "context": {"app": "cli"},
            },
            headers=auth_headers,
        )
        assert response.status_code == 200


def test_capture_different_app_contexts(client, auth_headers):
    """Capture endpoint accepts all valid app contexts."""
    for app in ["prime", "shortcuts", "cli", "web"]:
        response = client.post(
            "/capture",
            json={
                "text": f"Test from {app}",
                "source": "mac",
                "input": "text",
                "captured_at": "2025-12-21T14:30:00Z",
                "context": {"app": app},
            },
            headers=auth_headers,
        )
        assert response.status_code == 200
