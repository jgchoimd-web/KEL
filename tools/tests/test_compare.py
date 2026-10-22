import contextlib
import io
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from kel import cli
from kel.compare import (CONTENTS_IDENTICAL, DIFFERENT, ERROR, IDENTICAL, Comparison, PackageResult,
                         compare_repos, diff_entries, diff_metadata, elf_section_diff,
                         split_package_filename, report, to_json)
from kel.config import Layout, get_arch
from kel.pkg import PackageEntry, PackagePart, ensure_dev_key, make_apk, package_entries
from kel.recipe import Recipe


def find_apk() -> Path | None:
    """kel's host apk (KEL_WORKDIR or ./work) or one on PATH."""
    path = Layout.from_env().host_tools(get_arch("x86_64")) / "bin" / "apk"
    if path.exists():
        return path
    found = shutil.which("apk")
    return Path(found) if found else None


APK = find_apk()
CAN_PACKAGE = bool(APK and shutil.which("bwrap") and shutil.which("openssl"))
EPOCH = "1767225600"


class FileNameTests(unittest.TestCase):
    def test_split(self):
        self.assertEqual(split_package_filename("zlib-1.3.2-r0.apk"), ("zlib", "1.3.2-r0"))
        self.assertEqual(split_package_filename("gcc-dev-16.2.0-r0.apk"), ("gcc-dev", "16.2.0-r0"))
        self.assertEqual(split_package_filename("lib2to3-1-x-2.0_rc1-r3.apk"),
                         ("lib2to3-1-x", "2.0_rc1-r3"))
        for bad in ("Packages.adb", "noversion.apk", "-1.0-r0.apk"):
            self.assertIsNone(split_package_filename(bad), bad)


def entry(kind="file", mode=0o644, digest="a" * 64, size=1, target="", owner="root:root"):
    return PackageEntry(kind, mode, owner, size=size, digest=digest, target=target,
                        mtime=int(EPOCH))


class MetadataTests(unittest.TestCase):
    def test_entries_from_adbdump(self):
        # The shape of `apk adbdump --format json` output (apk-tools 3.0.8).
        meta = {"info": {"name": "demo"}, "paths": [
            {"acl": {"mode": 493, "user": "root", "group": "root"}},
            {"name": "usr/bin", "acl": {"mode": 493, "user": "root", "group": "root"}, "files": [
                {"name": "hello", "acl": {"mode": 2541, "user": "root", "group": "root"},
                 "size": 3, "mtime": 1767225600, "hash": "b" * 64},
                {"name": "hi", "acl": {"mode": 511, "user": "root", "group": "root"},
                 "size": 5, "mtime": 1767225600, "target": "00a0" + b"hello".hex()},
                {"name": "again", "acl": {"mode": 420, "user": "root", "group": "wheel"},
                 "size": 3, "mtime": 1767225600, "hash": "b" * 64,
                 "target": "0080" + b"usr/bin/hello".hex()},
            ]},
        ]}
        entries = package_entries(meta)
        self.assertEqual(sorted(entries), ["/", "/usr/bin", "/usr/bin/again", "/usr/bin/hello",
                                           "/usr/bin/hi"])
        self.assertEqual(entries["/usr/bin/hello"].mode, 0o4755)
        self.assertEqual((entries["/usr/bin/hi"].type, entries["/usr/bin/hi"].target),
                         ("symlink", "hello"))
        self.assertEqual((entries["/usr/bin/again"].type, entries["/usr/bin/again"].target),
                         ("hardlink", "/usr/bin/hello"))
        self.assertEqual(entries["/usr/bin/again"].owner, "root:wheel")
        self.assertEqual(entries["/usr/bin"].type, "dir")

    def test_diff_entries(self):
        a = {"/f": entry(), "/l": entry("symlink", 0o777, "", 5, "hello"), "/gone": entry(),
             "/m": entry(), "/o": entry()}
        b = {"/f": entry(digest="c" * 64), "/l": entry("symlink", 0o777, "", 6, "hello2"),
             "/new": entry(), "/m": entry(mode=0o600), "/o": entry(owner="bin:bin")}
        diffs = {d.path: d.kinds for d in diff_entries(a, b)}
        self.assertEqual(diffs, {"/f": ["content"], "/l": ["target"], "/gone": ["missing"],
                                 "/new": ["missing"], "/m": ["mode"], "/o": ["owner"]})

    def test_diff_metadata(self):
        a = {"info": {"name": "x", "build-time": 1, "hashes": "aa", "depends": ["so:libc.so.6"]},
             "paths": []}
        b = {"info": {"name": "x", "build-time": 2, "hashes": "bb", "depends": ["so:libc.so.6"]},
             "paths": [], "scripts": {"post-install": "x"}}
        self.assertEqual(diff_metadata(a, b), [("build-time", 1, 2),
                                               ("scripts", None, {"post-install": "x"})])


