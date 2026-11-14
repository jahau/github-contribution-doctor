"""Integration tests: real Git repositories, fake GitHub responses."""

from __future__ import annotations

import json
import subprocess
from datetime import timedelta
from pathlib import Path

from contribution_doctor.github import GitHubError
from contribution_doctor.models import Status
from contribution_doctor.render import render_json, render_text

from conftest import (
    ME,
    NOW,
    FakeGh,
    RepoBuilder,
    finding,
    load_fixture,
    run_scan,
    tree_digest,
)

NOREPLY = "1234567+alexdev@users.noreply.github.com"
WORK = ("Alex Morgan", "alex.morgan@contoso-corp.fi")
ALICE = ("Alice Smith", "alice@acme.dev")


def _mine(repo: RepoBuilder) -> RepoBuilder:
    return repo.config("user.name", ME[0]).config("user.email", ME[1])


# ------------------------------------------------------------------ repository states


def test_empty_repository(repo: RepoBuilder) -> None:
    report = run_scan(repo.path)
    assert finding(report, "REPO-STATE").status is Status.WARN
    for rid in ("COMMIT-IDENTITIES", "BRANCH-NON-DEFAULT", "COMMIT-AUTHORSHIP"):
        assert finding(report, rid).status is Status.SKIPPED
    assert report.scan["commits_scanned"] == 0


def test_detached_head(repo: RepoBuilder) -> None:
    _mine(repo)
    first = repo.commit("one")
    repo.commit("two")
    repo.git("checkout", "-q", "--detach", first)
    report = run_scan(repo.path)
    f = finding(report, "REPO-STATE")
    assert f.status is Status.WARN
    assert f.verified
    assert "detached" in f.description


def test_shallow_clone(repo: RepoBuilder, tmp_path: Path) -> None:
    _mine(repo)
    for i in range(3):
        repo.commit(f"c{i}")
    clone = tmp_path / "shallow"
    subprocess.run(
        ["git", "clone", "-q", "--depth", "1", repo.path.resolve().as_uri(), str(clone)],
        check=True,
    )
    report = run_scan(clone)
    assert finding(report, "REPO-SHALLOW").status is Status.WARN
    assert report.scan["commits_scanned"] == 1


def test_missing_remote(repo: RepoBuilder) -> None:
    _mine(repo).commit()
    report = run_scan(repo.path)
    assert finding(report, "REMOTE-GITHUB").status is Status.WARN
    assert finding(report, "BRANCH-UNPUSHED").status is Status.SKIPPED
    assert finding(report, "REPO-FORK").status is Status.SKIPPED


def test_non_github_remote(repo: RepoBuilder) -> None:
    _mine(repo).commit()
    repo.git("remote", "add", "origin", "git@gitlab.com:alexdev/widgets.git")
    f = finding(run_scan(repo.path), "REMOTE-GITHUB")
    assert f.status is Status.WARN
    assert "gitlab.com" in f.description


# ------------------------------------------------------------------ email scenarios


def test_missing_email_hostname_fallback(repo: RepoBuilder) -> None:
    """Git configured without user.email guessed an address from the machine name."""
    bad = ("Alex Morgan", "alex@DESKTOP-7Q2K9LM")
    repo.config("user.name", bad[0]).config("user.email", bad[1])
    repo.commit("first", author=bad)
    repo.commit("second", author=bad)
    report = run_scan(repo.path)
    unlinkable = finding(report, "COMMIT-EMAIL-UNLINKABLE")
    assert unlinkable.status is Status.FAIL
    assert unlinkable.verified
    assert "2 commits" in unlinkable.description
    assert finding(report, "CONFIG-EMAIL").status is Status.FAIL
    # Masked by default: the full hostname is not shown.
    assert "DESKTOP-7Q2K9LM" not in render_text(report)


def test_user_email_not_set(repo: RepoBuilder) -> None:
    repo.commit(author=ALICE)
    f = finding(run_scan(repo.path), "CONFIG-EMAIL")
    assert f.status is Status.WARN
    assert "not set" in f.description


def test_other_peoples_bad_emails_are_not_your_failure(repo: RepoBuilder) -> None:
    _mine(repo).commit()
    repo.commit(author=("Build Box", "builder@ci-runner"))
    f = finding(run_scan(repo.path), "COMMIT-EMAIL-UNLINKABLE")
    assert f.status is Status.PASS
    assert any("other identity" in e for e in f.evidence)


