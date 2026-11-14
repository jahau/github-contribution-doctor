"""Scan orchestration: collect facts, optionally query GitHub, run checks."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone

from contribution_doctor import __version__
from contribution_doctor.catalog import get_rule
from contribution_doctor.checks import CHECKS, DefaultBranch, ScanContext
from contribution_doctor.emails import normalize
from contribution_doctor.github import (
    GhClient,
    GitHubContext,
    fetch_account_emails,
    fetch_attribution,
    fetch_collaborator,
    fetch_compare,
    fetch_context,
)
from contribution_doctor.gitio import Git
from contribution_doctor.identity import (
    LIKELY,
    YOURS,
    Identity,
    OwnershipHints,
    assign_ownership,
    build_identities,
)
from contribution_doctor.models import Confidence, Finding, Report
from contribution_doctor.repo import RepoFacts, analyse_branches, collect

DEFAULT_HISTORY = 500
MAX_HISTORY = 100_000


@dataclass
class ScanOptions:
    path: str = "."
    user: str | None = None
    offline: bool = False
    history: int = DEFAULT_HISTORY
    emails: list[str] = field(default_factory=list)
    show_emails: bool = False
    timeout: float = 30.0


def resolve_default_branch(facts: RepoFacts, gh: GitHubContext) -> DefaultBranch:
    primary = facts.primary_remote
    local_head = facts.remote_heads.get(primary.name) if primary else None
    if gh.repo and gh.repo.default_branch:
        return DefaultBranch(
            gh.repo.default_branch, "GitHub API", Confidence.HIGH, True, local_head
        )
    if local_head and primary:
        return DefaultBranch(
            local_head,
            f"refs/remotes/{primary.name}/HEAD (local cache; may be stale)",
            Confidence.MEDIUM,
            False,
            local_head,
        )
    for rname, branch in facts.remote_heads.items():
        return DefaultBranch(
            branch, f"refs/remotes/{rname}/HEAD (local cache)", Confidence.LOW, False, None
        )
    names: set[str] = set(facts.local_branches)
    if primary:
        prefix = f"{primary.name}/"
        names |= {b[len(prefix) :] for b in facts.remote_branches if b.startswith(prefix)}
    common = [n for n in ("main", "master", "trunk") if n in names]
    if len(common) == 1:
        return DefaultBranch(
            common[0],
            f"guessed from branch names ('{common[0]}' exists)",
            Confidence.LOW,
            False,
            None,
        )
    if len(names) == 1:
        only = next(iter(names))
        return DefaultBranch(only, "guessed: it is the only branch", Confidence.LOW, False, None)
    return DefaultBranch(
        None, "no GitHub data and no refs/remotes/<remote>/HEAD", Confidence.LOW, False, None
    )


def _sample_shas(identities: dict[str, Identity], unpushed: set[str]) -> dict[str, str]:
    """Pick one commit per identity (newest likely-pushed one) for attribution lookups."""
    picks: dict[str, str] = {}
    ordered = sorted(identities.values(), key=lambda i: (not (i.mine or i.local_signal), -i.count))
    for ident in ordered:
        if not ident.authored:
            continue
        pushed = [c for c in ident.authored if c.sha not in unpushed]
        pool = pushed or ident.authored
        picks[ident.email] = max(pool, key=lambda c: c.author_date).sha
    return picks


def scan(
    options: ScanOptions,
    *,
    git: Git | None = None,
    gh_client: GhClient | None = None,
    now: datetime | None = None,
    progress: Callable[[str], None] | None = None,
) -> Report:
    def step(msg: str) -> None:
        if progress:
            progress(msg)

    history = max(1, min(options.history, MAX_HISTORY))
    git = git or Git(options.path, timeout=options.timeout)
    step("reading local repository")
    facts = collect(git, history)

    primary = facts.primary_remote
    github_remote = next(
        (r for r in ([primary] if primary else []) + facts.remotes if r and r.is_github), None
    )

    if options.offline:
        gh = GitHubContext("offline", "--offline was given")
    else:
        step("querying GitHub via gh")
        client = gh_client or GhClient(timeout=options.timeout)
        gh = fetch_context(
            client,
            user=options.user,
            owner=github_remote.owner if github_remote else None,
            name=github_remote.repo if github_remote else None,
        )
    if not gh.target_login and options.user:
        gh.target_login = options.user

    default = resolve_default_branch(facts, gh)
    branches = analyse_branches(git, facts, default.name) if facts.has_commits else None

    identities = build_identities(facts.commits)
    extra = frozenset(normalize(e) for e in options.emails if e.strip())
    hints = OwnershipHints(
        target_login=gh.target_login,
        target_id=gh.target_id,
        config_email=facts.config_email,
        config_name=facts.config_name,
        extra_emails=extra,
    )

    if gh.online:
        client = gh_client or GhClient(timeout=options.timeout)
        fetch_account_emails(client, gh)
        if gh.account_emails is not None:
            hints.verified_emails = frozenset(e for e, ok in gh.account_emails if ok)
        assign_ownership(identities, hints)  # preliminary, to prioritise lookups
        unpushed = set(branches.unpushed) if branches else set()
        samples = _sample_shas(identities, unpushed)
        fetch_attribution(client, gh, list(samples.values()))
        for email, sha in samples.items():
            att = gh.attribution.get(sha)
            if att is None:
                continue
            ident = identities[email]
            if not att.found:
                ident.attribution = "not_on_github"
            elif att.author_login:
                ident.attribution, ident.github_login = "linked", att.author_login
            else:
                ident.attribution = "unlinked"
        assign_ownership(identities, hints)
        if branches and default.name:
            tips = [
                b.tip
                for b in branches.branches
                if any(
                    identities[e].ownership in (YOURS, LIKELY) for e in b.authors if e in identities
                )
            ]
            fetch_compare(client, gh, tips, default.name)
        if gh.repo and gh.target_login and not gh.is_self:
            fetch_collaborator(client, gh)
    else:
        assign_ownership(identities, hints)

    ctx = ScanContext(
        facts=facts,
        default=default,
        branches=branches,
        identities=identities,
        gh=gh,
        now=now or datetime.now(timezone.utc),
        offline=options.offline,
        show_emails=options.show_emails,
        user_arg=options.user,
        extra_emails=extra,
    )
    step("running checks")
    findings = [_decorate(check(ctx)) for check in CHECKS]

    slug = gh.repo.name_with_owner if gh.repo else (github_remote.slug if github_remote else None)
    return Report(
        tool_version=__version__,
        generated_at=ctx.now.replace(microsecond=0).isoformat(),
        repository={
            "name": facts.name,
            "github": slug,
            "head_branch": facts.head_branch,
            "default_branch": default.name,
            "default_branch_source": default.source,
            "shallow": facts.is_shallow,
            "git_version": facts.git_version,
        },
        profile={
            "login": gh.target_login,
            "authenticated_as": gh.viewer_login,
            "github_state": gh.state,
        },
        scan={
            "mode": "offline" if options.offline else ("online" if gh.online else "local-only"),
            "history_limit": history,
            "commits_scanned": len(facts.commits),
            "history_truncated": facts.history_truncated,
            "emails_masked": not options.show_emails,
        },
        findings=findings,
    )


def _decorate(finding: Finding) -> Finding:
    rule = get_rule(finding.rule_id)
    finding.title = rule.title
    finding.category = rule.category
    finding.explanation = rule.explanation
    finding.docs = list(rule.docs)
    return finding
