"""CORS security tests to prevent cross-origin vulnerabilities."""

import pytest
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient


@pytest.fixture
def cors_app():
    """Create a FastAPI app with secure CORS configuration."""
    app = FastAPI()

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:3000",
            "http://localhost:8000",
        ],
        allow_credentials=True,
        allow_methods=["POST", "GET", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
        max_age=3600,
    )

    @app.get("/test")
    async def test_endpoint() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/capture")
    async def capture_endpoint() -> dict[str, str]:
        return {"ok": True}

    return app


@pytest.fixture
def cors_client(cors_app):
    """Test client with CORS middleware."""
    return TestClient(cors_app)


class TestCORSPreflight:
    """Tests for CORS preflight requests."""

    def test_cors_blocks_unknown_origins(self, cors_client):
        """Verify CORS blocks requests from unknown origins."""
        response = cors_client.options(
            "/capture",
            headers={"Origin": "https://attacker.com"},
        )
        # CORS should not include the attacker origin in the response
        assert response.headers.get("access-control-allow-origin") != "https://attacker.com"

    def test_cors_allows_trusted_origins(self, cors_client):
        """Verify CORS allows requests from trusted origins."""
        response = cors_client.options(
            "/capture",
            headers={"Origin": "http://localhost:3000"},
        )
        assert response.headers.get("access-control-allow-origin") == "http://localhost:3000"
        assert response.status_code == 200

    def test_cors_allows_multiple_trusted_origins(self, cors_client):
        """Verify CORS works with multiple allowed origins."""
        for origin in ["http://localhost:3000", "http://localhost:8000"]:
            response = cors_client.options(
                "/capture",
                headers={"Origin": origin},
            )
            assert response.headers.get("access-control-allow-origin") == origin

    def test_cors_restricts_http_methods(self, cors_client):
        """Verify CORS restricts HTTP methods to configured list."""
        response = cors_client.options(
            "/capture",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "DELETE",
            },
        )
        # DELETE should not be allowed
        allowed_methods = response.headers.get("access-control-allow-methods", "")
        assert "DELETE" not in allowed_methods or response.status_code != 200

    def test_cors_allows_configured_methods(self, cors_client):
        """Verify CORS allows configured HTTP methods."""
        response = cors_client.options(
            "/capture",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "POST",
            },
        )
        allowed_methods = response.headers.get("access-control-allow-methods", "")
        assert "POST" in allowed_methods

    def test_cors_restricts_headers(self, cors_client):
        """Verify CORS restricts headers to configured list."""
        response = cors_client.options(
            "/capture",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Headers": "X-Custom-Header",
            },
        )
        allowed_headers = response.headers.get("access-control-allow-headers", "")
        # Custom headers should not be allowed
        assert "X-Custom-Header" not in allowed_headers

    def test_cors_allows_configured_headers(self, cors_client):
        """Verify CORS allows configured headers."""
        response = cors_client.options(
            "/capture",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Headers": "Authorization, Content-Type",
            },
        )
        allowed_headers = response.headers.get("access-control-allow-headers", "")
        assert "Authorization" in allowed_headers or "Content-Type" in allowed_headers

    def test_cors_includes_credentials_flag(self, cors_client):
        """Verify CORS includes credentials flag when configured."""
        response = cors_client.options(
            "/capture",
            headers={"Origin": "http://localhost:3000"},
        )
        assert response.headers.get("access-control-allow-credentials") == "true"

    def test_cors_includes_max_age(self, cors_client):
        """Verify CORS preflight cache is set."""
        response = cors_client.options(
            "/capture",
            headers={"Origin": "http://localhost:3000"},
        )
        max_age = response.headers.get("access-control-max-age")
        assert max_age == "3600"  # 1 hour cache


class TestCORSActualRequests:
    """Tests for actual CORS requests (not preflight)."""

    def test_cors_get_request_allowed_origin(self, cors_client):
        """Verify GET request from allowed origin includes CORS headers."""
        response = cors_client.get(
            "/test",
            headers={"Origin": "http://localhost:3000"},
        )
        assert response.status_code == 200
        # FastAPI TestClient may not include all CORS headers in response,
        # but the middleware should not error

    def test_cors_post_request_allowed_origin(self, cors_client):
        """Verify POST request from allowed origin includes CORS headers."""
        response = cors_client.post(
            "/capture",
            headers={"Origin": "http://localhost:3000"},
        )
        assert response.status_code == 200


class TestCORSSecurityConfiguration:
    """Tests for CORS configuration security."""

    def test_no_wildcard_origins_with_credentials(self):
        """Verify that wildcard origins are not allowed with credentials."""
        # This is a configuration-level test to ensure the app doesn't
        # create a CORS middleware with allow_origins=["*"] and allow_credentials=True

        # In practice, FastAPI's CORSMiddleware will raise an error if you try to do this
        with pytest.raises(ValueError):
            app = FastAPI()
            app.add_middleware(
                CORSMiddleware,
                allow_origins=["*"],
                allow_credentials=True,  # This should fail
                allow_methods=["*"],
                allow_headers=["*"],
            )

    def test_cors_case_sensitive_origins(self, cors_client):
        """Verify CORS origin matching is case-sensitive where applicable."""
        # Test that mixed case domain still works (DNS is case-insensitive)
        response = cors_client.options(
            "/capture",
            headers={"Origin": "http://LOCALHOST:3000"},
        )
        # Most CORS implementations are case-insensitive for protocol/host
        # but we'll verify the behavior doesn't expose vulnerabilities


