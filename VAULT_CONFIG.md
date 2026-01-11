# Vault Configuration (.prime/settings.yaml)

**Complete guide to customizing how Prime stores captures in your vault.**

---

## Overview

The `.prime/settings.yaml` file lives in your **vault root** (not the server config) and allows you to personalize how captures are organized. This enables different vault structures for different users without changing server configuration.

### Location

Place `settings.yaml` in your vault root under `.prime/`:
```
/vault/.prime/settings.yaml
```

### Why Configure the Vault?

- **Flexible Folder Structure** - Use your own inbox folder name (e.g., "07-Inbox" for Obsidian numbering)
- **Organize by Time** - Group captures into weekly subfolders automatically
- **Smart Filenames** - Use timestamps and any combination of available placeholders
- **No Breaking Changes** - If `.prime.yaml` doesn't exist, uses sensible defaults

---

## Configuration Options

### Full Example

```yaml
inbox:
  # Folder name for incoming captures (relative to vault root)
  folder: "07-Inbox"

  # Create weekly subfolders (e.g., 2026-W01/)
  weekly_subfolders: true

  # Filename pattern for capture files
  file_pattern: "{year}-{month}-{day}_{hour}-{minute}-{second}_{source}.md"
```

### Inbox Folder

Customize the folder name where captures are stored:

```yaml
inbox:
  folder: "Inbox"        # Default
  # folder: "07-Inbox"   # Numbered (Obsidian-style)
  # folder: "00-Inbox"   # Leading zeros
  # folder: "Captures"   # Any name you prefer
```

### Weekly Subfolders

Automatically organize captures by ISO week:

```yaml
inbox:
  weekly_subfolders: true   # Creates Inbox/2026-W01/, Inbox/2026-W02/, etc.
  # weekly_subfolders: false  # All files directly in Inbox/
```

**Example structure with `weekly_subfolders: true`:**
```
07-Inbox/
├── 2026-W01/
│   ├── 2026-01-02_12-00-00_iphone.md
│   └── 2026-01-02_14-30-00_mac.md
└── 2026-W02/
    └── 2026-01-06_09-15-00_ipad.md
```

### File Patterns

Customize how capture files are named:

```yaml
inbox:
  file_pattern: "{year}-{month}-{day}_{hour}-{minute}-{second}_{source}.md"
```

**Available Placeholders:**

| Placeholder | Description | Example |
|-------------|-------------|---------|
| `{year}` | Full year | `2026` |
| `{month}` | Month (zero-padded) | `01` |
| `{day}` | Day (zero-padded) | `02` |
| `{hour}` | Hour (zero-padded, 24h) | `14` |
| `{minute}` | Minute (zero-padded) | `30` |
| `{second}` | Second (zero-padded) | `45` |
| `{source}` | Device source | `iphone`, `ipad`, `mac` |
| `{iso_year}` | ISO year | `2026` |
| `{iso_week}` | ISO week number | `01`, `52` |

**Pattern Examples:**

```yaml
# Timestamp with source (default)
file_pattern: "{year}-{month}-{day}_{hour}-{minute}-{second}_{source}.md"
# Result: 2026-01-02_14-30-45_iphone.md

# ISO week with timestamp
file_pattern: "{iso_year}-W{iso_week}_{hour}-{minute}_{source}.md"
# Result: 2026-W01_14-30_iphone.md

# Simple daily capture
file_pattern: "{year}-{month}-{day}_{source}.md"
# Result: 2026-01-02_iphone.md

# Compact format
file_pattern: "{year}{month}{day}_{hour}{minute}_{source}.md"
# Result: 20260102_1430_iphone.md
```

---

## Default Configuration

If `.prime/settings.yaml` doesn't exist, Prime uses these defaults:

```yaml
inbox:
  folder: ".prime/inbox"
  weekly_subfolders: true
  file_pattern: "{year}-{month}-{day}_{hour}-{minute}-{second}_{source}.md"

logs:
  folder: ".prime/logs"
```

**Default path example:**
```
.prime/inbox/2026-W01/2026-01-02_14-30-45_iphone.md
```

---

## Capture File Format

Each capture is stored as a standalone Markdown file with frontmatter:

```yaml
---
id: 2026-01-02T14:30:45Z-iphone
captured_at: 2026-01-02T14:30:45Z
source: iphone
input: voice
context:
  app: shortcuts
processed: true
processed_at: 2026-01-02T14:32:10Z
result:
  - Daily/2026-01-02.md
  - Notes/Authentication System.md
  - Tasks/Inbox.md
---

Had a great meeting with the development team today. We discussed
the new authentication system and decided to move forward with JWT tokens.
```

**Frontmatter Fields:**

