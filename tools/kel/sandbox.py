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
                  sh_is_bash: bool = False, as_root: bool = False) -> list[str]:
    cmd = ["bwrap", "--die-with-parent", "--unshare-all"]
    if as_root:
        # Appear as uid/gid 0 (only the caller's own ids are mapped).
        cmd += ["--uid", "0", "--gid", "0"]
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


def bwrap_root_command(argv: list[str], *, root: Path, chdir: str, env: dict[str, str],
                       binds: list[tuple[Path, str]], ro_binds: list[tuple[Path, str]] = (),
                       hostname: str = "kel-build") -> list[str]:
    """Run argv with root as "/", as uid 0 inside a user namespace.

    Used once the bootstrap sysroot has its own shell and toolchain (stage 3
    onwards): nothing from the host is visible except the extra binds.
    """
    cmd = ["bwrap", "--die-with-parent", "--unshare-all", "--uid", "0", "--gid", "0",
           "--hostname", hostname, "--bind", str(root), "/",
           "--dev", "/dev", "--proc", "/proc", "--tmpfs", "/tmp", "--tmpfs", "/run"]
    for src, dst in binds:
        cmd += ["--bind", str(src), dst]
    for src, dst in ro_binds:
        cmd += ["--ro-bind", str(src), dst]
    cmd.append("--clearenv")
    for key in sorted(env):
        cmd += ["--setenv", key, env[key]]
    cmd += ["--chdir", chdir, "--", *argv]
    return cmd


def require_bwrap() -> str:
    path = shutil.which("bwrap")
    if path is None:
        raise KelError("bubblewrap (bwrap) is required for isolated builds")
    return path
