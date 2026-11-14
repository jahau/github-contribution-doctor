# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/).

## [0.2.0] - unreleased

A rewrite of the prototype into an installable, tested diagnostic tool.

### Added

- `contribution-doctor` command, installable with pip/pipx, with `scan` and `rules`
  subcommands.
- `scan` options: `--user`, `--format text|json`, `--offline`, `--history N`, `--explain`,
  `--email`, `--show-emails`, `--strict`, `--color`, `--timeout`.
- 19 diagnostic rules with stable IDs. Each finding has a status
  (PASS/WARN/FAIL/UNKNOWN/SKIPPED), a confidence level, a *verified* vs *possible* label,
  evidence, remediation, and GitHub documentation links.
- History-wide author identity analysis (not only the latest commit), including committers
  and `Co-authored-by` trailers.
- Detection of unlinkable author emails (hostname fallbacks like `user@DESKTOP-ABC`,
  `.local`, `(none)`).
- Default-branch resolution from GitHub, then `refs/remotes/<remote>/HEAD`, then a labelled
  guess. Detects a stale local pointer.
- Commits only on non-default branches (`gh-pages` excluded), with online confirmation of
  whether branch tips are already merged on GitHub.
- Unpushed commit detection.
- Support for repositories with no commits, detached HEAD, shallow clones, missing or
  non-GitHub remotes, and bare repositories.
- Optional GitHub CLI integration: fork/parent, visibility, default branch, ownership and
  permission, commit attribution by SHA, and your own account's email list (with the `user`
  scope).
- Structured JSON output (`schema_version: 1`) with a summary of verified and possible
  issues.
- Exit codes: 0 (no failures), 1 (failures, or warnings with `--strict`), 2 (usage),
  3 (environment).
- Test suite with real Git repository fixtures, plus CI on Linux/Windows/macOS for Python
  3.10–3.14, Ruff, and mypy (strict).

### Changed

- The prototype script became the `contribution_doctor` package. `python doctor.py --repo .`
  still works as a compatibility shim.

### Security

- Git runs with an allowlist of read-only subcommands, timeouts, no pager or prompts, and
  signature verification and fsmonitor disabled. Repository-redirecting environment
  variables are ignored.
- Tokens are never read. Credentials in remote URLs and token-like strings are scrubbed
  from all output.
- Local commit email addresses are never sent to GitHub. Emails are masked in output by
  default.

## [0.1.0]

- Initial prototype: latest-commit author email, current branch, and `gh repo view` fork
  check.

[0.2.0]: https://github.com/jahau/github-contribution-doctor/compare/afca7c7...v0.2.0