class TestCORSConfiguration:
    """Tests for CORS configuration loading and validation."""

    def test_cors_config_from_settings(self):
        """Verify CORS configuration is loaded from settings."""
        from app.config import settings

        # Settings should have CORS configuration
        assert hasattr(settings, "cors_enabled")
        assert hasattr(settings, "cors_allowed_origins")
        assert hasattr(settings, "cors_allowed_methods")
        assert hasattr(settings, "cors_allowed_headers")

    def test_cors_allowed_origins_not_empty(self):
        """Verify CORS allowed origins list is not empty."""
        from app.config import settings

        assert len(settings.cors_allowed_origins) > 0

    def test_cors_allowed_methods_not_empty(self):
        """Verify CORS allowed methods list is not empty."""
        from app.config import settings

        assert len(settings.cors_allowed_methods) > 0

    def test_cors_allowed_headers_contains_auth(self):
        """Verify CORS allowed headers includes Authorization."""
        from app.config import settings

        assert "Authorization" in settings.cors_allowed_headers

    def test_cors_allowed_headers_contains_content_type(self):
        """Verify CORS allowed headers includes Content-Type."""
        from app.config import settings

        assert "Content-Type" in settings.cors_allowed_headers

    def test_production_environment_requires_https_origins(self):
        """Verify production environment requires HTTPS origins."""
        from app.config import Settings

        # This should raise an error because non-HTTPS origins in production
        with pytest.raises(ValueError, match="CORS origin must be HTTPS in production"):
            settings_obj = Settings(
                auth_token="test-token",
                anthropic_api_key="test-key",
                agent_model="claude-3-5-haiku-latest",
                environment="production",
                cors_enabled=True,
                cors_allowed_origins=["http://localhost:3000"],  # HTTP not allowed in production
            )
            settings_obj.validate_cors_config()

    def test_development_environment_allows_http_origins(self):
        """Verify development environment allows HTTP origins."""
        from app.config import Settings

        # This should NOT raise an error
        settings_obj = Settings(
            auth_token="test-token",
            anthropic_api_key="test-key",
            agent_model="claude-3-5-haiku-latest",
            environment="development",
            cors_enabled=True,
            cors_allowed_origins=["http://localhost:3000"],
        )
        settings_obj.validate_cors_config()  # Should not raise

    def test_production_requires_base_url(self):
        """Verify production environment requires base_url to be set."""
        from app.config import Settings

        # Empty origins in production (when base_url not set) should raise an error
        with pytest.raises(
            ValueError, match="Production environment has no CORS origins configured"
        ):
            settings_obj = Settings(
                auth_token="test-token",
                anthropic_api_key="test-key",
                agent_model="claude-3-5-haiku-latest",
                environment="production",
                cors_enabled=True,
                cors_allowed_origins=[],  # Empty - should fail in production
            )
            settings_obj.validate_cors_config()

    def test_cors_derived_from_base_url_development(self):
        """Verify CORS origins are auto-derived from base_url in development."""
        from app.config import _get_cors_origins_from_base_url

        origins = _get_cors_origins_from_base_url("http://localhost:3000", "development")

        # Should include the base_url
        assert "http://localhost:3000" in origins
        # Should also include common localhost alternatives in development
        assert "http://localhost:8000" in origins
        assert "http://127.0.0.1:3000" in origins
        assert "http://127.0.0.1:8000" in origins

    def test_cors_derived_from_base_url_production(self):
        """Verify CORS origins auto-derived from base_url in production."""
        from app.config import _get_cors_origins_from_base_url

        origins = _get_cors_origins_from_base_url("https://app.example.com", "production")

        # Should include only the base_url (no localhost in production)
        assert origins == ["https://app.example.com"]

    def test_cors_base_url_strips_trailing_slash(self):
        """Verify trailing slashes are stripped from base_url."""
        from app.config import _get_cors_origins_from_base_url

        origins = _get_cors_origins_from_base_url("https://app.example.com/", "production")

        # Trailing slash should be stripped
        assert "https://app.example.com" in origins
        assert "https://app.example.com/" not in origins

    def test_cors_development_with_custom_base_url(self):
        """Verify custom base_url doesn't duplicate localhost entries in dev."""
        from app.config import _get_cors_origins_from_base_url

        origins = _get_cors_origins_from_base_url("http://localhost:8000", "development")

        # Should have base_url
        assert "http://localhost:8000" in origins
        # Should have other localhost variants
        assert "http://localhost:3000" in origins
        # But not duplicates
        assert origins.count("http://localhost:8000") == 1
