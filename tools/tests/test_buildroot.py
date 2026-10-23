import dataclasses
import json
import os
import re
import shutil
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest import mock

from kel.bootstrap import load_stage, merged_usr_links, package_into_repo
from kel.buildroot import (TOOLS_APK, build_command, compose_root, index_packages, rebuild_package,
                           remove_tree)
from kel.config import REPO_ROOT, Layout, get_arch
from kel.pkg import HOST_PREFIX, ApkTool, PackagePart, ensure_dev_key, make_apk, make_index
from kel.recipe import BuildSpec, Recipe, Subpackage
from kel.util import KelError

APK = next((p for p in (REPO_ROOT / "work" / "x86_64" / "host-tools" / "bin" / "apk",)
            if p.exists()), None) or (Path(shutil.which("apk")) if shutil.which("apk") else None)
HAVE_APK = bool(APK and shutil.which("bwrap") and shutil.which("openssl"))
BUSYBOX = shutil.which("busybox")  # a static shell for package scripts, if the host has one
X86 = get_arch("x86_64")
BUILD_TIME = "1767225600"

_KEYS: Path | None = None


def dev_keys(dest: Path) -> tuple[Path, Path]:
    """ensure_dev_key(dest), generating the RSA-4096 key only once per test run."""
    global _KEYS
    if _KEYS is None:
        _KEYS = Path(tempfile.mkdtemp(prefix="kelkeys"))
        ensure_dev_key(_KEYS)
    shutil.copytree(_KEYS, dest, dirs_exist_ok=True)
    return ensure_dev_key(dest)


def tearDownModule():
    if _KEYS is not None:
        shutil.rmtree(_KEYS, ignore_errors=True)


def recipe(name: str, **kw) -> Recipe:
    return Recipe(name=name, version="1.0", revision=0, summary=f"{name} test package",
                  license="MIT", homepage="https://example.org/", sources=(), **kw)


def opts(cmd: list[str], option: str) -> list[list[str]]:
    """Arguments of every occurrence of a two-argument bwrap option."""
    return [cmd[i + 1:i + 3] for i, a in enumerate(cmd) if a == option]


def opt1(cmd: list[str], option: str) -> list[str]:
    """Arguments of every occurrence of a one-argument bwrap option."""
    return [cmd[i + 1] for i, a in enumerate(cmd) if a == option]


def last_mount(cmd: list[str]) -> int:
    mounts = ("--bind", "--ro-bind", "--dev", "--proc", "--tmpfs")
    return max(i for i, a in enumerate(cmd) if a in mounts)


