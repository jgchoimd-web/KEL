import io
import os
import tarfile
import tempfile
import unittest
from pathlib import Path

from kel.bootstrap import load_stage, prepare_sysroot, unpack_sources
from kel.config import REPO_ROOT, Layout, get_arch
from kel.recipe import Recipe, Source
from kel.sandbox import bwrap_command, bwrap_root_command
from kel.util import KelError, version_at_least


def make_tarball(path: Path, top: str, files: dict[str, str]) -> None:
    with tarfile.open(path, "w:gz") as tar:
        for name, text in files.items():
            data = text.encode()
            info = tarfile.TarInfo(f"{top}/{name}")
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))


class SysrootTests(unittest.TestCase):
    def test_merged_usr_layout_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            layout = Layout(repo=REPO_ROOT, workdir=Path(tmp), cachedir=Path(tmp) / "c")
            arch = get_arch("x86_64")
            root = prepare_sysroot(layout, arch)
            prepare_sysroot(layout, arch)
            self.assertEqual(os.readlink(root / "lib64"), "usr/lib")
            self.assertEqual(os.readlink(root / "sbin"), "usr/bin")
            self.assertEqual(os.readlink(root / "usr" / "sbin"), "bin")
            self.assertTrue((root / "tools").is_dir())

    def test_conflicting_entry_is_an_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            layout = Layout(repo=REPO_ROOT, workdir=Path(tmp), cachedir=Path(tmp) / "c")
            arch = get_arch("aarch64")
            (layout.sysroot(arch) / "lib").mkdir(parents=True)
            with self.assertRaises(KelError):
                prepare_sysroot(layout, arch)


class UnpackTests(unittest.TestCase):
    def test_main_and_dest_sources(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            make_tarball(tmp / "main.tar.gz", "main-1.0", {"configure": "#!/bin/sh\n"})
            make_tarball(tmp / "dep.tar.gz", "dep-2.0", {"README": "dep\n"})
            recipe = Recipe(name="main", version="1.0", revision=0, summary="s", license="MIT",
                            homepage="https://example.org/", sources=(
                                Source("https://e/main.tar.gz", "0" * 64, "main.tar.gz"),
                                Source("https://e/dep.tar.gz", "1" * 64, "dep.tar.gz", dest="dep")))
            work = tmp / "work"
            work.mkdir()
            src = unpack_sources(recipe, [tmp / "main.tar.gz", tmp / "dep.tar.gz"], work)
            self.assertTrue((src / "configure").is_file())
            self.assertEqual((src / "dep" / "README").read_text(), "dep\n")
            self.assertEqual(sorted(p.name for p in work.iterdir()), ["src"])

    def test_plain_file_sources_are_copied(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            make_tarball(tmp / "main.tar.gz", "main-1.0", {"configure": "#!/bin/sh\n"})
            (tmp / "fix-001").write_text("--- a\n+++ b\n")
            recipe = Recipe(name="main", version="1.0", revision=0, summary="s", license="MIT",
                            homepage="https://example.org/", sources=(
                                Source("https://e/main.tar.gz", "0" * 64, "main.tar.gz"),
                                Source("https://e/fix-001", "1" * 64, "fix-001")))
            work = tmp / "work"
            work.mkdir()
            unpack_sources(recipe, [tmp / "main.tar.gz", tmp / "fix-001"], work)
            self.assertEqual((work / "sources" / "fix-001").read_text(), "--- a\n+++ b\n")


class NativeRecipeTests(unittest.TestCase):
    def test_files_dir_becomes_source_tree(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            rdir = tmp / "recipes" / "native"
            (rdir / "files" / "etc").mkdir(parents=True)
            (rdir / "files" / "etc" / "issue").write_text("KEL\n")
            recipe = Recipe(name="native", version="1", revision=0, summary="s", license="MIT",
                            homepage="https://example.org/", sources=(),
                            path=rdir / "recipe.toml")
            work = tmp / "work"
            work.mkdir()
            src = unpack_sources(recipe, [], work)
            self.assertEqual((src / "etc" / "issue").read_text(), "KEL\n")


class StageDefinitionTests(unittest.TestCase):
    def test_stage1_definition(self):
        layout = Layout.from_env()
        stage = load_stage(layout, "stage1")
        self.assertEqual(stage.steps[0].label, "binutils:pass1")
        self.assertEqual(stage.steps[-1].label, "gcc:libstdcxx")
        self.assertIn("STAGE1 VERIFY OK", stage.verify)


class SandboxTests(unittest.TestCase):
    def test_root_mode_hides_host(self):
        cmd = bwrap_root_command(["/bin/true"], root=Path("/r"), chdir="/kel/build",
                                 env={}, binds=[(Path("/w"), "/kel/build")])
        self.assertEqual(cmd[cmd.index("--uid") + 1], "0")
        i = cmd.index("/r")
        self.assertEqual(cmd[i - 1:i + 2], ["--bind", "/r", "/"])
        ro = [cmd[k + 1] for k, a in enumerate(cmd) if a == "--ro-bind"]
        self.assertEqual(ro, ["/sys"])  # the host's / is never bound, only /sys read-only
        self.assertIn("--unshare-all", cmd)

    def test_no_network_and_clean_env(self):
        cmd = bwrap_command(["/bin/true"], chdir=Path("/w"), env={"A": "1"},
                            rw_binds=[Path("/w")])
        self.assertIn("--unshare-all", cmd)
        self.assertNotIn("--share-net", cmd)
        self.assertIn("--clearenv", cmd)
        self.assertEqual(cmd[cmd.index("--setenv") + 1:cmd.index("--setenv") + 3], ["A", "1"])
        self.assertEqual(cmd[-2:], ["--", "/bin/true"])


class VersionTests(unittest.TestCase):
    def test_compare(self):
        self.assertTrue(version_at_least("2.47", "2.13.1"))
        self.assertTrue(version_at_least("2.5.1a", "2.5.1a"))
        self.assertFalse(version_at_least("1.4.9", "1.4.10"))
        self.assertTrue(version_at_least("13.3.0", "5.4"))


if __name__ == "__main__":
    unittest.main()
