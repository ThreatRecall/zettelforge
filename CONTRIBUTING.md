# Contributing to ZettelForge

Thank you for your interest in contributing to ZettelForge! This document provides guidelines for contributing to the project.

## Development Setup

1. Fork and clone the repository
2. Create a virtual environment: `python -m venv venv`
3. Activate it: `source venv/bin/activate` (or `venv\Scripts\activate` on Windows)
4. Install in development mode: `pip install -e ".[dev]"`
5. Run tests to verify your setup: `pytest tests/ -v`

No external services (Ollama, TypeDB, Docker) are required for development. ZettelForge defaults to SQLite for storage and fastembed for in-process embeddings.

## Development Workflow

1. Create a feature branch: `git checkout -b feature/your-feature-name`
2. Make your changes
3. Run tests: `pytest tests/ -v`
4. Run linting: `ruff check src/zettelforge/`
5. Run formatting: `ruff format src/zettelforge/`
6. Commit with a Conventional Commits message (see "Commit Messages" below)
7. Push and create a pull request

CI enforces the same `ruff check` and `ruff format --check` invocations
plus `pytest --cov-fail-under=67`, `pip-audit`, governance spec-drift,
and Snyk SCA/SAST. The full active rule set is `{E, F, I, W, N, T20,
B, UP, SIM, RUF, S}` per GOV-003 §"Tooling and Automation"; only ANN
remains and is being ratcheted per-module.

## Where to contribute

All of `src/zettelforge/` is MIT-licensed and open to contributions.
Feature ideas, bug fixes, documentation, benchmarks — all welcome.

If your contribution needs TypeDB or OpenCTI, open an issue to discuss.
We keep the extension boundary clear so contributors know their work
will always remain open source.

### For major features: Start with an RFC

If you're proposing a significant new feature (new subsystem, new backend,
breaking API change), open an RFC before writing code. RFCs live in
`docs/rfcs/` and follow the template from the existing RFCs in that
directory. Open a Discussion first to socialize the idea, then file a
draft RFC as a PR. This prevents wasted effort on work that won't be
accepted.

See [ROADMAP.md](ROADMAP.md) for the current priorities and what's
planned for upcoming releases.

### Good first issues

Issues tagged [good first issue](https://github.com/rolandpg/zettelforge/issues?q=is%3Aissue+is%3Aopen+label%3A%22good+first+issue%22)
have structured acceptance criteria in the issue body. Check the issue
for: which files to edit, test expectations, and example input/output.
If an issue is unclear, ask in the issue comments.

## Issue triage

This project is maintained by a solo developer (per GOV-006). Here is
what you can expect:

- **New issues**: triaged within 7 days. You will get a response (even
  if it's "not planned, closing").
- **Bug reports**: severity assessed within 7 days. P0 (crash, data
  loss, security) gets a same-day response.
- **Feature requests**: tagged with `enhancement` on creation. The
  maintainer will add `planned`, `deferred`, or `won't fix` within 7
  days.
- **PR reviews**: first review within 14 days of submission. Smaller
  PRs get reviewed faster.
- **Stale issues**: issues with no activity for 60 days are tagged
  `stale` and closed after 14 more days without response. This keeps
  the tracker manageable for a solo maintainer.

## Contributor recognition

Every contributor is listed in [CONTRIBUTORS.md](CONTRIBUTORS.md),
regardless of contribution size. If you submit a PR that gets merged,
you will be added. If your name is missing, open a PR.

## Code Style

- Follow PEP 8
- Use type hints where possible
- Document functions with docstrings
- Keep functions focused and small
- Write tests for new functionality

## Testing

- Write tests for new features
- Ensure all tests pass before submitting PR
- Tests that require extension features should use the `enable_extensions` fixture from `tests/conftest.py`
- Use meaningful test names that describe behavior

## Commit Messages

Use clear, descriptive commit messages:

- `feat: Add entity extraction for CVE patterns`
- `fix: Correct vector similarity calculation`
- `docs: Update API reference`
- `test: Add tests for recall_cve method`

## Pull Request Process

1. Update documentation if needed
2. Add tests for new functionality
3. Ensure CI passes
4. Request review from maintainers
5. Address review feedback

## Questions?

- Open an issue for bugs or feature requests
- Start a discussion for questions or ideas
- Check existing issues before creating new ones
