## GitHub Contribution Doctor 0.0.0\-test (read-only)

| | |
| --- | --- |
| Repository | widgets on `github.com/alexdev/widgets` |
| Profile | `@alexdev` |
| Mode | offline, 2 commits scanned |
| Emails | masked |

**Summary:** FAIL 2 · WARN 1 · UNKNOWN 5 · PASS 9 · SKIPPED 2

### Potential contribution visibility issues

1. **FAIL** `CONFIG-EMAIL` (verified, high confidence): user.email a\*\*\*\@des\*\*\* \#1b26 can never be verified on GitHub: domain has no dot; looks like a machine hostname guessed by Git.
2. **FAIL** `COMMIT-EMAIL-UNLINKABLE` (verified, high confidence): 1 commit that appear to be yours use an author email that GitHub can never link to an account, so they cannot count.
3. **WARN** `COMMIT-IDENTITIES` (possible, medium confidence): Your commits use 2 different author emails in 2 scanned commits. Each one must be added to and verified on the same account.

**Not verifiable here (UNKNOWN):** `ACCOUNT-TARGET`, `REPO-FORK`, `REPO-VISIBILITY`, `COMMIT-ATTRIBUTION`, `ACCOUNT-PRIVATE-CONTRIB`

### Findings

| Status | Rule | Result | Basis |
| --- | --- | --- | --- |
| **SKIPPED** | `GH-AUTH` | Offline mode: GitHub was not contacted. | possible, high |
| **UNKNOWN** | `ACCOUNT-TARGET` | Inspecting \@alexdev \(not verified: \-\-offline was given\). | possible, low |
| **PASS** | `REPO-STATE` | On branch 'main'. | verified, high |
| **PASS** | `REPO-SHALLOW` | Full \(non\-shallow\) clone. | verified, high |
| **PASS** | `REMOTE-GITHUB` | Primary remote 'origin' is github.com/alexdev/widgets. | verified, high |
| **PASS** | `REPO-DEFAULT-BRANCH` | Default branch is 'main'. | possible, medium |
| **PASS** | `BRANCH-NON-DEFAULT` | Every scanned branch is contained in 'main' \(in this clone\). | possible, medium |
| **PASS** | `BRANCH-UNPUSHED` | Every local commit is on a remote\-tracking branch \(as of the last fetch/push\). | possible, medium |
| **UNKNOWN** | `REPO-FORK` | Fork status can only be confirmed by GitHub. | possible, low |
| **PASS** | `REPO-OWNERSHIP` | \@alexdev owns alexdev/widgets. | possible, medium |
| **UNKNOWN** | `REPO-VISIBILITY` | Visibility can only be read from GitHub. | possible, low |
| **FAIL** | `CONFIG-EMAIL` | user.email a\*\*\*\@des\*\*\* \#1b26 can never be verified on GitHub: domain has no dot; looks like a machine hostname guessed by Git. | verified, high |
| **WARN** | `COMMIT-IDENTITIES` | Your commits use 2 different author emails in 2 scanned commits. Each one must be added to and verified on the same account. | possible, medium |
| **FAIL** | `COMMIT-EMAIL-UNLINKABLE` | 1 commit that appear to be yours use an author email that GitHub can never link to an account, so they cannot count. | verified, high |
| **UNKNOWN** | `COMMIT-ATTRIBUTION` | Could not ask GitHub which account your commits are attributed to. | possible, low |
| **SKIPPED** | `ACCOUNT-EMAILS` | Requires GitHub \(\-\-offline was given\). | possible, high |
| **PASS** | `COMMIT-AUTHORSHIP` | No commits committed by you on behalf of other authors. | verified, medium |
| **PASS** | `COMMIT-TIMING` | No timing issues: no future\-dated or very recent commits. | verified, medium |
| **UNKNOWN** | `ACCOUNT-PRIVATE-CONTRIB` | Whether private contributions are shown on the profile cannot be read through any API, so it is not assumed either way. | possible, low |

### Details

<details><summary>UNKNOWN ACCOUNT-TARGET: Inspected GitHub profile</summary>

Inspecting \@alexdev \(not verified: \-\-offline was given\).

**Docs:** <https://docs.github.com/en/account-and-profile/setting-up-and-managing-your-github-profile/managing-contribution-settings-on-your-profile/viewing-contributions-on-your-profile>

</details>

<details><summary>UNKNOWN REPO-FORK: Fork status</summary>

Fork status can only be confirmed by GitHub.

**Evidence:**

- GitHub data unavailable: \-\-offline was given

**What to do:**

- Run the scan online with an authenticated gh to verify.

