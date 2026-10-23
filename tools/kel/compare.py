"""Compare two package repositories: the reproducibility check of stage 5.

Stage 5 rebuilds everything with the stage 4 packages and compares the
result with stage 4 (docs/DESIGN.md section 5). `kel compare A B` matches
the packages of two repositories by name. Packages whose .apk files are
identical are done; for the others both files are read with apk itself
(adbdump for the metadata, extract for the files) and compared:

- package metadata: every field apk records (build-time, depends, ...);
- every path: type, mode, owner, link target, content (sha256), mtime and
  xattrs as the metadata records them, after checking that the unpacked
  files match the metadata (so the hashes are those of the real contents);
- ELF files with different contents: the sections that differ.

If contents and metadata are the same but the .apk files are not, only the
signature or the compression differs. That still counts as a difference:
with the same RSA key apk's signatures are deterministic (D-019), so a
reproducible build gives bit-identical package files.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import stat
import subprocess
import tempfile
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from kel.elf import SHT_NOBITS, read_sections
from kel.pkg import APK_ENV, PackageEntry, extract_package, package_entries, package_metadata
from kel.sandbox import require_bwrap
from kel.util import KelError, log, sha256_file

IDENTICAL = "identical"
CONTENTS_IDENTICAL = "contents-identical"
DIFFERENT = "different"
ERROR = "error"

# Differences of a path, in report order ("missing" means absent on one side).
PATH_KINDS = ("missing", "type", "mode", "owner", "target", "content", "mtime", "xattrs")

# Hash algorithm of a metadata content hash, by length in hex digits.
DIGESTS = {64: "sha256", 40: "sha1", 32: "md5"}

# At most this many rows per package in the Markdown report (the JSON has all).
MAX_REPORT_ROWS = 200

_VERSION_START = re.compile(r"-[0-9]")

_STAT_TYPES = {stat.S_IFDIR: "dir", stat.S_IFREG: "file", stat.S_IFLNK: "symlink",
               stat.S_IFCHR: "char", stat.S_IFBLK: "block", stat.S_IFIFO: "fifo"}


@dataclass
class PathDiff:
    path: str
    kinds: list[str]
    a: PackageEntry | None
    b: PackageEntry | None
    # Contents differ and both are ELF files: the sections that differ
    # ([] if none does, i.e. only headers or padding differ).
    elf_sections: list[str] | None = None


@dataclass
class PackageResult:
    name: str
    status: str
    a: Path
    b: Path
    a_sha256: str = ""
    b_sha256: str = ""
    metadata: list[tuple[str, object, object]] = field(default_factory=list)
    paths: list[PathDiff] = field(default_factory=list)
    error: str = ""


@dataclass
class Comparison:
    a: Path
    b: Path
    packages: list[PackageResult] = field(default_factory=list)
    only_a: dict[str, Path] = field(default_factory=dict)
    only_b: dict[str, Path] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def with_status(self, status: str) -> list[PackageResult]:
        return [p for p in self.packages if p.status == status]

    @property
    def identical(self) -> bool:
        """True if both repositories hold the same packages, bit for bit."""
        return (not self.only_a and not self.only_b
                and all(p.status == IDENTICAL for p in self.packages))


def split_package_filename(filename: str) -> tuple[str, str] | None:
    """("gcc-dev", "16.2.0-r0") from "gcc-dev-16.2.0-r0.apk".

    The version starts at the last "-<digit>" (apk-package(5)).
    """
    if not filename.endswith(".apk"):
        return None
    stem = filename[:-len(".apk")]
    starts = [m.start() for m in _VERSION_START.finditer(stem)]
    if not starts or starts[-1] == 0:
        return None
    return stem[:starts[-1]], stem[starts[-1] + 1:]


def _newer(apk: Path, version: str, than: str) -> bool:
    proc = subprocess.run([str(apk), "version", "-t", version, than], capture_output=True,
                          text=True, env=APK_ENV)
    if proc.returncode != 0:
        raise KelError(f"apk version -t {version} {than} failed: {proc.stderr.strip()}")
    return proc.stdout.strip() == ">"


def find_packages(apk: Path, repo: Path, arch: str) -> tuple[Path, dict[str, Path], list[str]]:
    """The .apk files of a repository, one per package name.

    repo is the directory with the .apk files (work/<arch>/repo/<arch>) or
    its parent (work/<arch>/repo). Old builds stay in the directory, so a
    name may appear with several versions: the newest is used, with a note.
    """
    directory = repo
    if not any(repo.glob("*.apk")) and (repo / arch).is_dir():
        directory = repo / arch
    if not directory.is_dir():
        raise KelError(f"{repo} is not a directory")
    versions: dict[str, list[tuple[str, Path]]] = {}
    notes = []
    for path in sorted(directory.glob("*.apk")):
        parsed = split_package_filename(path.name)
        if parsed is None:
            notes.append(f"{path}: not a <name>-<version>.apk file name, skipped")
            continue
        versions.setdefault(parsed[0], []).append((parsed[1], path))
    if not versions:
        raise KelError(f"no packages (*.apk) in {repo}")
    packages = {}
    for name, found in sorted(versions.items()):
        best_version, best = found[0]
        for version, path in found[1:]:
            if _newer(apk, version, best_version):
                best_version, best = version, path
        if len(found) > 1:
            notes.append(f"{directory}: {name} has {len(found)} versions "
                         f"({', '.join(v for v, _ in found)}); compared {best_version}")
        packages[name] = best
    return directory, packages, notes


def _hash_file(path: Path, algorithm: str) -> str:
    h = hashlib.new(algorithm)
    with open(path, "rb") as f:
        while chunk := f.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()


def _tree_path(tree: Path, path: str) -> Path:
    return tree / path.lstrip("/")


def verify_tree(entries: dict[str, PackageEntry], tree: Path) -> list[str]:
    """Where the unpacked files at tree differ from the package metadata."""
    problems = []
    for path, entry in sorted(entries.items()):
        p = _tree_path(tree, path)
        try:
            st = os.lstat(p)
        except FileNotFoundError:
            problems.append(f"{path}: not unpacked")
            continue
        kind = _STAT_TYPES.get(stat.S_IFMT(st.st_mode), "other")
        expected = "file" if entry.type == "hardlink" else entry.type
        if kind != expected:
            problems.append(f"{path}: unpacked as {kind}, the metadata says {entry.type}")
        elif kind == "symlink" and os.readlink(p) != entry.target:
            problems.append(f"{path}: unpacked link target {os.readlink(p)!r}, "
                            f"the metadata says {entry.target!r}")
        elif kind == "file":
            algorithm = DIGESTS.get(len(entry.digest))
            if algorithm is None:
                problems.append(f"{path}: no content hash in the metadata")
            elif _hash_file(p, algorithm) != entry.digest:
                problems.append(f"{path}: contents do not match the metadata hash")
    for dirpath, dirnames, filenames in os.walk(tree):
        for name in dirnames + filenames:
            rel = "/" + os.path.relpath(os.path.join(dirpath, name), tree)
            if rel not in entries:
                problems.append(f"{rel}: unpacked but not in the metadata")
    return problems


def _entry_values(e: PackageEntry) -> dict[str, object]:
    # Only regular files have contents; a symlink's size is its target's length.
    content = (e.digest, e.size) if e.type in ("file", "hardlink") else None
    return {"type": e.type, "mode": e.mode, "owner": e.owner, "target": e.target,
            "content": content, "mtime": e.mtime, "xattrs": e.xattrs}


def diff_entries(a: dict[str, PackageEntry], b: dict[str, PackageEntry]) -> list[PathDiff]:
    diffs = []
    for path in sorted(a.keys() | b.keys()):
        ea, eb = a.get(path), b.get(path)
        if ea is None or eb is None:
            diffs.append(PathDiff(path, ["missing"], ea, eb))
            continue
        va, vb = _entry_values(ea), _entry_values(eb)
        kinds = [k for k in PATH_KINDS[1:] if va[k] != vb[k]]
        if kinds:
            diffs.append(PathDiff(path, kinds, ea, eb))
    return diffs


def diff_metadata(a: dict, b: dict) -> list[tuple[str, object, object]]:
    """Package fields that differ: "info" (except its hash) and scripts, triggers, ..."""
    diffs = []
    info_a, info_b = a.get("info", {}), b.get("info", {})
    for key in sorted(info_a.keys() | info_b.keys()):
        # "hashes" identifies the whole metadata block; it differs whenever
        # anything else does (checked separately in compare_package).
        if key != "hashes" and info_a.get(key) != info_b.get(key):
            diffs.append((key, info_a.get(key), info_b.get(key)))
    for key in sorted((a.keys() | b.keys()) - {"info", "paths"}):
        if a.get(key) != b.get(key):
            diffs.append((key, a.get(key), b.get(key)))
    return diffs


def elf_section_diff(a: bytes, b: bytes) -> list[str] | None:
    """Names of the ELF sections whose contents differ, or None unless both are ELF."""
    sections_a, sections_b = read_sections(a), read_sections(b)
    if sections_a is None or sections_b is None:
        return None

    def contents(data: bytes, sections) -> dict[str, tuple]:
        result: dict[str, tuple] = {}
        seen: Counter = Counter()
        for s in sections:
            if not s.name:
                continue
            seen[s.name] += 1
            key = s.name if seen[s.name] == 1 else f"{s.name}#{seen[s.name]}"
            body = b"" if s.type == SHT_NOBITS else data[s.offset:s.offset + s.size]
            result[key] = (s.type, s.size, hashlib.sha256(body).digest())
        return result

    ca, cb = contents(a, sections_a), contents(b, sections_b)
    names = []
    for key in list(ca) + [k for k in cb if k not in ca]:
        if key not in cb:
            names.append(f"{key} (only in A)")
        elif key not in ca:
            names.append(f"{key} (only in B)")
        elif ca[key] != cb[key]:
            names.append(key)
    return names


def compare_package(apk: Path, name: str, a: Path, b: Path, workdir: Path) -> PackageResult:
    """Compare two builds of a package; workdir/a/<name> and workdir/b/<name> get the files."""
    result = PackageResult(name, IDENTICAL, a, b, sha256_file(a), sha256_file(b))
    if result.a_sha256 == result.b_sha256:
        return result
    meta_a, meta_b = package_metadata(apk, a), package_metadata(apk, b)
    entries_a, entries_b = package_entries(meta_a), package_entries(meta_b)
    trees = []
    for side, path, entries in (("a", a, entries_a), ("b", b, entries_b)):
        tree = workdir / side / name
        shutil.rmtree(tree, ignore_errors=True)  # apk extract does not overwrite
        extract_package(apk, path, tree)
        problems = verify_tree(entries, tree)
        if problems:
            raise KelError(f"{path}: the unpacked files do not match the package metadata:\n  "
                           + "\n  ".join(problems[:20]))
        trees.append(tree)
    result.metadata = diff_metadata(meta_a, meta_b)
    result.paths = diff_entries(entries_a, entries_b)
    for d in result.paths:
        if ("content" in d.kinds and d.a.type in ("file", "hardlink")
                and d.b.type in ("file", "hardlink")):
            d.elf_sections = elf_section_diff(_tree_path(trees[0], d.path).read_bytes(),
                                              _tree_path(trees[1], d.path).read_bytes())
    if not result.metadata and not result.paths and meta_a != meta_b:
        # Same fields and paths, yet another metadata block (e.g. path order).
        result.metadata.append(("hashes", meta_a["info"].get("hashes"),
                                meta_b["info"].get("hashes")))
    result.status = DIFFERENT if result.metadata or result.paths else CONTENTS_IDENTICAL
    return result


def compare_repos(apk: Path, a: Path, b: Path, arch: str, keep: Path | None = None) -> Comparison:
    """Compare every package present in both repositories.

    With keep, the unpacked files stay in keep/a/<name> and keep/b/<name>
    (e.g. for diffoscope); otherwise each package's files are deleted as
    soon as it has been compared.
    """
    require_bwrap()
    dir_a, packages_a, notes_a = find_packages(apk, a, arch)
    dir_b, packages_b, notes_b = find_packages(apk, b, arch)
    result = Comparison(dir_a, dir_b, notes=notes_a + notes_b,
                        only_a={n: p for n, p in packages_a.items() if n not in packages_b},
                        only_b={n: p for n, p in packages_b.items() if n not in packages_a})
    common = sorted(packages_a.keys() & packages_b.keys())
    with tempfile.TemporaryDirectory(prefix="kel-compare-") as tmp:
        workdir = keep or Path(tmp)
        for n, name in enumerate(common, 1):
            try:
                pr = compare_package(apk, name, packages_a[name], packages_b[name], workdir)
            except KelError as e:
                pr = PackageResult(name, ERROR, packages_a[name], packages_b[name], error=str(e))
            result.packages.append(pr)
            if pr.status != IDENTICAL:
                log(f"[{n}/{len(common)}] {name}: {pr.status}")
            if keep is None:
                for side in ("a", "b"):
                    shutil.rmtree(workdir / side / name, ignore_errors=True)
    return result


# Output

def _entry_json(e: PackageEntry | None) -> dict | None:
    if e is None:
        return None
    data: dict[str, object] = {"type": e.type, "mode": f"{e.mode:04o}", "owner": e.owner}
    if e.type in ("file", "hardlink"):
        data["size"] = e.size
        data[DIGESTS.get(len(e.digest), "hash")] = e.digest
    if e.target:
        data["target"] = e.target
    if e.type != "dir":
        data["mtime"] = e.mtime
    if e.xattrs:
        data["xattrs"] = list(e.xattrs)
    return data


def to_json(c: Comparison) -> dict:
    """Machine-readable summary (see docs/DESIGN.md, kel compare)."""
    def files(p: PackageResult) -> dict:
        return {"name": p.name, "a": p.a.name, "b": p.b.name,
                "a_sha256": p.a_sha256, "b_sha256": p.b_sha256}

    return {
        "a": str(c.a),
        "b": str(c.b),
        "all_identical": c.identical,
        "counts": {
            "compared": len(c.packages),
            "identical": len(c.with_status(IDENTICAL)),
            "contents_identical": len(c.with_status(CONTENTS_IDENTICAL)),
            "different": len(c.with_status(DIFFERENT)),
            "error": len(c.with_status(ERROR)),
            "only_in_a": len(c.only_a),
            "only_in_b": len(c.only_b),
        },
        "identical": [p.name for p in c.with_status(IDENTICAL)],
        "contents_identical": [files(p) for p in c.with_status(CONTENTS_IDENTICAL)],
        "different": [dict(files(p),
                           metadata=[{"field": k, "a": va, "b": vb} for k, va, vb in p.metadata],
                           paths=[{"path": d.path, "kinds": d.kinds, "a": _entry_json(d.a),
                                   "b": _entry_json(d.b), "elf_sections": d.elf_sections}
                                  for d in p.paths])
                      for p in c.with_status(DIFFERENT)],
        "errors": [{"name": p.name, "a": p.a.name, "b": p.b.name, "error": p.error}
                   for p in c.with_status(ERROR)],
        "only_in_a": [{"name": n, "file": p.name} for n, p in sorted(c.only_a.items())],
        "only_in_b": [{"name": n, "file": p.name} for n, p in sorted(c.only_b.items())],
        "notes": c.notes,
    }


def _cell(text: object) -> str:
    return str(text).replace("\\", "\\\\").replace("|", "\\|").replace("\n", " ")


def _value(kind: str, e: PackageEntry | None) -> str:
    if e is None:
        return "(missing)"
    if kind in ("missing", "type"):
        return e.type
    if kind == "mode":
        return f"{e.mode:04o}"
    if kind == "owner":
        return e.owner
    if kind == "target":
        return e.target or "(none)"
    if kind == "content":
        algorithm = DIGESTS.get(len(e.digest), "hash")
        return f"{algorithm} {e.digest[:12]}... ({e.size} bytes)" if e.digest else f"{e.size} bytes"
    if kind == "mtime":
        return str(e.mtime)
    return ", ".join(e.xattrs) or "(none)"


def report(c: Comparison) -> str:
    """Human-readable Markdown report."""
    lines = ["# kel compare", "", f"- A: `{c.a}`", f"- B: `{c.b}`", "",
             "| result | packages |", "|---|---:|"]
    for label, count in (("identical", len(c.with_status(IDENTICAL))),
                         ("contents identical, package file differs",
                          len(c.with_status(CONTENTS_IDENTICAL))),
                         ("different", len(c.with_status(DIFFERENT))),
                         ("error", len(c.with_status(ERROR))),
                         ("only in A", len(c.only_a)),
                         ("only in B", len(c.only_b))):
        lines.append(f"| {label} | {count} |")
    lines += ["", "Result: " + ("**identical**" if c.identical else "**differences found**")]
    if c.notes:
        lines += ["", "Notes:", ""] + [f"- {_cell(n)}" for n in c.notes]
    for title, only in (("Only in A", c.only_a), ("Only in B", c.only_b)):
        if only:
            lines += ["", f"## {title}", ""]
            lines += [f"- `{n}` ({p.name})" for n, p in sorted(only.items())]
    for p in c.with_status(DIFFERENT):
        lines += ["", f"## Different: `{p.name}`", "",
                  f"- A: {p.a.name} (sha256 {p.a_sha256})",
                  f"- B: {p.b.name} (sha256 {p.b_sha256})"]
        if p.metadata:
            lines += ["", "| metadata | A | B |", "|---|---|---|"]
            lines += [f"| {_cell(k)} | {_cell(va)} | {_cell(vb)} |" for k, va, vb in p.metadata]
        if p.paths:
            lines += ["", "| path | difference | A | B |", "|---|---|---|---|"]
            rows = 0
            for d in p.paths:
                for kind in d.kinds:
                    if rows == MAX_REPORT_ROWS:
                        break
                    label = kind
                    if kind == "content" and d.elf_sections is not None:
                        label += ("; ELF sections: " + ", ".join(d.elf_sections) if d.elf_sections
                                  else "; no ELF section differs (headers or padding)")
                    lines.append(f"| {_cell(d.path)} | {_cell(label)} | {_cell(_value(kind, d.a))} "
                                 f"| {_cell(_value(kind, d.b))} |")
                    rows += 1
            total = sum(len(d.kinds) for d in p.paths)
            if total > rows:
                lines += ["", f"... and {total - rows} more (see the JSON summary)"]
    same = c.with_status(CONTENTS_IDENTICAL)
    if same:
        lines += ["", "## Contents identical, package file differs", "",
                  "Contents and metadata are the same; the .apk files differ in the signature "
                  "or the compression.", ""]
        lines += [f"- `{p.name}`: {p.a.name} (sha256 {p.a_sha256}) / {p.b.name} "
                  f"(sha256 {p.b_sha256})" for p in same]
    errors = c.with_status(ERROR)
    if errors:
        lines += ["", "## Errors", ""] + [f"- `{p.name}`: {_cell(p.error)}" for p in errors]
    identical = c.with_status(IDENTICAL)
    if identical:
        lines += ["", "## Identical", "", ", ".join(f"`{p.name}`" for p in identical)]
    return "\n".join(lines) + "\n"