class StageKindTests(unittest.TestCase):
    REBUILD = '''
        [stage]
        kind = "rebuild"
        input_repo = "repo"
        output_repo = "repo-s"
        tools_root = "sysroot"
        '''

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.layout = Layout(repo=root, workdir=root / "work", cachedir=root / "cache")
        (root / "bootstrap").mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def load(self, stage: str, steps: str = '[[step]]\nrecipe = "zlib"\nprofile = "package"\n'):
        (self.layout.bootstrap_defs / "s.toml").write_text(textwrap.dedent(stage) + "\n" + steps)
        return load_stage(self.layout, "s")

    def test_rebuild_stage(self):
        stage = self.load(self.REBUILD)
        self.assertEqual(stage.kind, "rebuild")
        self.assertEqual((stage.input_repo, stage.output_repo, stage.tools_root),
                         ("repo", "repo-s", "sysroot"))
        self.assertEqual(stage.root, "sysroot")  # a root is /, nothing from the host
        stage = self.load(self.REBUILD.replace('"sysroot"', '"buildroots/stage4"'))
        self.assertEqual(stage.tools_root, "buildroots/stage4")

    def test_build_stage_is_the_default(self):
        stage = self.load('[stage]\nroot = "sysroot"\n')
        self.assertEqual((stage.kind, stage.output_repo), ("build", ""))

    def assertRejected(self, stage: str, fragment: str, steps: str | None = None):
        with self.assertRaises(KelError) as cm:
            self.load(stage) if steps is None else self.load(stage, steps)
        self.assertIn(fragment, str(cm.exception))

    def test_bad_rebuild_stages(self):
        self.assertRejected(self.REBUILD.replace('output_repo = "repo-s"', ""), "needs output_repo")
        self.assertRejected(self.REBUILD.replace('"repo-s"', '"repo"'), "must differ")
        self.assertRejected(self.REBUILD + 'root = "host"\n', "drop 'root'")
        self.assertRejected(self.REBUILD.replace('"repo-s"', '"../x"'), "bad output_repo")
        self.assertRejected(self.REBUILD.replace('"repo-s"', '"a/b"'), "bad output_repo")
        self.assertRejected(self.REBUILD.replace('"sysroot"', '"../sysroot"'), "bad tools_root")
        self.assertRejected(self.REBUILD.replace('"sysroot"', '"/sysroot"'), "bad tools_root")
        self.assertRejected(self.REBUILD, "only has package steps",
                            '[[step]]\nrecipe = "zlib"\nprofile = "stage3"\n')
        self.assertRejected(self.REBUILD.replace('"rebuild"', '"rebuilt"'), "kind must be")
        self.assertRejected('[stage]\ninput_repo = "repo"\n', 'only apply to kind = "rebuild"')

    def test_stage4_definition(self):
        stage = load_stage(Layout.from_env(), "stage4")
        self.assertEqual(stage.kind, "rebuild")
        self.assertEqual((stage.input_repo, stage.output_repo, stage.tools_root),
                         ("repo", "repo-stage4", "sysroot"))
        self.assertEqual(stage.steps[0].label, "filesystem:package")
        self.assertIn("STAGE4 VERIFY OK", stage.verify)

    def test_stage4_mirrors_stage3b(self):
        """Stage 4 rebuilds the package steps of stage 3b, in the same order."""
        layout = Layout.from_env()
        if not (layout.bootstrap_defs / "stage3b.toml").exists():
            self.skipTest("bootstrap/stage3b.toml does not exist yet")
        expected: list[str] = []
        for step in load_stage(layout, "stage3b").steps:
            if step.profile == "package" and step.recipe not in expected:
                expected.append(step.recipe)
        self.assertEqual([s.recipe for s in load_stage(layout, "stage4").steps], expected)


