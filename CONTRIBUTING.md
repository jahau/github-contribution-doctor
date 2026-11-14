# Contributing

Thanks for helping make missing contributions less mysterious.

## Setup

```bash
git clone https://github.com/jahau/github-contribution-doctor
cd github-contribution-doctor
python -m venv .venv
# Windows: .venv\Scripts\activate    macOS/Linux: source .venv/bin/activate
python -m pip install -e ".[dev]"
```

## Checks to run before opening a pull request

```bash
ruff check src tests doctor.py
ruff format --check src tests doctor.py
mypy
pytest
```

CI runs the same commands on Linux, Windows, and macOS for Python 3.10–3.14.

## Project layout

| Module | Responsibility |
| --- | --- |
| `gitio.py` | The only place that runs Git: allowlisted read-only subcommands, timeouts, hardened config/env |
| `repo.py` | Collects repository facts (refs, remotes, history) and branch analysis |
| `emails.py` | Offline classification of author emails (noreply, bot, unlinkable, regular) |
| `identity.py` | Groups commits into identities and decides which belong to the profile |
| `github.py` | Optional `gh api` integration; never handles tokens; sends only SHAs and names |
| `checks.py` | One function per rule, each returning a `Finding` |
| `catalog.py` | Stable rule IDs, titles, explanations, and documentation links |
| `engine.py` | Orchestration: collect, query GitHub, assign ownership, run checks |
| `render.py`, `cli.py` | Text/JSON output and the command-line interface |

## Ground rules for changes

1. **Read-only, always.** Never add a Git command that writes, fetches, or changes config.
   New Git subcommands must be added to `ALLOWED_SUBCOMMANDS` in `gitio.py` and justified in
   review.
2. **Don't state guesses as facts.** Set `verified=True` only when the conclusion comes from
   GitHub data or from deterministic local facts. If something cannot be known, report
   `UNKNOWN`.
3. **Privacy.** Never send local email addresses to GitHub. Show emails through
   `ScanContext.email()` so they are masked by default. Never print anything from
   `gh auth token` or credential helpers.
4. **Rule IDs are public API.** Don't rename or reuse an ID. Add new rules to `catalog.py`
   and `CHECKS`, with docs links.
5. **Tests use real Git.** Build scenarios with `RepoBuilder` in `tests/conftest.py`, and
   mock GitHub with `FakeGh` and the JSON files in `tests/fixtures/`. Tests must not touch
   the network or your global Git config. Use fictional identities only.

## Reporting a wrong diagnosis

A false positive or a missed cause is a bug. Please open an issue with the
`--format json` output. Emails are masked by default, so review the output before posting
and remove anything else you consider private.
