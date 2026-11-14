"""Human-readable and JSON renderers."""

from __future__ import annotations

import json
import textwrap

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
