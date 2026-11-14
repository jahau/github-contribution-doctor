"""CLI behaviour: exit codes, legacy interface, output formats."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from contribution_doctor.catalog import RULES
from contribution_doctor.cli import _translate_legacy, main

from conftest import ME, RepoBuilder

ROOT = Path(__file__).resolve().parent.parent


def test_legacy_translation() -> None:
    assert _translate_legacy(["--repo", "x"]) == ["scan", "x"]
    assert _translate_legacy(["--repo=x", "--offline"]) == ["scan", "x", "--offline"]
    assert _translate_legacy([]) == ["scan"]
    assert _translate_legacy(["scan", "."]) == ["scan", "."]
    assert _translate_legacy(["--version"]) == ["--version"]


def test_exit_ok_and_json(repo: RepoBuilder, capsys: pytest.CaptureFixture[str]) -> None:
    repo.config("user.name", ME[0]).config("user.email", ME[1])
    repo.commit()
    code = main(["scan", str(repo.path), "--offline", "--format", "json"])
    data = json.loads(capsys.readouterr().out)
    assert code == 0
    assert data["scan"]["mode"] == "offline"


def test_exit_one_on_fail(repo: RepoBuilder, capsys: pytest.CaptureFixture[str]) -> None:
    bad = ("Alex", "alex@DESKTOP-1")
    repo.config("user.email", bad[1])
    repo.commit(author=bad)
    assert main(["scan", str(repo.path), "--offline"]) == 1
    assert "COMMIT-EMAIL-UNLINKABLE" in capsys.readouterr().out


def test_strict_turns_warnings_into_failure(repo: RepoBuilder) -> None:
    repo.config("user.name", ME[0]).config("user.email", ME[1])
    repo.commit()  # no remote -> WARN
    assert main(["scan", str(repo.path), "--offline"]) == 0
    assert main(["scan", str(repo.path), "--offline", "--strict"]) == 1


def test_exit_three_for_non_repository(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["scan", str(tmp_path), "--offline"]) == 3
    assert "not a Git repository" in capsys.readouterr().err
    assert main(["scan", str(tmp_path / "missing")]) == 3


def test_usage_errors_exit_two(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["scan", ".", "--history", "0"]) == 2
    assert main(["scan", ".", "--user", "not a login"]) == 2
    assert main(["scan", ".", "--format", "xml"]) == 2


def test_explain_includes_background(repo: RepoBuilder, capsys: pytest.CaptureFixture[str]) -> None:
    repo.config("user.name", ME[0]).config("user.email", ME[1])
    repo.commit()
    main(["scan", str(repo.path), "--offline", "--explain", "--color", "never"])
    out = capsys.readouterr().out
    assert "Why:" in out
    assert "docs.github.com" in out
    assert "\x1b[" not in out


def test_rules_command(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["rules"]) == 0
    out = capsys.readouterr().out
    for rule_id in RULES:
        assert rule_id in out


def test_doctor_py_compat(repo: RepoBuilder) -> None:
    repo.config("user.name", ME[0]).config("user.email", ME[1])
    repo.commit()
    proc = subprocess.run(
        [sys.executable, str(ROOT / "doctor.py"), "--repo", str(repo.path), "--offline"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert "GitHub Contribution Doctor" in proc.stdout


def test_module_entry_point() -> None:
    proc = subprocess.run(
        [sys.executable, "-m", "contribution_doctor", "--version"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0
    assert "0.2.0" in proc.stdout
