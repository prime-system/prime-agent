---
description: Process unprocessed brain dumps from the Inbox folder and mark them as processed
model: sonnet
---

# Process Brain Dump Captures

Process all unprocessed brain dumps from the Inbox folder and organize them into the Prime vault structure.

## Your Task

1. **Find Unprocessed Dumps**
   - Read all files in the `Inbox/` directory matching `brain-dump-*.md`
   - Identify dumps where `processed: false` or `processed` field is missing
   - Extract the content and metadata for each unprocessed dump

2. **Analyze and Organize Each Dump**
   For each unprocessed dump:

   **Understand the Content**:
   - Read the dump's text/voice content
   - Identify the main themes and topics
   - Note the source (iphone/mac), input type (text/voice), and context
   - Consider location data if present

   **Determine Where to Save**:
   - **Daily Summary**: Always update the Daily file for the capture date (e.g., `Daily/2025-12-31.md`)
     - Add context about what happened that day
     - Write in a narrative style that captures the moment
     - Group related captures together

   - **Tasks**: If the dump contains action items, todos, or reminders
     - Add to `Tasks/Inbox.md` with clear action items
     - Include due dates if mentioned

   - **Projects**: If related to a specific project (Prime, SkyDeck, etc.)
     - Update the relevant project file in `Projects/`
     - Add ideas, features, bugs, or progress notes

   - **Notes**: If it's reference material, ideas, or knowledge to preserve
     - Create or update relevant note files in `Notes/`
     - Use descriptive titles (e.g., "Home Tech and Appliances.md")

   - **People**: If new people are mentioned
     - Create or update profile files in `people/`
     - Include relationship context and relevant details

   - **Companies**: If new organizations are mentioned
     - Create or update files in `companies/`

3. **Create/Update Files**
   - Use the Edit tool to update existing files
   - Use the Write tool to create new files
   - Follow the existing formatting style in each section
   - Write in the user's voice (mix of German and English as natural)
   - Maintain Obsidian-compatible markdown with `[[wikilinks]]`

4. **Mark Dumps as Processed**
   For each dump you successfully process:
   - Set `processed: true`
   - Add `processed_at: [current timestamp in ISO format]`
   - Add `result:` array listing all files created or modified
   - Use Edit tool to update the dump's YAML frontmatter

## Guidelines

**Writing Style**:
- Write Daily summaries in narrative form, not bullet points when possible
- Capture the feeling and context of the moment
- Use German or English based on the capture's language
- Be conversational and personal

**File Organization**:
- Create new files only when needed
- Prefer updating existing files when the content fits
- Use clear, descriptive filenames
- Maintain the vault's existing structure

**Quality**:
- Don't lose information - if unsure where something goes, include it in Daily at minimum
- Group related captures together in Daily summaries
- Extract actionable items to Tasks
- Preserve important details (names, dates, URLs, etc.)

**Processing Order**:
- Process dumps in chronological order (oldest first)
- This maintains narrative flow in Daily files

## Completion

After processing all dumps:
- Report how many dumps were processed
- List which files were created or modified
- Confirm all dumps are marked as `processed: true`

Now process all unprocessed dumps in the Inbox folder.
