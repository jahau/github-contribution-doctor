"""Collect read-only facts about a local Git repository."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

from contribution_doctor.emails import normalize
from contribution_doctor.gitio import Git, GitError
from contribution_doctor.privacy import redact_url

GITHUB_HOSTS = frozenset({"github.com", "www.github.com", "ssh.github.com"})
PAGES_BRANCH = "gh-pages"
_SLUG = re.compile(r"^[A-Za-z0-9_.-]+$")
_SHA = re.compile(r"^[0-9a-f]{40}([0-9a-f]{24})?$")
_COAUTHOR = re.compile(r"^\s*(?P<name>.*?)\s*<(?P<email>[^>]*)>\s*$")
_FIELD = "\x1f"
_RECORD = "\x1e"
_TRAILER_SEP = "\x1d"
_LOG_FORMAT = (
    "%H%x1f%an%x1f%ae%x1f%aI%x1f%cn%x1f%ce%x1f%cI%x1f"
    "%(trailers:key=Co-authored-by,valueonly,separator=%x1d)%x1e"
)
MAX_BRANCHES = 30


class RepoError(Exception):
    """The path is not a usable Git repository."""


@dataclass(frozen=True)
class Remote:
    name: str
    url: str  # credentials already removed
    host: str | None
    owner: str | None = None
    repo: str | None = None

    @property
    def is_github(self) -> bool:
        return self.host in GITHUB_HOSTS and bool(self.owner and self.repo)

    @property
    def slug(self) -> str | None:
        return f"{self.owner}/{self.repo}" if self.is_github else None


@dataclass(frozen=True)
class Commit:
    sha: str
    author_name: str
    author_email: str
    author_date: datetime
    committer_name: str
    committer_email: str
    committer_date: datetime
    coauthors: tuple[tuple[str, str], ...] = ()


@dataclass
class BranchStat:
    ref: str  # e.g. "feature" or "origin/feature"
    tip: str
    is_remote: bool
    authors: list[str] = field(default_factory=list)  # normalized emails, newest first


@dataclass
class RepoFacts:
    root: str
    name: str
    git_version: str
    head_branch: str | None
    head_sha: str | None
    detached: bool
    is_shallow: bool
    remotes: list[Remote]
    remote_heads: dict[str, str]  # remote name -> default branch from refs/remotes/<r>/HEAD
    local_branches: dict[str, str]
    remote_branches: dict[str, str]  # "origin/main" -> sha
    config_email: str | None
    config_name: str | None
    commits: list[Commit]
    history_limit: int
    history_truncated: bool

    @property
    def has_commits(self) -> bool:
        return self.head_sha is not None or bool(self.local_branches) or bool(self.commits)

    @property
    def primary_remote(self) -> Remote | None:
        by_name = {r.name: r for r in self.remotes}
        if "origin" in by_name:
            return by_name["origin"]
        github = [r for r in self.remotes if r.is_github]
        if github:
            return github[0]
        return self.remotes[0] if self.remotes else None


@dataclass
class BranchAnalysis:
    default_refs: list[str]  # refs considered "the default branch" locally
    outside_default: list[str]  # SHAs not reachable from any default ref (capped)
    outside_truncated: bool
    branches: list[BranchStat]  # branches with commits outside the default branch
    unpushed: list[str]  # SHAs on local branches not reachable from any remote ref
    unpushed_truncated: bool


def parse_remote_url(name: str, raw_url: str) -> Remote:
    url = raw_url.strip()
    safe = redact_url(url)
    host: str | None = None
    path = ""
    if "://" in url:
        try:
            parts = urlsplit(url)
        except ValueError:
            return Remote(name, safe, None)
        if parts.scheme == "file":
            return Remote(name, safe, None)
        host = (parts.hostname or "").lower() or None
        path = parts.path
    else:
        m = re.match(r"^(?:[^@/]+@)?(?P<host>[^:/\\]+):(?P<path>.+)$", url)
        # A single-letter "host" is a Windows drive letter (C:\repo), i.e. a local path.
        if m and len(m.group("host")) > 1:
            host = m.group("host").lower()
            path = m.group("path")
        else:
            return Remote(name, safe, None)
    segments = [s for s in path.strip("/").split("/") if s]
    owner = repo = None
    if host in GITHUB_HOSTS and len(segments) == 2:
        owner, repo = segments[0], segments[1]
        if repo.endswith(".git"):
            repo = repo[:-4]
        if not (_SLUG.match(owner) and _SLUG.match(repo)):
            owner = repo = None
    return Remote(name, safe, host, owner, repo)


def _parse_date(value: str) -> datetime:
    return datetime.fromisoformat(value.strip().replace("Z", "+00:00"))


def parse_log(output: str) -> list[Commit]:
    commits: list[Commit] = []
    for record in output.split(_RECORD):
        record = record.strip("\r\n")
        if not record:
            continue
        parts = record.split(_FIELD)
        if len(parts) < 8:
            continue
        sha, an, ae, ad, cn, ce, cd, trailers = parts[:8]
        coauthors: list[tuple[str, str]] = []
        for value in trailers.split(_TRAILER_SEP):
            m = _COAUTHOR.match(value.strip())
            if m:
                coauthors.append((m.group("name"), normalize(m.group("email"))))
        try:
            commits.append(
                Commit(
                    sha=sha.strip(),
                    author_name=an,
                    author_email=normalize(ae),
                    author_date=_parse_date(ad),
                    committer_name=cn,
                    committer_email=normalize(ce),
                    committer_date=_parse_date(cd),
                    coauthors=tuple(coauthors),
                )
            )
        except ValueError:
            continue
    return commits


def is_sha(value: str) -> bool:
    return bool(_SHA.match(value))


def collect(git: Git, history: int) -> RepoFacts:
    """Gather repository facts. Raises RepoError for non-repositories."""
    version = git.out("version") or "unknown"
    top = git.run("rev-parse", "--show-toplevel")
    if not top.ok:
        bare = git.out("rev-parse", "--is-bare-repository")
        if bare == "true":
            root = git.out("rev-parse", "--absolute-git-dir") or git.cwd
        else:
            msg = top.stderr or "not a git repository"
            if "dubious ownership" in msg:
                msg = (
                    "Git refuses to read this repository because it is owned by another "
                    "user ('dubious ownership'). Review the path and, if you trust it, run "
                    "the `git config --global --add safe.directory ...` command Git "
                    "suggests. This tool will not change Git configuration for you."
                )
            raise RepoError(msg)
    else:
        root = top.stdout.strip()

    head_branch = git.out("symbolic-ref", "-q", "--short", "HEAD") or None
    head_sha = git.out("rev-parse", "-q", "--verify", "HEAD^{commit}") or None
    detached = head_branch is None and head_sha is not None
    is_shallow = git.out("rev-parse", "--is-shallow-repository") == "true"

    remotes: list[Remote] = []
    names = git.out("remote") or ""
    for rname in [n for n in names.splitlines() if n.strip()]:
        url = git.out("remote", "get-url", rname.strip())
        if url:
            remotes.append(parse_remote_url(rname.strip(), url))

    local_branches: dict[str, str] = {}
    remote_branches: dict[str, str] = {}
    remote_heads: dict[str, str] = {}
    # Use raw stdout: str.strip() treats the  separator as whitespace.
    refs = git.run(
        "for-each-ref",
        "--sort=-committerdate",
        "--format=%(refname)%1f%(objectname)%1f%(symref)",
        "refs/heads",
        "refs/remotes",
    )
    for line in (refs.stdout if refs.ok else "").splitlines():
        parts = line.split("\x1f")
        if len(parts) != 3:
            continue
        ref, sha, symref = parts
        if ref.startswith("refs/heads/"):
            local_branches[ref[len("refs/heads/") :]] = sha
        elif ref.startswith("refs/remotes/"):
            short = ref[len("refs/remotes/") :]
            if short.endswith("/HEAD"):
                if symref.startswith("refs/remotes/"):
                    rname = short[: -len("/HEAD")]
                    remote_heads[rname] = symref[len(f"refs/remotes/{rname}/") :]
                continue
            remote_branches[short] = sha

    config_email = git.out("config", "--get", "user.email") or None
    config_name = git.out("config", "--get", "user.name") or None

    commits: list[Commit] = []
    truncated = False
    if head_sha or local_branches or remote_branches:
        args = ["log", f"--max-count={history + 1}", "--date-order", f"--format={_LOG_FORMAT}"]
        args += ["--branches", "--remotes"]
        if head_sha:
            args.append("HEAD")
        result = git.run(*args)
        if result.ok:
            commits = parse_log(result.stdout)
            if len(commits) > history:
                truncated = True
                commits = commits[:history]
        else:
            raise GitError("could not read commit history", stderr=result.stderr)

    return RepoFacts(
        root=root,
        name=Path(root).name or root,
        git_version=version.replace("git version", "").strip(),
        head_branch=head_branch,
        head_sha=head_sha,
        detached=detached,
        is_shallow=is_shallow,
        remotes=remotes,
        remote_heads=remote_heads,
        local_branches=local_branches,
        remote_branches=remote_branches,
        config_email=normalize(config_email) if config_email else None,
        config_name=config_name,
        commits=commits,
        history_limit=history,
        history_truncated=truncated,
    )


def default_refs_for(facts: RepoFacts, branch: str) -> list[str]:
    """Local refs that represent the default branch (remote-tracking first)."""
    refs: list[str] = []
    for remote in facts.remotes:
        if f"{remote.name}/{branch}" in facts.remote_branches:
            refs.append(f"refs/remotes/{remote.name}/{branch}")
    if branch in facts.local_branches:
        refs.append(f"refs/heads/{branch}")
    return refs


def _sha_list(git: Git, args: list[str], limit: int) -> tuple[list[str], bool]:
    result = git.run(*args)
    if not result.ok:
        raise GitError("git rev-list failed", stderr=result.stderr)
    shas = [s for s in result.stdout.split() if s]
    return shas[:limit], len(shas) > limit


def analyse_branches(git: Git, facts: RepoFacts, default_branch: str | None) -> BranchAnalysis:
    limit = facts.history_limit
    default_refs = default_refs_for(facts, default_branch) if default_branch else []
    outside: list[str] = []
    outside_trunc = False
    stats: list[BranchStat] = []

    if default_refs:
        args = ["rev-list", f"--max-count={limit + 1}"]
        args += [f"--exclude={PAGES_BRANCH}", "--branches"]
        args += [f"--exclude=*/{PAGES_BRANCH}", "--exclude=*/HEAD", "--remotes"]
        if facts.detached:
            args.append("HEAD")
        args += ["--not", *default_refs]
        outside, outside_trunc = _sha_list(git, args, limit)

        candidates: list[tuple[str, str, bool]] = []
        for name, sha in facts.local_branches.items():
            if name not in (default_branch, PAGES_BRANCH):
                candidates.append((name, sha, False))
        for name, sha in facts.remote_branches.items():
            branch = name.split("/", 1)[1] if "/" in name else name
            if branch not in (default_branch, PAGES_BRANCH):
                candidates.append((name, sha, True))
        for name, sha, is_remote in candidates[:MAX_BRANCHES]:
            ref = f"refs/remotes/{name}" if is_remote else f"refs/heads/{name}"
            out = git.out(
                "log", f"--max-count={limit}", "--format=%ae", ref, "--not", *default_refs
            )
            emails = [normalize(e) for e in (out or "").splitlines() if e.strip()]
            if emails:
                stats.append(BranchStat(name, sha, is_remote, emails))

    unpushed: list[str] = []
    unpushed_trunc = False
    if facts.remotes and (facts.local_branches or facts.detached):
        args = ["rev-list", f"--max-count={limit + 1}", "--branches"]
        if facts.detached:
            args.append("HEAD")
        args += ["--not", "--remotes"]
        unpushed, unpushed_trunc = _sha_list(git, args, limit)

    return BranchAnalysis(default_refs, outside, outside_trunc, stats, unpushed, unpushed_trunc)
