"""Stage 0: check that the bootstrap host has what the bootstrap needs.

Minimum versions come from the LFS 12.4 host requirements
(https://www.linuxfromscratch.org/lfs/view/stable/chapter02/hostreqs.html)
plus what kel itself needs (Python 3.11 for tomllib, bubblewrap, gpg).
"""

from __future__ import annotations

import platform
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass

from kel.util import version_at_least

VERSION_RE = r"(\d+(?:\.\d+)+[a-z]?)"


@dataclass(frozen=True)
class Requirement:
    label: str
    argv: tuple[str, ...]
    minimum: str
    pattern: str = VERSION_RE


REQUIREMENTS = (
    Requirement("bash", ("bash", "--version"), "3.2"),
    Requirement("binutils (ld)", ("ld", "--version"), "2.13.1"),
    Requirement("bison", ("bison", "--version"), "2.7"),
    Requirement("coreutils", ("sort", "--version"), "8.1"),
    Requirement("diffutils", ("diff", "--version"), "2.8.1"),
    Requirement("findutils", ("find", "--version"), "4.2.31"),
    Requirement("gawk", ("gawk", "--version"), "4.0.1"),
    Requirement("gcc", ("gcc", "-dumpfullversion"), "5.4", r"(\d+(?:\.\d+)*)"),
    Requirement("g++", ("g++", "-dumpfullversion"), "5.4", r"(\d+(?:\.\d+)*)"),
    Requirement("grep", ("grep", "--version"), "2.5.1a"),
    Requirement("gzip", ("gzip", "--version"), "1.3.12"),
    Requirement("m4", ("m4", "--version"), "1.4.10"),
    Requirement("make", ("make", "--version"), "4.0"),
    Requirement("patch", ("patch", "--version"), "2.5.4"),
    Requirement("perl", ("perl", "-e", "print $^V"), "5.8.8", r"v?(\d+(?:\.\d+)+)"),
    Requirement("sed", ("sed", "--version"), "4.1.5"),
    Requirement("tar", ("tar", "--version"), "1.22"),
    Requirement("texinfo (makeinfo)", ("makeinfo", "--version"), "5.0"),
    Requirement("xz", ("xz", "--version"), "5.0.0"),
    Requirement("bubblewrap", ("bwrap", "--version"), "0.4"),
    Requirement("meson (host tools)", ("meson", "--version"), "0.64"),
    Requirement("ninja (host tools)", ("ninja", "--version"), "1.8"),
    Requirement("pkg-config (host tools)", ("pkg-config", "--version"), "0.29"),
    Requirement("gpg", ("gpg", "--version"), "2.2"),
)


@dataclass
class Result:
    label: str
    ok: bool
    found: str


def check_requirement(req: Requirement) -> Result:
    if shutil.which(req.argv[0]) is None:
        return Result(req.label, False, "not found")
    try:
        proc = subprocess.run(req.argv, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as e:
        return Result(req.label, False, f"error: {e}")
    m = re.search(req.pattern, proc.stdout + proc.stderr)
    if not m:
        return Result(req.label, False, "version not recognised")
    found = m.group(1)
    return Result(req.label, version_at_least(found, req.minimum), found)


def check_host() -> list[Result]:
    results = [check_requirement(r) for r in REQUIREMENTS]
    py = ".".join(map(str, sys.version_info[:3]))
    results.append(Result("python (kel)", sys.version_info >= (3, 11), py))
    kernel = platform.release().split("-")[0]
    results.append(Result("linux kernel", version_at_least(kernel, "5.4"), kernel))
    return results
