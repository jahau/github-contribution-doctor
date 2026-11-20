"""Human-readable, JSON and Markdown renderers."""

from __future__ import annotations

import html
import json
import re
import textwrap
import unicodedata

from contribution_doctor.models import Finding, Report, Status
from contribution_doctor.privacy import scrub_secrets

_COLORS = {
    Status.PASS: "32",
    Status.WARN: "33",
    Status.FAIL: "31",
    Status.UNKNOWN: "36",
    Status.SKIPPED: "90",
}
WIDTH = 92


class _Style:
    def __init__(self, color: bool):
        self.color = color

    def status(self, status: Status) -> str:
        label = f"[{status.value}]".ljust(9)
        if not self.color:
            return label
        return f"\x1b[{_COLORS[status]}m{label}\x1b[0m"

    def bold(self, text: str) -> str:
        return f"\x1b[1m{text}\x1b[0m" if self.color else text

    def dim(self, text: str) -> str:
        return f"\x1b[2m{text}\x1b[0m" if self.color else text


def _wrap(text: str, indent: str, first: str | None = None) -> list[str]:
    return textwrap.wrap(
        text,
        width=WIDTH,
        initial_indent=first if first is not None else indent,
        subsequent_indent=indent,
        break_on_hyphens=False,
        break_long_words=False,
    ) or [indent.rstrip()]


def _basis(f: Finding) -> str:
    return f"{'verified' if f.verified else 'possible'}, {f.confidence.value} confidence"


def render_text(report: Report, *, explain: bool = False, color: bool = False) -> str:
    s = _Style(color)
    pad = " " * 11
    out: list[str] = []
    repo, prof, scan = report.repository, report.profile, report.scan
    out.append(s.bold(f"GitHub Contribution Doctor {report.tool_version}") + "  (read-only)")
    gh = f"  ->  github.com/{repo['github']}" if repo.get("github") else ""
    out.append(f"Repository: {repo['name']}{gh}")
    who = f"@{prof['login']}" if prof.get("login") else "(none selected)"
    if prof.get("authenticated_as") and prof.get("login") != prof.get("authenticated_as"):
        who += f"  (authenticated as @{prof['authenticated_as']})"
    out.append(f"Profile:    {who}")
    trunc = " (limit reached; use --history to scan more)" if scan["history_truncated"] else ""
    out.append(f"Mode:       {scan['mode']}  |  commits scanned: {scan['commits_scanned']}{trunc}")
    out.append("")

    for f in report.findings:
        compact = f.status in (Status.PASS, Status.SKIPPED) and not explain
        head = f"{s.status(f.status)}  {s.bold(f.rule_id)}  {f.title}"
        out.append(head)
        out += _wrap(f.description, pad)
        if compact:
            continue
        out.append(pad + s.dim(f"({_basis(f)})"))
        if explain and f.explanation:
            out += _wrap("Why: " + f.explanation, pad + "     ", pad + "")
        if f.evidence:
            out.append(pad + "Evidence:")
            for e in f.evidence:
                out += _wrap(e, pad + "    ", pad + "  - ")
        if f.remediation:
            out.append(pad + "What to do:")
            for r in f.remediation:
                out += _wrap(r, pad + "    ", pad + "  - ")
        if f.docs and (explain or f.is_issue):
            out.append(pad + "Docs: " + f.docs[0])
            if explain:
                out += [pad + "      " + d for d in f.docs[1:]]
        out.append("")
    if out[-1] != "":
        out.append("")

    counts = report.counts()
    out.append(s.bold("Summary"))
    out.append("  " + "  ".join(f"{k} {v}" for k, v in counts.items()))
    issues = report.issues()
    if issues:
        out.append("")
        out.append("  Potential contribution visibility issues (most important first):")
        for n, f in enumerate(issues, 1):
            tag = "verified" if f.verified else "possible"
            out += _wrap(
                f"{f.rule_id} [{f.status.value}, {tag}]: {f.description}", "      ", f"  {n:>2}. "
            )
    else:
        out.append("  No contribution visibility problems were found in the checks that ran.")
    unknown = [f.rule_id for f in report.findings if f.status == Status.UNKNOWN]
    if unknown:
        out += _wrap("Not verifiable here (UNKNOWN): " + ", ".join(unknown), "    ", "  ")
    out.append("")
    out += _wrap(
        "'verified' = confirmed by GitHub data or by deterministic local facts; 'possible' = "
        "a likely explanation that could not be confirmed. Commit counts are local "
        "observations, not GitHub contribution counts. Nothing in the repository or Git "
        "configuration was changed.",
        "  ",
    )
    if not explain:
        out.append("  Run with --explain for background and documentation links.")
    return scrub_secrets("\n".join(out)) + "\n"


