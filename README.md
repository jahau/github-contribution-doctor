# GitHub Contribution Doctor

**Find out why your commits are not showing up on your GitHub contribution graph, without
changing anything in your repository.**

You pushed work, but the green squares never appeared. The usual causes are invisible from
the command line: commits made with an email address that isn't linked to your account, work
that only lives on a feature branch, a fork, a private repository, unpushed commits, or simply
GitHub's processing delay. `contribution-doctor` inspects your repository (and, if you allow
it, GitHub's metadata) and explains which of these apply. Each finding comes with evidence
and a fix.

- **Read-only.** It never commits, rewrites, pushes, fetches, or changes Git configuration.
- **Honest.** Every finding is labelled *verified* (confirmed by GitHub data or deterministic
  local facts) or *possible* (a likely explanation that could not be confirmed). Things it
  cannot know are reported as `UNKNOWN`, not guessed.
- **Privacy-friendly.** Email addresses are masked in output by default. Local commit emails
  are never sent to GitHub. Tokens are never read or printed.
- **No dependencies.** Pure Python 3.10+, plus `git`. The GitHub CLI (`gh`) is optional.

## Quick start

```bash
pipx install git+https://github.com/jahau/github-contribution-doctor
cd path/to/your/repo
contribution-doctor scan .
```

Or run it from a source checkout without installing:

```bash
python doctor.py --repo path/to/your/repo
```

For verified, GitHub-backed checks, log in to the GitHub CLI once with `gh auth login`.
Without it, all local checks still run.

## Usage

```bash
contribution-doctor scan .                  # diagnose the repo for the gh-authenticated account
contribution-doctor scan . --user octocat   # diagnose for a specific GitHub profile
contribution-doctor scan . --format json    # machine-readable output
contribution-doctor scan . --offline        # never contact GitHub
contribution-doctor scan . --history 100    # scan at most 100 commits (default 500)
contribution-doctor scan . --explain        # background + documentation for every finding
contribution-doctor rules                   # list all rule IDs
```

| Option | Purpose |
| --- | --- |
| `--user LOGIN` | Profile to diagnose. Defaults to the account `gh` is logged in as. |
| `--email ADDRESS` | Treat this author email as yours (repeatable). Used locally only; it is never sent anywhere. |
| `--show-emails` | Print full email addresses instead of masked ones (e.g. `a***@c***.fi #bb70`). |
| `--strict` | Exit with `1` on warnings too, not only failures. |
| `--color auto\|always\|never` | Terminal colors. Honours `NO_COLOR`. |
| `--timeout SECONDS` | Timeout for each `git`/`gh` call (default 30). |

### Exit codes

| Code | Meaning |
| --- | --- |
| `0` | Scan completed and no `FAIL` findings (with `--strict`: no `WARN` findings either). |
| `1` | Scan completed and at least one `FAIL` finding (or `WARN` with `--strict`). |
| `2` | Invalid command-line usage. |
| `3` | Environment error: Git missing, path is not a repository, Git failed or timed out. |

## Sample output

This is a repository where the developer committed from a laptop without configuring Git,
used a work email for some commits, and has a feature branch and two unpushed commits.
Excerpt from `contribution-doctor scan . --offline --user alexdev`:

```text
GitHub Contribution Doctor 0.2.0  (read-only)
Repository: widgets  ->  github.com/alexdev/widgets
Profile:    @alexdev
Mode:       offline  |  commits scanned: 7

[PASS]     REMOTE-GITHUB  GitHub remote
           Primary remote 'origin' is github.com/alexdev/widgets.
[WARN]     BRANCH-UNPUSHED  Unpushed commits
           2 local commits (2 by you) are not on any remote-tracking branch, so GitHub most
           likely has not received them.
           (possible, high confidence)
           Evidence:
             - ae192b7  2026-11-02  a***@des*** #bd65
             - a0d8a7f  2026-11-01  a***@des*** #bd65
           What to do:
             - Push the branch: `git push -u origin <branch>`.
             - If you pushed from another machine, run `git fetch` and re-check.

[FAIL]     COMMIT-EMAIL-UNLINKABLE  Author emails that cannot belong to any account
           2 commits that appear to be yours use an author email that GitHub can never link
           to an account, so they cannot count.
           (verified, high confidence)
           Evidence:
             - a***@des*** #bd65 (Alex Morgan): 2 commits, last 2026-11-02 - domain has no
               dot; looks like a machine hostname guessed by Git
           What to do:
             - Configure a real address for future commits: `git config --global
               user.email <email-on-your-GitHub-account>`.
             - Existing commits keep their author email. Re-attributing them requires
               rewriting history (e.g. git filter-repo), which changes commit SHAs and
               disrupts anyone else using the branch. This tool never does that for you.
           Docs: https://docs.github.com/en/.../setting-your-commit-email-address

[WARN]     COMMIT-IDENTITIES  Commit author identities
           Your commits use 3 different author emails in 7 scanned commits. Each one must be
           added to and verified on the same account.
           (possible, medium confidence)
           Evidence:
             - a***@c***.fi #bb70 (Alex Morgan): 3 commits, 2026-09-10..2026-10-01 [probably
               yours - author name matches configured user.name]
             - a***@des*** #bd65 (Alex Morgan): 2 commits, 2026-11-01..2026-11-02 [probably
               yours - matches configured user.email; author name matches configured
               user.name]
             - a***@a***.dev #9ae1 (Alice Smith): 1 commit, 2026-09-02 [unknown owner]
             - a***@a***.dev #eec1 (Alex Morgan): 1 commit, 2026-09-01 [probably yours -
               author name matches configured user.name]
...

Summary
  PASS 7  WARN 3  FAIL 2  UNKNOWN 5  SKIPPED 2

  Potential contribution visibility issues (most important first):
   1. CONFIG-EMAIL [FAIL, verified]: user.email a***@des*** #bd65 can never be verified on
      GitHub: domain has no dot; looks like a machine hostname guessed by Git.
   2. COMMIT-EMAIL-UNLINKABLE [FAIL, verified]: 2 commits that appear to be yours use an
      author email that GitHub can never link to an account, so they cannot count.
   3. BRANCH-UNPUSHED [WARN, possible]: 2 local commits (2 by you) are not on any
      remote-tracking branch, so GitHub most likely has not received them.
   4. BRANCH-NON-DEFAULT [WARN, possible]: 1 commit authored by you (in the scanned history)
      is not on 'main' in this clone. They count only after they reach the default branch.
   5. COMMIT-IDENTITIES [WARN, possible]: Your commits use 3 different author emails in 7
      scanned commits. Each one must be added to and verified on the same account.
  Not verifiable here (UNKNOWN): ACCOUNT-TARGET, REPO-FORK, REPO-VISIBILITY,
    COMMIT-ATTRIBUTION, ACCOUNT-PRIVATE-CONTRIB
```

Online (`gh auth login`), the `UNKNOWN` rows turn into verified answers. For example,
`COMMIT-ATTRIBUTION` reports which account GitHub actually credits for each of your email
addresses.

With `--format json`, every finding has the same fields:

```json
{
  "id": "COMMIT-EMAIL-UNLINKABLE",
  "title": "Author emails that cannot belong to any account",
  "category": "identity",
  "status": "FAIL",
  "confidence": "high",
  "verified": true,
  "description": "2 commits that appear to be yours use an author email that GitHub can never link to an account, so they cannot count.",
  "evidence": ["a***@des*** #bd65 (Alex Morgan): 2 commits, last 2026-11-02 - domain has no dot; looks like a machine hostname guessed by Git"],
  "remediation": ["Configure a real address for future commits: ...", "..."],
  "docs": ["https://docs.github.com/en/.../setting-your-commit-email-address", "..."],
  "explanation": "Addresses without a real mail domain ... cannot be verified on GitHub ..."
}
```

The JSON also includes `summary.verified_issues`, `summary.possible_issues`, and
`summary.counts`, and a `schema_version` so scripts can rely on the format.

## What is checked

Statuses: `PASS`, `WARN`, `FAIL`, `UNKNOWN` (cannot be determined here), `SKIPPED` (not
applicable or not requested).

