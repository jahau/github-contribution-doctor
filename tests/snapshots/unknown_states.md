## GitHub Contribution Doctor 0.0.0\-test (read-only)

| | |
| --- | --- |
| Repository | widgets on `github.com/alexdev/widgets` |
| Profile | `@alexdev` |
| Mode | offline, 3 commits scanned |
| Emails | masked |

**Summary:** FAIL 0 · WARN 0 · UNKNOWN 3 · PASS 1 · SKIPPED 1

### Potential contribution visibility issues

No contribution visibility problems were found in the checks that ran.

**Not verifiable here (UNKNOWN):** `REPO-FORK`, `REPO-VISIBILITY`, `ACCOUNT-PRIVATE-CONTRIB`

### Findings

| Status | Rule | Result | Basis |
| --- | --- | --- | --- |
| **SKIPPED** | `GH-AUTH` | Offline mode: GitHub was not contacted. | possible, high |
| **UNKNOWN** | `REPO-FORK` | Fork status can only be confirmed by GitHub. | possible, low |
| **UNKNOWN** | `REPO-VISIBILITY` | Visibility can only be read from GitHub. | possible, low |
| **UNKNOWN** | `ACCOUNT-PRIVATE-CONTRIB` | Whether private contributions are shown cannot be read through any API. | possible, low |
| **PASS** | `REPO-STATE` | On branch 'main'. | verified, high |

### Details

<details><summary>UNKNOWN REPO-FORK: Repo-Fork title</summary>

Fork status can only be confirmed by GitHub.

**Evidence:**

- GitHub data unavailable: \-\-offline was given

**What to do:**

- Run the scan online with an authenticated `gh` to verify.

**Docs:** <https://docs.github.com/en/example>

</details>

<details><summary>UNKNOWN REPO-VISIBILITY: Repo-Visibility title</summary>

Visibility can only be read from GitHub.

**Docs:** <https://docs.github.com/en/example>

</details>

<details><summary>UNKNOWN ACCOUNT-PRIVATE-CONTRIB: Account-Private-Contrib title</summary>

Whether private contributions are shown cannot be read through any API.

**Docs:** <https://docs.github.com/en/example>

</details>

_'verified' = confirmed by GitHub data or by deterministic local facts; 'possible' = a likely explanation that could not be confirmed. Commit counts are local observations, not GitHub contribution counts. Nothing in the repository or Git configuration was changed._
