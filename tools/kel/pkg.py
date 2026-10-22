"""From a build's DESTDIR to signed apk packages and a signed index.

Steps: split subpackages, derive "so:" provides/depends from ELF files,
check the packaging policy, create .apk files with `apk mkpkg` and update
the repository index with `apk mkndx`. Packaging runs as uid 0 inside a
user namespace so that file owners are recorded as root (apk stores owner
names, resolved through the root's /etc/passwd).

Reading packages back (for `kel sbom` and `kel compare`) also goes through
apk itself: `apk adbdump` for the metadata and `apk extract` for the files.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import stat
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from kel.elf import ET_DYN, read_elf
from kel.recipe import Recipe
from kel.sandbox import bwrap_command, bwrap_root_command
from kel.util import KelError, log

# Merged /usr (DESIGN.md 4.7): these paths may only be shipped as exactly
# these symlinks (by the filesystem package), never as directories.
MERGED_LINKS = {"bin": "usr/bin", "sbin": "usr/bin", "lib": "usr/lib", "lib64": "usr/lib",
                "usr/sbin": "bin", "usr/lib64": "lib", "var/run": "../run",
                "var/lock": "../run/lock"}
# Mount points, runtime, home and site-local paths: empty directories only.
EMPTY_ONLY = ("usr/local", "opt", "tmp", "var/tmp", "run", "home", "root", "dev", "proc",
              "sys", "mnt", "media", "srv")
# Bootstrap and build locations that must never reach a package.
NEVER_SHIPPED = ("tools", "kel")
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
    for rel, target in MERGED_LINKS.items():
        p = part.root / rel
        if p.is_symlink():
            if os.readlink(p) != target:
                problems.append(f"{part.name}: /{rel} must be a symlink to {target}")
        elif p.exists():
            problems.append(f"{part.name}: ships /{rel} (must be under /usr)")
    for rel in EMPTY_ONLY:
        p = part.root / rel
        if p.is_symlink() or (p.exists() and not p.is_dir()):
            problems.append(f"{part.name}: /{rel} must be a directory")
        elif p.is_dir():
            content = [c for c in p.rglob("*") if c.is_symlink() or not c.is_dir()]
            if content:
                problems.append(f"{part.name}: ships files under /{rel} "
                                f"(e.g. /{content[0].relative_to(part.root)})")
    for rel in NEVER_SHIPPED:
        p = part.root / rel
        if p.exists() or p.is_symlink():
            problems.append(f"{part.name}: ships /{rel} (build location)")
    if not any(part.root.iterdir()):
        problems.append(f"{part.name}: package is empty")
    return problems


def package_files(part: PackagePart) -> list[str]:
    """Absolute paths of everything a package ships except directories."""
    return sorted("/" + p.relative_to(part.root).as_posix()
                  for p in part.root.rglob("*") if p.is_symlink() or not p.is_dir())


def check_conflicts(parts: list[PackagePart], manifest_dir: Path) -> list[str]:
    """Report files that another package in the repository already ships.

    apk refuses to install two packages that own the same path, so this is
    caught when the package is built instead of when it is installed.
    """
    own = {part.name for part in parts}
    claimed: dict[str, str] = {}
    for manifest in sorted(manifest_dir.glob("*.json")) if manifest_dir.is_dir() else ():
        data = json.loads(manifest.read_text())
        if data["name"] not in own:
            claimed.update((f, data["name"]) for f in data["files"])
    return [f"{part.name}: {f} is already shipped by {claimed[f]}"
            for part in parts for f in package_files(part) if f in claimed]


def write_manifests(parts: list[PackagePart], manifest_dir: Path, version: str) -> None:
    manifest_dir.mkdir(parents=True, exist_ok=True)
    for part in parts:
        data = {"name": part.name, "version": version, "files": package_files(part)}
        (manifest_dir / f"{part.name}.json").write_text(json.dumps(data, indent=1) + "\n")


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


def dev_key_paths(keydir: Path) -> tuple[Path, Path]:
    """(private key, public key) of the development signing key in keydir."""
    # Public key in its own directory: apk --keys-dir reads every file there.
    return keydir / "kel-dev.rsa", keydir / "trusted" / "kel-dev.rsa.pub"


def ensure_dev_key(keydir: Path) -> tuple[Path, Path]:
    """Throwaway RSA-4096 signing key for development builds (D-014, D-019).

    It lives under the work directory, is never committed and is never used
    for anything published.
    """
    priv, pub = dev_key_paths(keydir)
    pub.parent.mkdir(parents=True, exist_ok=True)
    if not priv.exists():
        subprocess.run(["openssl", "genrsa", "-out", str(priv), "4096"], check=True,
                       capture_output=True)
        priv.chmod(0o600)
    if not pub.exists():
        subprocess.run(["openssl", "rsa", "-in", str(priv), "-pubout", "-out", str(pub)],
                       check=True, capture_output=True)
    return priv, pub


# Where host directories appear when apk runs from a tools root. /run is a
# fresh tmpfs in the sandbox, so the mount points are not created in the
# (read-only) tools root itself.
HOST_PREFIX = "/run/host"


def _outermost(paths: list[Path]) -> list[Path]:
    """Drop paths inside another listed path; parents come first."""
    out: list[Path] = []
    for p in sorted({Path(p) for p in paths}, key=lambda p: (len(p.parts), str(p))):
        if not p.is_absolute():
            raise KelError(f"apk sandbox paths must be absolute: {p}")
        if not any(p == q or q in p.parents for q in out):
            out.append(p)
    return out


@dataclass(frozen=True)
class ApkTool:
    """An apk binary and the sandbox it runs in.

    root=None: binary is a host program (the bootstrap's host-tools apk) and
    runs with the host visible read-only (stage 3). Otherwise binary is a
    path inside root, a KEL userland mounted read-only as / (stage 4 on:
    KEL's own apk, nothing from the host is used), and host directories
    appear inside under HOST_PREFIX. Either way apk runs as uid 0 in a user
    namespace, and only the directories given to run() are visible.
    """

    binary: Path
    root: Path | None = None

    def path(self, p: Path) -> str:
        """How apk sees host path p (p must be inside a directory given to run())."""
        return str(p) if self.root is None else HOST_PREFIX + str(p)

    def command(self, applet: str, args: list[str], *, global_args: list[str] = (),
                rw: list[Path] = (), ro: list[Path] = (), chroot_into: Path | None = None,
                env: dict[str, str] | None = None) -> list[str]:
        """The sandboxed apk command line.

        rw/ro are host directories apk may write or read. Writable binds are
        mounted first, so a read-only directory may lie inside a writable one
        but not the other way round. chroot_into is the --root apk installs
        into: apk runs package scripts chrooted there.
        """
        rw, ro = _outermost(list(rw)), _outermost(list(ro))
        for p in rw:
            hidden = [q for q in ro if q == p or q in p.parents]
            if hidden:
                raise KelError(f"cannot bind {p} writable inside read-only {hidden[0]}")
        argv = [str(self.binary), *global_args, applet, *args]
        env = {"PATH": "/usr/bin:/bin", **(env or {})}
        chroot = [self.path(chroot_into)] if chroot_into else []
        if self.root is None:
            return bwrap_command(argv, chdir=Path("/"), env=env, rw_binds=rw, ro_binds=ro,
                                 as_root=True, chroot_into=chroot)
        return bwrap_root_command(argv, root=self.root, chdir="/", env=env,
                                  binds=[(p, self.path(p)) for p in rw],
                                  ro_binds=[(p, self.path(p)) for p in ro],
                                  readonly=True, chroot_into=chroot)

    def run(self, applet: str, args: list[str], *, logfile: Path | None = None,
            **kwargs) -> str:
        """Run apk (see command()); return its standard output.

        With logfile, the whole output goes there instead and "" is returned.
        """
        cmd = self.command(applet, args, **kwargs)
        if logfile is None:
            proc = subprocess.run(cmd, capture_output=True, text=True)
            output = proc.stdout + proc.stderr
        else:
            logfile.parent.mkdir(parents=True, exist_ok=True)
            with open(logfile, "w") as out:
                proc = subprocess.run(cmd, stdout=out, stderr=subprocess.STDOUT, text=True)
            output = logfile.read_text(errors="replace")
        if proc.returncode != 0:
            tail = "\n".join(output.strip().splitlines()[-40:])
            where = f"; log: {logfile}" if logfile else ""
            raise KelError(f"apk {applet} failed (exit {proc.returncode}){where}:\n{tail}")
        return proc.stdout if logfile is None else ""


def _apk_tool(apk: Path | ApkTool) -> ApkTool:
    return apk if isinstance(apk, ApkTool) else ApkTool(apk)


def make_apk(apk: Path | ApkTool, part: PackagePart, recipe: Recipe, arch_name: str,
             outdir: Path, key: Path, build_time: str) -> Path:
    """Create one signed package; apk is a host binary path or an ApkTool."""
    tool = _apk_tool(apk)
    outdir.mkdir(parents=True, exist_ok=True)
    out = outdir / f"{part.name}-{recipe.pkgver}.apk"
    args = ["--files", tool.path(part.root),
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
            args += ["--info", f"{key_name}:{' '.join(values)}"]
    args += ["--sign-key", tool.path(key), "--output", tool.path(out)]
    tool.run("mkpkg", args, rw=[outdir], ro=[part.root, key.parent],
             env={"SOURCE_DATE_EPOCH": build_time})
    return out


def make_index(apk: Path | ApkTool, repodir: Path, key: Path, pubkey: Path,
               description: str) -> Path:
    """Sign a new index of every package in repodir; apk as for make_apk."""
    tool = _apk_tool(apk)
    pkgs = sorted(repodir.glob("*.apk"))
    if not pkgs:
        raise KelError(f"no packages in {repodir}")
    index = repodir / "Packages.adb"
    # --keys-dir must be absolute: a relative one is taken relative to apk's root.
    tool.run("mkndx", ["--output", tool.path(index), "--description", description,
                       "--sign-key", tool.path(key), *(tool.path(p) for p in pkgs)],
             global_args=["--keys-dir", tool.path(pubkey.parent)],
             rw=[repodir], ro=[key.parent, pubkey.parent])
    log(f"index: {index} ({len(pkgs)} packages)")
    return index


def install_into_root(parts: list[PackagePart], root: Path) -> None:
    """Bootstrap only: copy package contents over the build root (LFS-style)."""
    for part in parts:
        subprocess.run(["cp", "-a", "--remove-destination", f"{part.root}/.", f"{root}/"],
                       check=True)


# Reading packages back. The v3 format is only documented through apk's own
# code (DESIGN.md 4.2), so kel never parses .apk files itself.

APK_ENV = {"PATH": "/usr/bin:/bin"}

# File types in a v3 file's "target" field (src/extract_v3.c in apk-tools).
_TARGET_TYPES = {stat.S_IFLNK: "symlink", stat.S_IFREG: "hardlink", stat.S_IFCHR: "char",
                 stat.S_IFBLK: "block", stat.S_IFIFO: "fifo"}


@dataclass(frozen=True)
class PackageEntry:
    """One path of a package as its metadata records it."""

    type: str  # dir, file, hardlink, symlink, char, block or fifo
    mode: int  # permission bits including setuid/setgid/sticky
    owner: str  # "user:group"; apk stores names, not ids
    size: int = 0
    digest: str = ""  # content hash (hex) of regular files: sha256 in v3 packages
    target: str = ""  # symlink target, hard link target (absolute) or device number
    mtime: int = 0
    xattrs: tuple[str, ...] = ()


def package_metadata(apk: Path, package: Path) -> dict:
    """The metadata block of a .apk file as `apk adbdump --format json` shows it.

    "info" holds the package fields (name, version, license, depends, ...)
    and "paths" every directory and file with mode, owner, size, mtime,
    content hash and link target (apk-package(5), apk-v3(5)).
    """
    proc = subprocess.run([str(apk), "adbdump", "--format", "json", str(package)],
                          capture_output=True, env=APK_ENV)
    if proc.returncode != 0:
        raise KelError(f"apk adbdump {package.name} failed: "
                       f"{proc.stderr.decode(errors='replace').strip()}")
    try:
        # apk escapes only quotes, backslashes, newlines and tabs: strict=False
        # takes other control characters, surrogateescape non-UTF-8 file names.
        data = json.loads(proc.stdout.decode("utf-8", "surrogateescape"), strict=False)
    except ValueError as e:
        raise KelError(f"apk adbdump {package.name}: cannot parse the output: {e}")
    if not isinstance(data, dict) or not isinstance(data.get("info"), dict):
        raise KelError(f"{package.name} is not an apk v3 package")
    return data


def _acl(acl: dict) -> tuple[int, str, tuple[str, ...]]:
    return (int(acl.get("mode", 0)), f"{acl.get('user', '')}:{acl.get('group', '')}",
            tuple(acl.get("xattrs", ())))


def package_entries(meta: dict) -> dict[str, PackageEntry]:
    """Every path of a package (absolute, "/" for the root) from its metadata."""
    entries: dict[str, PackageEntry] = {}
    for d in meta.get("paths", []):
        dirname = d.get("name", "")
        mode, owner, xattrs = _acl(d.get("acl", {}))
        entries["/" + dirname] = PackageEntry("dir", mode, owner, xattrs=xattrs)
        for f in d.get("files", []):
            path = f"/{dirname}/{f['name']}" if dirname else f"/{f['name']}"
            mode, owner, xattrs = _acl(f.get("acl", {}))
            kind, target = "file", ""
            if "target" in f:
                # A 16-bit little-endian file type, then the link target or a
                # 64-bit device number.
                raw = bytes.fromhex(f["target"])
                ftype = stat.S_IFMT(int.from_bytes(raw[:2], "little"))
                kind = _TARGET_TYPES.get(ftype, f"type-{ftype:o}")
                if kind in ("symlink", "hardlink"):
                    target = raw[2:].decode("utf-8", "surrogateescape")
                    if kind == "hardlink":
                        target = "/" + target
                else:
                    target = str(int.from_bytes(raw[2:], "little"))
            entries[path] = PackageEntry(kind, mode, owner, size=int(f.get("size", 0)),
                                         digest=f.get("hash", ""), target=target,
                                         mtime=int(f.get("mtime", 0)), xattrs=xattrs)
    return entries


def _make_accessible(root: Path) -> None:
    """Let the caller read and delete an unpacked tree (0555 directories, 0000 files)."""
    stack = [root]
    while stack:
        d = stack.pop()
        os.chmod(d, stat.S_IMODE(os.lstat(d).st_mode) | stat.S_IRWXU)
        with os.scandir(d) as it:
            for entry in it:
                if entry.is_dir(follow_symlinks=False):
                    stack.append(Path(entry.path))
                elif entry.is_file(follow_symlinks=False):
                    mode = entry.stat(follow_symlinks=False).st_mode
                    if not mode & stat.S_IRUSR:
                        os.chmod(entry.path, stat.S_IMODE(mode) | stat.S_IRUSR)


def extract_package(apk: Path, package: Path, dest: Path) -> None:
    """Unpack the files of a package into dest with `apk extract`.

    Nothing is installed and no scripts run. apk runs as uid 0 in a user
    namespace, with CAP_DAC_OVERRIDE inside it so that read-only directories
    in the package do not stop the extraction, and with --no-chown because
    only the caller's own uid is mapped (owners come from the metadata
    instead). Signatures are not checked, since the packages being compared
    may be signed with different keys, but apk still checks every file
    against the hashes in the metadata. Afterwards the caller can read and
    delete everything under dest: owner read is added to files and owner
    rwx to directories; the real modes are in the metadata.
    """
    apk, package = apk.resolve(), package.resolve()
    dest.mkdir(parents=True, exist_ok=True)
    dest = dest.resolve()
    argv = [str(apk), "--allow-untrusted", "extract", "--no-chown", "--destination", str(dest),
            str(package)]
    cmd = bwrap_command(argv, chdir=dest, env=APK_ENV, rw_binds=[dest],
                        ro_binds=sorted({apk.parent, package.parent}), as_root=True,
                        cap_add=["CAP_DAC_OVERRIDE"])
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise KelError(f"apk extract {package.name} failed: {(proc.stdout + proc.stderr).strip()}")
    _make_accessible(dest)