class SandboxCommandTests(unittest.TestCase):
    def test_build_root_is_read_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            (work / "src").mkdir()
            env = {"PATH": "/usr/bin:/usr/sbin", "HOME": "/root", "DESTDIR": "/kel/build/pkg"}
            cmd = build_command(["/bin/bash", "-c", "true"], root=Path("/r"), workdir=work,
                                env=env, recipe_dir=Path("/rd"), config_site=Path("/cs"))
        self.assertIn(["/r", "/"], opts(cmd, "--bind"))
        self.assertEqual(opt1(cmd, "--remount-ro"), ["/"])
        # Last, so that it only makes / read-only, not the binds.
        self.assertGreater(cmd.index("--remount-ro"), last_mount(cmd))
        self.assertIn([str(work), "/kel/build"], opts(cmd, "--bind"))
        self.assertIn(["/rd", "/kel/recipe"], opts(cmd, "--ro-bind"))
        self.assertIn(["/cs", "/kel/config.site"], opts(cmd, "--ro-bind"))
        self.assertIn("/tmp", opt1(cmd, "--tmpfs"))
        self.assertIn("--unshare-all", cmd)
        self.assertNotIn("--share-net", cmd)
        self.assertNotIn("--cap-add", cmd)
        setenv = dict(tuple(x) for x in opts(cmd, "--setenv"))
        self.assertEqual(setenv["HOME"], "/kel/build/.home")  # / is read-only
        self.assertEqual(setenv["KEL_WORKDIR"], "/kel/build")
        self.assertEqual(setenv["KEL_SRCDIR"], "/kel/build/src")
        self.assertEqual(setenv["KEL_RECIPEDIR"], "/kel/recipe")
        self.assertEqual(setenv["CONFIG_SITE"], "/kel/config.site")
        self.assertEqual(setenv["DESTDIR"], "/kel/build/pkg")
        self.assertEqual(opt1(cmd, "--chdir"), ["/kel/build/src"])
        self.assertEqual(cmd[-4:], ["--", "/bin/bash", "-c", "true"])

    def test_apk_from_tools_root(self):
        tool = ApkTool(TOOLS_APK, root=Path("/w/sysroot"))
        target, repo, keys = Path("/w/root"), Path("/w/repo/x86_64"), Path("/w/keys/trusted")
        cmd = tool.command("add", ["zlib"], global_args=["--root", tool.path(target)],
                           rw=[target], ro=[repo, keys], chroot_into=target)
        self.assertEqual(tool.path(target), HOST_PREFIX + "/w/root")
        self.assertIn(["/w/sysroot", "/"], opts(cmd, "--bind"))
        self.assertIn(["/w/root", "/run/host/w/root"], opts(cmd, "--bind"))
        self.assertIn(["/w/repo/x86_64", "/run/host/w/repo/x86_64"], opts(cmd, "--ro-bind"))
        self.assertIn(["/w/keys/trusted", "/run/host/w/keys/trusted"], opts(cmd, "--ro-bind"))
        # Package scripts: apk chroots into the target, which gets /proc and /dev.
        self.assertEqual(opt1(cmd, "--cap-add"), ["CAP_SYS_CHROOT"])
        self.assertIn("/run/host/w/root/proc", opt1(cmd, "--proc"))
        self.assertIn("/run/host/w/root/dev", opt1(cmd, "--dev"))
        self.assertEqual(opt1(cmd, "--remount-ro"), ["/"])
        self.assertGreater(cmd.index("--remount-ro"), last_mount(cmd))
        self.assertEqual(cmd[-5:], ["/usr/bin/apk", "--root", "/run/host/w/root", "add", "zlib"])

    def test_apk_on_the_host(self):
        tool = ApkTool(Path("/opt/apk"))
        cmd = tool.command("mkndx", ["x"], rw=[Path("/w/repo")], ro=[Path("/w/keys")])
        self.assertIn(["/", "/"], opts(cmd, "--ro-bind"))
        self.assertIn(["/w/repo", "/w/repo"], opts(cmd, "--bind"))
        self.assertIn(["/w/keys", "/w/keys"], opts(cmd, "--ro-bind"))
        self.assertEqual(opt1(cmd, "--uid"), ["0"])
        self.assertNotIn("--cap-add", cmd)
        self.assertNotIn("--remount-ro", cmd)
        self.assertEqual(cmd[-3:], ["/opt/apk", "mkndx", "x"])

    def test_bind_plan(self):
        tool = ApkTool(Path("/opt/apk"))
        cmd = tool.command("x", [], ro=[Path("/w/keys/trusted"), Path("/w/keys")])
        self.assertEqual([b for b in opts(cmd, "--ro-bind") if b[0].startswith("/w")],
                         [["/w/keys", "/w/keys"]])
        with self.assertRaises(KelError):  # it would be hidden by the read-only bind
            tool.command("x", [], rw=[Path("/w/keys/new")], ro=[Path("/w/keys")])
        with self.assertRaises(KelError):
            tool.command("x", [], rw=[Path("relative")])


class FakeApk:
    """Records what compose_root asks apk to do, and the root's links at that time."""

    root = None

    def __init__(self, target: Path, arch):
        self.target, self.arch, self.calls = target, arch, []

    def path(self, p: Path) -> str:
        return str(p)

    def run(self, applet, args, **kw):
        links = {name: os.readlink(self.target / name)
                 for name in merged_usr_links(self.arch) if (self.target / name).is_symlink()}
        # apk writes its database through lib -> usr/lib: no link may dangle.
        links = {name: dest for name, dest in links.items() if (self.target / name).is_dir()}
        self.calls.append((applet, list(kw["global_args"]), list(args), links))
        return ""


class ComposeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="kelroot"))
        self.repo = self.tmp / "repo" / "x86_64"
        self.repo.mkdir(parents=True)
        (self.repo / "Packages.adb").write_bytes(b"")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_links_exist_before_initdb(self):
        for arch in (X86, get_arch("aarch64")):
            target = self.tmp / f"root-{arch.name}"
            tool = FakeApk(target, arch)
            compose_root(tool, target, arch, self.repo, self.tmp / "keys", ["filesystem", "zlib"])
            [(applet, global_args, args, links)] = tool.calls
            self.assertEqual(links, merged_usr_links(arch))  # already there when apk ran
            self.assertEqual(arch.name == "x86_64", "lib64" in links)
            self.assertEqual((applet, args), ("add", ["filesystem", "zlib"]))
            self.assertEqual(global_args[:3], ["--root", str(target), "--initdb"])
            self.assertIn("--no-cache", global_args)
            self.assertIn("--no-logfile", global_args)
            self.assertEqual(global_args[global_args.index("--arch") + 1], arch.name)
            self.assertEqual(global_args[global_args.index("--keys-dir") + 1],
                             str(self.tmp / "keys"))
            self.assertEqual(global_args[global_args.index("--repository") + 1],
                             str(self.repo / "Packages.adb"))

    def test_target_must_be_empty(self):
        target = self.tmp / "root"
        (target / "etc").mkdir(parents=True)
        with self.assertRaises(KelError):
            compose_root(FakeApk(target, X86), target, X86, self.repo, self.tmp, ["zlib"])