| Rule ID | What it looks at | Offline | Needs GitHub |
| --- | --- | :-: | :-: |
| `GH-AUTH` | Whether `gh` is installed and logged in (the token is never read) | | ✔ |
| `ACCOUNT-TARGET` | Whether the selected profile exists | partial | ✔ |
| `REPO-STATE` | No commits yet, detached HEAD | ✔ | |
| `REPO-SHALLOW` | Shallow clone (incomplete local history) | ✔ | |
| `REMOTE-GITHUB` | Missing remotes, non-github.com remotes (GitLab, GHES) | ✔ | |
| `REPO-DEFAULT-BRANCH` | Default branch from GitHub, else `refs/remotes/<r>/HEAD`, else a labelled guess; flags a stale local pointer | partial | for certainty |
| `BRANCH-NON-DEFAULT` | Your commits that exist only on non-default branches (`gh-pages` excluded); online it asks GitHub whether the branch tip is already merged | ✔ | to confirm |
| `BRANCH-UNPUSHED` | Local commits not on any remote-tracking branch | ✔ | |
| `REPO-FORK` | Fork status and parent repository | hint only | ✔ |
| `REPO-OWNERSHIP` | Owner vs. profile; collaborator access and stars where visible | partial | ✔ |
| `REPO-VISIBILITY` | Public / private / internal | | ✔ |
| `CONFIG-EMAIL` | `git config user.email`: missing, unlinkable, wrong noreply, linked or not | partial | to confirm |
| `COMMIT-IDENTITIES` | All author emails in the scanned history, and which look like yours | ✔ | to confirm |
| `COMMIT-EMAIL-UNLINKABLE` | Addresses GitHub can never verify (`user@DESKTOP-ABC`, `.local`, `(none)`) | ✔ | |
| `COMMIT-ATTRIBUTION` | Which account GitHub credits each identity to (looked up by commit SHA) | | ✔ |
| `ACCOUNT-EMAILS` | Your own account's email list vs. your commit emails (needs the `user` scope) | | ✔ |
| `COMMIT-AUTHORSHIP` | Commits you committed but others authored; `Co-authored-by` trailers | ✔ | |
| `COMMIT-TIMING` | The 24-hour processing delay; future-dated commits | ✔ | |
| `ACCOUNT-PRIVATE-CONTRIB` | The "Private contributions" profile setting, always `UNKNOWN` because no API exposes it | | |

## How identities are matched

The tool never assumes that every commit is yours, or that the authenticated account
authored everything. Each author email is labelled:

- **yours**: GitHub attributes its commits to the profile, it is the profile's noreply
  address, it is a verified email on your own authenticated account, or you passed it with
  `--email`.
- **probably yours**: it matches your configured `user.email` or `user.name`. This is a
  guess, and it is labelled as one.
- **other account**: GitHub attributes it to someone else, or it is another account's
  noreply address or a bot.
- **unknown owner**: no signal either way, typically other contributors.

Only identities that are yours or probably yours can produce failures.

## Privacy and safety

- **No writes.** Only an allowlist of read-only Git subcommands can run (`rev-parse`, `log`,
  `rev-list`, `for-each-ref`, `symbolic-ref`, `remote get-url`, `config --get`). The test
  suite hashes `.git` before and after a scan to prove nothing changes.
- **No repository-controlled code execution.** Git runs with pagers, terminal prompts,
  signature verification (`gpg.program`), and fsmonitor hooks disabled. `GIT_DIR`-style
  overrides are removed. Every call has a timeout.
- **No network from Git.** The tool never fetches. Remote-tracking refs are used as they
  are, which is why branch findings say "as of the last fetch".
- **What GitHub sees.** Only repository names, your login, and commit SHAs. Local commit
  email addresses are never sent. If you scan your own account and your token has the
  `user` scope, your account's email list is downloaded and compared locally.
- **Other people's data.** With `--user someone-else`, their private emails and settings
  are not accessible and are not assumed.
- **Secrets.** Tokens are never requested from `gh`. Credentials embedded in remote URLs
  (`https://TOKEN@github.com/...`) are removed, and token-like strings are scrubbed from all
  output.
- **Shareable reports.** Emails are masked by default (`a***@c***.fi #bb70`). The short
  hash keeps different addresses distinguishable. Noreply addresses are public by design and
  are shown as-is. Absolute paths are not included in reports.

## Limitations and false positives

- **Local view only for branches.** "Not on the default branch" and "unpushed" reflect your
  clone as of the last `git fetch`. Squash and rebase merges create new commits, so feature
  branch commits may never be "merged" even though the work was counted. Online, the tool
  asks GitHub about branch tips to reduce this.
- **Identity matching is heuristic offline.** A colleague with the same name as your
  `user.name` will be labelled *probably yours*. Use `--email`, or go online, for certainty.
- **Attribution samples one commit per identity** (up to 25 identities), and only for
  commits that GitHub has. `.mailmap` does not affect GitHub attribution, so it is ignored
  on purpose.
- **Not checked:** whether you opened an issue or PR in the repository (one of GitHub's
  qualifying conditions), organization membership, repository transfers, and contributions
  that were removed because you lost access to a private repository.
- **Counts are not GitHub's counts.** All numbers describe the scanned local history window
  (`--history`), not your contribution graph.
- **github.com only.** GitHub Enterprise Server remotes are reported as non-github.com
  remotes.
- **Private contributions setting.** It is always `UNKNOWN`, because no API exposes it.

## Development

See [CONTRIBUTING.md](CONTRIBUTING.md). Release history is in [CHANGELOG.md](CHANGELOG.md).

MIT License.
