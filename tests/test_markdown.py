"""Markdown output: snapshots, escaping, redaction and CLI behaviour.

Snapshots live in tests/snapshots/. Regenerate them after an intentional change with:

    UPDATE_SNAPSHOTS=1 pytest tests/test_markdown.py

and review the diff before committing.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

from contribution_doctor import __version__
from contribution_doctor.cli import main
from contribution_doctor.github import GhClient
from contribution_doctor.models import Confidence, Finding, Report, Status
from contribution_doctor.render import md_escape, render_json, render_markdown, render_text

from conftest import ME, NOW, RepoBuilder, run_scan

SNAPSHOTS = Path(__file__).parent / "snapshots"
TOKEN = "ghp_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"  # fake, built at runtime
PAT = "github_pat_" + "11ABCDEFG0123456789_abcdefghijklmnopqrstuvwxyz"


def _check_snapshot(name: str, actual: str) -> None:
    path = SNAPSHOTS / name
    if os.environ.get("UPDATE_SNAPSHOTS"):
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(actual.encode("utf-8"))
    assert path.exists(), f"missing snapshot {name}; run with UPDATE_SNAPSHOTS=1"
    expected = path.read_bytes().decode("utf-8").replace("\r\n", "\n")
    assert actual == expected, f"Markdown differs from snapshot {name}"


def _report(findings: list[Finding], **scan: object) -> Report:
    return Report(
        tool_version="0.0.0-test",
        generated_at=NOW.isoformat(),
        repository={"name": "widgets", "github": "alexdev/widgets"},
        profile={"login": "alexdev", "authenticated_as": "alexdev", "github_state": "offline"},
        scan={
            "mode": "offline",
            "history_limit": 500,
            "commits_scanned": 3,
            "history_truncated": False,
            "emails_masked": True,
            **scan,
        },
        findings=findings,
    )


def _f(rule: str, status: Status, desc: str, **kw: object) -> Finding:
    f = Finding(rule, status, desc, kw.pop("confidence", Confidence.LOW), **kw)  # type: ignore[arg-type]
    f.title = f"{rule.title()} title"
    f.docs = ["https://docs.github.com/en/example"]
    return f


# ------------------------------------------------------------------ snapshots


def test_snapshot_empty_findings() -> None:
    out = render_markdown(_report([], commits_scanned=0))
    assert "No checks produced findings." in out
    assert "### Findings" not in out
    _check_snapshot("empty_findings.md", out)


def test_snapshot_unknown_states() -> None:
    findings = [
        _f(
            "GH-AUTH",
            Status.SKIPPED,
            "Offline mode: GitHub was not contacted.",
            confidence=Confidence.HIGH,
        ),
        _f(
            "REPO-FORK",
            Status.UNKNOWN,
            "Fork status can only be confirmed by GitHub.",
            evidence=["GitHub data unavailable: --offline was given"],
            remediation=["Run the scan online with an authenticated `gh` to verify."],
        ),
        _f("REPO-VISIBILITY", Status.UNKNOWN, "Visibility can only be read from GitHub."),
        _f(
            "ACCOUNT-PRIVATE-CONTRIB",
            Status.UNKNOWN,
            "Whether private contributions are shown cannot be read through any API.",
        ),
        _f(
            "REPO-STATE",
            Status.PASS,
            "On branch 'main'.",
            verified=True,
            confidence=Confidence.HIGH,
        ),
    ]
    out = render_markdown(_report(findings))
    assert "No contribution visibility problems were found" in out
    assert "**Not verifiable here (UNKNOWN):** `REPO-FORK`, `REPO-VISIBILITY`, " in out
    assert out.count("<details>") == 3  # UNKNOWN findings get details, PASS/SKIPPED don't
    _check_snapshot("unknown_states.md", out)


def test_snapshot_unicode_and_hostile_markup() -> None:
    findings = [
        _f(
            "COMMIT-IDENTITIES",
            Status.WARN,
            "Jürgen Ölander 李雷 🧑‍💻 uses 2 emails | see ![x](https://evil.example/p.png)",
            evidence=[
                "Zoë <script>alert(1)</script> [click](javascript:alert(1)) *bold* _it_",
                "1. looks like a list\nsecond line\x1b[31m red ‮evil‬",
                "mention @octocat and #42, math $x$, ~~strike~~, &amp; entity",
            ],
            remediation=['Run `git config user.email "Zoë@例え.jp"` | then `git log`'],
        ),
        _f(
            "BRANCH-NON-DEFAULT",
            Status.FAIL,
            "Branch `feat/ü|x` and branch with odd ` backtick",
            verified=True,
            confidence=Confidence.HIGH,
        ),
    ]
    report = _report(findings)
    report.repository["name"] = "wïdgets <b>|</b>"
    out = render_markdown(report)
    for raw in ("<script>", "![x]", "[click](", "<b>", "\x1b", "‮"):
        assert raw not in out
    for kept in ("Jürgen Ölander 李雷 🧑‍💻", "例え", "Zoë"):
        assert kept in out
    _check_snapshot("unicode.md", out)


def test_snapshot_redaction(repo: RepoBuilder) -> None:
    secret_name = f"Alex {TOKEN}"
    repo.config("user.name", ME[0]).config("user.email", "alex@DESKTOP-7Q2X")
    repo.commit("one", author=(secret_name, "alex@DESKTOP-7Q2X"))
    repo.commit("two", author=("Alex Morgan", "alex.morgan@contoso-corp.fi"))
    repo.add_github_remote()
    repo.git(
        "remote",
        "set-url",
        "origin",
        f"https://x-access-token:{PAT}@github.com/alexdev/widgets.git",
    )
    report = run_scan(repo.path, user="alexdev")
    report.tool_version = "0.0.0-test"  # keep the snapshot stable across releases
    out = render_markdown(report)
    for secret in (
        TOKEN,
        PAT,
        "ghp_",
        "github_pat_",
        "DESKTOP-7Q2X",
        "contoso-corp",
        "alex.morgan@",
    ):
        assert secret not in out
    assert "Emails | masked" in out
    _check_snapshot("redaction.md", out)


# ------------------------------------------------------------------ properties


def test_markdown_is_deterministic(repo: RepoBuilder) -> None:
    repo.config("user.name", ME[0]).config("user.email", ME[1])
    repo.commit()
    first = run_scan(repo.path)
    second = run_scan(repo.path)
    second.generated_at = "1999-01-01T00:00:00+00:00"  # timestamps never reach Markdown
    assert render_markdown(first) == render_markdown(second)
    assert render_markdown(first, explain=True) == render_markdown(second, explain=True)
    assert NOW.isoformat()[:10] not in render_markdown(first).split("### Details")[0]


def test_show_emails_is_flagged(repo: RepoBuilder) -> None:
    repo.config("user.name", ME[0]).config("user.email", ME[1])
    repo.commit()
    out = render_markdown(run_scan(repo.path, show_emails=True))
    assert "shown in full" in out
    assert "alexmorgan" in out


def test_escape_neutralises_markup() -> None:
    assert md_escape("a|b") == "a\\|b"
    assert md_escape("![i](u)") == "\\!\\[i\\]\\(u\\)"
    assert md_escape("<img src=x>") == "\\<img src=x\\>"
    assert md_escape("line\nbreak\ttab") == "line break tab"
    # Secrets are scrubbed before escaping so "_" escaping cannot hide a token.
    assert "ghp" not in md_escape(TOKEN)


def test_every_table_row_has_four_cells() -> None:
    findings = [_f("X-RULE", Status.WARN, "a | b `c|d` e")]
    out = render_markdown(_report(findings))
    row = next(line for line in out.splitlines() if line.startswith("| **WARN**"))
    assert len(re.findall(r"(?<!\\)\|", row)) == 5


def test_explain_adds_why_and_passes() -> None:
    f = _f("REPO-STATE", Status.PASS, "fine", verified=True)
    f.explanation = "Because."
    assert "<details>" not in render_markdown(_report([f]))
    assert "**Why:** Because." in render_markdown(_report([f]), explain=True)


def test_other_formats_unchanged(repo: RepoBuilder) -> None:
    repo.config("user.name", ME[0]).config("user.email", ME[1])
    repo.commit()
    report = run_scan(repo.path)
    assert render_text(report).startswith(f"GitHub Contribution Doctor {__version__}")
    assert '"schema_version": 1' in render_json(report)


# ------------------------------------------------------------------ CLI


@pytest.fixture
def no_github(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_a: object, **_k: object) -> None:
        raise AssertionError("GitHub must not be contacted in offline mode")

    monkeypatch.setattr(GhClient, "_call", boom)
    monkeypatch.setattr(GhClient, "graphql", boom)
    monkeypatch.setattr(GhClient, "rest", boom)


@pytest.mark.usefixtures("no_github")
def test_cli_markdown_offline_ok(
    repo: RepoBuilder, capsysbinary: pytest.CaptureFixture[bytes]
) -> None:
    repo.config("user.name", "Zoë Ölander").config("user.email", ME[1])
    repo.commit(author=("Zoë Ölander", ME[1]))
    assert main(["scan", str(repo.path), "--offline", "--format", "markdown"]) == 0
    raw = capsysbinary.readouterr().out
    out = raw.decode("utf-8")  # always UTF-8, regardless of console code page
    assert out.startswith("## GitHub Contribution Doctor")
    assert b"\r\n" not in raw
    assert "\x1b[" not in out
    assert "alex@alexmorgan.dev" not in out


@pytest.mark.usefixtures("no_github")
def test_cli_markdown_exit_codes_match_text(
    repo: RepoBuilder, capsysbinary: pytest.CaptureFixture[bytes]
) -> None:
    repo.config("user.email", "alex@DESKTOP-1")
    repo.commit(author=("Alex", "alex@DESKTOP-1"))
    base = ["scan", str(repo.path), "--offline"]
    for extra in ([], ["--strict"]):
        assert main([*base, *extra, "--format", "markdown"]) == main([*base, *extra]) == 1
    assert b"COMMIT-EMAIL-UNLINKABLE" in capsysbinary.readouterr().out


def test_cli_markdown_strict_on_warnings(repo: RepoBuilder) -> None:
    repo.config("user.name", ME[0]).config("user.email", ME[1])
    repo.commit()  # no remote -> WARN
    base = ["scan", str(repo.path), "--offline", "--format", "markdown"]
    assert main(base) == 0
    assert main([*base, "--strict"]) == 1
