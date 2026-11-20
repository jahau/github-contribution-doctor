# GitHub Contribution Doctor v0.3.0

v0.3.0 adds Markdown output, so you can show the diagnosis in a GitHub Actions job summary
or paste it into an issue without leaking anything.

```bash
pipx install git+https://github.com/jahau/github-contribution-doctor@v0.3.0
contribution-doctor scan . --offline --format markdown >> "$GITHUB_STEP_SUMMARY"
```

## Highlights

- **`--format markdown`.** It has the same findings, statuses, *verified*/*possible* labels,
  and confidence levels as the text and JSON formats. It shows a summary table, a ranked
  list of issues, and a findings table. `FAIL`, `WARN`, and `UNKNOWN` findings get
  collapsible details with evidence and remediation.
- **Safe to publish.**
  - Emails are masked by default. The output says so when `--show-emails` is used.
  - Token-like strings and URL credentials are scrubbed. This happens before escaping, so
    escaping cannot hide a token from the scrubber.
  - Every value taken from the repository is escaped, so it cannot inject links, images,
    HTML, mentions, or table cells. Control and bidirectional override characters are
    removed. Unicode names are kept.
- **Deterministic.** There is no timestamp. The output is always UTF-8 with LF line
  endings, so the same repository state gives identical bytes on Linux, macOS, and Windows.
- **CI example.** The README has a workflow that runs the scan without changing anything:
  it has a read-only token, does not persist credentials, runs offline (no token needed),
  and only writes to the job summary.

## Compatibility

Text output, JSON output (`schema_version: 1`), and exit codes are unchanged. Exit codes
are the same for every format, so `--format markdown` fails a job exactly when the text
format would.

## Known limitations

- Escaping `@` keeps Markdown from treating it as markup, but GitHub may still turn a
  mention-shaped string into a link in some views. Job summaries do not send notifications.
- The raw Markdown is heavily escaped, for example `\-\-offline`. It is meant to be read
  rendered.
- The limitations listed in v0.2.0 still apply.

See the [CHANGELOG](../CHANGELOG.md) for the full list of changes.
