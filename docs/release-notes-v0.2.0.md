# GitHub Contribution Doctor v0.2.0

v0.2.0 turns the one-file prototype into a tool you can install. It explains why commits
are missing from a GitHub contribution graph and never touches your repository.

```bash
pipx install git+https://github.com/jahau/github-contribution-doctor@v0.2.0
contribution-doctor scan .
```

## Highlights

- **19 diagnostics** covering the real reasons contributions go missing:
  - unlinked or unlinkable author emails
  - several identities across the history
  - work stuck on feature branches or never pushed
  - forks
  - private repositories
  - repository ownership
  - author vs. committer vs. co-author
  - the 24-hour processing delay
- **Verified vs. possible.** Each finding says whether it was confirmed (by GitHub or by
  deterministic local facts) or is a likely explanation. Things nobody can check, such as
  your "Private contributions" setting, are reported as `UNKNOWN`.
- **GitHub-backed answers when you want them.** With `gh auth login`, the tool asks GitHub
  which account each of your email identities is credited to, whether the repository is a
  fork or private, its real default branch, and whether your feature branch is already
  merged. It looks things up by commit SHA only, so your local email addresses are never
  sent.
- **Works offline.** `--offline` runs all local checks without any network access.
- **Shareable output.** Text for humans and JSON for scripts. Emails are masked by default.
  Tokens and URL credentials are scrubbed.
- **Read-only by construction.** An allowlist of read-only Git subcommands, hardened Git
  invocation, and a test that hashes `.git` before and after a scan.

## Upgrading from 0.1

`python doctor.py --repo .` still works. The new entry point is
`contribution-doctor scan .`. Exit codes are now meaningful: `1` means at least one `FAIL`
finding, so use `--strict` if warnings should also fail a CI job.

## Known limitations

- Branch findings reflect your clone as of the last `git fetch`. Squash-merged branches are
  explained but can still be reported as "not on the default branch" when offline.
- Offline identity matching is heuristic (based on `user.email` and `user.name`). Use
  `--email`, or go online, for certainty.
- Not checked: whether you opened an issue or PR in a repository you don't own, and
  organization membership. Only github.com is supported, not GitHub Enterprise Server.

See the [CHANGELOG](../CHANGELOG.md) for the full list of changes.
