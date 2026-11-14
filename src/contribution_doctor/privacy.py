"""Redaction helpers: email masking, secret scrubbing and URL credential removal."""

from __future__ import annotations

import re
from urllib.parse import urlsplit, urlunsplit

# Mail providers whose domain reveals nothing about the person.
_PUBLIC_DOMAINS = frozenset(
    {
        "gmail.com",
        "googlemail.com",
        "outlook.com",
        "hotmail.com",
        "live.com",
        "yahoo.com",
        "icloud.com",
        "me.com",
        "proton.me",
        "protonmail.com",
        "users.noreply.github.com",
    }
)

_TOKEN_PATTERNS = (
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{16,}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"(?i)\b(authorization|token|bearer)\s*[:=]?\s*[A-Za-z0-9_\-.]{20,}"),
)
# Credentials embedded in HTTP(S)/FTP URLs: scheme://user:secret@host or scheme://token@host.
# ssh://git@host carries a plain username and is left alone; redact_url strips ssh passwords.
_URL_USERINFO = re.compile(r"(?i)\b((?:https?|ftps?)://)[^/@\s]+@")


def scrub_secrets(text: str) -> str:
    """Remove anything that looks like a token or URL credentials from free text."""
    for pattern in _TOKEN_PATTERNS:
        text = pattern.sub("[REDACTED]", text)
    return _URL_USERINFO.sub(r"\1[REDACTED]@", text)


def is_noreply(email: str) -> bool:
    return email.lower().endswith("@users.noreply.github.com")


def mask_email(email: str, *, show: bool = False) -> str:
    """Mask an email for shareable output.

    GitHub noreply addresses are designed to be public and are left intact so users can
    compare them with their account settings.
    """
    if show or not email or is_noreply(email):
        return email
    if "@" not in email:
        return email[:1] + "***" if len(email) > 1 else "***"
    local, _, domain = email.rpartition("@")
    masked_local = (local[:1] + "***") if local else "***"
    if domain.lower() in _PUBLIC_DOMAINS:
        return f"{masked_local}@{domain}"
    if "." in domain:
        head, _, tld = domain.rpartition(".")
        return f"{masked_local}@{head[:1]}***.{tld}"
    # Hostname-like domains (DESKTOP-ABC123) are the interesting part of the diagnosis
    # but can identify a machine; keep only a short prefix.
    return f"{masked_local}@{domain[:3]}***"


def redact_url(url: str) -> str:
    """Strip credentials from a remote URL while keeping it recognisable."""
    if "://" not in url:
        # scp-like syntax (git@github.com:owner/repo.git) cannot carry a password.
        return scrub_secrets(url)
    try:
        parts = urlsplit(url)
    except ValueError:
        return scrub_secrets(url)
    if parts.username is None and parts.password is None:
        return scrub_secrets(url)
    host = parts.hostname or ""
    if parts.port:
        host = f"{host}:{parts.port}"
    keep_user = parts.scheme in ("ssh", "git+ssh") and parts.password is None
    if keep_user and parts.username and not _looks_like_secret(parts.username):
        host = f"{parts.username}@{host}"
    return scrub_secrets(urlunsplit((parts.scheme, host, parts.path, parts.query, "")))


def _looks_like_secret(value: str) -> bool:
    return len(value) >= 20 or bool(_TOKEN_PATTERNS[0].search(value))
