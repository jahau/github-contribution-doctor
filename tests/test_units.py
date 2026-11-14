"""Unit tests for pure helpers: privacy, email classification, parsing, gh client."""

from __future__ import annotations

import json
import subprocess
from typing import Any

import pytest

from contribution_doctor.emails import EmailKind, classify
from contribution_doctor.github import GhClient, GitHubContext, GitHubError, fetch_context
from contribution_doctor.gitio import Git, GitTimeout
from contribution_doctor.identity import (
    LIKELY,
    OTHER,
    UNKNOWN,
    YOURS,
    OwnershipHints,
    assign_ownership,
    build_identities,
)
from contribution_doctor.privacy import mask_email, redact_url, scrub_secrets
from contribution_doctor.repo import parse_log, parse_remote_url

# ------------------------------------------------------------------ privacy


@pytest.mark.parametrize(
    ("email", "expected"),
    [
        ("alex@alexmorgan.dev", "a***@a***.dev"),
        ("someone@gmail.com", "s***@gmail.com"),
        ("1234567+alexdev@users.noreply.github.com", "1234567+alexdev@users.noreply.github.com"),
        ("alex@DESKTOP-ABC123", "a***@DES***"),
        ("", ""),
    ],
)
def test_mask_email(email: str, expected: str) -> None:
    assert mask_email(email) == expected


def test_mask_email_show() -> None:
    assert mask_email("alex@alexmorgan.dev", show=True) == "alex@alexmorgan.dev"


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        (
            "https://x-access-token:ghp_abcdefghijklmnopqrstuvwxyz0123@github.com/o/r.git",
            "https://github.com/o/r.git",
        ),
        ("https://ghp_abcdefghijklmnopqrstuvwxyz0123@github.com/o/r", "https://github.com/o/r"),
        ("git@github.com:o/r.git", "git@github.com:o/r.git"),
        ("ssh://git@ssh.github.com:443/o/r.git", "ssh://git@ssh.github.com:443/o/r.git"),
        ("https://github.com/o/r.git", "https://github.com/o/r.git"),
    ],
)
def test_redact_url(url: str, expected: str) -> None:
    assert redact_url(url) == expected


def test_scrub_secrets() -> None:
    text = "token gho_1234567890abcdefghijXYZ and github_pat_11ABCDEFG0123456789_abcdefghijkl"
    out = scrub_secrets(text)
    assert "gho_" not in out
    assert "github_pat_" not in out
    assert scrub_secrets("see https://user:hunter2@example.com/x") == (
        "see https://[REDACTED]@example.com/x"
    )


# ------------------------------------------------------------------ emails


@pytest.mark.parametrize(
    ("email", "kind"),
    [
        ("alex@alexmorgan.dev", EmailKind.REGULAR),
        ("1234567+alexdev@users.noreply.github.com", EmailKind.NOREPLY),
        ("alexdev@users.noreply.github.com", EmailKind.NOREPLY),
        ("41898282+github-actions[bot]@users.noreply.github.com", EmailKind.BOT),
        ("alex@DESKTOP-ABC123", EmailKind.UNLINKABLE),
        ("alex@laptop.local", EmailKind.UNLINKABLE),
        ("root@localhost", EmailKind.UNLINKABLE),
        ("dev@example.com", EmailKind.UNLINKABLE),
        ("(none)", EmailKind.UNLINKABLE),
        ("", EmailKind.UNLINKABLE),
        ("not-an-email", EmailKind.UNLINKABLE),
        ("me@192.168.1.10", EmailKind.UNLINKABLE),
    ],
)
def test_classify(email: str, kind: EmailKind) -> None:
    assert classify(email).kind is kind


def test_classify_noreply_parts() -> None:
    info = classify("1234567+AlexDev@users.noreply.github.com")
    assert info.noreply_login == "alexdev"
    assert info.noreply_id == 1234567


# ------------------------------------------------------------------ remote parsing


