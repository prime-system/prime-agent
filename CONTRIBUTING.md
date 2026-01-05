# Contributing to PrimeAgent

Thank you for your interest in PrimeAgent!

---

## Current Status: Alpha Development

PrimeAgent is currently in **early alpha** and the architecture is still evolving rapidly. To maintain focus and stability during this foundational phase:

**We are not accepting external contributions at this time.**

This policy will change as the project matures and the core architecture stabilizes.

---

## How You Can Help

While we're not accepting code contributions yet, you can still help:

### 1. Report Issues

If you encounter bugs, unexpected behavior, or have questions:

**Open an issue on [GitHub Issues](https://github.com/prime-system/prime-agent/issues)**

Please include:
- Clear description of the issue
- Steps to reproduce
- Expected vs. actual behavior
- Your environment (OS, Docker version, Python version, etc.)
- Relevant logs (use `docker-compose logs primeai`)
- Configuration (sanitized, no secrets)

### 2. Share Feedback

We value your experience using PrimeAgent:
- What works well?
- What's confusing?
- What features would be most valuable?
- How's the API design?
- Documentation gaps?

Open a GitHub issue labeled `feedback` to share your thoughts.

### 3. Improve Documentation

Found a typo or unclear explanation?
- Open an issue describing the problem
- Suggest improved wording or examples
- Point out missing API documentation

---

## Issue Labels

When reporting issues, we'll categorize them using these labels:

- `bug` - Something isn't working correctly
- `documentation` - Improvements or additions to documentation
- `enhancement` - New feature requests
- `api` - API design or endpoint issues
- `configuration` - Configuration-related problems
- `feedback` - General feedback and suggestions
- `question` - Questions about usage or behavior
- `agent` - Processing agent behavior
- `git-sync` - Git synchronization issues
- `wontfix` - Issues that won't be addressed (with explanation)

---

## Response Times

PrimeAgent is a **personal project** maintained by a single developer alongside other commitments.

**Expected response times:**
- Critical bugs: 1-3 days
- Other issues: 1-2 weeks
- Feature requests: Acknowledged when reviewed, implemented based on roadmap

Please be patient. All issues will be reviewed, though not all can be addressed immediately.

---

## Future Contribution Guidelines

When PrimeAgent reaches a more stable state, we plan to accept contributions for:

- Bug fixes
- API endpoint improvements
- Documentation enhancements
- Test coverage
- Performance optimizations
- New features (after discussion)
- Agent processing improvements

**What we'll look for:**
- Clear, focused pull requests
- Tests for new functionality (pytest)
- API documentation updates
- Configuration examples
- Adherence to existing code style (Black, isort)
- Alignment with project vision (see [../PRD.md](../PRD.md))

We'll update this document when we're ready to accept contributions.

---

## Development Philosophy

To understand PrimeAgent's design decisions, read:

- [CLAUDE.md](./CLAUDE.md) - Architecture and design principles

PrimeAgent is built on these core beliefs:

1. **Capture is dumb** - No decisions at input time
2. **Processing is intelligent** - Agent makes all structural choices
3. **Serialized execution** - Deterministic, repeatable processing
4. **Plain text storage** - Markdown files, not databases
5. **Single-user focus** - Personal knowledge system, not a platform

---

## Code of Conduct

### Our Standards

PrimeAgent is a small, focused project. We expect:

- **Respectful communication** - Disagree constructively
- **Patience** - Remember this is a personal project
- **Clear reporting** - Help us help you by providing details
- **Understanding** - Not all requests can be accommodated

### Unacceptable Behavior

- Harassment, trolling, or personal attacks
- Spam or off-topic issues
- Demanding immediate responses or features
- Repeatedly reopening closed issues without new information

**Enforcement:** Issues violating these standards will be closed and users may be blocked.

---

## Security Issues

**Do not open public issues for security vulnerabilities.**

Instead, email the maintainer directly (contact information will be added).

Include:
- Description of the vulnerability
- Steps to reproduce
- Potential impact
- Suggested fix (if any)

We'll respond within 72 hours and coordinate a responsible disclosure.

---

## Testing

If you're testing PrimeAgent and want to help improve quality:

### What to Test

- **API endpoints** - Try various input patterns
- **Configuration** - Test different config combinations
- **Git sync** - Both SSH and HTTPS authentication
- **Error handling** - Invalid inputs, missing configs
- **Agent processing** - Various dump formats and complexity
- **Docker deployment** - Different environments

### Reporting Test Results

Open an issue with:
- Test scenario
- Expected behavior
- Actual behavior
- Configuration used (sanitized)
- Logs (if applicable)

---

## Documentation Improvements

Documentation is crucial for adoption. Help us improve:

### What Needs Documentation

- Common setup issues and solutions
- Real-world configuration examples
- API usage patterns
- Integration guides (Shortcuts, Obsidian, etc.)
- Processing behavior examples

### How to Suggest Improvements

Open an issue with:
- Current documentation section (link or quote)
- What's unclear or missing
- Suggested improvement
- Target audience (beginner, advanced, developer)

---

## Feature Requests

We're open to feature ideas, but remember:

**Design Constraints:**
- Must preserve append-only inbox principle
- Must maintain serialized processing
- Must output plain Markdown
- Must support single-user use case
- Must not add capture-time friction

When suggesting features:
- Explain the problem it solves
- Describe your use case
- Consider alternatives
- Reference the PRD principles

---

## Questions?

- **Bug reports:** [GitHub Issues](https://github.com/prime-system/prime-agent/issues)
- **General questions:** [GitHub Issues](https://github.com/prime-system/prime-agent/issues) (use `question` label)
- **Security concerns:** Email maintainer (contact TBD)
- **API questions:** [GitHub Issues](https://github.com/prime-system/prime-agent/issues) (use `api` label)

---

## Related Projects

PrimeAgent is part of the Prime ecosystem:

- **[PrimeClaude](https://github.com/prime-system/prime-claude)** - Interactive SSH container
- **Prime-App** (private) - iOS/macOS/iPadOS capture app

Issues specific to those components should be reported in their respective repositories.

---

## License

By reporting issues or providing feedback, you agree that:
- Your contributions are provided voluntarily
- Any suggestions become part of the project
- PrimeAgent remains under the [Apache License 2.0](LICENSE)

---

**Thank you for your interest in PrimeAgent!**

We appreciate your patience as we build this system. Your feedback during this alpha phase is invaluable, even if we can't accept code contributions yet.

---

*Last updated: January 2026*
