"""Offline classification of commit email addresses."""

from __future__ import annotations

import enum
import re
from dataclasses import dataclass

_NOREPLY = re.compile(
    r"^(?:(?P<id>\d+)\+)?(?P<login>[a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\[bot\])?)"
    r"@users\.noreply\.github\.com$",
    re.IGNORECASE,
)
_BASIC = re.compile(r"^[^@\s]+@[^@\s]+$")

# TLDs / suffixes that cannot receive mail from GitHub's verification system.
_LOCAL_SUFFIXES = (
    ".local",
    ".localdomain",
    ".localhost",
    ".lan",
    ".home",
    ".internal",
    ".intranet",
    ".corp",
    ".invalid",
    ".test",
    ".example",
    ".workgroup",
)
_RESERVED_DOMAINS = frozenset({"localhost", "example.com", "example.org", "example.net"})
_BOT_SUFFIX = "[bot]"


class EmailKind(str, enum.Enum):
    NOREPLY = "noreply"  # <id>+<login>@users.noreply.github.com or legacy <login>@...
    BOT = "bot"  # GitHub App / Actions bot identity
    REGULAR = "regular"  # looks deliverable; linkage to an account is unknown offline
    UNLINKABLE = "unlinkable"  # can never be verified on GitHub


@dataclass(frozen=True)
class EmailInfo:
    email: str
    kind: EmailKind
    reason: str = ""
    noreply_login: str | None = None
    noreply_id: int | None = None


def normalize(email: str) -> str:
    return email.strip().strip("<>").strip().lower()


def classify(email: str) -> EmailInfo:
    e = normalize(email)
    if not e or e == "(none)":
        return EmailInfo(e, EmailKind.UNLINKABLE, "email is empty or '(none)'")
    m = _NOREPLY.match(e)
    if m:
        login = m.group("login")
        uid = int(m.group("id")) if m.group("id") else None
        kind = EmailKind.BOT if login.endswith(_BOT_SUFFIX) else EmailKind.NOREPLY
        return EmailInfo(e, kind, "", login, uid)
    if not _BASIC.match(e):
        return EmailInfo(e, EmailKind.UNLINKABLE, "not a valid email address")
    domain = e.rpartition("@")[2]
    if domain in _RESERVED_DOMAINS:
        return EmailInfo(
            e, EmailKind.UNLINKABLE, f"'{domain}' is a reserved, non-deliverable domain"
        )
    if "." not in domain:
        return EmailInfo(
            e,
            EmailKind.UNLINKABLE,
            "domain has no dot; looks like a machine hostname guessed by Git",
        )
    if domain.endswith(_LOCAL_SUFFIXES):
        return EmailInfo(e, EmailKind.UNLINKABLE, "domain is a local/reserved network name")
    if re.fullmatch(r"[\d.]+", domain) or domain.startswith("["):
        return EmailInfo(e, EmailKind.UNLINKABLE, "domain is an IP address")
    return EmailInfo(e, EmailKind.REGULAR)
