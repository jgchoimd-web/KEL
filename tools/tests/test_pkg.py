import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from kel.config import REPO_ROOT
from kel.pkg import (PackagePart, check_conflicts, check_policy, ensure_dev_key, make_apk,
                     make_index, resolve_dependencies, split_subpackages, write_manifests)
from kel.recipe import Recipe, Subpackage
from kel.sandbox import bwrap_command

APK = next((p for p in (REPO_ROOT / "work" / "x86_64" / "host-tools" / "bin" / "apk",)
            if p.exists()), None) or (Path(shutil.which("apk")) if shutil.which("apk") else None)


def demo_recipe() -> Recipe:
    return Recipe(name="demo", version="1.0", revision=2, summary="Demo package", license="MIT",
                  homepage="https://example.org/", sources=(),
                  subpackages=(Subpackage("dev", "Demo headers", ("usr/include", "usr/lib/*.so")),))


@unittest.skipUnless(shutil.which("cc"), "no C compiler")
class PackagingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="kelpkg"))
        dest = self.tmp / "pkg"
        (dest / "usr" / "lib").mkdir(parents=True)
        (dest / "usr" / "bin").mkdir(parents=True)
        (dest / "usr" / "include").mkdir(parents=True)
        src = self.tmp / "src"
        src.mkdir()
        (src / "lib.c").write_text('#include <stdio.h>\nint demo(void) { return puts("demo"); }\n')
        (src / "main.c").write_text("int demo(void);\nint main(void) { return demo() < 0; }\n")
        subprocess.run(["cc", "-shared", "-fPIC", "-Wl,-soname,libdemo.so.1", "-o",
                        str(dest / "usr/lib/libdemo.so.1"), "lib.c"], cwd=src, check=True)
        (dest / "usr/lib/libdemo.so").symlink_to("libdemo.so.1")
        subprocess.run(["cc", "-o", str(dest / "usr/bin/demo"), "main.c",
                        f"-L{dest}/usr/lib", "-ldemo"], cwd=src, check=True)
        (dest / "usr/include/demo.h").write_text("int demo(void);\n")
        self.dest = dest

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_split_and_dependencies(self):
        parts = split_subpackages(demo_recipe(), self.dest, self.tmp)
        main, dev = parts
        self.assertEqual(dev.name, "demo-dev")
        self.assertTrue((dev.root / "usr/include/demo.h").exists())
        self.assertTrue((dev.root / "usr/lib/libdemo.so").is_symlink())
        self.assertFalse((main.root / "usr/include").exists())
        self.assertEqual(resolve_dependencies(parts), [])
        self.assertIn("so:libdemo.so.1=1", main.provides)
        self.assertIn("so:libc.so.6", main.depends)
        self.assertNotIn("so:libdemo.so.1", main.depends)
        self.assertEqual(check_policy(main), [])

    def test_policy_rejects_unmerged_paths(self):
        (self.dest / "sbin").mkdir()
        (self.dest / "sbin" / "tool").write_text("x")
        main = split_subpackages(demo_recipe(), self.dest, self.tmp)[0]
        self.assertTrue(any("/sbin" in p for p in check_policy(main)))

    @unittest.skipUnless(APK and shutil.which("bwrap") and shutil.which("openssl"),
                         "needs apk, bwrap and openssl")
    def test_apk_roundtrip(self):
        recipe = demo_recipe()
        parts = split_subpackages(recipe, self.dest, self.tmp)
        resolve_dependencies(parts)
        key, pub = ensure_dev_key(self.tmp / "keys")
        repo = self.tmp / "repo" / "x86_64"
        for part in parts:
            out = make_apk(APK, part, recipe, "x86_64", repo, key, "1767225600")
            self.assertTrue(out.exists(), out)
        # demo needs so:libc.so.6; a stub package provides it in this test repo.
        stub_root = self.tmp / "stub"
        (stub_root / "usr/share/doc/libc-stub").mkdir(parents=True)
        (stub_root / "usr/share/doc/libc-stub/README").write_text("test stub\n")
        stub = Recipe(name="libc-stub", version="1", revision=0, summary="Test stub",
                      license="MIT", homepage="https://example.org/", sources=())
        make_apk(APK, PackagePart("libc-stub", "Test stub", stub_root, provides=["so:libc.so.6=6"]),
                 stub, "x86_64", repo, key, "1767225600")
        make_index(APK, repo, key, pub, "kel-test")
        root = self.tmp / "root"
        (root / "etc/apk/keys").mkdir(parents=True)
        shutil.copy(pub, root / "etc/apk/keys/")
        argv = [str(APK), "--root", str(root), "--initdb", "--arch", "x86_64", "--no-cache",
                "-X", str(repo / "Packages.adb"), "add", "demo-dev"]
        cmd = bwrap_command(argv, chdir=self.tmp, env={"PATH": "/usr/bin:/bin"},
                            rw_binds=[self.tmp], as_root=True)
        proc = subprocess.run(cmd, capture_output=True, text=True)
        self.assertTrue((root / "usr/bin/demo").exists(), proc.stdout + proc.stderr)
        self.assertTrue((root / "usr/include/demo.h").exists())
        self.assertEqual(os.readlink(root / "usr/lib/libdemo.so"), "libdemo.so.1")


class ConflictTests(unittest.TestCase):
    def test_file_shipped_twice(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            for name in ("coreutils", "util-linux"):
                (tmp / name / "usr/bin").mkdir(parents=True)
                (tmp / name / "usr/bin/kill").write_text(name)
            (tmp / "coreutils/usr/bin/ls").write_text("ls")
            manifests = tmp / "manifests"
            first = [PackagePart("coreutils", "s", tmp / "coreutils")]
            self.assertEqual(check_conflicts(first, manifests), [])
            write_manifests(first, manifests, "9.12-r0")
            # Rebuilding the same package is not a conflict.
            self.assertEqual(check_conflicts(first, manifests), [])
            second = [PackagePart("util-linux", "s", tmp / "util-linux")]
            self.assertEqual(check_conflicts(second, manifests),
                             ["util-linux: /usr/bin/kill is already shipped by coreutils"])


class PolicyTests(unittest.TestCase):
    def test_base_layout(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "usr/bin").mkdir(parents=True)
            (root / "bin").symlink_to("usr/bin")
            (root / "tmp").mkdir()
            (root / "usr/local/share/man").mkdir(parents=True)
            part = PackagePart("filesystem", "Base layout", root)
            self.assertEqual(check_policy(part), [])
            (root / "lib64").symlink_to("lib")
            (root / "tmp/stray").write_text("x")
            (root / "kel").mkdir()
            problems = check_policy(part)
            self.assertTrue(any("/lib64 must be a symlink to usr/lib" in p for p in problems),
                            problems)
            self.assertTrue(any("files under /tmp" in p for p in problems), problems)
            self.assertTrue(any("/kel (build location)" in p for p in problems), problems)


if __name__ == "__main__":
    unittest.main()
