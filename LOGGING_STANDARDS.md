# Logging Standards

All application logging should use structured JSON format with well-defined fields for better observability.

## Pattern

All logs must follow this pattern:

```python
import logging

logger = logging.getLogger(__name__)

# ✓ GOOD - Structured fields in extra dict
logger.info("Event description", extra={"field1": value1, "field2": value2})

# ❌ BAD - String formatting (not parsed by log aggregators)
logger.info(f"Event description: {value1}, {value2}")
```

## Common Fields by Operation Type

### Capture Operations

```python
logger.info("Capture received", extra={
    "dump_id": "2026-01-02T14:30:45Z-iphone",
    "source": "iphone",
    "size_bytes": 1024,
})

logger.info("Capture saved locally", extra={
    "dump_id": dump_id,
    "relative_path": "Inbox/2025-W51/...",
    "size_bytes": len(content),
})

logger.error("Failed to write capture file", extra={
    "dump_id": dump_id,
    "error": str(e),
    "error_type": "OSError",
    "path": str(inbox_file),
}, exc_info=True)
```

### Git Operations

```python
logger.info("Cloning vault from repository", extra={
    "repo_url": repo_url,
    "timeout_seconds": 30,
    "vault_path": str(vault_path),
})

logger.debug("Git commit completed", extra={
    "message": commit_msg,
    "files_count": 5,
})

logger.info("Auto-commit and push completed", extra={
    "files_count": 3,
    "timestamp": "2026-01-02 14:30:00 UTC",
})

logger.error("Git clone failed", extra={
    "repo_url": repo_url,
    "error": str(e),
    "error_type": "GitCommandError",
}, exc_info=True)
```

### Agent Processing

```python
logger.info("Agent worker initialized", extra={
    "git_enabled": True,
})

logger.info("Starting agent processing")

logger.info("Processing completed successfully", extra={
    "duration_seconds": 45.23,
    "cost_usd": 0.0123,
})

logger.error("Processing failed", extra={
    "duration_seconds": 60.0,
    "error": "Agent error message",
})

logger.error("Agent processing timed out", extra={
    "timeout_seconds": 300,
})
```

### Background Tasks

```python
logger.error("Background task failed", extra={
    "task_name": "git_auto_commit",
    "error": "Push failed: authentication error",
    "error_type": "GitError",
}, exc_info=error)
```

## Field Naming Conventions

- Use `snake_case` for all field names
- Use descriptive names that are self-explanatory
- Common fields:
  - `error`: Error message (string)
  - `error_type`: Exception type name (string)
  - `duration_seconds`: Operation duration in seconds (float)
  - `cost_usd`: API cost in USD (float)
  - `timestamp`: ISO 8601 timestamp (string)
  - `files_count`: Number of files affected (int)
  - `size_bytes`: Size in bytes (int)
  - `timeout_seconds`: Timeout duration (int)
  - `vault_path`: Path to vault (string)
  - `dump_id`: Unique capture ID (string)
  - `source`: Source of capture (string: "iphone", "web", etc.)

## Log Levels

Use appropriate log levels:

- **DEBUG**: Detailed internal state (low frequency, disabled in production)
  - Git operations completed
  - File lock acquired
  - Template loaded

- **INFO**: Normal operation milestones (high-level events)
  - Capture received
  - Processing started/completed
  - Worker initialized
  - Auto-commit succeeded

- **WARNING**: Recoverable issues
  - Title generation failed (fallback used)
  - No changes to auto-commit
  - Git pull failed but continuing

- **ERROR**: Operation failures
  - Capture write failed
  - Git operations failed
  - Processing failed
  - Timeout exceeded

## JSON Output Example

When structured logging is enabled, logs output as JSON:

```json
{
  "timestamp": "2026-01-05T14:30:47.123Z",
  "level": "INFO",
  "name": "app.services.git",
  "message": "Auto-commit and push completed",
  "files_count": 3,
  "timestamp": "2026-01-02 14:30:00 UTC"
}
```

## Security Best Practices

**NEVER log sensitive data:**

❌ BAD:
```python
logger.info(f"Git credentials: {git_token}")
logger.info(f"API key starts with: {api_key[:20]}")
```

✓ GOOD:
```python
logger.info("Git authentication succeeded")
logger.info("API configured", extra={"api_base_url": api_base_url})
```

See CLAUDE.md "Security Best Practices: Credential Handling" for detailed guidelines.

## Integration with Log Aggregation

Structured logs are compatible with log aggregation systems:

- **Datadog Logs**: Parse JSON fields automatically
- **ELK Stack**: Use json input filter
- **CloudWatch**: Query using JSON field syntax
- **Grafana Loki**: JSON parser

Example Datadog query:
```
service:prime-agent @dump_id:abc123 @level:ERROR
```

## Configuration

Logging format is configured at startup in `app/main.py`:

```python
from app.logging_config import configure_json_logging

# Configure structured JSON logging
configure_json_logging(log_level=settings.log_level)
```

To disable JSON output (development):
```python
configure_json_logging(log_level=settings.log_level, use_json=False)
```

## Testing

When testing, capture JSON logs:

```python
import json
import logging
from io import StringIO
from app.utils import json_formatter

# Capture logs
log_stream = StringIO()
handler = logging.StreamHandler(log_stream)
handler.setFormatter(json_formatter.JsonFormatter())
logger = logging.getLogger("test")
logger.addHandler(handler)

# Log something
logger.info("Test", extra={"field": "value"})

# Parse JSON
log_line = log_stream.getvalue()
log_data = json.loads(log_line)
assert log_data["field"] == "value"
```

## Checklist for New Code

When adding new logging:

- [ ] Use `logger = logging.getLogger(__name__)` at module level
- [ ] Use `extra` dict for structured fields (not f-strings)
- [ ] Include relevant fields (dump_id, error type, duration, etc.)
- [ ] Use appropriate log level (DEBUG/INFO/WARNING/ERROR)
- [ ] Never log credentials or sensitive data
- [ ] Use `exc_info=True` for exceptions
- [ ] Use snake_case for field names
- [ ] Check that JSON output is valid and parseable

## References

- [Python JSON Logger](https://github.com/madzak/python-json-logger)
- [Logging HOWTO](https://docs.python.org/3/howto/logging.html)
- [CLAUDE.md - Logging section](./CLAUDE.md#logging)
