"""Stable rule catalogue.

Rule IDs are part of the public interface (JSON output, CI filters, docs). Never rename
or reuse an ID; retire it instead.
"""

from __future__ import annotations

from dataclasses import dataclass

_DOCS = "https://docs.github.com/en"
_CONTRIB = (
    f"{_DOCS}/account-and-profile/setting-up-and-managing-your-github-profile/"
    "managing-contribution-settings-on-your-profile"
)
_EMAIL = (
    f"{_DOCS}/account-and-profile/setting-up-and-managing-your-personal-account-on-github/"
    "managing-email-preferences"
)

DOC_WHY_MISSING = f"{_CONTRIB}/why-are-my-contributions-not-showing-up-on-my-profile"
DOC_PRIVATE_CONTRIB = (
    f"{_CONTRIB}/showing-your-private-contributions-and-achievements-on-your-profile"
)
DOC_VIEWING = f"{_CONTRIB}/viewing-contributions-on-your-profile"
DOC_COMMIT_EMAIL = f"{_EMAIL}/setting-your-commit-email-address"
DOC_ADD_EMAIL = f"{_EMAIL}/adding-an-email-address-to-your-github-account"
DOC_VERIFY_EMAIL = f"{_EMAIL}/verifying-your-email-address"
DOC_CO_AUTHORS = (
    f"{_DOCS}/pull-requests/committing-changes-to-your-project/creating-and-editing-commits/"
    "creating-a-commit-with-multiple-authors"
)
DOC_DEFAULT_BRANCH = (
    f"{_DOCS}/repositories/configuring-branches-and-merges-in-your-repository/"
    "managing-branches-in-your-repository/changing-the-default-branch"
)
DOC_FORKS = f"{_DOCS}/pull-requests/collaborating-with-pull-requests/working-with-forks/about-forks"
DOC_DETACH_FORK = (
    f"{_DOCS}/pull-requests/collaborating-with-pull-requests/working-with-forks/detaching-a-fork"
)
DOC_GH_AUTH = "https://cli.github.com/manual/gh_auth_login"
DOC_RATE_LIMITS = f"{_DOCS}/rest/using-the-rest-api/rate-limits-for-the-rest-api"
DOC_GIT_UNSHALLOW = "https://git-scm.com/docs/git-fetch#Documentation/git-fetch.txt---unshallow"
DOC_GIT_PUSH = "https://git-scm.com/docs/git-push"


@dataclass(frozen=True)
class Rule:
    id: str
    title: str
    category: str
    explanation: str
    docs: tuple[str, ...]
    needs_github: bool = False


