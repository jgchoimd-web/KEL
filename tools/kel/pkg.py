"""From a build's DESTDIR to signed apk packages and a signed index.

Steps: split subpackages, derive "so:" provides/depends from ELF files,
check the packaging policy, create .apk files with `apk mkpkg` and update
the repository index with `apk mkndx`. Packaging runs as uid 0 inside a
user namespace so that file owners are recorded as root (apk stores owner
names, resolved through the root's /etc/passwd).
"""

from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from kel.elf import ET_DYN, read_elf
from kel.recipe import Recipe
from kel.sandbox import bwrap_command
from kel.util import KelError, log

# Paths that must be symlinks into /usr (merged /usr, DESIGN.md 4.7) or must
# not be shipped at all.
FORBIDDEN_DIRS = ("bin", "sbin", "lib", "lib64", "usr/sbin", "usr/lib64",
                  "usr/local", "tools", "kel", "tmp", "run", "home", "dev", "proc", "sys")
LEAK_MARKERS = ("/kel/build", "/tools/")


@dataclass
class PackagePart:
    name: str
    summary: str
    root: Path
    depends: list[str] = field(default_factory=list)
    provides: list[str] = field(default_factory=list)
    replaces: list[str] = field(default_factory=list)


def _prune_empty_dirs(root: Path) -> None:
    for d in sorted((p for p in root.rglob("*") if p.is_dir() and not p.is_symlink()),
                    key=lambda p: len(p.parts), reverse=True):
        try:
            d.rmdir()
        except OSError:
            pass


def split_subpackages(recipe: Recipe, destdir: Path, workdir: Path) -> list[PackagePart]:
    parts = []
    for sub in recipe.subpackages:
        subroot = workdir / f"pkg-{sub.suffix}"
        subroot.mkdir(parents=True, exist_ok=True)
        for pattern in sub.files:
            for match in sorted(destdir.glob(pattern)):
                if not (match.exists() or match.is_symlink()):
                    continue  # already moved with a parent directory
                target = subroot / match.relative_to(destdir)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(match), str(target))
        _prune_empty_dirs(subroot)
        # Subpackages (dev, doc, ...) belong with the exact same main package,
        # e.g. a -dev package's libfoo.so symlink points into it.
        parts.append(PackagePart(f"{recipe.name}-{sub.suffix}",
                                 sub.summary or f"{recipe.summary} ({sub.suffix})",
                                 subroot, [f"{recipe.name}={recipe.pkgver}", *sub.depends]))
    _prune_empty_dirs(destdir)
    main = PackagePart(recipe.name, recipe.summary, destdir, list(recipe.depends),
                       list(recipe.provides), list(recipe.replaces))
    return [main, *parts]


def _so_version(filename: str) -> str:
    """Version for a so: provide: libz.so.1.3.1 -> 1.3.1 (0 if none).

    apk only auto-selects providers whose provided name carries a version
    (apk-package(5)), so so: provides are always versioned.
    """
    _, sep, ver = filename.partition(".so.")
    return ver if sep and re.fullmatch(r"[0-9]+(\.[0-9]+)*", ver) else "0"


def scan_shared_objects(root: Path) -> tuple[set[str], set[str], list[str]]:
    """Return (provided so: names, needed so: names, leak problems)."""
    provides: set[str] = set()
    needs: set[str] = set()
    problems: list[str] = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink() or not path.is_file():
            continue
        info = read_elf(path)
        if info is None:
            continue
        rel = "/" + path.relative_to(root).as_posix()
        if info.soname and info.etype == ET_DYN:
            provides.add(f"so:{info.soname}={_so_version(path.name)}")
        needs.update(f"so:{n}" for n in info.needed)
        for rp in info.rpath + info.runpath:
            if any(m in rp for m in LEAK_MARKERS):
                problems.append(f"{rel}: RPATH/RUNPATH points into the build tree: {rp}")
        if info.interpreter and any(m in info.interpreter for m in LEAK_MARKERS):
            problems.append(f"{rel}: interpreter points into the build tree: {info.interpreter}")
    return provides, needs, problems