@pytest.mark.parametrize(
    ("url", "slug", "host"),
    [
        ("https://github.com/alexdev/widgets.git", "alexdev/widgets", "github.com"),
        ("https://github.com/alexdev/widgets", "alexdev/widgets", "github.com"),
        ("git@github.com:alexdev/widgets.git", "alexdev/widgets", "github.com"),
        ("ssh://git@ssh.github.com:443/alexdev/widgets.git", "alexdev/widgets", "ssh.github.com"),
        ("https://tok@github.com/alexdev/widgets.git", "alexdev/widgets", "github.com"),
        ("https://gitlab.com/alexdev/widgets.git", None, "gitlab.com"),
        ("git@ghe.corp.example:team/widgets.git", None, "ghe.corp.example"),
        (r"C:\repos\widgets.git", None, None),
        ("/srv/git/widgets.git", None, None),
        ("file:///srv/git/widgets.git", None, None),
        ("https://github.com/alexdev/widgets/tree/main", None, "github.com"),
    ],
)
def test_parse_remote_url(url: str, slug: str | None, host: str | None) -> None:
    remote = parse_remote_url("origin", url)
    assert remote.slug == slug
    assert remote.host == host
    assert "tok@" not in remote.url


def test_parse_log_with_coauthors_and_separators() -> None:
    raw = (
        "a" * 40 + "\x1fAlice\x1fAlice@Acme.dev\x1f2026-05-01T10:00:00+03:00\x1f"
        "Bob\x1fbob@acme.dev\x1f2026-05-01T11:00:00Z\x1f"
        "Carol <carol@acme.dev>\x1dDan <DAN@acme.dev>\x1e\n"
        + "b"
        * 40
        + "\x1fAlice\x1falice@acme.dev\x1f2026-05-02T10:00:00+00:00\x1f"
        "Alice\x1falice@acme.dev\x1f2026-05-02T10:00:00+00:00\x1f\x1e\n"
    )
    commits = parse_log(raw)
    assert len(commits) == 2
    assert commits[0].author_email == "alice@acme.dev"
    assert commits[0].committer_email == "bob@acme.dev"
    assert commits[0].coauthors == (("Carol", "carol@acme.dev"), ("Dan", "dan@acme.dev"))
    assert commits[1].coauthors == ()


# ------------------------------------------------------------------ identity ownership


def test_ownership_levels() -> None:
    raw = ""
    rows = [
        ("Alex Morgan", "alex@alexmorgan.dev"),
        ("Alex Morgan", "alex@work.fi"),
        ("alexdev", "1234567+alexdev@users.noreply.github.com"),
        ("Someone", "88+octocat@users.noreply.github.com"),
        ("Bot", "41898282+github-actions[bot]@users.noreply.github.com"),
        ("Alice", "alice@acme.dev"),
    ]
    for i, (name, email) in enumerate(rows):
        raw += (
            f"{i:040d}\x1f{name}\x1f{email}\x1f2026-05-01T10:00:00Z\x1f"
            f"{name}\x1f{email}\x1f2026-05-01T10:00:00Z\x1f\x1e"
        )
    idents = build_identities(parse_log(raw))
    assign_ownership(
        idents,
        OwnershipHints(
            target_login="alexdev",
            config_email="alex@alexmorgan.dev",
            config_name="Alex Morgan",
        ),
    )
    assert idents["alex@alexmorgan.dev"].ownership == LIKELY
    assert idents["alex@work.fi"].ownership == LIKELY  # same name, different email
    assert idents["1234567+alexdev@users.noreply.github.com"].ownership == YOURS
    assert idents["88+octocat@users.noreply.github.com"].ownership == OTHER
    assert idents["41898282+github-actions[bot]@users.noreply.github.com"].ownership == OTHER
    assert idents["alice@acme.dev"].ownership == UNKNOWN

    # GitHub's answer beats local guesses.
    idents["alex@work.fi"].github_login = "alexdev-work"
    assign_ownership(idents, OwnershipHints(target_login="alexdev", config_name="Alex Morgan"))
    assert idents["alex@work.fi"].ownership == OTHER
    assert idents["alex@work.fi"].local_signal


# ------------------------------------------------------------------ git runner


def test_git_rejects_write_commands(tmp_path: Any) -> None:
    git = Git(str(tmp_path))
    for args in (
        ("commit", "-m", "x"),
        ("push",),
        ("remote", "add", "x", "y"),
        ("config", "user.email", "x@y.z"),
        ("fetch",),
    ):
        with pytest.raises(ValueError, match=r"not allowed|not read-only|only allowed"):
            git.run(*args)


def test_git_timeout(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*a: Any, **k: Any) -> Any:
        raise subprocess.TimeoutExpired(cmd="git", timeout=1)

    git = Git(str(tmp_path), timeout=1)
    monkeypatch.setattr(subprocess, "run", boom)
    with pytest.raises(GitTimeout):
        git.run("rev-parse", "--show-toplevel")