@unittest.skipUnless(shutil.which("cc"), "no C compiler")
class ElfSectionTests(unittest.TestCase):
    def test_sections_that_differ(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            for name, text in (("a", "kel one"), ("b", "KEL TWO")):
                (tmp / f"{name}.c").write_text(
                    f'#include <stdio.h>\nint main(void) {{ return puts("{text}") < 0; }}\n')
                # Same source file name in both builds, so only the string differs.
                shutil.copy(tmp / f"{name}.c", tmp / "main.c")
                subprocess.run(["cc", "-O2", "-o", str(tmp / name), "main.c"], cwd=tmp, check=True)
            a, b = (tmp / "a").read_bytes(), (tmp / "b").read_bytes()
            self.assertIn(".rodata", elf_section_diff(a, b))
            self.assertEqual(elf_section_diff(a, a), [])
            self.assertIsNone(elf_section_diff(a, b"not an ELF file"))


class ReportTests(unittest.TestCase):
    def comparison(self) -> Comparison:
        d = Path("/r")
        c = Comparison(Path("/a"), Path("/b"), only_a={"old": d / "old-1-r0.apk"})
        c.packages = [
            PackageResult("same", IDENTICAL, d / "same-1-r0.apk", d / "same-1-r0.apk", "1" * 64,
                          "1" * 64),
            PackageResult("resigned", CONTENTS_IDENTICAL, d / "resigned-1-r0.apk",
                          d / "resigned-1-r0.apk", "2" * 64, "3" * 64),
            PackageResult("demo", DIFFERENT, d / "demo-1-r0.apk", d / "demo-1-r0.apk", "4" * 64,
                          "5" * 64, metadata=[("build-time", 1, 2)],
                          paths=diff_entries({"/a|b": entry()}, {"/a|b": entry(mode=0o755)})),
            PackageResult("broken", ERROR, d / "broken-1-r0.apk", d / "broken-1-r0.apk",
                          error="apk extract failed"),
        ]
        return c

    def test_report(self):
        text = report(self.comparison())
        self.assertIn("## Different: `demo`", text)
        self.assertIn("| /a\\|b | mode | 0644 | 0755 |", text)
        self.assertIn("| build-time | 1 | 2 |", text)
        self.assertIn("## Contents identical, package file differs", text)
        self.assertIn("## Only in A", text)
        self.assertIn("`broken`: apk extract failed", text)
        self.assertIn("**differences found**", text)

    def test_json(self):
        c = self.comparison()
        data = to_json(c)
        json.dumps(data)  # serializable
        self.assertFalse(data["all_identical"])
        self.assertEqual(data["counts"], {"compared": 4, "identical": 1, "contents_identical": 1,
                                          "different": 1, "error": 1, "only_in_a": 1,
                                          "only_in_b": 0})
        self.assertEqual(data["identical"], ["same"])
        path = data["different"][0]["paths"][0]
        self.assertEqual((path["path"], path["kinds"]), ("/a|b", ["mode"]))
        self.assertEqual((path["a"]["mode"], path["b"]["mode"]), ("0644", "0755"))
        self.assertEqual(data["only_in_a"], [{"name": "old", "file": "old-1-r0.apk"}])
        self.assertFalse(c.identical)
        c.packages, c.only_a = c.packages[:1], {}
        self.assertTrue(c.identical)


@unittest.skipUnless(CAN_PACKAGE, "needs apk, bwrap and openssl")
class RepositoryCompareTests(unittest.TestCase):
    """Real packages made with the host apk, like test_pkg's roundtrip test."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="kelcmp"))
        cls.key, _ = ensure_dev_key(cls.tmp / "keys")
        cls.other_key = cls.tmp / "other" / "other.rsa"
        cls.other_key.parent.mkdir()
        subprocess.run(["openssl", "genrsa", "-out", str(cls.other_key), "2048"], check=True,
                       capture_output=True)
        cls.has_cc = bool(shutil.which("cc"))
        cls.build("A", "base", cls.key, extra="only-a", old_version=True)
        cls.build("B", "base", cls.key, extra="only-b")
        cls.build("A2", "base", cls.key)
        cls.build("C", "changed", cls.key)
        cls.build("D", "base", cls.other_key)

    @classmethod
    def tearDownClass(cls):
        for p in cls.tmp.rglob("*"):
            if p.is_dir() and not p.is_symlink():
                p.chmod(0o755)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    @classmethod
    def tree(cls, root: Path, variant: str) -> None:
        changed = variant == "changed"
        (root / "usr/bin").mkdir(parents=True)
        (root / "usr/share/demo").mkdir(parents=True)
        (root / "usr/bin/hello").write_text("#!/bin/sh\necho hello\n")
        (root / "usr/bin/hello").chmod(0o755)
        (root / "usr/bin/hi").symlink_to("hello2" if changed else "hello")
        (root / "usr/share/demo/data.txt").write_text("DATA\n" if changed else "data\n")
        (root / "usr/share/demo/mode").write_text("m\n")
        (root / "usr/share/demo/mode").chmod(0o600 if changed else 0o644)
        (root / "usr/share/demo/new" if changed else root / "usr/share/demo/gone").write_text("x\n")
        # Awkward modes: unpacking must still work for an unprivileged user.
        (root / "usr/share/ro").mkdir()
        (root / "usr/share/ro/inside").write_text("inside\n")
        (root / "usr/share/ro").chmod(0o555)
        (root / "usr/share/secret").write_text("secret\n")
        # apk mkpkg can only read a mode 0000 file as real root.
        (root / "usr/share/secret").chmod(0o000 if os.geteuid() == 0 else 0o400)
        if cls.has_cc:
            src = root.parent / f"{root.name}.src"
            src.mkdir()
            text = "KEL CHANGED" if changed else "kel base"
            (src / "main.c").write_text(
                f'#include <stdio.h>\nint main(void) {{ return puts("{text}") < 0; }}\n')
            subprocess.run(["cc", "-O2", "-o", str(root / "usr/bin/prog"), "main.c"], cwd=src,
                           check=True)

    @classmethod
    def build(cls, repo: str, variant: str, key: Path, extra: str | None = None,
              old_version: bool = False) -> None:
        out = cls.tmp / repo / "x86_64"
        packages = [("demo", "1.0"), ("same", "1.0")]
        if extra:
            packages.append((extra, "1.0"))
        if old_version:
            packages.append(("demo", "0.9"))
        for name, version in packages:
            root = cls.tmp / "roots" / repo / f"{name}-{version}" / "root"
            if name == "demo" and version == "1.0":
                cls.tree(root, variant)
            else:
                (root / "usr/share" / name).mkdir(parents=True)
                (root / "usr/share" / name / "README").write_text(f"{name} {version}\n")
            recipe = Recipe(name=name, version=version, revision=0, summary=name, license="MIT",
                            homepage="https://example.org/", sources=())
            make_apk(APK, PackagePart(name, name, root), recipe, "x86_64", out, key, EPOCH)
            for d in root.rglob("*"):  # let tearDownClass remove read-only directories
                if d.is_dir():
                    d.chmod(0o755)

    def compare(self, a: str, b: str):
        with contextlib.redirect_stderr(io.StringIO()):  # progress lines
            return compare_repos(APK, self.tmp / a, self.tmp / b, "x86_64")

    def test_identical_builds(self):
        result = self.compare("A", "A2")
        self.assertEqual({p.name: p.status for p in result.packages},
                         {"demo": IDENTICAL, "same": IDENTICAL})
        self.assertEqual(sorted(result.only_a), ["only-a"])
        self.assertTrue(any("demo has 2 versions" in n for n in result.notes), result.notes)
        self.assertEqual(result.packages[0].a.name, "demo-1.0-r0.apk")  # the newer one
        self.assertFalse(result.identical)  # only-a is missing in A2
        result = self.compare("A2", "A2")
        self.assertTrue(result.identical)

    def test_only_in_one_repository(self):
        result = self.compare("A", "B")
        self.assertEqual((sorted(result.only_a), sorted(result.only_b)), (["only-a"], ["only-b"]))
        self.assertTrue(all(p.status == IDENTICAL for p in result.packages))

    def test_changed_build(self):
        result = self.compare("A2", "C")
        status = {p.name: p for p in result.packages}
        self.assertEqual(status["same"].status, IDENTICAL)
        demo = status["demo"]
        self.assertEqual(demo.status, DIFFERENT, demo.error)
        kinds = {d.path: d.kinds for d in demo.paths}
        self.assertEqual(kinds["/usr/share/demo/data.txt"], ["content"])
        self.assertEqual(kinds["/usr/share/demo/mode"], ["mode"])
        self.assertEqual(kinds["/usr/share/demo/gone"], ["missing"])
        self.assertEqual(kinds["/usr/share/demo/new"], ["missing"])
        self.assertEqual(kinds["/usr/bin/hi"], ["target"])
        self.assertNotIn("/usr/share/ro/inside", kinds)
        self.assertNotIn("/usr/share/secret", kinds)
        if self.has_cc:
            prog = next(d for d in demo.paths if d.path == "/usr/bin/prog")
            self.assertEqual(prog.kinds, ["content"])
            self.assertIn(".rodata", prog.elf_sections)
        self.assertFalse(result.identical)

    def test_other_signing_key(self):
        result = self.compare("A2", "D")
        self.assertEqual({p.name: p.status for p in result.packages},
                         {"demo": CONTENTS_IDENTICAL, "same": CONTENTS_IDENTICAL})
        self.assertFalse(result.identical)

    def test_cli(self):
        work = self.tmp / "work"
        tools = work / "x86_64" / "host-tools" / "bin"
        tools.mkdir(parents=True, exist_ok=True)
        if not (tools / "apk").exists():
            (tools / "apk").symlink_to(APK)
        summary = self.tmp / "summary.json"
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            rc = cli.main(["--workdir", str(work), "compare", str(self.tmp / "A2"),
                           str(self.tmp / "C"), "--json", str(summary)])
        self.assertEqual(rc, 1)
        self.assertIn("## Different: `demo`", out.getvalue())
        data = json.loads(summary.read_text())
        self.assertEqual(data["counts"]["different"], 1)
        self.assertEqual(data["identical"], ["same"])
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            rc = cli.main(["--workdir", str(work), "compare", str(self.tmp / "A2" / "x86_64"),
                           str(self.tmp / "A2")])
        self.assertEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()