def check_policy(part: PackagePart) -> list[str]:
    problems = []
    for d in FORBIDDEN_DIRS:
        p = part.root / d
        if p.exists() or p.is_symlink():
            problems.append(f"{part.name}: ships /{d} (must be under /usr or not shipped)")
    if not any(part.root.iterdir()):
        problems.append(f"{part.name}: package is empty")
    return problems


def resolve_dependencies(parts: list[PackagePart]) -> list[str]:
    """Add so: provides/depends; return policy problems found while scanning."""
    problems: list[str] = []
    all_provided: set[str] = set()
    scanned = []
    for part in parts:
        provides, needs, leaks = scan_shared_objects(part.root)
        problems += [f"{part.name}: {msg}" for msg in leaks]
        scanned.append((part, provides, needs))
        all_provided |= provides
    for part, provides, needs in scanned:
        part.provides = sorted(set(part.provides) | provides)
        own = {p.split("=", 1)[0] for p in provides}
        # A subpackage needing a library from its sibling depends on the sibling
        # through so: names, which apk resolves.
        part.depends = sorted(set(part.depends) | (needs - own))
    return problems


def ensure_dev_key(keydir: Path) -> tuple[Path, Path]:
    """Throwaway RSA-4096 signing key for development builds (D-014, D-019).

    It lives under the work directory, is never committed and is never used
    for anything published.
    """
    priv = keydir / "kel-dev.rsa"
    # Public key in its own directory: apk --keys-dir reads every file there.
    pub = keydir / "trusted" / "kel-dev.rsa.pub"
    pub.parent.mkdir(parents=True, exist_ok=True)
    if not priv.exists():
        subprocess.run(["openssl", "genrsa", "-out", str(priv), "4096"], check=True,
                       capture_output=True)
        priv.chmod(0o600)
    if not pub.exists():
        subprocess.run(["openssl", "rsa", "-in", str(priv), "-pubout", "-out", str(pub)],
                       check=True, capture_output=True)
    return priv, pub


def _run_as_root(argv: list[str], rw: list[Path], env: dict[str, str]) -> None:
    cmd = bwrap_command(argv, chdir=rw[0], env=env, rw_binds=rw, as_root=True)
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise KelError(f"{argv[1]} failed: {(proc.stdout + proc.stderr).strip()}")


def make_apk(apk: Path, part: PackagePart, recipe: Recipe, arch_name: str, outdir: Path,
             key: Path, build_time: str) -> Path:
    outdir.mkdir(parents=True, exist_ok=True)
    out = outdir / f"{part.name}-{recipe.pkgver}.apk"
    argv = [str(apk), "mkpkg", "--files", str(part.root),
            "--info", f"name:{part.name}",
            "--info", f"version:{recipe.pkgver}",
            "--info", f"arch:{arch_name}",
            "--info", f"license:{recipe.license}",
            "--info", f"description:{part.summary}",
            "--info", f"url:{recipe.homepage}",
            "--info", f"origin:{recipe.name}",
            "--info", f"build-time:{build_time}"]
    for key_name, values in (("depends", part.depends), ("provides", part.provides),
                             ("replaces", part.replaces)):
        if values:
            argv += ["--info", f"{key_name}:{' '.join(values)}"]
    argv += ["--sign-key", str(key), "--output", str(out)]
    env = {"PATH": "/usr/bin:/bin", "SOURCE_DATE_EPOCH": build_time}
    _run_as_root(argv, [outdir, part.root.parent, key.parent], env)
    return out


def make_index(apk: Path, repodir: Path, key: Path, pubkey: Path, description: str) -> Path:
    pkgs = sorted(str(p) for p in repodir.glob("*.apk"))
    if not pkgs:
        raise KelError(f"no packages in {repodir}")
    index = repodir / "Packages.adb"
    argv = [str(apk), "--keys-dir", str(pubkey.parent), "mkndx", "--output", str(index),
            "--description", description, "--sign-key", str(key), *pkgs]
    _run_as_root(argv, [repodir, key.parent], {"PATH": "/usr/bin:/bin"})
    log(f"index: {index} ({len(pkgs)} packages)")
    return index


def install_into_root(parts: list[PackagePart], root: Path) -> None:
    """Bootstrap only: copy package contents over the build root (LFS-style)."""
    for part in parts:
        subprocess.run(["cp", "-a", "--remove-destination", f"{part.root}/.", f"{root}/"],
                       check=True)