- `id` - Unique capture identifier (timestamp + source)
- `captured_at` - ISO 8601 timestamp (UTC)
- `source` - Device used (iphone, ipad, mac)
- `input` - Input method (voice, text)
- `context` - Additional metadata (app, location)
- `processed` - Processing status (added by agent)
- `processed_at` - When processing completed
- `result` - Files created/updated during processing

---

## Configuration Examples

### Organized by Week (Recommended Default)

Best balance of organization and flexibility:

```yaml
inbox:
  folder: "07-Inbox"
  weekly_subfolders: true
  file_pattern: "{year}-{month}-{day}_{hour}-{minute}-{second}_{source}.md"
```

**Result:** `07-Inbox/2026-W01/2026-01-02_14-30-45_iphone.md`

**Pros:**
- Weekly folders keep things organized
- Chronologically sorted within folders
- Fast capture processing
- Never conflicts

**Cons:**
- Less human-readable filenames
- Can't tell content at a glance

### Simple Daily Captures

Minimal approach for daily notes workflow:

```yaml
inbox:
  folder: "Inbox"
  weekly_subfolders: false
  file_pattern: "{iso_year}-W{iso_week}-{source}.md"
```

**Result:** `Inbox/2026-W01-iphone.md`

**Pros:**
- Very simple structure
- One file per source per week
- Fast capture processing

**Cons:**
- Multiple captures append to same file
- Less granular organization

### Compact Format

Maximum information in filenames:

```yaml
inbox:
  folder: "00-Inbox"
  weekly_subfolders: true
  file_pattern: "{iso_year}W{iso_week}_{year}-{month}-{day}_{hour}{minute}_{source}.md"
```

**Result:** `00-Inbox/2026-W01/2026W01_2026-01-02_1430_iphone.md`

**Pros:**
- Everything at a glance
- Sortable by week, date, time
- Compact format

**Cons:**
- Less human-readable than spaced format
- Potentially difficult to parse visually

---

## Tips & Best Practices

### Start Simple

Use the defaults first, then customize once you understand your workflow:

```yaml
# Start here - sensible defaults
inbox:
  folder: "Inbox"
  weekly_subfolders: true
  file_pattern: "{year}-{month}-{day}_{hour}-{minute}-{second}_{source}.md"
```

After a week, evaluate:
- Are the filenames useful or confusing?
- Is the weekly organization working?
- Do you need more or less detail in filenames?

### Weekly Subfolders Recommended

Unless you have a specific reason not to, enable weekly subfolders:

```yaml
weekly_subfolders: true  # Do this
```

**Why:**
- Keeps inbox folder manageable (12-20 files per folder)
- Natural organization by time period
- Easy to archive old weeks
- Better file system performance

### Consistent Naming

Stick to one pattern. Changing patterns creates inconsistent filenames across your vault.

**Bad:**
```yaml
# Week 1: timestamps with seconds
file_pattern: "{year}-{month}-{day}_{hour}-{minute}-{second}_{source}.md"

# Week 2: simple dates (changed mind)
file_pattern: "{year}-{month}-{day}_{source}.md"

# Week 3: ISO week format (changed again)
file_pattern: "{iso_year}-W{iso_week}_{source}.md"
```

**Result:** Mixed naming in your vault, hard to browse.

**Good:** Pick one pattern and stick with it. You can always refine it, but avoid constant changes.

### Test Your Pattern

Before committing to a pattern:

1. Create a test `.prime/settings.yaml` in your vault
2. Send 5-10 test captures with varied content
3. Browse the resulting files
4. Ask yourself:
   - Can I find captures easily?
   - Are filenames useful?
   - Does the organization make sense?
5. Adjust and test again if needed

### Obsidian Integration

If using Obsidian for viewing your vault:

**Folder numbering:**
```yaml
inbox:
  folder: "07-Inbox"  # Shows near bottom in sidebar
  # folder: "00-Inbox"  # Shows at top
  # folder: "Inbox"     # Alphabetical
```

**Weekly subfolders:**
- Enable for cleaner folder view
- Collapsed folders hide processed captures

**Filename considerations:**
- Obsidian search works regardless of filename pattern
- Timestamps sort chronologically in file explorer
- Use descriptive folder names for easier navigation

---

## Reloading Configuration

Prime automatically detects changes to `.prime/settings.yaml`:

- **New captures** use the updated configuration immediately
- **Existing files** are not renamed (intentional - prevents breaking links)
- **No server restart** needed
- **Takes effect** on next capture after file is saved

### Testing Changes

```bash
# 1. Edit .prime/settings.yaml
nano /vault/.prime/settings.yaml

# 2. Send a test capture
curl -X POST http://localhost:8000/api/v1/capture \
  -H "Authorization: Bearer $AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "text": "Test capture with new config",
    "source": "mac",
    "input": "text",
    "context": {"app": "cli"}
  }'

# 3. Check the resulting filename
ls -la /vault/.prime/inbox/  # or your custom inbox folder
```

---

## Troubleshooting

### Files Going to Wrong Folder