_RULES: tuple[Rule, ...] = (
    Rule(
        "REPO-STATE",
        "Repository state",
        "repository",
        "Contributions are computed from commits that exist on GitHub. A repository with no "
        "commits has nothing to count, and a detached HEAD means new commits are not on any "
        "branch until you create or update one.",
        (DOC_WHY_MISSING,),
    ),
    Rule(
        "REPO-SHALLOW",
        "Shallow clone",
        "repository",
        "A shallow clone contains only part of the history, so local analysis of authors and "
        "branches is incomplete. GitHub still has the full history; this only limits what "
        "this tool can see.",
        (DOC_GIT_UNSHALLOW,),
    ),
    Rule(
        "REMOTE-GITHUB",
        "GitHub remote",
        "repository",
        "Only commits pushed to a repository on github.com can appear on a github.com "
        "profile. Commits that live only on your machine, or on another host such as "
        "GitLab or a GitHub Enterprise Server instance, are not counted on github.com.",
        (DOC_WHY_MISSING,),
    ),
    Rule(
        "REPO-DEFAULT-BRANCH",
        "Default branch",
        "branches",
        "GitHub counts commits on the repository's default branch or on the gh-pages "
        "branch. The default branch is a GitHub repository setting; the local "
        "refs/remotes/<remote>/HEAD pointer is only a cached copy that can be stale.",
        (DOC_WHY_MISSING, DOC_DEFAULT_BRANCH),
    ),
    Rule(
        "BRANCH-NON-DEFAULT",
        "Commits outside the default branch",
        "branches",
        "Commits that are only on feature branches are not counted until they reach the "
        "default branch. Squash and rebase merges create new commits on the default branch, "
        "so the original feature-branch commits may never be merged even though the work "
        "was counted. A local clone can also be out of date, so 'not on the local default "
        "branch' is not proof that a contribution is missing on GitHub.",
        (DOC_WHY_MISSING,),
    ),
    Rule(
        "BRANCH-UNPUSHED",
        "Unpushed commits",
        "branches",
        "Commits that are not reachable from any remote-tracking branch have most likely "
        "not been pushed. GitHub cannot count commits it has never received. Remote-tracking "
        "refs are only updated by fetch/pull/push, so run `git fetch` first if unsure.",
        (DOC_WHY_MISSING, DOC_GIT_PUSH),
    ),
    Rule(
        "REPO-FORK",
        "Fork status",
        "repository",
        "Commits made in a fork are not counted on your profile. They count once they are "
        "merged into the parent repository through a pull request (then the commits in the "
        "parent count), or if the fork is detached and becomes a standalone repository.",
        (DOC_WHY_MISSING, DOC_FORKS, DOC_DETACH_FORK),
        needs_github=True,
    ),
    Rule(
        "REPO-OWNERSHIP",
        "Repository ownership and relationship",
        "repository",
        "For commits in repositories you do not own, GitHub additionally requires at least "
        "one of: you are a collaborator or a member of the owning organization, you forked "
        "the repository, you opened an issue or pull request in it, or you starred it.",
        (DOC_WHY_MISSING,),
    ),
    Rule(
        "REPO-VISIBILITY",
        "Repository visibility",
        "repository",
        "Contributions to private repositories appear to other people only as anonymized "
        "counts, and only if the profile owner has enabled the 'Private contributions' "
        "setting. Losing access to a private repository can also remove its contributions.",
        (DOC_PRIVATE_CONTRIB, DOC_VIEWING),
        needs_github=True,
    ),
    Rule(
        "CONFIG-EMAIL",
        "Configured commit email",
        "identity",
        "Git stamps new commits with user.email. GitHub attributes a commit to an account "
        "only when the commit's author email is added to and verified on that account (or "
        "is the account's noreply address). This tool reads the setting; it never changes "
        "it.",
        (DOC_COMMIT_EMAIL, DOC_ADD_EMAIL),
    ),
    Rule(
        "COMMIT-IDENTITIES",
        "Commit author identities",
        "identity",
        "Each distinct author email in the history is a separate identity on GitHub. Using "
        "several emails is fine as long as every one is linked to the same account. Adding "
        "an email to your account later also attributes the existing commits that use it, "
        "so no history rewrite is needed.",
        (DOC_WHY_MISSING, DOC_ADD_EMAIL),
    ),
    Rule(
        "COMMIT-EMAIL-UNLINKABLE",
        "Author emails that cannot belong to any account",
        "identity",
        "Addresses without a real mail domain (for example user@DESKTOP-ABC, "
        "user@host.local or '(none)') cannot be verified on GitHub, so commits that use "
        "them are never attributed to any account. This usually happens when Git was not "
        "configured and guessed an address from the machine name.",
        (DOC_COMMIT_EMAIL, DOC_WHY_MISSING),
    ),
    Rule(
        "COMMIT-ATTRIBUTION",
        "GitHub commit attribution",
        "identity",
        "GitHub links each commit to an account by its author email. For commits already "
        "pushed to GitHub, the tool asks GitHub which account (if any) a sample commit per "
        "identity is attributed to. Only commit SHAs are sent; local email addresses are "
        "never sent to GitHub.",
        (DOC_WHY_MISSING, DOC_ADD_EMAIL, DOC_VERIFY_EMAIL),
        needs_github=True,
    ),
    Rule(
        "ACCOUNT-EMAILS",
        "Emails on your GitHub account",
        "account",
        "When you scan your own authenticated account and your token has the 'user' or "
        "'user:email' scope, the tool downloads your account's email list and compares it "
        "with local commit emails on your machine. Other users' private emails are never "
        "accessible and are not assumed.",
        (DOC_ADD_EMAIL, DOC_VERIFY_EMAIL),
        needs_github=True,
    ),
    Rule(
        "COMMIT-AUTHORSHIP",
        "Authors, committers and co-authors",
        "identity",
        "GitHub credits the commit author (and co-authors listed in Co-authored-by "
        "trailers), not the committer. Commits you cherry-picked, rebased or applied for "
        "someone else credit them, not you.",
        (DOC_WHY_MISSING, DOC_CO_AUTHORS),
    ),
    Rule(
        "COMMIT-TIMING",
        "Commit dates and processing delay",
        "timing",
        "After a qualifying commit is pushed, it can take up to 24 hours to appear on the "
        "contribution graph. Contributions are placed by the commit's timestamp, so commits "
        "with a wrong clock (e.g. future dates) can land on unexpected days.",
        (DOC_WHY_MISSING, DOC_VIEWING),
    ),
    Rule(
        "GH-AUTH",
        "GitHub CLI access",
        "github",
        "Verified checks (fork status, visibility, default branch, attribution) use the "
        "GitHub CLI's existing login. The tool never reads, prints or stores your token. "
        "Without gh, local checks still run and GitHub-only checks report UNKNOWN or "
        "SKIPPED.",
        (DOC_GH_AUTH, DOC_RATE_LIMITS),
    ),
    Rule(
        "ACCOUNT-TARGET",
        "Inspected GitHub profile",
        "account",
        "The profile whose contributions are being diagnosed. Defaults to the authenticated "
        "gh account; use --user to inspect another profile. Account-private data of other "
        "users (emails, settings) is never available.",
        (DOC_VIEWING,),
    ),
    Rule(
        "ACCOUNT-PRIVATE-CONTRIB",
        "Private contributions setting",
        "account",
        "Whether private-repository contributions are shown publicly is a profile setting "
        "that no API exposes. The tool always reports it as UNKNOWN; check it yourself on "
        "your profile page.",
        (DOC_PRIVATE_CONTRIB,),
    ),
)

RULES: dict[str, Rule] = {r.id: r for r in _RULES}
RULE_ORDER: dict[str, int] = {r.id: i for i, r in enumerate(_RULES)}


def get_rule(rule_id: str) -> Rule:
    return RULES[rule_id]