def test_git_hardening_flags(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    def fake(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        seen["cmd"], seen["env"] = cmd, kwargs["env"]
        return subprocess.CompletedProcess(cmd, 0, b"ok\n", b"")

    monkeypatch.setenv("GIT_DIR", "/elsewhere")
    git = Git(str(tmp_path))
    monkeypatch.setattr(subprocess, "run", fake)
    assert git.out("rev-parse", "HEAD") == "ok"
    assert "--no-pager" in seen["cmd"]
    assert "log.showSignature=false" in seen["cmd"]
    assert "core.fsmonitor=false" in seen["cmd"]
    assert "GIT_DIR" not in seen["env"]
    assert seen["env"]["GIT_TERMINAL_PROMPT"] == "0"


# ------------------------------------------------------------------ gh client


def _runner(rc: int, stdout: str = "", stderr: str = "") -> Any:
    calls: list[dict[str, Any]] = []

    def run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        calls.append({"cmd": cmd, **kwargs})
        return subprocess.CompletedProcess(cmd, rc, stdout.encode(), stderr.encode())

    run.calls = calls  # type: ignore[attr-defined]
    return run


@pytest.mark.parametrize(
    ("rc", "stderr", "kind"),
    [
        (4, "To get started with GitHub CLI, please run:  gh auth login", "not_authenticated"),
        (1, "gh: Bad credentials (HTTP 401)", "not_authenticated"),
        (1, "gh: API rate limit exceeded for user ID 1. (HTTP 403)", "rate_limited"),
        (1, "gh: Not Found (HTTP 404)", "not_found"),
        (1, "gh: Resource not accessible by integration (HTTP 403)", "forbidden"),
        (
            1,
            "error connecting to api.github.com\ndial tcp: lookup api.github.com: no such host",
            "network",
        ),
        (1, 'gh: This API operation needs the "user" scope.', "scope"),
    ],
)
def test_gh_error_classification(rc: int, stderr: str, kind: str) -> None:
    client = GhClient(executable="gh", runner=_runner(rc, "", stderr))
    with pytest.raises(GitHubError) as exc:
        client.rest("user")
    assert exc.value.kind == kind


def test_gh_not_installed() -> None:
    ctx = fetch_context(
        GhClient(executable=None, runner=_runner(0)), user=None, owner="o", name="r"
    )
    # executable=None falls back to shutil.which; force the not-installed path:
    client = GhClient(runner=_runner(0))
    client.executable = None
    ctx = fetch_context(client, user=None, owner="o", name="r")
    assert ctx.state == "not_installed"


def test_gh_never_leaks_tokens_in_errors() -> None:
    client = GhClient(
        executable="gh",
        runner=_runner(1, "", "unexpected failure for token ghp_abcdefghijklmnopqrstuvwxyz012345"),
    )
    with pytest.raises(GitHubError) as exc:
        client.rest("user")
    assert "ghp_" not in str(exc.value)


def test_gh_graphql_partial_data_and_env() -> None:
    body = {
        "data": {"viewer": {"login": "alexdev"}, "repository": None},
        "errors": [{"type": "NOT_FOUND", "path": ["repository"], "message": "Could not resolve"}],
    }
    run = _runner(1, json.dumps(body), "gh: Could not resolve to a Repository")
    ctx = fetch_context(GhClient(executable="gh", runner=run), user=None, owner="o", name="r")
    assert ctx.state == "ok"
    assert ctx.viewer_login == "alexdev"
    assert ctx.repo is None
    assert ctx.repo_error == "Could not resolve"
    call = run.calls[0]
    assert call["cmd"][:4] == ["gh", "api", "--hostname", "github.com"]
    assert call["env"]["GH_PROMPT_DISABLED"] == "1"
    assert "GH_DEBUG" not in call["env"]


def test_gh_invalid_user_rejected_before_network() -> None:
    run = _runner(0, "{}")
    ctx = fetch_context(
        GhClient(executable="gh", runner=run), user="bad name!", owner=None, name=None
    )
    assert ctx.state == "error"
    assert run.calls == []


def test_context_is_self() -> None:
    assert GitHubContext("ok", viewer_login="AlexDev", target_login="alexdev").is_self
    assert not GitHubContext("ok", viewer_login="alexdev", target_login="octo").is_self
