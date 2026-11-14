"""Diagnostic rules. Each check takes a :class:`ScanContext` and returns one Finding."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from contribution_doctor.emails import EmailKind, classify
from contribution_doctor.github import GitHubContext
from contribution_doctor.identity import LIKELY, OTHER, YOURS, Identity
from contribution_doctor.models import Confidence, Finding, Status
from contribution_doctor.privacy import mask_email
from contribution_doctor.repo import BranchAnalysis, Commit, RepoFacts

H, M, L = Confidence.HIGH, Confidence.MEDIUM, Confidence.LOW
MAX_EVIDENCE = 10
PROCESSING_DELAY = timedelta(hours=24)


@dataclass
class DefaultBranch:
    name: str | None
    source: str
    confidence: Confidence
    verified: bool
    local_head: str | None = None  # what refs/remotes/<primary>/HEAD says, if anything


@dataclass
class ScanContext:
    facts: RepoFacts
    default: DefaultBranch
    branches: BranchAnalysis | None
    identities: dict[str, Identity]
    gh: GitHubContext
    now: datetime
    offline: bool
    show_emails: bool = False
    user_arg: str | None = None
    extra_emails: frozenset[str] = field(default_factory=frozenset)

    def email(self, address: str) -> str:
        masked = mask_email(address, show=self.show_emails)
        if masked == address:
            return masked
        # A short, stable tag keeps different addresses distinguishable after masking.
        tag = hashlib.sha256(address.encode("utf-8")).hexdigest()[:4]
        return f"{masked} #{tag}"

    @property
    def target(self) -> str | None:
        return self.gh.target_login or self.user_arg

    @property
    def mine(self) -> list[Identity]:
        return sorted((i for i in self.identities.values() if i.mine), key=lambda i: -i.count)

    @property
    def commits_by_sha(self) -> dict[str, Commit]:
        return {c.sha: c for c in self.facts.commits}

    @property
    def github_remote(self) -> bool:
        primary = self.facts.primary_remote
        return bool(primary and primary.is_github)

    def is_mine(self, email: str) -> bool:
        ident = self.identities.get(email)
        return bool(ident and ident.mine)

    def offline_reason(self) -> str:
        if self.offline:
            return "--offline was given"
        return self.gh.message or f"GitHub data unavailable ({self.gh.state})"


def _f(
    rule: str,
    status: Status,
    description: str,
    confidence: Confidence,
    *,
    verified: bool = False,
    evidence: list[str] | None = None,
    remediation: list[str] | None = None,
) -> Finding:
    return Finding(
        rule, status, description, confidence, verified, evidence or [], remediation or []
    )


def _day(d: datetime | None) -> str:
    return d.date().isoformat() if d else "?"


def _span(first: datetime | None, last: datetime | None) -> str:
    a, b = _day(first), _day(last)
    return a if a == b else f"{a}..{b}"


def _cap(lines: list[str], total: int | None = None) -> list[str]:
    total = len(lines) if total is None else total
    if total > MAX_EVIDENCE:
        return [*lines[:MAX_EVIDENCE], f"... and {total - MAX_EVIDENCE} more"]
    return lines


def _plural(n: int, word: str) -> str:
    if n == 1:
        return f"{n} {word}"
    if word.endswith(("ch", "sh", "s")):
        return f"{n} {word}es"
    if word.endswith("y"):
        return f"{n} {word[:-1]}ies"
    return f"{n} {word}s"


def _are(n: int) -> str:
    return "is" if n == 1 else "are"


def _have(n: int) -> str:
    return "has" if n == 1 else "have"


def _were(n: int) -> str:
    return "was" if n == 1 else "were"


def _ident_label(ctx: ScanContext, ident: Identity) -> str:
    return f"{ctx.email(ident.email)} ({ident.display_name or 'no name'})"


# --------------------------------------------------------------------------- repository


def check_repo_state(ctx: ScanContext) -> Finding:
    f = ctx.facts
    if not f.has_commits:
        return _f(
            "REPO-STATE",
            Status.WARN,
            "The repository has no commits yet, so there is nothing that could be counted.",
            H,
            verified=True,
            evidence=[f"HEAD points to unborn branch '{f.head_branch or '?'}'"],
            remediation=["Create a commit and push it to the GitHub repository."],
        )
    if f.detached:
        sha = (f.head_sha or "")[:7]
        return _f(
            "REPO-STATE",
            Status.WARN,
            f"HEAD is detached at {sha}. New commits made here are not on any branch and "
            "will not be pushed by a normal `git push`.",
            H,
            verified=True,
            evidence=[f"HEAD = {sha} (no branch)"],
            remediation=[
                "Keep the work by creating a branch: `git switch -c <branch-name>`, then push "
                "it and merge it into the default branch.",
            ],
        )
    return _f(
        "REPO-STATE",
        Status.PASS,
        f"On branch '{f.head_branch}'.",
        H,
        verified=True,
        evidence=[
            f"{_plural(len(f.local_branches), 'local branch')}, "
            f"{_plural(len(f.remote_branches), 'remote-tracking branch')}"
        ],
    )


def check_shallow(ctx: ScanContext) -> Finding:
    if ctx.facts.is_shallow:
        return _f(
            "REPO-SHALLOW",
            Status.WARN,
            "This is a shallow clone, so older history is missing locally. Author and branch "
            "findings only cover the commits that were downloaded.",
            H,
            verified=True,
            evidence=["git rev-parse --is-shallow-repository = true"],
            remediation=[
                "For a complete analysis run `git fetch --unshallow` yourself, then "
                "re-run the scan."
            ],
        )
    return _f("REPO-SHALLOW", Status.PASS, "Full (non-shallow) clone.", H, verified=True)


def check_remote(ctx: ScanContext) -> Finding:
    remotes = ctx.facts.remotes
    if not remotes:
        return _f(
            "REMOTE-GITHUB",
            Status.WARN,
            "No Git remote is configured. Commits made in this clone only exist locally "
            "unless they were pushed from another clone.",
            H,
            verified=True,
            remediation=[
                "Create a repository on GitHub and add it: "
                "`git remote add origin https://github.com/<owner>/<repo>.git`, then "
                "`git push -u origin <branch>`.",
            ],
        )
    evidence = [
        f"{r.name} -> {r.url}"
        + ("  [github.com]" if r.is_github else f"  [{r.host or 'local path'}]")
        for r in remotes
    ]
    github = [r for r in remotes if r.is_github]
    if not github:
        hosts = sorted({r.host or "local path" for r in remotes})
        return _f(
            "REMOTE-GITHUB",
            Status.WARN,
            f"No remote points to github.com (found: {', '.join(hosts)}). Contributions to "
            "other hosts, including GitHub Enterprise Server, do not appear on a github.com "
            "profile.",
            H,
            verified=True,
            evidence=evidence,
            remediation=[
                "Push the repository to github.com if you want it on your github.com profile.",
                "GitHub Enterprise Server users can enable unified contributions to send "
                "contribution counts (not code) to github.com.",
            ],
        )
    primary = ctx.facts.primary_remote
    if primary is None:  # pragma: no cover - remotes is non-empty here
        raise RuntimeError("no primary remote")
    desc = f"Primary remote '{primary.name}' is github.com/{primary.slug}."
    if not primary.is_github:
        desc = (
            f"Primary remote '{primary.name}' is not on github.com, but "
            f"'{github[0].name}' is ({github[0].slug}). GitHub checks use '{github[0].name}'."
        )
    return _f("REMOTE-GITHUB", Status.PASS, desc, H, verified=True, evidence=evidence)


def check_default_branch(ctx: ScanContext) -> Finding:
    d = ctx.default
    if not d.name:
        return _f(
            "REPO-DEFAULT-BRANCH",
            Status.UNKNOWN,
            "Could not determine the repository's default branch.",
            L,
            evidence=[d.source],
            remediation=[
                "Run without --offline and with `gh auth login` to read it from GitHub, or "
                "refresh the local pointer with `git remote set-head origin --auto`.",
            ],
        )
    evidence = [f"source: {d.source}"]
    head = ctx.facts.head_branch
    if head and head != d.name:
        evidence.append(f"you are currently on '{head}', not on '{d.name}'")
    if ctx.branches is not None and not ctx.branches.default_refs:
        evidence.append(f"'{d.name}' is not present locally; branch analysis is limited")
    if d.verified and d.local_head and d.local_head != d.name:
        return _f(
            "REPO-DEFAULT-BRANCH",
            Status.WARN,
            f"GitHub's default branch is '{d.name}', but the local "
            f"refs/remotes/.../HEAD still points to '{d.local_head}'. Work merged into "
            f"'{d.local_head}' is not counted.",
            H,
            verified=True,
            evidence=evidence,
            remediation=[
                f"Merge your work into '{d.name}'.",
                "Refresh the local pointer yourself with `git remote set-head origin --auto`.",
            ],
        )
    return _f(
        "REPO-DEFAULT-BRANCH",
        Status.PASS,
        f"Default branch is '{d.name}'.",
        d.confidence,
        verified=d.verified,
        evidence=evidence,
    )


def check_non_default(ctx: ScanContext) -> Finding:
    rid = "BRANCH-NON-DEFAULT"
    if not ctx.facts.has_commits:
        return _f(rid, Status.SKIPPED, "No commits to analyse.", H)
    if not ctx.default.name or ctx.branches is None:
        return _f(
            rid,
            Status.UNKNOWN,
            "Default branch unknown; cannot tell which commits are outside it.",
            L,
        )
    b = ctx.branches
    if not b.default_refs:
        return _f(
            rid,
            Status.UNKNOWN,
            f"The default branch '{ctx.default.name}' is not available in this clone.",
            L,
            remediation=[f"Run `git fetch origin {ctx.default.name}` and re-run the scan."],
        )
    by_sha = ctx.commits_by_sha
    outside = [by_sha[s] for s in b.outside_default if s in by_sha]
    mine_outside = [c for c in outside if ctx.is_mine(c.author_email)]
    total = len(b.outside_default)
    more = "+" if b.outside_truncated else ""
    if not total:
        return _f(
            rid,
            Status.PASS,
            f"Every scanned branch is contained in '{ctx.default.name}' (in this clone).",
            M,
        )
    if not mine_outside:
        return _f(
            rid,
            Status.PASS,
            f"{_plural(total, 'commit')}{more} {_are(total)} outside '{ctx.default.name}', "
            "but none appear to be authored by you.",
            L,
        )

    evidence: list[str] = []
    mine_branches = [s for s in b.branches if any(ctx.is_mine(e) for e in s.authors)]
    verdicts: list[str] = []
    for stat in mine_branches:
        n_mine = sum(1 for e in stat.authors if ctx.is_mine(e))
        kind = "remote-tracking" if stat.is_remote else "local"
        line = (
            f"{stat.ref} ({kind}): {_plural(len(stat.authors), 'commit')} not in "
            f"'{ctx.default.name}', {n_mine} yours"
        )
        cmp = ctx.gh.compare.get(stat.tip)
        if cmp in ("behind", "identical"):
            line += " - GitHub: already contained in the default branch (local clone is stale)"
            verdicts.append("merged")
        elif cmp in ("ahead", "diverged"):
            line += " - GitHub confirms these commits are not in the default branch"
            verdicts.append("outside")
        elif cmp == "not_found":
            line += " - GitHub does not have this branch tip (not pushed?)"
            verdicts.append("outside")
        evidence.append(line)
    evidence = _cap(evidence)

    if verdicts and all(v == "merged" for v in verdicts):
        return _f(
            rid,
            Status.PASS,
            "Your feature-branch commits are already in GitHub's default branch; only the "
            "local copy is out of date.",
            H,
            verified=True,
            evidence=evidence,
            remediation=["Run `git fetch` to update remote-tracking branches."],
        )
    confirmed = "outside" in verdicts
    return _f(
        rid,
        Status.WARN,
        f"{_plural(len(mine_outside), 'commit')} authored by you (in the scanned history) "
        f"{_are(len(mine_outside))} not on '{ctx.default.name}' in this clone. "
        "They count only after they reach the default branch."
        + ("" if confirmed else " This is based on local refs and may be out of date."),
        M if not confirmed else H,
        verified=confirmed,
        evidence=evidence,
        remediation=[
            f"Open a pull request and merge the branch into '{ctx.default.name}'.",
            "If the pull request was squash- or rebase-merged, the new commit on the default "
            "branch is what counts; the original branch commits will never be merged and "
            "that is expected.",
            "Run `git fetch` first so that the local view matches GitHub.",
        ],
    )


def check_unpushed(ctx: ScanContext) -> Finding:
    rid = "BRANCH-UNPUSHED"
    if not ctx.facts.has_commits:
        return _f(rid, Status.SKIPPED, "No commits to analyse.", H)
    if not ctx.facts.remotes or ctx.branches is None:
        return _f(rid, Status.SKIPPED, "No remotes configured (see REMOTE-GITHUB).", H)
    b = ctx.branches
    if not b.unpushed:
        return _f(
            rid,
            Status.PASS,
            "Every local commit is on a remote-tracking branch (as of the last fetch/push).",
            M,
        )
    by_sha = ctx.commits_by_sha
    known = [by_sha[s] for s in b.unpushed if s in by_sha]
    mine = [c for c in known if ctx.is_mine(c.author_email)]
    more = "+" if b.unpushed_truncated else ""
    evidence = _cap(
        [f"{c.sha[:7]}  {_day(c.author_date)}  {ctx.email(c.author_email)}" for c in known],
        len(b.unpushed),
    )
    return _f(
        rid,
        Status.WARN,
        f"{_plural(len(b.unpushed), 'local commit')}{more} ({len(mine)} by you) "
        f"{_are(len(b.unpushed))} not on any remote-tracking branch, so GitHub most likely "
        "has not received them.",
        H if mine else M,
        evidence=evidence,
        remediation=[
            "Push the branch: `git push -u origin <branch>`.",
            "If you pushed from another machine, run `git fetch` and re-check.",
        ],
    )


def check_fork(ctx: ScanContext) -> Finding:
    rid = "REPO-FORK"
    if not ctx.github_remote:
        return _f(rid, Status.SKIPPED, "Not a github.com repository.", H)
    repo = ctx.gh.repo
    if repo is None:
        evidence = [f"GitHub data unavailable: {ctx.gh.repo_error or ctx.offline_reason()}"]
        primary = ctx.facts.primary_remote
        for r in ctx.facts.remotes:
            if r.name == "upstream" and r.is_github and primary and r.slug != primary.slug:
                evidence.append(
                    f"remote 'upstream' points to {r.slug}; this layout is common for forks"
                )
        return _f(
            rid,
            Status.UNKNOWN,
            "Fork status can only be confirmed by GitHub.",
            L,
            evidence=evidence,
            remediation=["Run the scan online with an authenticated gh to verify."],
        )
    if repo.is_fork:
        return _f(
            rid,
            Status.WARN,
            f"{repo.name_with_owner} is a fork"
            + (f" of {repo.parent}" if repo.parent else "")
            + ". Commits made only in a fork are not counted on your profile.",
            H,
            verified=True,
            evidence=[f"GitHub: isFork = true, parent = {repo.parent or 'unknown'}"],
            remediation=[
                "Open a pull request to the parent repository; once merged into its default "
                "branch, the commits count.",
                "If the fork has become an independent project, detach it from the fork "
                "network (see the linked documentation).",
            ],
        )
    return _f(rid, Status.PASS, f"{repo.name_with_owner} is not a fork.", H, verified=True)


def check_ownership(ctx: ScanContext) -> Finding:
    rid = "REPO-OWNERSHIP"
    if not ctx.github_remote:
        return _f(rid, Status.SKIPPED, "Not a github.com repository.", H)
    target = ctx.target
    if not target:
        return _f(
            rid,
            Status.UNKNOWN,
            "No GitHub profile selected, so ownership cannot be compared.",
            L,
            remediation=["Pass --user <login> or log in with `gh auth login`."],
        )
    repo = ctx.gh.repo
    primary = ctx.facts.primary_remote
    owner = repo.owner if repo else (primary.owner if primary and primary.is_github else None)
    slug = repo.name_with_owner if repo else (primary.slug if primary else "?")
    if owner and owner.lower() == target.lower():
        return _f(
            rid,
            Status.PASS,
            f"@{target} owns {slug}.",
            H if repo else M,
            verified=repo is not None,
            evidence=["source: " + ("GitHub API" if repo else "remote URL")],
        )
    owner_kind = repo.owner_type if repo else "account"
    evidence = [f"{slug} is owned by {owner_kind} '{owner}'"]
    if repo and ctx.gh.is_self:
        perm = repo.viewer_permission or "NONE"
        evidence.append(f"your permission: {perm}")
        if perm in ("ADMIN", "MAINTAIN", "WRITE"):
            return _f(
                rid,
                Status.PASS,
                f"You have {perm} access to {slug}, which satisfies GitHub's "
                "relationship requirement.",
                H,
                verified=True,
                evidence=evidence,
            )
        if repo.viewer_has_starred:
            return _f(
                rid,
                Status.PASS,
                f"You starred {slug}, which satisfies GitHub's relationship requirement.",
                H,
                verified=True,
                evidence=evidence,
            )
    if ctx.gh.collaborator:
        return _f(
            rid,
            Status.PASS,
            f"@{target} is a collaborator on {slug}.",
            H,
            verified=True,
            evidence=evidence,
        )
    return _f(
        rid,
        Status.UNKNOWN,
        f"@{target} does not own {slug}. Commits count only if @{target} is a collaborator or "
        "organization member, forked it, opened an issue or pull request in it, or starred it. "
        "Not all of these can be checked.",
        M,
        evidence=evidence,
        remediation=[
            "Confirm you are a collaborator/member, or star the repository, or contribute "
            "through a pull request.",
        ],
    )


def check_visibility(ctx: ScanContext) -> Finding:
    rid = "REPO-VISIBILITY"
    if not ctx.github_remote:
        return _f(rid, Status.SKIPPED, "Not a github.com repository.", H)
    repo = ctx.gh.repo
    if repo is None:
        return _f(
            rid,
            Status.UNKNOWN,
            "Visibility can only be read from GitHub.",
            L,
            evidence=[ctx.gh.repo_error or ctx.offline_reason()],
        )
    if repo.visibility == "PUBLIC":
        return _f(rid, Status.PASS, f"{repo.name_with_owner} is public.", H, verified=True)
    return _f(
        rid,
        Status.WARN,
        f"{repo.name_with_owner} is {repo.visibility.lower()}. Other people see these "
        "contributions only as anonymized counts, and only if the profile's 'Private "
        "contributions' setting is enabled (see ACCOUNT-PRIVATE-CONTRIB).",
        H,
        verified=True,
        evidence=[f"GitHub: visibility = {repo.visibility}"],
        remediation=[
            "Enable 'Private contributions' in your profile's contribution settings "
            "if you want them counted publicly."
        ],
    )


def check_private_setting(ctx: ScanContext) -> Finding:
    rid = "ACCOUNT-PRIVATE-CONTRIB"
    repo = ctx.gh.repo
    if repo is not None and repo.visibility == "PUBLIC":
        return _f(rid, Status.SKIPPED, "Not relevant for a public repository.", H, verified=True)
    return _f(
        rid,
        Status.UNKNOWN,
        "Whether private contributions are shown on the profile cannot be read through any "
        "API, so it is not assumed either way.",
        L,
        remediation=[
            "Open your profile, click 'Contribution settings' above the graph and "
            "check 'Private contributions'."
        ],
    )


# ----------------------------------------------------------------------------- identity


def check_config_email(ctx: ScanContext) -> Finding:
    rid = "CONFIG-EMAIL"
    email = ctx.facts.config_email
    fix = (
        "Set it yourself: `git config --global user.email <email-on-your-GitHub-account>` "
        "(your <id>+<login>@users.noreply.github.com address works and keeps your email private)."
    )
    if not email:
        return _f(
            rid,
            Status.WARN,
            "user.email is not set. Git may invent an address from your user and host names, "
            "which GitHub cannot attribute to any account.",
            H,
            verified=True,
            remediation=[fix],
        )
    info = classify(email)
    shown = ctx.email(email)
    ident = ctx.identities.get(email)
    used = (
        f"used by {_plural(ident.count, 'scanned commit')}"
        if ident and ident.count
        else "not used by any scanned commit"
    )
    evidence = [f"user.email = {shown} ({used})"]
    if info.kind == EmailKind.UNLINKABLE:
        return _f(
            rid,
            Status.FAIL,
            f"user.email {shown} can never be verified on GitHub: {info.reason}.",
            H,
            verified=True,
            evidence=evidence,
            remediation=[fix],
        )
    target = ctx.target
    if info.kind == EmailKind.NOREPLY and target:
        if (
            info.noreply_login
            and info.noreply_login.lower() != target.lower()
            and not (ctx.gh.target_id and info.noreply_id == ctx.gh.target_id)
        ):
            return _f(
                rid,
                Status.WARN,
                f"user.email is the noreply address of @{info.noreply_login}, not @{target}.",
                H,
                verified=True,
                evidence=evidence,
                remediation=[fix],
            )
        if info.noreply_id is None:
            evidence.append(
                "legacy noreply form without numeric ID; it breaks if the username changes"
            )
        return _f(
            rid,
            Status.PASS,
            f"user.email is the noreply address of @{target}.",
            H,
            verified=True,
            evidence=evidence,
        )
    if ident and ident.github_login:
        if target and ident.github_login.lower() == target.lower():
            return _f(
                rid,
                Status.PASS,
                f"GitHub attributes commits using {shown} to @{target}.",
                H,
                verified=True,
                evidence=evidence,
            )
        return _f(
            rid,
            Status.FAIL,
            f"GitHub attributes commits using {shown} to "
            f"@{ident.github_login}, not @{target or '?'}.",
            H,
            verified=True,
            evidence=evidence,
            remediation=[fix],
        )
    if ident and ident.attribution == "unlinked":
        return _f(
            rid,
            Status.FAIL,
            f"GitHub does not link {shown} to any account.",
            H,
            verified=True,
            evidence=evidence,
            remediation=[
                "Add and verify this address on your GitHub account (this also credits "
                "past commits), or " + fix[0].lower() + fix[1:]
            ],
        )
    emails = ctx.gh.account_emails
    if emails is not None:
        state = dict(emails)
        if state.get(email):
            return _f(
                rid,
                Status.PASS,
                f"{shown} is a verified email on your account.",
                H,
                verified=True,
                evidence=evidence,
            )
        if email in state:
            return _f(
                rid,
                Status.FAIL,
                f"{shown} is on your account but not verified.",
                H,
                verified=True,
                evidence=evidence,
                remediation=["Verify the address from your GitHub email settings."],
            )
        return _f(
            rid,
            Status.FAIL,
            f"{shown} is not on your GitHub account.",
            H,
            verified=True,
            evidence=evidence,
            remediation=[
                "Add and verify it on GitHub (this also credits past commits), or "
                + fix[0].lower()
                + fix[1:]
            ],
        )
    return _f(
        rid,
        Status.UNKNOWN,
        f"user.email is set to {shown}; whether it is linked to your account could not be "
        "verified.",
        L,
        evidence=evidence,
        remediation=[
            "Check that this address is listed and verified under GitHub Settings -> Emails."
        ],
    )


def _ident_line(ctx: ScanContext, ident: Identity) -> str:
    label = {YOURS: "yours", LIKELY: "probably yours", OTHER: "other account"}.get(
        ident.ownership, "unknown owner"
    )
    why = f" - {'; '.join(ident.reasons)}" if ident.reasons else ""
    return (
        f"{_ident_label(ctx, ident)}: {_plural(ident.count, 'commit')}, "
        f"{_span(ident.first_date, ident.last_date)} [{label}{why}]"
    )


def check_identities(ctx: ScanContext) -> Finding:
    rid = "COMMIT-IDENTITIES"
    authors = sorted((i for i in ctx.identities.values() if i.count), key=lambda i: -i.count)
    if not authors:
        return _f(rid, Status.SKIPPED, "No commits to analyse.", H)
    n_commits = len(ctx.facts.commits)
    scope = _plural(n_commits, "scanned commit") + ("+" if ctx.facts.history_truncated else "")
    evidence = _cap([_ident_line(ctx, i) for i in authors])
    mine = [i for i in authors if i.mine]
    if not mine:
        return _f(
            rid,
            Status.WARN,
            f"None of the {_plural(len(authors), 'author identity')} in {scope} could be "
            f"matched to {('@' + ctx.target) if ctx.target else 'you'}.",
            L,
            evidence=evidence,
            remediation=[
                "If some of these are yours, pass them with --email <address> (repeatable) "
                "or select the right profile with --user <login>.",
            ],
        )
    all_linked = all(i.ownership == YOURS and i.github_login for i in mine)
    if len(mine) > 1:
        return _f(
            rid,
            Status.PASS if all_linked else Status.WARN,
            f"Your commits use {len(mine)} different author emails in {scope}. "
            + (
                "GitHub links all of them to your account."
                if all_linked
                else "Each one must be added to and verified on the same account."
            ),
            H if all_linked else M,
            verified=all_linked,
            evidence=evidence,
            remediation=[]
            if all_linked
            else [
                "Add every address you commit with under GitHub Settings -> Emails; existing "
                "commits are credited retroactively.",
                "Use one address going forward (`git config --global user.email ...`).",
            ],
        )
    return _f(
        rid,
        Status.PASS,
        f"Your commits use a single author email in {scope}.",
        H if all_linked else L,
        verified=all_linked,
        evidence=evidence,
    )


def check_unlinkable(ctx: ScanContext) -> Finding:
    rid = "COMMIT-EMAIL-UNLINKABLE"
    authors = [i for i in ctx.identities.values() if i.count]
    if not authors:
        return _f(rid, Status.SKIPPED, "No commits to analyse.", H)
    bad = [i for i in authors if i.info.kind == EmailKind.UNLINKABLE]
    mine = [i for i in bad if i.mine or i.local_signal]
    others = [i for i in bad if i not in mine]
    evidence = [
        f"{_ident_label(ctx, i)}: {_plural(i.count, 'commit')}, last {_day(i.last_date)} - "
        f"{i.info.reason}"
        for i in mine
    ]
    if others:
        evidence.append(
            f"{_plural(sum(i.count for i in others), 'commit')} by "
            f"{_plural(len(others), 'other identity')} also use unlinkable addresses"
        )
    if not mine:
        return _f(
            rid,
            Status.PASS,
            "No commits of yours use an address that GitHub could never attribute.",
            M,
            evidence=evidence,
        )
    total = sum(i.count for i in mine)
    return _f(
        rid,
        Status.FAIL,
        f"{_plural(total, 'commit')} that appear to be yours use an author email that GitHub "
        "can never link to an account, so they cannot count.",
        H,
        verified=True,
        evidence=evidence,
        remediation=[
            "Configure a real address for future commits: `git config --global user.email "
            "<email-on-your-GitHub-account>`.",
            "Existing commits keep their author email. Re-attributing them requires rewriting "
            "history (e.g. git filter-repo), which changes commit SHAs and disrupts anyone "
            "else using the branch. This tool never does that for you.",
        ],
    )


def check_attribution(ctx: ScanContext) -> Finding:
    rid = "COMMIT-ATTRIBUTION"
    if not ctx.facts.has_commits:
        return _f(rid, Status.SKIPPED, "No commits to analyse.", H)
    if not ctx.github_remote:
        return _f(rid, Status.SKIPPED, "Not a github.com repository.", H)
    candidates = [i for i in ctx.identities.values() if i.count and (i.mine or i.local_signal)]
    if ctx.gh.repo is None or not ctx.gh.online or ctx.gh.attribution_error:
        reason = ctx.gh.attribution_error or ctx.gh.repo_error or ctx.offline_reason()
        evidence = [f"GitHub attribution not checked: {reason}"]
        for i in candidates:
            if i.info.kind == EmailKind.NOREPLY:
                evidence.append(
                    f"{_ident_label(ctx, i)}: noreply format - attributed to "
                    f"@{i.info.noreply_login} if that account exists"
                )
            elif i.info.kind == EmailKind.REGULAR:
                evidence.append(f"{_ident_label(ctx, i)}: cannot be verified offline")
        return _f(
            rid,
            Status.UNKNOWN,
            "Could not ask GitHub which account your commits are attributed to.",
            L,
            evidence=_cap(evidence),
            remediation=["Run online with `gh auth login` to verify attribution."],
        )
    target = ctx.target
    bad: list[str] = []
    unknown: list[str] = []
    good: list[str] = []
    for i in sorted(candidates, key=lambda x: -x.count):
        label = f"{_ident_label(ctx, i)} ({_plural(i.count, 'commit')})"
        if i.attribution == "linked" and i.github_login:
            if target and i.github_login.lower() == target.lower():
                good.append(f"{label}: attributed to @{i.github_login}")
            else:
                bad.append(f"{label}: attributed to @{i.github_login}, not @{target or '?'}")
        elif i.attribution == "unlinked":
            bad.append(f"{label}: GitHub links this email to no account")
        elif i.attribution == "not_on_github":
            unknown.append(f"{label}: sample commit not found on GitHub (not pushed yet?)")
        else:
            unknown.append(f"{label}: not checked")
    evidence = _cap(bad + unknown + good)
    if bad:
        return _f(
            rid,
            Status.FAIL,
            f"GitHub does not credit {_plural(len(bad), 'identity')} that appear to be yours "
            f"to @{target or '?'}.",
            H,
            verified=True,
            evidence=evidence,
            remediation=[
                "Add and verify the email on the account that should get credit (GitHub "
                "Settings -> Emails); past commits are re-attributed automatically.",
                "If an address belongs to a second GitHub account of yours, remove it there "
                "and add it to the main account.",
            ],
        )
    if not candidates:
        return _f(
            rid,
            Status.UNKNOWN,
            "No identities matched to you, so there was nothing to check (see COMMIT-IDENTITIES).",
            L,
        )
    if unknown and not good:
        return _f(
            rid,
            Status.UNKNOWN,
            "GitHub could not confirm attribution for your identities.",
            L,
            evidence=evidence,
        )
    return _f(
        rid,
        Status.PASS if not unknown else Status.UNKNOWN,
        f"GitHub attributes your checked commits to @{target}."
        + (" Some identities could not be checked." if unknown else ""),
        H if not unknown else M,
        verified=not unknown,
        evidence=evidence,
    )


def check_account_emails(ctx: ScanContext) -> Finding:
    rid = "ACCOUNT-EMAILS"
    if not ctx.gh.online:
        return _f(rid, Status.SKIPPED, f"Requires GitHub ({ctx.offline_reason()}).", H)
    if not ctx.gh.is_self:
        return _f(
            rid,
            Status.SKIPPED,
            f"Only possible for your own authenticated account; @{ctx.target} is a different "
            "account and its email addresses are private.",
            H,
        )
    if ctx.gh.account_emails is None:
        return _f(
            rid,
            Status.UNKNOWN,
            "Your account's email list could not be read.",
            L,
            evidence=[ctx.gh.account_emails_error or "unknown error"],
            remediation=[
                "Optional: `gh auth refresh -h github.com -s user` grants the scope "
                "needed for this check."
            ],
        )
    state = dict(ctx.gh.account_emails)
    missing: list[str] = []
    unverified: list[str] = []
    ok: list[str] = []
    for i in ctx.mine + [
        x for x in ctx.identities.values() if x.local_signal and not x.mine and x.count
    ]:
        if i.info.kind != EmailKind.REGULAR:
            continue
        label = f"{_ident_label(ctx, i)} ({_plural(i.count, 'commit')})"
        if i.email not in state:
            missing.append(f"{label}: not on your account")
        elif not state[i.email]:
            unverified.append(f"{label}: on your account but unverified")
        else:
            ok.append(f"{label}: verified")
    evidence = _cap(missing + unverified + ok)
    if missing or unverified:
        return _f(
            rid,
            Status.FAIL,
            "Some commit emails that look like yours are missing from, or unverified on, "
            "your GitHub account.",
            H,
            verified=True,
            evidence=evidence,
            remediation=[
                "Add and verify them under GitHub Settings -> Emails; existing "
                "commits are credited retroactively."
            ],
        )
    return _f(
        rid,
        Status.PASS,
        "Your regular commit emails are verified on your account.",
        H,
        verified=True,
        evidence=evidence,
    )


def check_authorship(ctx: ScanContext) -> Finding:
    rid = "COMMIT-AUTHORSHIP"
    commits = ctx.facts.commits
    if not commits:
        return _f(rid, Status.SKIPPED, "No commits to analyse.", H)
    committed_for_others = [
        c for c in commits if ctx.is_mine(c.committer_email) and not ctx.is_mine(c.author_email)
    ]
    coauthored = [
        c
        for c in commits
        if not ctx.is_mine(c.author_email) and any(ctx.is_mine(e) for _, e in c.coauthors)
    ]
    by_others = [
        c for c in commits if ctx.is_mine(c.author_email) and not ctx.is_mine(c.committer_email)
    ]
    evidence: list[str] = []
    if coauthored:
        evidence.append(
            f"{_plural(len(coauthored), 'commit')} list you in a "
            "Co-authored-by trailer; they count for you if that email is linked"
        )
    if by_others:
        evidence.append(
            f"{_plural(len(by_others), 'commit')} authored by you "
            f"{_were(len(by_others))} committed by someone else (e.g. GitHub web merges); "
            "they are credited to you"
        )
    if committed_for_others:
        evidence.append(
            f"{_plural(len(committed_for_others), 'commit')} you committed "
            f"{_are(len(committed_for_others))} authored by someone else"
        )
        return _f(
            rid,
            Status.WARN,
            f"{_plural(len(committed_for_others), 'commit')} {_were(len(committed_for_others))} "
            "committed by you but authored by someone else (cherry-picks, rebases or "
            "applied patches). GitHub credits the author, so these do not count for you.",
            H,
            verified=True,
            evidence=evidence,
            remediation=[
                "This is expected behaviour. For shared work, add a "
                "`Co-authored-by: Name <email>` trailer to the commit message."
            ],
        )
    return _f(
        rid,
        Status.PASS,
        "No commits committed by you on behalf of other authors.",
        M,
        verified=True,
        evidence=evidence,
    )


def check_timing(ctx: ScanContext) -> Finding:
    rid = "COMMIT-TIMING"
    commits = [c for c in ctx.facts.commits if ctx.is_mine(c.author_email)]
    if not ctx.facts.commits:
        return _f(rid, Status.SKIPPED, "No commits to analyse.", H)
    if not commits:
        return _f(rid, Status.SKIPPED, "No commits matched to you.", L)
    now = ctx.now
    future = [c for c in commits if c.author_date - now > PROCESSING_DELAY]
    recent = [c for c in commits if timedelta(0) <= now - c.author_date < PROCESSING_DELAY]
    old = [c for c in commits if now - c.author_date > timedelta(days=365)]
    evidence: list[str] = []
    if old:
        evidence.append(
            f"{_plural(len(old), 'commit')} {_are(len(old))} older than one year; pick the year "
            "on the profile page to see them"
        )
    if future:
        evidence += [f"{c.sha[:7]} dated {c.author_date.isoformat()}" for c in future[:5]]
        return _f(
            rid,
            Status.WARN,
            f"{_plural(len(future), 'commit')} {_have(len(future))} author "
            "dates in the future, so they may appear on unexpected days.",
            H,
            verified=True,
            evidence=evidence,
            remediation=[
                "Check the system clock and timezone of the machine that made these commits."
            ],
        )
    if recent:
        newest = max(recent, key=lambda c: c.author_date)
        hours = (now - newest.author_date).total_seconds() / 3600
        evidence.insert(0, f"newest: {newest.sha[:7]}, {hours:.1f} hours ago")
        return _f(
            rid,
            Status.WARN,
            f"{_plural(len(recent), 'commit')} by you {_are(len(recent))} less than 24 hours "
            "old. GitHub can take up to 24 hours to show new contributions.",
            M,
            evidence=evidence,
            remediation=["Wait up to 24 hours after pushing, then check again."],
        )
    return _f(
        rid,
        Status.PASS,
        "No timing issues: no future-dated or very recent commits.",
        M,
        verified=True,
        evidence=evidence,
    )


# ------------------------------------------------------------------------------ github


def check_gh_auth(ctx: ScanContext) -> Finding:
    rid = "GH-AUTH"
    gh = ctx.gh
    if ctx.offline:
        return _f(rid, Status.SKIPPED, "Offline mode: GitHub was not contacted.", H)
    if gh.state == "not_installed":
        return _f(
            rid,
            Status.SKIPPED,
            "GitHub CLI (gh) is not installed; only local checks ran.",
            H,
            remediation=[
                "Install gh from https://cli.github.com and run "
                "`gh auth login` for verified checks."
            ],
        )
    if gh.state == "not_authenticated":
        return _f(
            rid,
            Status.SKIPPED,
            "gh is installed but not logged in; only local checks ran.",
            H,
            remediation=["Run `gh auth login`."],
        )
    if gh.state != "ok":
        return _f(
            rid,
            Status.UNKNOWN,
            f"GitHub could not be queried: {gh.message}",
            M,
            remediation=["Check your network connection, or wait if rate limited."],
        )
    if gh.rate_limited:
        return _f(
            rid,
            Status.UNKNOWN,
            f"Authenticated as @{gh.viewer_login}, but some requests "
            "hit the GitHub rate limit; affected checks report UNKNOWN.",
            H,
            verified=True,
            remediation=["Re-run later."],
        )
    return _f(
        rid,
        Status.PASS,
        f"Authenticated as @{gh.viewer_login} via gh (token not read or displayed).",
        H,
        verified=True,
    )


def check_target(ctx: ScanContext) -> Finding:
    rid = "ACCOUNT-TARGET"
    gh = ctx.gh
    target = ctx.target
    if not target:
        return _f(
            rid,
            Status.UNKNOWN,
            "No GitHub profile selected; identity matching relies on local Git configuration only.",
            L,
            remediation=["Pass --user <login>, or log in with `gh auth login`."],
        )
    if not gh.online:
        return _f(
            rid, Status.UNKNOWN, f"Inspecting @{target} (not verified: {ctx.offline_reason()}).", L
        )
    if gh.target_exists is False:
        return _f(
            rid,
            Status.FAIL,
            f"GitHub user @{target} was not found.",
            H,
            verified=True,
            evidence=[gh.target_error or ""],
            remediation=["Check the spelling of --user."],
        )
    evidence = []
    if not gh.is_self:
        evidence.append(
            f"authenticated as @{gh.viewer_login}; @{target}'s private emails and "
            "settings are not accessible, so only public attribution is used"
        )
    return _f(
        rid,
        Status.PASS,
        f"Inspecting GitHub profile @{target}.",
        H,
        verified=True,
        evidence=evidence,
    )


CHECKS: tuple[Callable[[ScanContext], Finding], ...] = (
    check_gh_auth,
    check_target,
    check_repo_state,
    check_shallow,
    check_remote,
    check_default_branch,
    check_non_default,
    check_unpushed,
    check_fork,
    check_ownership,
    check_visibility,
    check_config_email,
    check_identities,
    check_unlinkable,
    check_attribution,
    check_account_emails,
    check_authorship,
    check_timing,
    check_private_setting,
)
