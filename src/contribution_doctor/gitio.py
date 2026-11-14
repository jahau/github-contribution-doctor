"""Hardened, read-only Git subprocess runner.

Every Git invocation in this package goes through :class:`Git`, which

* never uses a shell and only accepts argument lists,
* applies a timeout,
* disables pagers, prompts, signature verification (which would execute ``gpg.program``
  from repository config), fsmonitor hooks and optional lock files,
* strips environment variables that could redirect Git to another repository.

Only read-only subcommands are used by callers; :data:`ALLOWED_SUBCOMMANDS` enforces it.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass

DEFAULT_TIMEOUT = 30.0

ALLOWED_SUBCOMMANDS = frozenset(
    {"rev-parse", "symbolic-ref", "log", "rev-list", "for-each-ref", "remote", "config", "version"}
)

# Config overrides that neutralise repository-controlled command execution and noise.
_SAFE_CONFIG = (
    "core.fsmonitor=false",
    "core.untrackedCache=false",
    "core.pager=cat",
    "color.ui=never",
    "log.showSignature=false",
    "log.decorate=false",
    "i18n.logOutputEncoding=UTF-8",
)

_STRIP_ENV = (
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_INDEX_FILE",
    "GIT_OBJECT_DIRECTORY",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_NAMESPACE",
    "GIT_EXTERNAL_DIFF",
    "GIT_PAGER",
    "GIT_TRACE",
    "GIT_TRACE_CURL",
    "GIT_TRACE_PACKET",
    "PAGER",
)

# Read-only subcommands of `git remote` / `git config` that callers may use.
_REMOTE_READ = frozenset({"get-url", "-v", "show"})
_CONFIG_READ = frozenset({"--get", "--get-all", "--get-regexp", "--list", "-l"})


class GitError(RuntimeError):
    """A Git command failed."""

    def __init__(self, message: str, *, stderr: str = "", returncode: int | None = None):
        super().__init__(message)
        self.stderr = stderr
        self.returncode = returncode


class GitUnavailable(GitError):
    """Git is not installed or could not be executed."""


class GitTimeout(GitError):
    """A Git command exceeded its timeout."""


@dataclass(frozen=True)
class GitResult:
    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0


def _check_read_only(args: tuple[str, ...]) -> None:
    if not args:
        raise ValueError("empty git command")
    sub = args[0]
    if sub not in ALLOWED_SUBCOMMANDS:
        raise ValueError(f"git subcommand not allowed: {sub}")
    if sub == "remote" and len(args) > 1 and args[1] not in _REMOTE_READ:
        raise ValueError(f"git remote {args[1]} is not read-only")
    if sub == "config" and not any(a in _CONFIG_READ for a in args[1:]):
        raise ValueError("git config is only allowed with --get/--get-all/--get-regexp")


class Git:
    """Run read-only Git commands against one repository path."""

    def __init__(
        self,
        cwd: str,
        *,
        timeout: float = DEFAULT_TIMEOUT,
        executable: str | None = None,
    ) -> None:
        exe = executable or shutil.which("git")
        if not exe:
            raise GitUnavailable("Git executable not found on PATH.")
        self.executable = exe
        self.cwd = cwd
        self.timeout = timeout
        self.env = self._build_env()

    @staticmethod
    def _build_env() -> dict[str, str]:
        env = {k: v for k, v in os.environ.items() if k not in _STRIP_ENV}
        env.update(
            {
                "GIT_TERMINAL_PROMPT": "0",
                "GIT_OPTIONAL_LOCKS": "0",
                "GIT_PAGER": "cat",
                "GCM_INTERACTIVE": "never",
                "LC_ALL": "C",
                "LANGUAGE": "C",
            }
        )
        return env

    def run(self, *args: str) -> GitResult:
        _check_read_only(args)
        cmd = [self.executable, "--no-pager", "-C", self.cwd]
        for item in _SAFE_CONFIG:
            cmd += ["-c", item]
        cmd += list(args)
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                stdin=subprocess.DEVNULL,
                timeout=self.timeout,
                env=self.env,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise GitTimeout(f"git {args[0]} timed out after {self.timeout:g}s") from exc
        except OSError as exc:
            raise GitUnavailable(f"could not run git: {exc}") from exc
        return GitResult(
            proc.returncode,
            proc.stdout.decode("utf-8", errors="replace"),
            proc.stderr.decode("utf-8", errors="replace").strip(),
        )

    def out(self, *args: str) -> str | None:
        """Return stripped stdout, or None when the command fails."""
        result = self.run(*args)
        if not result.ok:
            return None
        return result.stdout.strip()