def test_multi_account_offline(repo: RepoBuilder) -> None:
    _mine(repo)
    repo.commit(author=ME)
    repo.commit(author=WORK)
    repo.commit(author=WORK)
    repo.commit(author=ALICE)
    report = run_scan(repo.path, user="alexdev")
    f = finding(report, "COMMIT-IDENTITIES")
    assert f.status is Status.WARN
    assert "2 different author emails" in f.description
    assert not f.verified
    assert finding(report, "COMMIT-ATTRIBUTION").status is Status.SKIPPED  # no github remote


def test_multi_account_online_attribution(repo: RepoBuilder) -> None:
    _mine(repo)
    repo.commit(author=ME)
    repo.commit(author=WORK)
    repo.commit(author=ALICE)
    repo.add_github_remote()
    gh = FakeGh(
        repo.path,
        load_fixture("gh_context_owner.json"),
        logins={ME[1]: "alexdev", WORK[1]: "alexmorgan-work", ALICE[1]: "alice"},
    )
    report = run_scan(repo.path, gh)
    att = finding(report, "COMMIT-ATTRIBUTION")
    assert att.status is Status.FAIL
    assert att.verified
    assert any("@alexmorgan-work" in e for e in att.evidence)
    assert not any("alice" in e.lower() for e in att.evidence)  # other people are not judged
    assert finding(report, "CONFIG-EMAIL").status is Status.PASS


def test_unlinked_email_online(repo: RepoBuilder) -> None:
    _mine(repo).commit()
    repo.add_github_remote()
    gh = FakeGh(repo.path, load_fixture("gh_context_owner.json"), logins={ME[1]: None})
    report = run_scan(repo.path, gh)
    assert finding(report, "COMMIT-ATTRIBUTION").status is Status.FAIL
    assert finding(report, "CONFIG-EMAIL").status is Status.FAIL


def test_noreply_identity(repo: RepoBuilder) -> None:
    repo.config("user.name", ME[0]).config("user.email", NOREPLY)
    repo.commit(author=(ME[0], NOREPLY))
    report = run_scan(repo.path, user="alexdev")
    assert finding(report, "CONFIG-EMAIL").status is Status.PASS
    assert NOREPLY in render_json(report)  # noreply addresses are public by design


def test_account_emails_compared_locally(repo: RepoBuilder) -> None:
    _mine(repo)
    repo.commit(author=ME)
    old = ("Alex Morgan", "a.morgan@old-employer.fi")
    repo.commit(author=old)
    repo.add_github_remote()
    gh = FakeGh(
        repo.path, load_fixture("gh_context_owner.json"), emails=load_fixture("gh_user_emails.json")
    )
    report = run_scan(repo.path, gh)
    f = finding(report, "ACCOUNT-EMAILS")
    assert f.status is Status.FAIL
    assert any("unverified" in e for e in f.evidence)
    # Local commit emails are never sent to GitHub.
    payload = gh.sent_payloads()
    assert ME[1] not in payload
    assert old[1] not in payload


def test_account_emails_scope_missing_is_unknown(repo: RepoBuilder) -> None:
    _mine(repo).commit()
    repo.add_github_remote()
    gh = FakeGh(repo.path, load_fixture("gh_context_owner.json"))
    f = finding(run_scan(repo.path, gh), "ACCOUNT-EMAILS")
    assert f.status is Status.UNKNOWN
    assert "scope" in " ".join(f.evidence)


def test_other_user_private_data_not_assumed(repo: RepoBuilder) -> None:
    repo.config("user.name", "Octo Dev").config("user.email", "octo@acme.dev")
    repo.commit(author=("Octo Dev", "octo@acme.dev"))
    repo.add_github_remote("acme/widgets")
    repo.git("branch", "-m", "main", "trunk")
    gh = FakeGh(
        repo.path,
        load_fixture("gh_context_private_org.json"),
        emails=load_fixture("gh_user_emails.json"),
    )
    report = run_scan(repo.path, gh, user="octo-dev")
    assert finding(report, "ACCOUNT-EMAILS").status is Status.SKIPPED
    assert not any(c[1] == "user/emails" for c in gh.calls)
    assert finding(report, "REPO-VISIBILITY").status is Status.WARN
    assert finding(report, "ACCOUNT-PRIVATE-CONTRIB").status is Status.UNKNOWN
    assert finding(report, "REPO-OWNERSHIP").status is Status.UNKNOWN
    assert report.repository["default_branch"] == "trunk"