**Docs:** <https://docs.github.com/en/account-and-profile/setting-up-and-managing-your-github-profile/managing-contribution-settings-on-your-profile/why-are-my-contributions-not-showing-up-on-my-profile>

</details>

<details><summary>UNKNOWN REPO-VISIBILITY: Repository visibility</summary>

Visibility can only be read from GitHub.

**Evidence:**

- \-\-offline was given

**Docs:** <https://docs.github.com/en/account-and-profile/setting-up-and-managing-your-github-profile/managing-contribution-settings-on-your-profile/showing-your-private-contributions-and-achievements-on-your-profile>

</details>

<details><summary>FAIL CONFIG-EMAIL: Configured commit email</summary>

user.email a\*\*\*\@des\*\*\* \#1b26 can never be verified on GitHub: domain has no dot; looks like a machine hostname guessed by Git.

**Evidence:**

- user.email = a\*\*\*\@des\*\*\* \#1b26 \(used by 1 scanned commit\)

**What to do:**

- Set it yourself: `git config --global user.email <email-on-your-GitHub-account>` \(your \<id\>\+\<login\>\@users.noreply.github.com address works and keeps your email private\).

**Docs:** <https://docs.github.com/en/account-and-profile/setting-up-and-managing-your-personal-account-on-github/managing-email-preferences/setting-your-commit-email-address>

</details>

<details><summary>WARN COMMIT-IDENTITIES: Commit author identities</summary>

Your commits use 2 different author emails in 2 scanned commits. Each one must be added to and verified on the same account.

**Evidence:**

- a\*\*\*\@c\*\*\*.fi \#bb70 \(Alex Morgan\): 1 commit, 2026\-05\-02 \[probably yours \- author name matches configured user.name\]
- a\*\*\*\@des\*\*\* \#1b26 \(Alex \[REDACTED\]\): 1 commit, 2026\-05\-02 \[probably yours \- matches configured user.email\]

**What to do:**

- Add every address you commit with under GitHub Settings \-\> Emails; existing commits are credited retroactively.
- Use one address going forward \(`git config --global user.email ...`\).

**Docs:** <https://docs.github.com/en/account-and-profile/setting-up-and-managing-your-github-profile/managing-contribution-settings-on-your-profile/why-are-my-contributions-not-showing-up-on-my-profile>

</details>

<details><summary>FAIL COMMIT-EMAIL-UNLINKABLE: Author emails that cannot belong to any account</summary>

1 commit that appear to be yours use an author email that GitHub can never link to an account, so they cannot count.

**Evidence:**

- a\*\*\*\@des\*\*\* \#1b26 \(Alex \[REDACTED\]\): 1 commit, last 2026\-05\-02 \- domain has no dot; looks like a machine hostname guessed by Git

**What to do:**

- Configure a real address for future commits: `git config --global user.email <email-on-your-GitHub-account>`.
- Existing commits keep their author email. Re\-attributing them requires rewriting history \(e.g. git filter\-repo\), which changes commit SHAs and disrupts anyone else using the branch. This tool never does that for you.

**Docs:** <https://docs.github.com/en/account-and-profile/setting-up-and-managing-your-personal-account-on-github/managing-email-preferences/setting-your-commit-email-address>

</details>

<details><summary>UNKNOWN COMMIT-ATTRIBUTION: GitHub commit attribution</summary>

Could not ask GitHub which account your commits are attributed to.

**Evidence:**

- GitHub attribution not checked: \-\-offline was given
- a\*\*\*\@c\*\*\*.fi \#bb70 \(Alex Morgan\): cannot be verified offline

**What to do:**

- Run online with `gh auth login` to verify attribution.

**Docs:** <https://docs.github.com/en/account-and-profile/setting-up-and-managing-your-github-profile/managing-contribution-settings-on-your-profile/why-are-my-contributions-not-showing-up-on-my-profile>

</details>

<details><summary>UNKNOWN ACCOUNT-PRIVATE-CONTRIB: Private contributions setting</summary>

Whether private contributions are shown on the profile cannot be read through any API, so it is not assumed either way.

**What to do:**

- Open your profile, click 'Contribution settings' above the graph and check 'Private contributions'.

**Docs:** <https://docs.github.com/en/account-and-profile/setting-up-and-managing-your-github-profile/managing-contribution-settings-on-your-profile/showing-your-private-contributions-and-achievements-on-your-profile>

</details>

_'verified' = confirmed by GitHub data or by deterministic local facts; 'possible' = a likely explanation that could not be confirmed. Commit counts are local observations, not GitHub contribution counts. Nothing in the repository or Git configuration was changed._
