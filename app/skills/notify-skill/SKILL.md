---
name: notify
description: Sends push notifications to Apple devices (iPhone, iPad, Mac) via Prime API. Use when processing brain dumps completes, errors occur during agent operations, long-running tasks finish, or the user explicitly requests notifications.
---

# Notify Skill

Sends push notifications to Apple devices via the Prime API backend. Dependencies are automatically managed by `uv run` - no manual installation required.

## Quick Start

```bash
uv run notify.py --title "Processing Complete" --body "5 notes created from brain dump"
```

The script is located in this skill's directory. Run from the skill directory or use the full path to `notify.py`.

## Arguments

**Required:**
- `--title` - Notification title
- `--body` - Message body

**Optional:**
- `[DEVICE_FILTER]` - Device name, type, or comma-separated list (e.g., `michaels-iphone`, `iphone`, `iphone,mac`)
- `--priority` - `high` or `normal` (default: normal)
- `--environment` - Filter by `development` or `production`
- `--data` - Custom JSON data
- `--badge` - Badge count (integer)
- `--verbose` - Show detailed output
- `--json` - Output results as JSON

## Common Patterns

### After Processing Brain Dumps

```bash
uv run notify.py \
  --title "Processing Complete" \
  --body "Created 3 notes: [[Note 1]], [[Note 2]], [[Note 3]]"
```

### On Agent Errors

```bash
uv run notify.py \
  --title "Processing Error" \
  --body "Failed to parse dump content" \
  --priority high
```

### For Specific Devices

```bash
# Send to specific device
uv run notify.py michaels-iphone --title "Test" --body "Hello"

# Send to all iPhones
uv run notify.py iphone --title "iOS Update" --body "New feature"

# Send to production devices only
uv run notify.py --environment production --title "Alert" --body "System update required"
```

### With Custom Data

```bash
uv run notify.py \
  --title "Processing Complete" \
  --body "5 notes created" \
  --data '{"type":"processing_complete","note_count":5,"duration":12}'
```

## Workflow for Multi-Step Notifications

For complex operations, track progress with notifications:

```
Notification Progress:
- [ ] Step 1: Send "started" notification
- [ ] Step 2: Perform operation
- [ ] Step 3: Send "complete" or "error" notification
```

**Example workflow:**

1. **Send start notification:**
   ```bash
   uv run notify.py --title "Processing Started" --body "Processing 10 brain dumps..."
   ```

2. **Perform operation** (process dumps, create notes, etc.)

3. **Send completion notification:**
   ```bash
   # On success:
   uv run notify.py --title "Processing Complete" --body "Created 15 notes, updated 3 projects"

   # On error:
   uv run notify.py --title "Processing Error" --body "Failed after processing 5 of 10 dumps" --priority high
   ```

## Exit Codes

- `0` - Success (all sent)
- `1` - Partial failure (some failed)
- `2` - Complete failure (none sent)
- `3` - Configuration error (missing API token, connection failed)

## Configuration

The script requires configuration via environment variables:

**Required:**
- `PRIME_API_URL` - API endpoint URL
- `PRIME_API_TOKEN` - API authentication token

**Setup:**
```bash
export PRIME_API_URL="your-api-url"
export PRIME_API_TOKEN="your-api-token"
```

## How It Works

The notify script:
1. Loads API configuration (token and URL)
2. Makes an HTTPS request to `/api/v1/notifications/send`
3. The Prime backend handles:
   - Device token lookup
   - APNs connection and authentication
   - Notification delivery
   - Invalid token cleanup
4. Returns detailed results (sent/failed counts, per-device status)

## Error Handling

The backend automatically:
- Removes invalid/expired device tokens
- Provides detailed per-device status
- Handles APNs connection failures gracefully

Common errors:
- **401 Invalid API token**: Check your `PRIME_API_TOKEN` environment variable
- **503 Service unavailable**: Push notifications not enabled on server
- **Connection error**: Prime server not reachable - check `PRIME_API_URL` and network
