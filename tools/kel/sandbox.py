"""bubblewrap sandbox for build steps.

Builds run with no network, a read-only view of the host and write access
only to the directories passed in rw_binds (docs/DESIGN.md section 4.3).
bubblewrap 0.12+ needs unprivileged user namespaces, which the bootstrap
host provides (docs/research/2026-10-22-environment.md section 6).
"""

from __future__ import annotations

import shutil
from pathlib import Path

from kel.util import KelError


def bwrap_command(argv: list[str], *, chdir: Path, env: dict[str, str],
                  rw_binds: list[Path], share_net: bool = False,
                  sh_is_bash: bool = False) -> list[str]:
    cmd = ["bwrap", "--die-with-parent", "--unshare-all"]
    if share_net:
        cmd.append("--share-net")
    cmd += ["--ro-bind", "/", "/", "--dev", "/dev", "--proc", "/proc", "--tmpfs", "/tmp"]
    if sh_is_bash:
        # Build systems assume /bin/sh is bash (as on KEL itself); some hosts
        # use dash. Show bash as /bin/sh inside the sandbox only.
        sh = Path("/bin/sh").resolve()
        bash = Path("/bin/bash").resolve()
        cmd += ["--ro-bind", str(bash), str(sh)]
    for path in rw_binds:
        cmd += ["--bind", str(path), str(path)]
    cmd.append("--clearenv")
    for key in sorted(env):
        cmd += ["--setenv", key, env[key]]
    cmd += ["--chdir", str(chdir), "--", *argv]
    return cmd


def require_bwrap() -> str:
    path = shutil.which("bwrap")
    if path is None:
        raise KelError("bubblewrap (bwrap) is required for isolated builds")
    return path
