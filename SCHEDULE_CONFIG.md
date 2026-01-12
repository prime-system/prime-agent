# Schedule Configuration (.prime/schedule.yaml)

**Run vault slash commands on a schedule.**

---

## Overview

The `.prime/schedule.yaml` file lives in your **vault root** and lets you trigger
slash commands automatically (the same commands listed by `/api/v1/commands`).

### Location

```
/vault/.prime/schedule.yaml
```

---

## Full Example

```yaml
timezone: "Europe/Berlin"
jobs:
  - id: "daily-brief"
    command: "dailyBrief"
    cron: "0 6 * * *"
    overlap: "queue"
    queue_max: 1
    timeout_seconds: 900
    max_budget_usd: 1.0
```

---

## Configuration Options

### Top-Level

- `timezone` (string, optional)
  - IANA timezone name. Default: system timezone (falls back to `UTC`).
  - Example: `Europe/Berlin`, `America/New_York`.

### Jobs

Each entry in `jobs` defines a scheduled run.

- `id` (string, required)
  - Unique job identifier.
- `command` (string, required)
  - Slash command name **without** the leading `/`.
  - If your command lives in a namespace, use `namespace:command`.
- `arguments` (string, optional)
  - Extra arguments appended to the command.
- `cron` (string, required)
  - Standard 5-field cron expression.
  - Example: every 15 minutes: `*/15 * * * *`.
- `overlap` (string, optional)
  - `skip` or `queue`. Default: `skip`.
  - `skip`: ignore runs while the job is already running.
  - `queue`: queue runs while the job is running.
- `queue_max` (int, optional)
  - Maximum queued runs when `overlap: queue`.
  - Default: `1`. New runs are dropped once the queue is full.
- `timeout_seconds` (int, optional)
  - Per-run timeout override (in seconds).
- `max_budget_usd` (float, optional)
  - Per-run budget override (in USD).
- `model` (string, optional)
  - Model override for this job.
- `enabled` (bool, optional)
  - Enable/disable the job. Default: `true`.
- `use_vault_lock` (bool, optional)
  - Acquire the global vault lock during execution. Default: `false`.

---

## Monitoring & Control

- **Status:** `GET /api/v1/schedule/status`
  - Shows running jobs, elapsed time, next run, last status, and errors.
- **Cancel:** `POST /api/v1/schedule/jobs/{job_id}/cancel`
  - Cancels a running job and clears its queue.

---

## Notes

- Cron uses **5 fields**: `min hour day month weekday`.
- Commands come from `.claude/commands/` in the vault or plugins.
- If a command is missing, the job records an error and continues scheduling.