def render_json(report: Report) -> str:
    return scrub_secrets(json.dumps(report.to_dict(), indent=2, ensure_ascii=False)) + "\n"


# ---------------------------------------------------------------------------- Markdown
#
# Markdown output is meant for GitHub Actions job summaries ($GITHUB_STEP_SUMMARY) and PR
# comments. Every dynamic string (repository and author names, evidence, branch names) is
# untrusted. It is scrubbed for secrets *before* escaping, because escaping could split a
# token so that the scrubber no longer recognises it. It is then stripped of control and
# bidi characters, collapsed onto one line, and escaped so that it cannot inject links,
# images, HTML, table cells, math or mentions. The output has no timestamp, so the same
# report always renders to the same bytes.

# CommonMark guarantees that a backslash before any ASCII punctuation yields that literal.
_MD_SPECIAL = re.compile(r"([\\`*_{}\[\]()<>!|~&$@#+\-])")
_LIST_START = re.compile(r"^(\d+)([.)])")  # "2026. x" would otherwise start an ordered list
_BIDI = frozenset("؜‎‏‪‫‬‭‮⁦⁧⁨⁩")
_WS = re.compile(r"\s+")
_MD_ORDER = (Status.FAIL, Status.WARN, Status.UNKNOWN, Status.PASS, Status.SKIPPED)
_DOC_URL = re.compile(r"https://[A-Za-z0-9.-]+(?:/[A-Za-z0-9._~%/#?=&+-]*)?")


def _clean(text: str) -> str:
    """Scrub secrets, drop control/bidi/format characters and collapse whitespace."""
    out: list[str] = []
    for ch in scrub_secrets(str(text)):
        if ch in _BIDI:
            continue
        cat = unicodedata.category(ch)
        if cat == "Cc":
            out.append(" " if ch in "\t\n\r\x0b\x0c" else "�")
        elif cat in ("Cf", "Cs", "Co", "Cn") and ch != "‍":  # keep ZWJ for emoji
            out.append("�")
        else:
            out.append(ch)
    return _WS.sub(" ", "".join(out)).strip()


def _escape_clean(text: str) -> str:
    return _MD_SPECIAL.sub(r"\\\1", text)


def _code_clean(text: str, *, table: bool) -> str:
    if not text.strip() or "`" in text:
        return _escape_clean(text)
    if table:
        text = text.replace("|", "\\|")  # GFM splits table cells before parsing code spans
    return f"`{text}`"


def md_escape(text: str) -> str:
    """Escape untrusted text for inline Markdown; safe inside GFM table cells too."""
    return _escape_clean(_clean(text))


def _md_code(text: str, *, table: bool = False) -> str:
    """Inline code span; falls back to escaped text if *text* contains a backtick."""
    return _code_clean(_clean(text), table=table)


def _md_inline(text: str, *, table: bool = False) -> str:
    """Escape text, keeping balanced `backtick` segments (commands) as code spans.

    The result is safe at the start of a line (no list, heading or quote markers).
    """
    t = _clean(text)
    parts = t.split("`")
    if len(parts) % 2 == 0:  # unbalanced backticks: everything is plain text
        rendered = _escape_clean(t)
    else:
        rendered = "".join(
            _code_clean(p, table=table) if i % 2 else _escape_clean(p) for i, p in enumerate(parts)
        )
    return _LIST_START.sub(r"\1\\\2", rendered)


def _md_link(url: str) -> str:
    u = _clean(url)
    return f"<{u}>" if _DOC_URL.fullmatch(u) else md_escape(u)


