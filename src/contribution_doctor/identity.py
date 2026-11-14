"""Group commits into author identities and decide which ones belong to the profile.

Ownership levels, strongest evidence first:

* ``yours``   - GitHub attributes a commit to the profile, the address is the profile's
                noreply address, it is a verified email on the authenticated account, or
                the user passed it with ``--email``.
* ``likely``  - matches the local ``user.email`` or the configured ``user.name``; this is
                a guess, because the configured identity is not necessarily the profile.
* ``other``   - attributed to (or a noreply address of) a different account, or a bot.
* ``unknown`` - no signal either way (typically other contributors).

The tool never assumes that the authenticated account authored every commit.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime

from contribution_doctor.emails import EmailInfo, EmailKind, classify
from contribution_doctor.repo import Commit

YOURS = "yours"
LIKELY = "likely"
OTHER = "other"
UNKNOWN = "unknown"


@dataclass
class Identity:
    email: str
    info: EmailInfo
    names: Counter[str] = field(default_factory=Counter)
    authored: list[Commit] = field(default_factory=list)
    committed_only: int = 0  # commits where this identity is committer but not author
    coauthored: int = 0
    ownership: str = UNKNOWN
    reasons: list[str] = field(default_factory=list)
    github_login: str | None = None  # from GitHub attribution, when checked
    attribution: str = "unchecked"  # unchecked | linked | unlinked | not_on_github
    local_signal: bool = False  # matches user.email / user.name / --email

    @property
    def mine(self) -> bool:
        return self.ownership in (YOURS, LIKELY)

    @property
    def count(self) -> int:
        return len(self.authored)

    @property
    def latest(self) -> Commit | None:
        return max(self.authored, key=lambda c: c.author_date) if self.authored else None

    @property
    def first_date(self) -> datetime | None:
        return min((c.author_date for c in self.authored), default=None)

    @property
    def last_date(self) -> datetime | None:
        return max((c.author_date for c in self.authored), default=None)

    @property
    def display_name(self) -> str:
        return self.names.most_common(1)[0][0] if self.names else ""


@dataclass
class OwnershipHints:
    target_login: str | None = None
    target_id: int | None = None
    config_email: str | None = None
    config_name: str | None = None
    extra_emails: frozenset[str] = frozenset()
    verified_emails: frozenset[str] = frozenset()


def build_identities(commits: list[Commit]) -> dict[str, Identity]:
    identities: dict[str, Identity] = {}

    def get(email: str) -> Identity:
        if email not in identities:
            identities[email] = Identity(email, classify(email))
        return identities[email]

    for c in commits:
        ident = get(c.author_email)
        ident.authored.append(c)
        ident.names[c.author_name] += 1
        if c.committer_email != c.author_email:
            get(c.committer_email).committed_only += 1
        for _name, email in c.coauthors:
            if email and email != c.author_email:
                get(email).coauthored += 1
    return identities


def assign_ownership(identities: dict[str, Identity], hints: OwnershipHints) -> None:
    target = (hints.target_login or "").lower()
    cfg_name = (hints.config_name or "").strip().casefold()
    for ident in identities.values():
        info = ident.info
        reasons: list[str] = []
        level = UNKNOWN

        # Local signals: what the user's own configuration and flags say.
        local: list[str] = []
        if ident.email in hints.extra_emails:
            local.append("passed with --email")
        if hints.config_email and ident.email == hints.config_email:
            local.append("matches configured user.email")
        if cfg_name and any(n.strip().casefold() == cfg_name for n in ident.names):
            local.append("author name matches configured user.name")
        if target and any(n.strip().lower() == target for n in ident.names):
            local.append("author name equals the profile login")
        ident.local_signal = bool(local)

        # Strong signals: GitHub's own answer or GitHub-defined address formats.
        if ident.github_login:
            reasons.append(f"GitHub attributes its commits to @{ident.github_login}")
            level = YOURS if target and ident.github_login.lower() == target else OTHER
        elif info.kind == EmailKind.BOT:
            level = OTHER
            reasons.append("GitHub bot address")
        elif info.kind == EmailKind.NOREPLY and info.noreply_login and target:
            id_match = hints.target_id is not None and info.noreply_id == hints.target_id
            if info.noreply_login.lower() == target or id_match:
                level = YOURS
                reasons.append("noreply address of the inspected profile")
            else:
                level = OTHER
                reasons.append(f"noreply address of @{info.noreply_login}")
        elif ident.email in hints.verified_emails:
            level = YOURS
            reasons.append("verified email on the authenticated account")
        elif "passed with --email" in local:
            level = YOURS

        if level == UNKNOWN and local:
            level = LIKELY
        ident.reasons = reasons + local
        ident.ownership = level