# ------------------------------------------------------------------ branches


def test_feature_branch_commits_outside_default(repo: RepoBuilder) -> None:
    _mine(repo).commit("base")
    repo.add_github_remote()
    repo.git("switch", "-q", "-c", "feature/login")
    repo.commit("wip 1")
    repo.commit("wip 2")
    repo.push("feature/login")
    report = run_scan(repo.path)
    f = finding(report, "BRANCH-NON-DEFAULT")
    assert f.status is Status.WARN
    assert not f.verified  # local refs only
    assert any("feature/login" in e for e in f.evidence)
    assert finding(report, "BRANCH-UNPUSHED").status is Status.PASS


def test_feature_branch_already_merged_on_github(repo: RepoBuilder) -> None:
    _mine(repo).commit("base")
    repo.add_github_remote()
    repo.git("switch", "-q", "-c", "feature/login")
    tip = repo.commit("wip")
    repo.push("feature/login")
    gh = FakeGh(
        repo.path,
        load_fixture("gh_context_owner.json"),
        logins={ME[1]: "alexdev"},
        compare={tip: "behind"},
    )
    f = finding(run_scan(repo.path, gh), "BRANCH-NON-DEFAULT")
    assert f.status is Status.PASS
    assert f.verified


def test_gh_pages_is_not_a_problem(repo: RepoBuilder) -> None:
    _mine(repo).commit("base")
    repo.git("switch", "-q", "--orphan", "gh-pages")
    repo.commit("site")
    repo.add_github_remote()
    assert finding(run_scan(repo.path), "BRANCH-NON-DEFAULT").status is Status.PASS


def test_unpushed_commits(repo: RepoBuilder) -> None:
    _mine(repo).commit("base")
    repo.add_github_remote()
    repo.commit("local only")
    f = finding(run_scan(repo.path), "BRANCH-UNPUSHED")
    assert f.status is Status.WARN
    assert "1 local commit" in f.description


def test_stale_local_origin_head(repo: RepoBuilder) -> None:
    _mine(repo).commit()
    repo.add_github_remote()
    ctx = load_fixture("gh_context_owner.json")
    ctx["data"]["repository"]["defaultBranchRef"]["name"] = "develop"
    repo.git("branch", "develop")
    repo.push("develop")
    f = finding(run_scan(repo.path, FakeGh(repo.path, ctx)), "REPO-DEFAULT-BRANCH")
    assert f.status is Status.WARN
    assert "develop" in f.description


# ------------------------------------------------------------------ github repository facts


def test_fork(repo: RepoBuilder) -> None:
    _mine(repo).commit()
    repo.add_github_remote()
    repo.git("remote", "add", "upstream", "https://github.com/acme/widgets.git")
    gh = FakeGh(repo.path, load_fixture("gh_context_fork.json"), logins={ME[1]: "alexdev"})
    f = finding(run_scan(repo.path, gh), "REPO-FORK")
    assert f.status is Status.WARN
    assert f.verified
    assert "acme/widgets" in f.description


def test_fork_offline_hint(repo: RepoBuilder) -> None:
    _mine(repo).commit()
    repo.add_github_remote()
    repo.git("remote", "add", "upstream", "https://github.com/acme/widgets.git")
    f = finding(run_scan(repo.path), "REPO-FORK")
    assert f.status is Status.UNKNOWN
    assert any("upstream" in e for e in f.evidence)


def test_repo_not_accessible_on_github(repo: RepoBuilder) -> None:
    _mine(repo).commit()
    repo.add_github_remote()
    gh = FakeGh(repo.path, load_fixture("gh_context_repo_not_found.json"))
    report = run_scan(repo.path, gh)
    assert finding(report, "REPO-FORK").status is Status.UNKNOWN
    assert finding(report, "COMMIT-ATTRIBUTION").status is Status.UNKNOWN
    assert finding(report, "GH-AUTH").status is Status.PASS


