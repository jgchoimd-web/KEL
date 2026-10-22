"""Architectures and directory layout."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from kel.util import KelError

REPO_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Arch:
    name: str  # KEL architecture name, also used by apk
    triplet: str  # GNU target triplet with the "kel" vendor field
    kernel_arch: str  # ARCH= value for the Linux build system
    isa_flags: str  # compiler flags for the ISA baseline (D-001)


ARCHES = {
    "x86_64": Arch("x86_64", "x86_64-kel-linux-gnu", "x86", "-march=x86-64-v2 -mtune=generic"),
    "aarch64": Arch("aarch64", "aarch64-kel-linux-gnu", "arm64", "-march=armv8-a -mtune=generic"),
}


def get_arch(name: str) -> Arch:
    try:
        return ARCHES[name]
    except KeyError:
        raise KelError(f"unknown architecture {name!r} (known: {', '.join(ARCHES)})")


@dataclass(frozen=True)
class Layout:
    """Where kel keeps its inputs and outputs.

    Everything under workdir and cachedir can be deleted at any time and
    rebuilt from the recipes; nothing there is committed to git.
    """

    repo: Path
    workdir: Path
    cachedir: Path

    @classmethod
    def from_env(cls, workdir: str | None = None, cachedir: str | None = None) -> "Layout":
        repo = REPO_ROOT
        work = Path(workdir or os.environ.get("KEL_WORKDIR") or repo / "work")
        cache = Path(cachedir or os.environ.get("KEL_CACHEDIR") or repo / "cache")
        return cls(repo=repo, workdir=work.resolve(), cachedir=cache.resolve())

    @property
    def recipes(self) -> Path:
        return self.repo / "recipes"

    @property
    def bootstrap_defs(self) -> Path:
        return self.repo / "bootstrap"

    @property
    def upstream_keys(self) -> Path:
        return self.repo / "keys" / "upstream"

    @property
    def sources(self) -> Path:
        return self.cachedir / "sources"

    def arch_root(self, arch: Arch) -> Path:
        return self.workdir / arch.name

    def sysroot(self, arch: Arch) -> Path:
        return self.arch_root(arch) / "sysroot"

    def tools(self, arch: Arch) -> Path:
        # Like LFS, the cross toolchain lives inside the sysroot as /tools so
        # that paths such as --with-gxx-include-dir=/tools/... resolve both
        # from the host (via the sysroot) and later from inside it.
        return self.sysroot(arch) / "tools"

    def host_tools(self, arch: Arch) -> Path:
        # Bootstrap-only tools built for the host (e.g. apk for packaging).
        return self.arch_root(arch) / "host-tools"

    def repository(self, arch: Arch) -> Path:
        # apk layout: <base>/<arch>/Packages.adb and <base>/<arch>/*.apk
        return self.arch_root(arch) / "repo" / arch.name

    def keys(self) -> Path:
        # Development signing key (never committed, never published).
        return self.workdir / "keys"

    def builds(self, arch: Arch) -> Path:
        return self.arch_root(arch) / "build"

    def logs(self, arch: Arch) -> Path:
        return self.arch_root(arch) / "logs"

    def stamps(self, arch: Arch) -> Path:
        return self.arch_root(arch) / "stamps"