def render_markdown(report: Report, *, explain: bool = False) -> str:
    """Render a report as deterministic GitHub-flavoured Markdown."""
    repo, prof, scan = report.repository, report.profile, report.scan
    out: list[str] = [
        f"## GitHub Contribution Doctor {md_escape(report.tool_version)} (read-only)",
        "",
        "| | |",
        "| --- | --- |",
    ]
    name = md_escape(repo.get("name") or "(unknown)")
    if repo.get("github"):
        name += " on " + _md_code(f"github.com/{repo['github']}", table=True)
    out.append(f"| Repository | {name} |")
    if prof.get("login"):
        who = _md_code(f"@{prof['login']}", table=True)
        if prof.get("authenticated_as") and prof.get("login") != prof.get("authenticated_as"):
            viewer = _md_code("@" + str(prof["authenticated_as"]), table=True)
            who += f" (authenticated as {viewer})"
    else:
        who = "(none selected)"
    out.append(f"| Profile | {who} |")
    trunc = " (history limit reached)" if scan.get("history_truncated") else ""
    out.append(
        f"| Mode | {md_escape(str(scan.get('mode', '')))}, "
        f"{int(scan.get('commits_scanned', 0))} commits scanned{trunc} |"
    )
    masked = scan.get("emails_masked", True)
    out.append(f"| Emails | {'masked' if masked else '**shown in full (--show-emails)**'} |")
    out.append("")

    counts = report.counts()
    out.append("**Summary:** " + " · ".join(f"{s.value} {counts[s.value]}" for s in _MD_ORDER))
    out += ["", "### Potential contribution visibility issues", ""]
    issues = report.issues()
    for n, f in enumerate(issues, 1):
        tag = "verified" if f.verified else "possible"
        out.append(
            f"{n}. **{f.status.value}** {_md_code(f.rule_id)} ({tag}, "
            f"{f.confidence.value} confidence): {_md_inline(f.description)}"
        )
    if not issues:
        out.append(
            "No contribution visibility problems were found in the checks that ran."
            if report.findings
            else "No checks produced findings."
        )
    unknown = [f for f in report.findings if f.status == Status.UNKNOWN]
    if unknown:
        out += [
            "",
            "**Not verifiable here (UNKNOWN):** " + ", ".join(_md_code(f.rule_id) for f in unknown),
        ]
    out.append("")

    if report.findings:
        out += [
            "### Findings",
            "",
            "| Status | Rule | Result | Basis |",
            "| --- | --- | --- | --- |",
        ]
        for f in report.findings:
            basis = f"{'verified' if f.verified else 'possible'}, {f.confidence.value}"
            out.append(
                f"| **{f.status.value}** | {_md_code(f.rule_id, table=True)} | "
                f"{_md_inline(f.description, table=True)} | {basis} |"
            )
        out.append("")

    detailed = [
        f
        for f in report.findings
        if explain or f.status in (Status.FAIL, Status.WARN, Status.UNKNOWN)
    ]
    if detailed:
        out += ["### Details", ""]
    for f in detailed:
        summary = html.escape(_clean(f"{f.status.value} {f.rule_id}: {f.title}"), quote=True)
        out += [f"<details><summary>{summary}</summary>", "", _md_inline(f.description), ""]
        if explain and f.explanation:
            out += ["**Why:** " + _md_inline(f.explanation), ""]
        if f.evidence:
            out += ["**Evidence:**", "", *("- " + _md_inline(e) for e in f.evidence), ""]
        if f.remediation:
            out += ["**What to do:**", "", *("- " + _md_inline(r) for r in f.remediation), ""]
        docs = f.docs if explain else f.docs[:1]
        if docs:
            out += ["**Docs:** " + " ".join(_md_link(d) for d in docs), ""]
        out += ["</details>", ""]

    out.append(
        "_'verified' = confirmed by GitHub data or by deterministic local facts; 'possible' = "
        "a likely explanation that could not be confirmed. Commit counts are local "
        "observations, not GitHub contribution counts. Nothing in the repository or Git "
        "configuration was changed._"
    )
    return scrub_secrets("\n".join(out)) + "\n"