class RepoTestCase(unittest.TestCase):
    """A temporary directory and a tiny signed repository made with the host apk."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="kelrepo"))
        self.repo = self.tmp / "repo" / "x86_64"
        self.key, self.pub = dev_keys(self.tmp / "keys")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def make_repo(self) -> list[str]:
        """Base layout, a data package and, with busybox, a package script."""
        tool = ApkTool(APK)
        base = self.tmp / "src" / "base"
        for d in ("etc", "usr/bin", "usr/lib", "var", "dev", "proc", "sys", "tmp", "run"):
            (base / d).mkdir(parents=True)
        for name, dest in merged_usr_links(X86).items():
            (base / name).symlink_to(dest)
        (base / "etc/passwd").write_text("root:x:0:0:root:/root:/bin/sh\n")
        (base / "etc/os-release").write_text("ID=kel\n")
        make_apk(tool, PackagePart("base", "base", base), recipe("base"), "x86_64", self.repo,
                 self.key, BUILD_TIME)
        data = self.tmp / "src" / "hello"
        (data / "usr/share/hello").mkdir(parents=True)
        (data / "usr/share/hello/README").write_text("hello\n")
        make_apk(tool, PackagePart("hello", "hello", data, depends=["base"]), recipe("hello"),
                 "x86_64", self.repo, self.key, BUILD_TIME)
        names = ["base", "hello"]
        if BUSYBOX:
            sh = self.tmp / "src" / "sh"
            (sh / "usr/bin").mkdir(parents=True)
            shutil.copy2(BUSYBOX, sh / "usr/bin/busybox")
            (sh / "usr/bin/sh").symlink_to("busybox")
            make_apk(tool, PackagePart("sh", "sh", sh, depends=["base"]), recipe("sh"),
                     "x86_64", self.repo, self.key, BUILD_TIME)
            # Writing /etc/hook-ran only works chrooted in the new root: the
            # sandbox's own / is read-only.
            hook = self.tmp / "src" / "hook"
            (hook / "usr/share/hook").mkdir(parents=True)
            (hook / "usr/share/hook/README").write_text("hook\n")
            script = self.tmp / "src" / "hook.post-install"
            script.write_text("#!/bin/sh\necho chrooted > /etc/hook-ran\n")
            tool.run("mkpkg", ["--files", tool.path(hook), "--info", "name:hook",
                               "--info", "version:1.0-r0", "--info", "arch:x86_64",
                               "--info", "depends:sh",
                               "--script", f"post-install:{tool.path(script)}",
                               "--sign-key", tool.path(self.key),
                               "--output", tool.path(self.repo / "hook-1.0-r0.apk")],
                     rw=[self.repo], ro=[self.tmp / "src", self.key.parent])
            names += ["hook", "sh"]
        make_index(tool, self.repo, self.key, self.pub, "kel-test")
        return sorted(names)

    def check_root(self, target: Path, names: list[str]) -> None:
        self.assertTrue((target / "usr/share/hello/README").is_file())
        for name, dest in merged_usr_links(X86).items():
            self.assertEqual(os.readlink(target / name), dest)
        # The database went through the lib -> usr/lib link.
        self.assertTrue((target / "usr/lib/apk/db/installed").is_file())
        self.assertEqual(sorted((target / "etc/apk/world").read_text().split()), names)
        self.assertFalse((target / "var/log/apk.log").exists())
        if BUSYBOX:
            self.assertEqual((target / "etc/hook-ran").read_text(), "chrooted\n")


@unittest.skipUnless(HAVE_APK, "needs apk, bwrap and openssl")
class HostApkComposeTests(RepoTestCase):
    def test_compose_from_repo(self):
        names = self.make_repo()
        tool = ApkTool(APK)
        self.assertEqual(index_packages(tool, self.repo), names)
        target = self.tmp / "root"
        log = self.tmp / "logs" / "root.log"
        self.assertEqual(compose_root(tool, target, X86, self.repo, self.pub.parent,
                                      logfile=log), names)
        self.check_root(target, names)
        self.assertIn("Installing hello", log.read_text())
        # An explicit list: those packages and their dependencies only.
        small = self.tmp / "small"
        compose_root(tool, small, X86, self.repo, self.pub.parent, ["hello"])
        self.assertEqual((small / "etc/apk/world").read_text().split(), ["hello"])
        self.assertTrue((small / "etc/os-release").is_file())
        self.assertFalse((small / "usr/share/hook").exists())

    def test_untrusted_repository_is_refused(self):
        self.make_repo()
        nokeys = self.tmp / "no-keys"
        nokeys.mkdir()
        with self.assertRaises(KelError) as cm:
            compose_root(ApkTool(APK), self.tmp / "root", X86, self.repo, nokeys)
        self.assertIn("UNTRUSTED", str(cm.exception))


def fake_tools_root(root: Path) -> None:
    """A stand-in for a KEL userland: the host apk and the libraries it needs."""
    (root / "usr/bin").mkdir(parents=True)
    for d in ("etc", "dev", "proc", "sys", "tmp", "run"):
        (root / d).mkdir()
    (root / "etc/passwd").write_text("root:x:0:0:root:/root:/bin/sh\n")
    (root / "etc/group").write_text("root:x:0:\n")
    shutil.copy2(APK, root / "usr/bin/apk")
    ldd = subprocess.run(["ldd", str(APK)], capture_output=True, text=True)
    if ldd.returncode == 0:  # dynamically linked
        if "not found" in ldd.stdout:
            raise unittest.SkipTest("not all of apk's libraries are found")
        for lib in re.findall(r"(/\S+)", ldd.stdout):
            dest = root / lib.lstrip("/")
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(os.path.realpath(lib), dest)


@unittest.skipUnless(HAVE_APK and shutil.which("ldd"), "needs apk, bwrap, openssl and ldd")
class ToolsRootTests(RepoTestCase):
    """The stage 4 path: apk runs from a read-only tools root, not from the host."""

    def test_compose_and_package(self):
        names = self.make_repo()
        tools = self.tmp / "tools"
        fake_tools_root(tools)
        before = sorted(p.relative_to(tools) for p in tools.rglob("*"))
        tool = ApkTool(TOOLS_APK, root=tools)
        target = self.tmp / "root"
        self.assertEqual(compose_root(tool, target, X86, self.repo, self.pub.parent), names)
        self.check_root(target, names)
        # Packages and index of a new repository, made by the same apk.
        work = self.tmp / "build"
        (work / "pkg/usr/share/demo").mkdir(parents=True)
        (work / "pkg/usr/share/demo/data").write_text("demo\n")
        out = self.tmp / "repo-stage4" / "x86_64"
        package_into_repo(tool, recipe("demo"), X86, work, out, self.key, self.pub, "kel-test")
        self.assertEqual(index_packages(tool, out), ["demo"])
        again = self.tmp / "root2"
        compose_root(tool, again, X86, out, self.pub.parent)
        self.assertEqual((again / "usr/share/demo/data").read_text(), "demo\n")
        # The tools root was read-only: no mount points or files appeared in it.
        self.assertEqual(sorted(p.relative_to(tools) for p in tools.rglob("*")), before)


STAGE = '''
[stage]
name = "s4"
summary = "test rebuild"
kind = "rebuild"
input_repo = "repo"
output_repo = "repo-s4"
tools_root = "sysroot"

[[step]]
recipe = "demo"
profile = "package"

[[step]]
recipe = "extra"
profile = "package"

[verify]
script = "true"
'''

RECIPE = '''
[package]
name = "{name}"
version = "1.0"
summary = "{name} test package"
license = "MIT"
homepage = "https://example.org/"

[build]
style = "custom"
install = "true"
'''


@unittest.skipUnless(HAVE_APK and shutil.which("ldd"), "needs apk, bwrap, openssl and ldd")
class RebuildStageTests(RepoTestCase):
    """A whole rebuild stage with real apk and bwrap; only the build scripts are faked."""

    def setUp(self):
        super().setUp()
        kel = self.tmp / "kel"
        self.layout = Layout(repo=kel, workdir=self.tmp / "work", cachedir=self.tmp / "cache")
        (kel / "bootstrap").mkdir(parents=True)
        (kel / "bootstrap" / "s4.toml").write_text(STAGE)
        for name in ("demo", "extra"):
            (kel / "recipes" / name).mkdir(parents=True)
            (kel / "recipes" / name / "recipe.toml").write_text(RECIPE.format(name=name))
        self.key, self.pub = dev_keys(self.layout.keys())
        self.repo = self.layout.repository(X86)
        self.names = self.make_repo()
        fake_tools_root(self.layout.arch_root(X86) / "sysroot")
        self.runs = []

    def fake_run(self, cmd, logfile):
        """Stands in for running a script in the sandbox: a build installs one file."""
        binds = {dst: src for src, dst in opts(cmd, "--bind")}
        setenv = dict(tuple(x) for x in opts(cmd, "--setenv"))
        self.runs.append((Path(binds["/"]).name, setenv.get("KEL_PKGNAME"), "--remount-ro" in cmd))
        if "KEL_PKGNAME" in setenv:
            data = Path(binds["/kel/build"]) / "pkg/usr/share" / setenv["KEL_PKGNAME"] / "data"
            data.parent.mkdir(parents=True)
            data.write_text("built\n")
        logfile.parent.mkdir(parents=True, exist_ok=True)
        logfile.write_text("fake\n")
        return 0

    def run_stage(self, force: bool = False):
        from kel.bootstrap import run_stage
        self.runs.clear()
        with mock.patch("kel.buildroot._run_logged", self.fake_run), \
                mock.patch.dict(os.environ, {"KEL_ALLOW_ROOT": "1"}):
            run_stage(self.layout, X86, "s4", jobs=1, force=force)

    def test_stage(self):
        self.run_stage()
        # Both builds in the composed root, read-only; [verify] in a root of the new packages.
        self.assertEqual(self.runs, [("s4", "demo", True), ("s4", "extra", True),
                                     ("s4-verify", None, True)])
        root = self.layout.buildroots(X86) / "s4"
        self.check_root(root, self.names)
        out = self.layout.repository(X86, "repo-s4")
        self.assertEqual(index_packages(ApkTool(APK), out), ["demo", "extra"])
        self.assertFalse((self.layout.buildroots(X86) / "s4-verify").exists())
        self.assertIn("Installing demo", (self.layout.logs(X86) / "s4/verify-root.log").read_text())

        # Resumed: the root and both steps are up to date.
        self.run_stage()
        self.assertEqual(self.runs, [("s4-verify", None, True)])

        # A failed composition of the same input keeps the output repository:
        # the root is composed again, but nothing has to be rebuilt.
        with mock.patch("kel.buildroot.compose_root", side_effect=KelError("interrupted")):
            with self.assertRaises(KelError):
                self.run_stage(force=True)
        self.run_stage()
        self.assertEqual(self.runs, [("s4-verify", None, True)])
        self.check_root(root, self.names)

        # Steps whose packages are gone from the output repository are built again.
        remove_tree(out.parent)
        self.run_stage()
        self.assertEqual([r[1] for r in self.runs], ["demo", "extra", None])

        # A new input repository: a new root, and everything is rebuilt into an
        # emptied output repository.
        stale = out / "stale-1.0-r0.apk"
        shutil.copy2(out / "demo-1.0-r0.apk", stale)
        more = self.tmp / "src" / "more"
        (more / "usr/share/more").mkdir(parents=True)
        (more / "usr/share/more/README").write_text("more\n")
        make_apk(ApkTool(APK), PackagePart("more", "more", more), recipe("more"), "x86_64",
                 self.repo, self.key, BUILD_TIME)
        make_index(ApkTool(APK), self.repo, self.key, self.pub, "kel-test")
        self.run_stage()
        self.assertEqual([r[1] for r in self.runs], ["demo", "extra", None])
        self.assertTrue((root / "usr/share/more/README").is_file())
        self.assertFalse(stale.exists())


@unittest.skipUnless(HAVE_APK, "needs apk, bwrap and openssl")
class RebuildPackageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="kelrebuild"))
        self.key, self.pub = dev_keys(self.tmp / "keys")
        self.out = self.tmp / "repo-stage4" / "x86_64"
        self.root = self.tmp / "buildroot"
        (self.root / "usr/bin").mkdir(parents=True)
        (self.root / "usr/bin/bash").write_text("stand-in\n")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def build(self, r: Recipe, files: dict[str, str]) -> list[list[str]]:
        """rebuild_package, with the sandboxed build replaced by writing files to DESTDIR."""
        work = self.tmp / "build" / r.name
        work.mkdir(parents=True)
        commands = []

        def fake_build(cmd, logfile):
            commands.append(cmd)
            for rel, text in files.items():
                (work / "pkg" / rel).parent.mkdir(parents=True, exist_ok=True)
                (work / "pkg" / rel).write_text(text)
            return 0

        recipe_dir = self.tmp / "recipes" / r.name
        recipe_dir.mkdir(parents=True)
        r = dataclasses.replace(r, path=recipe_dir / "recipe.toml")
        with mock.patch("kel.buildroot._run_logged", fake_build):
            rebuild_package(ApkTool(APK), self.root, r, X86, work, {"PATH": "/usr/bin"},
                            self.tmp / "logs" / f"{r.name}.log", self.out, self.key, self.pub,
                            "kel-test")
        return commands

    def test_packages_go_to_the_output_repository(self):
        before = sorted(self.root.rglob("*"))
        demo = recipe("demo", build=BuildSpec(style="custom", phases={"install": "true"}),
                      subpackages=(Subpackage("doc", "", ("usr/share/doc",)),))
        [cmd] = self.build(demo, {"usr/share/demo/data": "demo\n",
                                  "usr/share/doc/demo/README": "doc\n"})
        self.assertIn([str(self.root), "/"], opts(cmd, "--bind"))
        self.assertEqual(opt1(cmd, "--remount-ro"), ["/"])
        setenv = dict(tuple(x) for x in opts(cmd, "--setenv"))
        self.assertEqual((setenv["KEL_PKGNAME"], setenv["DESTDIR"]), ("demo", "/kel/build/pkg"))
        self.assertIn("-march=x86-64-v2", setenv["CFLAGS"])
        self.assertEqual(index_packages(ApkTool(APK), self.out), ["demo", "demo-doc"])
        manifest = json.loads((self.out.parent / "manifests" / "demo.json").read_text())
        self.assertEqual(manifest["files"], ["/usr/share/demo/data"])
        self.assertEqual(sorted(self.root.rglob("*")), before)  # nothing installed

    def test_conflicts_with_packages_in_the_output_repository(self):
        spec = BuildSpec(style="custom", phases={"install": "true"})
        self.build(recipe("one", build=spec), {"usr/bin/tool": "one\n"})
        with self.assertRaises(KelError) as cm:
            self.build(recipe("two", build=spec), {"usr/bin/tool": "two\n"})
        self.assertIn("already shipped by one", str(cm.exception))

    def test_packaging_policy_applies(self):
        spec = BuildSpec(style="custom", phases={"install": "true"})
        with self.assertRaises(KelError) as cm:
            self.build(recipe("bad", build=spec), {"kel/build/leak": "x\n"})
        self.assertIn("build location", str(cm.exception))


class RemoveTreeTests(unittest.TestCase):
    def test_read_only_directories(self):
        with tempfile.TemporaryDirectory() as tmp:
            tree = Path(tmp) / "root"
            (tree / "usr/share/locked").mkdir(parents=True)
            (tree / "usr/share/locked/file").write_text("x")
            (tree / "link").symlink_to("/nonexistent")
            os.chmod(tree / "usr/share/locked", 0o500)
            os.chmod(tree / "usr", 0o555)
            remove_tree(tree)
            self.assertFalse(tree.exists())
            remove_tree(tree)  # nothing to do


if __name__ == "__main__":
    unittest.main()