def test_github_unavailable_degrades_gracefully(repo: RepoBuilder) -> None:
    class Down(FakeGh):
        def graphql(self, query, variables):  # type: ignore[no-untyped-def]
            raise GitHubError("network", "could not reach api.github.com (offline?)")

    _mine(repo).commit()
    repo.add_github_remote()
    report = run_scan(repo.path, Down(repo.path, {}))
    assert finding(report, "GH-AUTH").status is Status.UNKNOWN
    assert finding(report, "REPO-VISIBILITY").status is Status.UNKNOWN
    assert report.repository["default_branch"] == "main"  # from local origin/HEAD


def test_not_authenticated(repo: RepoBuilder) -> None:
    class NoAuth(FakeGh):
        def graphql(self, query, variables):  # type: ignore[no-untyped-def]
            raise GitHubError("not_authenticated", "gh is not authenticated")

    _mine(repo).commit()
    f = finding(run_scan(repo.path, NoAuth(repo.path, {})), "GH-AUTH")
    assert f.status is Status.SKIPPED


# ------------------------------------------------------------------ authorship & timing


def test_committer_is_not_author(repo: RepoBuilder) -> None:
    _mine(repo)
    repo.commit("mine")
    repo.commit("cherry-picked", author=ALICE, committer=ME)
    repo.commit("pair", author=ALICE, coauthors=(ME,))
    f = finding(run_scan(repo.path), "COMMIT-AUTHORSHIP")
    assert f.status is Status.WARN
    assert "1 commit was committed by you" in f.description
    assert any("Co-authored-by" in e for e in f.evidence)


def test_recent_commit_processing_delay(repo: RepoBuilder) -> None:
    _mine(repo).commit(date=NOW - timedelta(hours=3))
    f = finding(run_scan(repo.path), "COMMIT-TIMING")
    assert f.status is Status.WARN
    assert "24 hours" in f.description


def test_future_dated_commit(repo: RepoBuilder) -> None:
    _mine(repo).commit(date=NOW + timedelta(days=40))
    assert finding(run_scan(repo.path), "COMMIT-TIMING").status is Status.WARN


def test_history_limit(repo: RepoBuilder) -> None:
    _mine(repo)
    for i in range(6):
        repo.commit(f"c{i}")
    report = run_scan(repo.path, history=4)
    assert report.scan["commits_scanned"] == 4
    assert report.scan["history_truncated"] is True


# ------------------------------------------------------------------ safety & privacy


def test_scan_is_read_only(repo: RepoBuilder) -> None:
    _mine(repo).commit("base")
    repo.add_github_remote()
    repo.git("switch", "-q", "-c", "feature")
    repo.commit("wip")
    before = tree_digest(repo.path)
    gh = FakeGh(repo.path, load_fixture("gh_context_owner.json"), logins={ME[1]: "alexdev"})
    run_scan(repo.path, gh)
    run_scan(repo.path)
    assert tree_digest(repo.path) == before


def test_offline_never_contacts_github(repo: RepoBuilder) -> None:
    _mine(repo).commit()
    repo.add_github_remote()
    report = run_scan(repo.path)  # uses ExplodingGh
    assert report.scan["mode"] == "offline"


def test_emails_masked_by_default_and_tokens_hidden(repo: RepoBuilder) -> None:
    _mine(repo).commit()
    repo.add_github_remote()
    token = "ghp_" + "a1B2c3D4e5" * 4
    repo.git("remote", "set-url", "origin", f"https://{token}@github.com/alexdev/widgets.git")
    report = run_scan(repo.path)
    text, data = render_text(report), render_json(report)
    for out in (text, data):
        assert ME[1] not in out
        assert token not in out
    assert json.loads(data)["scan"]["emails_masked"] is True
    shown = run_scan(repo.path, show_emails=True)
    assert ME[1] in render_text(shown)


def test_json_schema_shape(repo: RepoBuilder) -> None:
    _mine(repo).commit()
    data = json.loads(render_json(run_scan(repo.path)))
    assert data["read_only"] is True
    assert set(data["summary"]["counts"]) == {"PASS", "WARN", "FAIL", "UNKNOWN", "SKIPPED"}
    ids = [f["id"] for f in data["findings"]]
    assert len(ids) == len(set(ids))
    for f in data["findings"]:
        assert {
            "id",
            "status",
            "description",
            "evidence",
            "confidence",
            "remediation",
            "docs",
            "verified",
        } <= set(f)
        assert f["docs"]
