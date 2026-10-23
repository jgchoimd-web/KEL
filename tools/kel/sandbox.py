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


def _chroot_args(roots: list[str]) -> list[str]:
    """Let the command chroot into roots (paths inside the sandbox).

    apk runs package scripts chrooted into its --root. bwrap drops every
    capability by default, so CAP_SYS_CHROOT is added back; it is only held
    inside the sandbox's user namespace and grants nothing outside it. Each
    root gets its own /proc and /dev for the scripts.
    """
    args: list[str] = []
    for root in roots:
        args += ["--proc", f"{root}/proc", "--dev", f"{root}/dev"]
    if roots:
        args += ["--cap-add", "CAP_SYS_CHROOT"]
    return args


def bwrap_command(argv: list[str], *, chdir: Path, env: dict[str, str],
                  rw_binds: list[Path], share_net: bool = False,
                  sh_is_bash: bool = False, as_root: bool = False,
                  ro_binds: list[Path] = (), cap_add: list[str] = (),
                  chroot_into: list[str] = ()) -> list[str]:
    """Run argv with the host's / visible read-only.

    ro_binds are only needed for paths the sandbox hides (under /tmp) or
    that must stay read-only inside a writable bind.
    """
    cmd = ["bwrap", "--die-with-parent", "--unshare-all"]
    if as_root:
        # Appear as uid/gid 0 (only the caller's own ids are mapped).
        cmd += ["--uid", "0", "--gid", "0"]
    for cap in cap_add:
        # bwrap drops all capabilities by default. For an unprivileged caller
        # these exist only in the new user namespace: they cover files owned
        # by the mapped uid, nothing else on the host.
        cmd += ["--cap-add", cap]
    if share_net:
        cmd.append("--share-net")
    cmd += ["--ro-bind", "/", "/", "--dev", "/dev", "--proc", "/proc", "--tmpfs", "/tmp"]
    if sh_is_bash:
        # Build systems assume /bin/sh is bash (as on KEL itself); some hosts
        # use dash. Show bash as /bin/sh inside the sandbox only.
        sh = Path("/bin/sh").resolve()
        bash = Path("/bin/bash").resolve()
        cmd += ["--ro-bind", str(bash), str(sh)]
    # Explicit binds come after the /tmp tmpfs so that paths under /tmp stay
    # visible; read-only ones last, so they also apply inside a writable bind.
    for path in rw_binds:
        cmd += ["--bind", str(path), str(path)]
    for path in ro_binds:
        cmd += ["--ro-bind", str(path), str(path)]
    cmd += _chroot_args(list(chroot_into))
    cmd.append("--clearenv")
    for key in sorted(env):
        cmd += ["--setenv", key, env[key]]
    cmd += ["--chdir", str(chdir), "--", *argv]
    return cmd


def bwrap_root_command(argv: list[str], *, root: Path, chdir: str, env: dict[str, str],
                       binds: list[tuple[Path, str]], ro_binds: list[tuple[Path, str]] = (),
                       hostname: str = "kel-build", readonly: bool = False,
                       chroot_into: list[str] = (), cap_add: list[str] = ()) -> list[str]:
    """Run argv with root as "/", as uid 0 inside a user namespace.

    Used once the bootstrap sysroot has its own shell and toolchain (stage 3
    onwards): nothing from the host is visible except the extra binds.

    readonly: root is remounted read-only after all mounts are set up, so
    the command cannot change it (build and tools roots shared by many steps
    from stage 4 on). bwrap still creates missing mount points in root while
    setting up, except under /tmp and /run, which are fresh tmpfs mounts.
    """
    # /sys is shown read-only: some build systems and test suites read it
    # (LFS mounts sysfs in the chroot too).
    cmd = ["bwrap", "--die-with-parent", "--unshare-all", "--uid", "0", "--gid", "0",
           "--hostname", hostname, "--bind", str(root), "/",
           "--dev", "/dev", "--proc", "/proc", "--ro-bind", "/sys", "/sys",
           "--tmpfs", "/tmp", "--tmpfs", "/run"]
    for src, dst in binds:
        cmd += ["--bind", str(src), dst]
    for src, dst in ro_binds:
        cmd += ["--ro-bind", str(src), dst]
    cmd += _chroot_args(list(chroot_into))
    for cap in cap_add:
        # Held only inside the sandbox's user namespace (see bwrap_command).
        cmd += ["--cap-add", cap]
    if readonly:
        # Must come after every mount: it only affects the root mount itself,
        # the binds above keep their own modes.
        cmd += ["--remount-ro", "/"]
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
