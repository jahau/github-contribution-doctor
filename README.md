# GitHub Contribution Doctor

A read-only CLI to diagnose why commits may not appear on your GitHub contribution graph.

## Quick start

```bash
python doctor.py --repo .
```

The tool checks Git author email, whether HEAD is on the default branch, and whether the repository is a fork (when GitHub CLI is authenticated). It cannot determine GitHub account email verification or private contribution visibility without account-level access; these are flagged as manual checks.

## Roadmap
- Support GitHub GraphQL contribution checks and authenticated email comparison
- Verify merged pull request contribution eligibility
- Machine-readable JSON output and CI test matrix

MIT License. Contributions welcome.
