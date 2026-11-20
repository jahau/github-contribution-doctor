## GitHub Contribution Doctor 0.0.0\-test (read-only)

| | |
| --- | --- |
| Repository | wïdgets \<b\>\|\</b\> on `github.com/alexdev/widgets` |
| Profile | `@alexdev` |
| Mode | offline, 3 commits scanned |
| Emails | masked |

**Summary:** FAIL 1 · WARN 1 · UNKNOWN 0 · PASS 0 · SKIPPED 0

### Potential contribution visibility issues

1. **FAIL** `BRANCH-NON-DEFAULT` (verified, high confidence): Branch \`feat/ü\|x\` and branch with odd \` backtick
2. **WARN** `COMMIT-IDENTITIES` (possible, low confidence): Jürgen Ölander 李雷 🧑‍💻 uses 2 emails \| see \!\[x\]\(https://evil.example/p.png\)

### Findings

| Status | Rule | Result | Basis |
| --- | --- | --- | --- |
| **WARN** | `COMMIT-IDENTITIES` | Jürgen Ölander 李雷 🧑‍💻 uses 2 emails \| see \!\[x\]\(https://evil.example/p.png\) | possible, low |
| **FAIL** | `BRANCH-NON-DEFAULT` | Branch \`feat/ü\|x\` and branch with odd \` backtick | verified, high |

### Details

<details><summary>WARN COMMIT-IDENTITIES: Commit-Identities title</summary>

Jürgen Ölander 李雷 🧑‍💻 uses 2 emails \| see \!\[x\]\(https://evil.example/p.png\)

**Evidence:**

- Zoë \<script\>alert\(1\)\</script\> \[click\]\(javascript:alert\(1\)\) \*bold\* \_it\_
- 1\. looks like a list second line�\[31m red evil
- mention \@octocat and \#42, math \$x\$, \~\~strike\~\~, \&amp; entity

**What to do:**

- Run `git config user.email "Zoë@例え.jp"` \| then `git log`

**Docs:** <https://docs.github.com/en/example>

</details>

<details><summary>FAIL BRANCH-NON-DEFAULT: Branch-Non-Default title</summary>

Branch \`feat/ü\|x\` and branch with odd \` backtick

**Docs:** <https://docs.github.com/en/example>

</details>

_'verified' = confirmed by GitHub data or by deterministic local facts; 'possible' = a likely explanation that could not be confirmed. Commit counts are local observations, not GitHub contribution counts. Nothing in the repository or Git configuration was changed._