**Symptom:** Captures appear in `.prime/inbox/` instead of your custom folder

**Cause:** `.prime/settings.yaml` not found or has syntax errors

**Solutions:**
```bash
# Check file exists in vault root
ls -la /vault/.prime/settings.yaml

# Validate YAML syntax
python3 -c "import yaml; yaml.safe_load(open('/vault/.prime/settings.yaml'))"

# Check for common mistakes
grep -E "^\s+\t" /vault/.prime/settings.yaml  # Mixed tabs/spaces (bad)
```

### Weekly Subfolders Not Created

**Symptom:** Files appear directly in inbox folder

**Causes:**
1. `weekly_subfolders: false` in config
2. `.prime.yaml` not found (uses defaults)

**Solutions:**
```yaml
# Explicitly enable in .prime.yaml
inbox:
  weekly_subfolders: true
```

### Filename Conflicts

**Symptom:** Error saving capture, file already exists

**Cause:** Using overly simplified patterns without enough granularity

**Solutions:**
```yaml
# Add seconds to timestamp for uniqueness
file_pattern: "{year}-{month}-{day}_{hour}-{minute}-{second}_{source}.md"

# Or use ISO week with time
file_pattern: "{iso_year}-W{iso_week}_{hour}-{minute}-{second}_{source}.md"
```

### Configuration Not Reloading

**Symptom:** Changes to `.prime/settings.yaml` not taking effect

**Cause:** File not in vault root, or syntax errors preventing load

**Solutions:**
```bash
# Ensure correct location
ls -la /vault/.prime/settings.yaml  # NOT /vault/Inbox/.prime/settings.yaml

# Check file permissions
chmod 644 /vault/.prime/settings.yaml

# Force reload by restarting (usually not needed)
docker-compose restart primeai
```

---

## Advanced Use Cases

### Multiple Patterns Based on Source

While `.prime.yaml` doesn't support conditional patterns directly, you can use the source placeholder to differentiate:

**Approach: Use source in filename**
```yaml
inbox:
  file_pattern: "{source}_{year}-{month}-{day}_{hour}-{minute}.md"
```
Result: `iphone_2026-01-02_14-30.md`, `mac_2026-01-02_16-45.md`

**Alternative: Different workflows per device**
Configure your capture apps to use different vault folders or include metadata that helps you identify later.

### Custom Date Formats

Combine placeholders for any date format:

```yaml
# ISO date
file_pattern: "{year}-{month}-{day}.md"
# Result: 2026-01-02.md

# US date format
file_pattern: "{month}-{day}-{year}_{source}.md"
# Result: 01-02-2026_iphone.md

# European date format
file_pattern: "{day}.{month}.{year}_{hour}-{minute}_{source}.md"
# Result: 02.01.2026_14-30_iphone.md

# Compact format
file_pattern: "{year}{month}{day}_{hour}{minute}_{source}.md"
# Result: 20260102_1430_iphone.md
```

### Weekly vs Daily Organization

**Weekly (recommended):**
```yaml
inbox:
  weekly_subfolders: true
  file_pattern: "{year}-{month}-{day}_{hour}-{minute}_{source}.md"
```
Result: `Inbox/2026-W01/2026-01-02_14-30_iphone.md`

**Daily (alternative):**
```yaml
inbox:
  weekly_subfolders: false
  file_pattern: "{year}-{month}-{day}/{hour}-{minute}_{source}.md"  # Note: pattern creates subfolders
```
Result: `Inbox/2026-01-02/14-30_iphone.md`

**Monthly:**
```yaml
inbox:
  weekly_subfolders: false
  file_pattern: "{year}-{month}/{day}_{hour}-{minute}_{source}.md"
```
Result: `Inbox/2026-01/02_14-30_iphone.md`

---

## Migration Guide

### From Weekly Files to Per-Capture

If you were using the old weekly append mode:

**Old structure:**
```
Inbox/brain-dump-2026-W01.md  # Multiple captures in one file
```

**New structure:**
```
Inbox/2026-W01/
  ├── 2026-01-02_12-00-00_iphone.md  # One capture per file
  └── 2026-01-02_14-30-00_mac.md
```

**Migration steps:**
1. Create `.prime.yaml` with desired pattern
2. New captures use new pattern automatically
3. Old weekly files remain unchanged (safe)
4. Optionally: Manually split old files if needed

**No action required** - both formats coexist peacefully.

---

## Related Documentation

- [Main README](./README.md) - Server setup and API reference
- [Server Configuration](./README.md#configuration) - `config.yaml` for server settings
- [API Reference](./README.md#api-reference) - Capture endpoint details
- [Vault Structure](./README.md#vault-structure) - Overall vault organization

---

**Questions or Issues?**

Open an issue on [GitHub](https://github.com/prime-system/prime-agent/issues) or check the [troubleshooting section](#troubleshooting) above.
