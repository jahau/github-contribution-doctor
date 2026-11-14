"""Shared fixtures: isolated Git environment, real repository builder, fake GitHub."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from contribution_doctor.engine import ScanOptions, scan
from contribution_doctor.github import GhClient, GitHubError
from contribution_doctor.gitio import Git
from contribution_doctor.models import Finding, Report

FIXTURES = Path(__file__).parent / "fixtures"
# Fixed "now" so date-based rules are deterministic.
NOW = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
ME = ("Alex Morgan", "alex@alexmorgan.dev")


def load_fixture(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.fixture(autouse=True)
def isolated_git(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> None:
    """Never read the developer's real ~/.gitconfig or system config."""
    home = tmp_path_factory.mktemp("home")
    cfg = home / ".gitconfig"
    cfg.write_text("[init]\n\tdefaultBranch = main\n", encoding="utf-8")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(cfg))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    for var in (
        "GIT_AUTHOR_NAME",
        "GIT_AUTHOR_EMAIL",
        "GIT_COMMITTER_NAME",
        "GIT_COMMITTER_EMAIL",
        "EMAIL",
        "GIT_DIR",
        "GIT_WORK_TREE",
    ):
        monkeypatch.delenv(var, raising=False)


class RepoBuilder:
    """Creates real Git repositories with controlled authors and dates."""

    def __init__(self, path: Path):
        self.path = path
        self.clock = NOW - timedelta(days=30)
        path.mkdir(parents=True, exist_ok=True)
        self.git("init", "-q", "-b", "main")

    def git(self, *args: str, env: dict[str, str] | None = None) -> str:
        full_env = {**os.environ, **(env or {})}
        proc = subprocess.run(
            ["git", "-C", str(self.path), *args],
            capture_output=True,
            text=True,
            env=full_env,
            check=False,
        )
        if proc.returncode != 0:
            raise AssertionError(f"git {' '.join(args)} failed: {proc.stderr}")
        return proc.stdout.strip()

    def config(self, key: str, value: str) -> RepoBuilder:
        self.git("config", key, value)
        return self

    def commit(
        self,
        message: str = "change",
        *,
        author: tuple[str, str] = ME,
        committer: tuple[str, str] | None = None,
        date: datetime | None = None,
        coauthors: tuple[tuple[str, str], ...] = (),
    ) -> str:
        if date is None:
            self.clock += timedelta(hours=1)
            date = self.clock
        committer = committer or author
        body = message
        if coauthors:
            body += "\n\n" + "\n".join(f"Co-authored-by: {n} <{e}>" for n, e in coauthors)
        stamp = date.isoformat()
        self.git(
            "commit",
            "-q",
            "--allow-empty",
            "-m",
            body,
            env={
                "GIT_AUTHOR_NAME": author[0],
                "GIT_AUTHOR_EMAIL": author[1],
                "GIT_AUTHOR_DATE": stamp,
                "GIT_COMMITTER_NAME": committer[0],
                "GIT_COMMITTER_EMAIL": committer[1],
                "GIT_COMMITTER_DATE": stamp,
            },
        )
        return self.git("rev-parse", "HEAD")

    def add_github_remote(self, slug: str = "alexdev/widgets", name: str = "origin") -> Path:
        """Push to a local bare repo, then point the remote at github.com.

        This yields realistic remote-tracking refs (refs/remotes/origin/*, origin/HEAD)
        without any network access.
        """
        bare = self.path.parent / f"{self.path.name}-{name}.git"
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(bare)], check=True)
        self.git("remote", "add", name, str(bare))
        self.git("push", "-q", name, "--all")
        self.git("remote", "set-head", name, "main")
        self.git("remote", "set-url", name, f"https://github.com/{slug}.git")
        return bare

    def push(self, branch: str, remote: str = "origin") -> None:
        """Update the remote-tracking ref as if `git push` had succeeded."""
        sha = self.git("rev-parse", branch)
        self.git("update-ref", f"refs/remotes/{remote}/{branch}", sha)


@pytest.fixture
def repo(tmp_path: Path) -> RepoBuilder:
    return RepoBuilder(tmp_path / "widgets")


class FakeGh(GhClient):
    """In-memory stand-in for `gh api`, recording every request."""

    def __init__(
        self,
        repo_path: Path,
        context: dict[str, Any],
        *,
        logins: dict[str, str | None] | None = None,
        compare: dict[str, str] | None = None,
        emails: list[dict[str, Any]] | GitHubError | None = None,
        not_on_github: set[str] | None = None,
    ):
        super().__init__(executable="gh")
        self.repo_path = repo_path
        self.context = context
        self.logins = logins or {}
        self.compare_status = compare or {}
        self.emails = emails
        self.not_on_github = not_on_github or set()
        self.calls: list[tuple[str, str, Any]] = []

    def _author(self, sha: str) -> str:
        return (
            subprocess.run(
                ["git", "-C", str(self.repo_path), "log", "-1", "--format=%ae", sha],
                capture_output=True,
                text=True,
                check=True,
            )
            .stdout.strip()
            .lower()
        )

    def graphql(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(("graphql", query, variables))
        if "viewer" in query:
            return self.context
        repo: dict[str, Any] = {}
        for alias, sha in re.findall(r'(c\d+): object\(oid: "([0-9a-f]+)"\)', query):
            email = self._author(sha)
            if email in self.not_on_github:
                repo[alias] = None
                continue
            login = self.logins.get(email)
            repo[alias] = {"author": {"user": {"login": login} if login else None}}
        return {"data": {"repository": repo}}

    def rest(self, path: str) -> Any:
        self.calls.append(("rest", path, None))
        if path == "user/emails":
            if isinstance(self.emails, GitHubError):
                raise self.emails
            if self.emails is None:
                raise GitHubError("scope", 'This API operation needs the "user" scope.')
            return self.emails
        if "/compare/" in path:
            sha = path.rsplit("...", 1)[1]
            status = self.compare_status.get(sha)
            if status is None:
                raise GitHubError("not_found", "Not Found (HTTP 404)")
            return {"status": status}
        if "/collaborators/" in path:
            raise GitHubError("forbidden", "Must have push access (HTTP 403)")
        raise GitHubError("not_found", f"unexpected path {path}")

    def sent_payloads(self) -> str:
        return json.dumps([c[1:] for c in self.calls])


class ExplodingGh(GhClient):
    """Fails the test if GitHub is contacted at all."""

    def __init__(self) -> None:
        super().__init__(executable="gh")

    def graphql(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        raise AssertionError("GitHub must not be contacted")

    def rest(self, path: str) -> Any:
        raise AssertionError("GitHub must not be contacted")


def run_scan(path: Path, gh: GhClient | None = None, **kwargs: Any) -> Report:
    options = ScanOptions(path=str(path), **kwargs)
    if gh is None:
        options.offline = True
        gh = ExplodingGh()
    return scan(options, git=Git(str(path)), gh_client=gh, now=NOW)


def finding(report: Report, rule_id: str) -> Finding:
    return next(f for f in report.findings if f.rule_id == rule_id)


def tree_digest(path: Path) -> str:
    """Hash every file under .git (names and contents) to prove nothing changed."""
    h = hashlib.sha256()
    git_dir = path / ".git"
    for p in sorted(git_dir.rglob("*")):
        if p.is_file():
            h.update(str(p.relative_to(git_dir)).encode())
            h.update(p.read_bytes())
    return h.hexdigest()
