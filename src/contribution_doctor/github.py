"""Optional GitHub integration through the GitHub CLI (``gh``).

Design rules:

* The token is never requested, read or printed; ``gh`` handles authentication.
* Only commit SHAs, repository names and logins are sent to GitHub. Local commit email
  addresses are never sent. The authenticated user's own email list may be downloaded and
  compared locally.
* Every failure (missing gh, no login, rate limit, missing permission, offline) degrades
  to UNKNOWN/SKIPPED findings instead of crashing.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote

from contribution_doctor.privacy import scrub_secrets
from contribution_doctor.repo import is_sha

HOST = "github.com"
DEFAULT_TIMEOUT = 20.0
MAX_ATTRIBUTION_LOOKUPS = 25
MAX_COMPARE_LOOKUPS = 5
_LOGIN = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})$")
_NAME = re.compile(r"^[A-Za-z0-9_.-]{1,100}$")


class GitHubError(Exception):
    """A gh call failed. ``kind`` is a stable machine-readable category."""

    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind  # not_installed|not_authenticated|rate_limited|not_found|
        #                   forbidden|scope|network|timeout|error


Runner = Callable[..., "subprocess.CompletedProcess[bytes]"]


def valid_login(login: str) -> bool:
    return bool(_LOGIN.match(login)) and "--" not in login


def _classify(returncode: int, stderr: str, body: Any) -> GitHubError:
    text = stderr.lower()
    msg = scrub_secrets(stderr.strip().splitlines()[-1] if stderr.strip() else "gh failed")
    if (
        returncode == 4
        or "gh auth login" in text
        or "http 401" in text
        or "bad credentials" in text
    ):
        return GitHubError("not_authenticated", "gh is not authenticated (run `gh auth login`)")
    if "rate limit" in text or "http 429" in text:
        return GitHubError("rate_limited", "GitHub API rate limit exceeded; try again later")
    if "needs the" in text and "scope" in text:
        return GitHubError("scope", msg)
    if "http 404" in text or "could not resolve to" in text:
        return GitHubError("not_found", msg)
    if "http 403" in text or "must have" in text or "resource not accessible" in text:
        return GitHubError("forbidden", msg)
    network_markers = (
        "error connecting",
        "dial tcp",
        "no such host",
        "could not resolve host",
        "network is unreachable",
        "connection refused",
        "tls handshake",
        "i/o timeout",
    )
    if any(m in text for m in network_markers):
        return GitHubError("network", "could not reach api.github.com (offline?)")
    if isinstance(body, dict) and body.get("message"):
        return GitHubError("error", scrub_secrets(str(body["message"])))
    return GitHubError("error", msg)


class GhClient:
    """Thin wrapper around ``gh api``."""

    def __init__(
        self,
        *,
        timeout: float = DEFAULT_TIMEOUT,
        executable: str | None = None,
        runner: Runner | None = None,
    ) -> None:
        self.executable = executable or shutil.which("gh")
        self.timeout = timeout
        self._runner: Runner = runner or subprocess.run

    @property
    def installed(self) -> bool:
        return self.executable is not None

    def _env(self) -> dict[str, str]:
        env = {k: v for k, v in os.environ.items() if k not in ("GH_DEBUG", "DEBUG", "GH_HOST")}
        env.update(
            {
                "GH_PROMPT_DISABLED": "1",
                "GH_NO_UPDATE_NOTIFIER": "1",
                "GH_SPINNER_DISABLED": "1",
                "GH_PAGER": "cat",
                "NO_COLOR": "1",
                "CLICOLOR": "0",
            }
        )
        return env

    def _call(self, args: Sequence[str], stdin: bytes | None = None) -> Any:
        if not self.executable:
            raise GitHubError("not_installed", "GitHub CLI (gh) is not installed")
        cmd = [self.executable, "api", "--hostname", HOST, *args]
        try:
            proc = self._runner(
                cmd,
                input=stdin if stdin is not None else b"",
                capture_output=True,
                timeout=self.timeout,
                env=self._env(),
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise GitHubError("timeout", f"gh timed out after {self.timeout:g}s") from exc
        except OSError as exc:
            raise GitHubError("not_installed", f"could not run gh: {exc}") from exc
        stdout = proc.stdout.decode("utf-8", errors="replace").strip()
        stderr = proc.stderr.decode("utf-8", errors="replace")
        body: Any = None
        if stdout:
            try:
                body = json.loads(stdout)
            except json.JSONDecodeError:
                body = None
        if proc.returncode != 0:
            # GraphQL partial errors still return useful data alongside "errors".
            if isinstance(body, dict) and "data" in body and body["data"] is not None:
                return body
            raise _classify(proc.returncode, stderr, body)
        return body

    def graphql(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        payload = json.dumps({"query": query, "variables": variables}).encode("utf-8")
        body = self._call(["graphql", "--input", "-"], stdin=payload)
        if not isinstance(body, dict):
            raise GitHubError("error", "unexpected GraphQL response")
        errors = body.get("errors") or []
        for err in errors:
            if isinstance(err, dict) and err.get("type") == "RATE_LIMITED":
                raise GitHubError("rate_limited", "GitHub GraphQL rate limit exceeded")
        return body

    def rest(self, path: str) -> Any:
        return self._call([path])


@dataclass
class RepoInfo:
    name_with_owner: str
    owner: str
    owner_type: str  # "User" or "Organization"
    is_fork: bool
    parent: str | None
    visibility: str  # PUBLIC | PRIVATE | INTERNAL
    default_branch: str | None
    viewer_has_starred: bool | None
    viewer_permission: str | None


@dataclass
class Attribution:
    sha: str
    found: bool
    author_login: str | None = None


@dataclass
class GitHubContext:
    """Everything learned from GitHub. ``state`` explains why data may be missing."""

    state: str  # offline | not_installed | not_authenticated | ok | error
    message: str = ""
    viewer_login: str | None = None
    target_login: str | None = None
    target_id: int | None = None
    target_exists: bool | None = None
    target_error: str | None = None
    repo: RepoInfo | None = None
    repo_error: str | None = None
    repo_error_kind: str | None = None
    account_emails: list[tuple[str, bool]] | None = None  # (email, verified)
    account_emails_error: str | None = None
    attribution: dict[str, Attribution] = field(default_factory=dict)
    attribution_error: str | None = None
    compare: dict[str, str] = field(default_factory=dict)  # sha -> ahead|behind|identical|...
    collaborator: bool | None = None
    rate_limited: bool = False

    @property
    def online(self) -> bool:
        return self.state == "ok"

    @property
    def is_self(self) -> bool:
        return bool(
            self.viewer_login
            and self.target_login
            and self.viewer_login.lower() == self.target_login.lower()
        )


_MAIN_QUERY = """
query($owner: String!, $name: String!, $login: String!, $hasRepo: Boolean!, $hasLogin: Boolean!) {
  viewer { login }
  user(login: $login) @include(if: $hasLogin) { login databaseId }
  repository(owner: $owner, name: $name) @include(if: $hasRepo) {
    nameWithOwner isFork visibility viewerHasStarred viewerPermission
    defaultBranchRef { name }
    owner { __typename login }
    parent { nameWithOwner }
  }
}
"""


def _note(ctx: GitHubContext, err: GitHubError) -> str:
    if err.kind == "rate_limited":
        ctx.rate_limited = True
    return str(err)


def fetch_context(
    client: GhClient,
    *,
    user: str | None,
    owner: str | None,
    name: str | None,
) -> GitHubContext:
    """Query viewer, target user and repository metadata in one GraphQL call."""
    if not client.installed:
        return GitHubContext("not_installed", "GitHub CLI (gh) is not installed")
    if user and not valid_login(user):
        return GitHubContext("error", f"'{user}' is not a valid GitHub username")
    has_repo = bool(owner and name and _NAME.match(owner) and _NAME.match(name))
    variables = {
        "owner": owner or "",
        "name": name or "",
        "login": user or "",
        "hasRepo": has_repo,
        "hasLogin": bool(user),
    }
    try:
        body = client.graphql(_MAIN_QUERY, variables)
    except GitHubError as err:
        state = err.kind if err.kind in ("not_installed", "not_authenticated") else "error"
        ctx = GitHubContext(state, str(err))
        ctx.rate_limited = err.kind == "rate_limited"
        return ctx

    data = body.get("data") or {}
    errors = [e for e in body.get("errors") or [] if isinstance(e, dict)]
    viewer = (data.get("viewer") or {}).get("login")
    ctx = GitHubContext("ok", viewer_login=viewer)

    if user:
        u = data.get("user")
        if u:
            ctx.target_login, ctx.target_id, ctx.target_exists = (
                u["login"],
                u.get("databaseId"),
                True,
            )
        else:
            ctx.target_login, ctx.target_exists = user, False
            ctx.target_error = _path_error(errors, "user") or f"user '{user}' not found"
    else:
        ctx.target_login, ctx.target_exists = viewer, bool(viewer)

    if has_repo:
        r = data.get("repository")
        if r:
            ctx.repo = RepoInfo(
                name_with_owner=r["nameWithOwner"],
                owner=r["owner"]["login"],
                owner_type=r["owner"]["__typename"],
                is_fork=bool(r.get("isFork")),
                parent=(r.get("parent") or {}).get("nameWithOwner"),
                visibility=str(r.get("visibility") or "UNKNOWN"),
                default_branch=(r.get("defaultBranchRef") or {}).get("name"),
                viewer_has_starred=r.get("viewerHasStarred"),
                viewer_permission=r.get("viewerPermission"),
            )
        else:
            ctx.repo_error = _path_error(errors, "repository") or "repository not accessible"
            ctx.repo_error_kind = "not_found"
    return ctx


def _path_error(errors: list[dict[str, Any]], key: str) -> str | None:
    for err in errors:
        if key in (err.get("path") or []):
            return scrub_secrets(str(err.get("message", "")))
    return None


def fetch_attribution(client: GhClient, ctx: GitHubContext, shas: Sequence[str]) -> None:
    """Ask GitHub which account each commit is attributed to. Sends only SHAs."""
    if not (ctx.online and ctx.repo):
        return
    wanted = [s for s in dict.fromkeys(shas) if is_sha(s)][:MAX_ATTRIBUTION_LOOKUPS]
    if not wanted:
        return
    owner, name = ctx.repo.name_with_owner.split("/", 1)
    fields = "\n".join(
        f'c{i}: object(oid: "{sha}") {{ ... on Commit {{ author {{ user {{ login }} }} }} }}'
        for i, sha in enumerate(wanted)
    )
    query = (
        "query($owner: String!, $name: String!) {"
        f" repository(owner: $owner, name: $name) {{ {fields} }} }}"
    )
    try:
        body = client.graphql(query, {"owner": owner, "name": name})
    except GitHubError as err:
        ctx.attribution_error = _note(ctx, err)
        return
    repo = (body.get("data") or {}).get("repository") or {}
    for i, sha in enumerate(wanted):
        obj = repo.get(f"c{i}")
        if not obj:
            ctx.attribution[sha] = Attribution(sha, found=False)
            continue
        user = ((obj.get("author") or {}).get("user")) or {}
        ctx.attribution[sha] = Attribution(sha, found=True, author_login=user.get("login"))


def fetch_compare(
    client: GhClient, ctx: GitHubContext, shas: Sequence[str], default_branch: str
) -> None:
    """Check on GitHub whether branch tips are already contained in the default branch."""
    if not (ctx.online and ctx.repo) or not _NAME.match(default_branch.replace("/", "_")):
        return
    for sha in [s for s in dict.fromkeys(shas) if is_sha(s)][:MAX_COMPARE_LOOKUPS]:
        path = f"repos/{ctx.repo.name_with_owner}/compare/{quote(default_branch, safe='')}...{sha}"
        try:
            body = client.rest(path)
        except GitHubError as err:
            ctx.compare[sha] = "not_found" if err.kind == "not_found" else "error"
            if err.kind == "rate_limited":
                ctx.rate_limited = True
                return
            continue
        status = body.get("status") if isinstance(body, dict) else None
        ctx.compare[sha] = str(status or "error")


def fetch_account_emails(client: GhClient, ctx: GitHubContext) -> None:
    """Download the authenticated user's own emails (needs the 'user' scope)."""
    if not (ctx.online and ctx.is_self):
        return
    try:
        body = client.rest("user/emails")
    except GitHubError as err:
        if err.kind in ("scope", "not_found", "forbidden"):
            ctx.account_emails_error = (
                "token lacks the 'user' scope; run `gh auth refresh -h github.com -s user` "
                "to allow this check"
            )
        else:
            ctx.account_emails_error = _note(ctx, err)
        return
    if isinstance(body, list):
        ctx.account_emails = [
            (str(e.get("email", "")).lower(), bool(e.get("verified")))
            for e in body
            if isinstance(e, dict)
        ]


def fetch_collaborator(client: GhClient, ctx: GitHubContext) -> None:
    if not (ctx.online and ctx.repo and ctx.target_login and valid_login(ctx.target_login)):
        return
    try:
        client.rest(f"repos/{ctx.repo.name_with_owner}/collaborators/{ctx.target_login}")
        ctx.collaborator = True
    except GitHubError as err:
        # 404 can mean "not a collaborator"; 403 means we may not ask. Both stay unknown
        # unless the answer is unambiguous.
        if err.kind == "not_found" and ctx.repo.viewer_permission in ("ADMIN", "MAINTAIN", "WRITE"):
            ctx.collaborator = False
        if err.kind == "rate_limited":
            ctx.rate_limited = True
