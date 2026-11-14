"""Command-line interface.

Exit codes:
    0  scan completed, no FAIL findings (and no WARN findings with --strict)
    1  scan completed, at least one FAIL finding (or WARN with --strict)
    2  invalid command-line usage
    3  environment error: Git missing, path is not a repository, Git failure or timeout
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence

from contribution_doctor import __version__
from contribution_doctor.catalog import RULES
from contribution_doctor.engine import DEFAULT_HISTORY, MAX_HISTORY, ScanOptions, scan
from contribution_doctor.github import valid_login
from contribution_doctor.gitio import GitError, GitTimeout, GitUnavailable
from contribution_doctor.models import Status
from contribution_doctor.privacy import scrub_secrets
from contribution_doctor.render import render_json, render_text
from contribution_doctor.repo import RepoError

EXIT_OK = 0
EXIT_FINDINGS = 1
EXIT_USAGE = 2
EXIT_ENV = 3

_SUBCOMMANDS = ("scan", "rules")


def _history(value: str) -> int:
    try:
        n = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be an integer") from exc
    if not 1 <= n <= MAX_HISTORY:
        raise argparse.ArgumentTypeError(f"must be between 1 and {MAX_HISTORY}")
    return n


def _login(value: str) -> str:
    value = value.lstrip("@")
    if not valid_login(value):
        raise argparse.ArgumentTypeError(f"'{value}' is not a valid GitHub username")
    return value


def _timeout(value: str) -> float:
    try:
        t = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a number of seconds") from exc
    if not 1 <= t <= 600:
        raise argparse.ArgumentTypeError("must be between 1 and 600 seconds")
    return t


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="contribution-doctor",
        description="Read-only diagnostics for Git commits missing from a GitHub "
        "contribution graph. Never modifies your repository or Git configuration.",
        epilog="Exit codes: 0 no failures, 1 failures found, 2 usage error, 3 environment error.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", metavar="COMMAND")

    p = sub.add_parser("scan", help="diagnose a repository (default command)")
    p.add_argument("path", nargs="?", default=".", help="repository path (default: .)")
    p.add_argument(
        "--user",
        type=_login,
        metavar="LOGIN",
        help="GitHub profile to diagnose (default: the gh-authenticated account)",
    )
    p.add_argument(
        "--format", choices=("text", "json"), default="text", help="output format (default: text)"
    )
    p.add_argument(
        "--offline", action="store_true", help="do not contact GitHub; local checks only"
    )
    p.add_argument(
        "--history",
        type=_history,
        default=DEFAULT_HISTORY,
        metavar="N",
        help=f"maximum number of commits to scan (default: {DEFAULT_HISTORY})",
    )
    p.add_argument(
        "--explain",
        action="store_true",
        help="show background, evidence and documentation for every finding",
    )
    p.add_argument(
        "--email",
        action="append",
        default=[],
        metavar="ADDRESS",
        help="treat this author email as yours (repeatable); never sent to GitHub",
    )
    p.add_argument(
        "--show-emails",
        action="store_true",
        help="print full email addresses instead of masked ones",
    )
    p.add_argument("--strict", action="store_true", help="exit with 1 on WARN findings too")
    p.add_argument(
        "--color",
        choices=("auto", "always", "never"),
        default="auto",
        help="colorize text output (default: auto; honours NO_COLOR)",
    )
    p.add_argument(
        "--timeout",
        type=_timeout,
        default=30.0,
        metavar="SECONDS",
        help="timeout for each git/gh call (default: 30)",
    )

    sub.add_parser("rules", help="list all diagnostic rule IDs")
    return parser


def _translate_legacy(argv: list[str]) -> list[str]:
    """Map the v0.1 interface (`doctor.py --repo PATH`) onto `scan PATH`."""
    if argv and (argv[0] in _SUBCOMMANDS or argv[0] in ("-h", "--help", "--version")):
        return argv
    out: list[str] = ["scan"]
    path: str | None = None
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--repo" and i + 1 < len(argv):
            path = argv[i + 1]
            i += 2
            continue
        if arg.startswith("--repo="):
            path = arg.split("=", 1)[1]
        else:
            out.append(arg)
        i += 1
    if path is not None:
        out.insert(1, path)
    return out


def _enable_windows_ansi() -> bool:
    if os.name != "nt":
        return True
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined,unused-ignore]
        handle = kernel32.GetStdHandle(-11)
        mode = ctypes.c_uint32()
        if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            return False
        return bool(kernel32.SetConsoleMode(handle, mode.value | 0x0004))
    except Exception:
        return False


def _use_color(choice: str) -> bool:
    if choice == "never":
        return False
    if choice == "always":
        return _enable_windows_ansi() or True
    if os.environ.get("NO_COLOR") or os.environ.get("TERM") == "dumb":
        return False
    return sys.stdout.isatty() and _enable_windows_ansi()


def _print_rules() -> int:
    for rule in RULES.values():
        net = " (GitHub)" if rule.needs_github else ""
        print(f"{rule.id:<26} {rule.category:<11} {rule.title}{net}")
    return EXIT_OK


def _err(msg: str) -> None:
    print(f"contribution-doctor: error: {scrub_secrets(msg)}", file=sys.stderr)


def main(argv: Sequence[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure:
            reconfigure(errors="replace")

    args_list = _translate_legacy(list(sys.argv[1:] if argv is None else argv))
    parser = build_parser()
    try:
        args = parser.parse_args(args_list)
    except SystemExit as exc:  # argparse exits 2 on usage errors, 0 on --help
        return int(exc.code or 0)

    if args.command == "rules":
        return _print_rules()

    if not os.path.isdir(args.path):
        _err(f"path does not exist or is not a directory: {args.path}")
        return EXIT_ENV

    options = ScanOptions(
        path=args.path,
        user=args.user,
        offline=args.offline,
        history=args.history,
        emails=args.email,
        show_emails=args.show_emails,
        timeout=args.timeout,
    )
    try:
        report = scan(options)
    except GitUnavailable as exc:
        _err(f"{exc} Install Git from https://git-scm.com/downloads.")
        return EXIT_ENV
    except RepoError as exc:
        _err(f"not a Git repository: {exc}")
        return EXIT_ENV
    except GitTimeout as exc:
        _err(f"{exc}. Try a larger --timeout or a smaller --history.")
        return EXIT_ENV
    except GitError as exc:
        _err(f"{exc}: {exc.stderr}")
        return EXIT_ENV

    if args.format == "json":
        sys.stdout.write(render_json(report))
    else:
        sys.stdout.write(render_text(report, explain=args.explain, color=_use_color(args.color)))

    statuses = {f.status for f in report.findings}
    if Status.FAIL in statuses or (args.strict and Status.WARN in statuses):
        return EXIT_FINDINGS
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
