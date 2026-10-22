"""Build roots made only of KEL packages, and rebuilds in them (DESIGN.md 5.4).

From stage 4 on, nothing from the host or the bootstrap tools takes part in
a build. compose_root() installs packages from a repository into an empty
directory with KEL's own apk, run from a "tools root" (a KEL userland with
/usr/bin/apk, such as the stage 3 sysroot). A stage of kind "rebuild"
composes one such root, mounts it read-only as / for every package build,
and packages the results with the same apk into a new repository.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
from pathlib import Path

from kel import __version__
from kel.bootstrap import (CONFIG_SITE_VALUES, INNER_CONFIG_SITE, INNER_RECIPEDIR, INNER_WORKDIR,
                           SCRIPT_PRELUDE, Stage, _run_logged, _tail, base_env,
                           make_merged_usr_links, package_env, package_into_repo, step_key,
                           unpack_sources)
from kel.build import build_script
from kel.config import Arch, Layout
from kel.fetch import fetch_recipe
from kel.pkg import ApkTool, PackagePart, dev_key_paths, ensure_dev_key
from kel.recipe import Recipe, load_recipe
from kel.sandbox import bwrap_root_command, require_bwrap
from kel.util import KelError, Timer, format_duration, log, sha256_file, warn

# apk inside a tools root: KEL's apk-tools package.
TOOLS_APK = Path("/usr/bin/apk")


def remove_tree(path: Path) -> None:
    """Remove a tree that may contain read-only directories (composed roots).

    Deleting an entry needs write access to its directory, and packages may
    ship directories without it; the caller owns every file in the tree.
    """
    if path.is_symlink() or path.is_file():
        path.unlink()
        return
    if not path.exists():
        return

    def make_writable(p: str | Path) -> None:
        mode = stat.S_IMODE(os.lstat(p).st_mode)
        if mode & 0o700 != 0o700:
            os.chmod(p, mode | 0o700)

    make_writable(path)
    for dirpath, dirnames, _ in os.walk(path):
        for name in dirnames:  # before os.walk descends into them
            sub = os.path.join(dirpath, name)
            if not os.path.islink(sub):
                make_writable(sub)
    shutil.rmtree(path)


def index_packages(tool: ApkTool, repo: Path) -> list[str]:
    """Names of all packages in the index repo/Packages.adb, sorted."""
    index = repo / "Packages.adb"
    out = tool.run("adbdump", ["--format", "json", tool.path(index)], ro=[repo])
    try:
        names = {p["name"] for p in json.loads(out).get("packages", [])}
    except (ValueError, AttributeError, KeyError, TypeError) as e:
        raise KelError(f"cannot read the package list of {index}: {e}")
    if not names:
        raise KelError(f"{index} lists no packages")
    return sorted(names)


def compose_root(tool: ApkTool, target: Path, arch: Arch, repo: Path, keys_dir: Path,
                 packages: list[str] | None = None, logfile: Path | None = None) -> list[str]:
    """Install packages from repo (the directory of Packages.adb) into a new root.

    packages=None installs every package in the index: the full root that
    stage 4 builds in. A list (later: a recipe's build depends) installs
    those and their dependencies. The index and the packages must be signed
    by a key in keys_dir. Package scripts run chrooted in target. Returns the
    requested package names.
    """
    if target.is_symlink() or (target.exists() and (not target.is_dir() or any(target.iterdir()))):
        raise KelError(f"{target} must be a new or empty directory")
    index = repo / "Packages.adb"
    if not index.is_file():
        raise KelError(f"no repository index {index}")
    if packages is None:
        packages = index_packages(tool, repo)
    if not packages:
        raise KelError("no packages to install")
    target.mkdir(parents=True, exist_ok=True)
    # apk 3 creates its database as lib/apk/db relative to the root. Without
    # the merged-/usr links in place first it would create a real /lib, and
    # the filesystem package's lib -> usr/lib link could not be installed.
    # (usr/lib must exist too: apk writes the database through the link.)
    make_merged_usr_links(target, arch)
    tool.run("add", list(packages),
             global_args=["--root", tool.path(target), "--initdb", "--arch", arch.name,
                          # Nothing is cached, and no /var/log/apk.log in the root.
                          "--no-cache", "--no-logfile",
                          # Absolute: apk takes a relative --keys-dir relative to --root.
                          "--keys-dir", tool.path(keys_dir),
                          "--repository", tool.path(index)],
             rw=[target], ro=[repo, keys_dir], chroot_into=target, logfile=logfile)
    make_merged_usr_links(target, arch)  # still links: no package replaced them
    return list(packages)


def build_command(argv: list[str], *, root: Path, workdir: Path, env: dict[str, str],
                  recipe_dir: Path | None = None, config_site: Path | None = None) -> list[str]:
    """Sandbox for a script in a composed root: root is a read-only /, no network.

    Only the work directory (/kel/build, which also holds HOME), /tmp and
    /run are writable. The variables and read-only binds are those of a
    "sysroot" stage (bootstrap.run_script).
    """
    env = dict(env, KEL_WORKDIR=INNER_WORKDIR, HOME=f"{INNER_WORKDIR}/.home")
    ro_binds = []
    if (workdir / "src").is_dir():
        env["KEL_SRCDIR"] = f"{INNER_WORKDIR}/src"
    if (workdir / "sources").is_dir():
        env["KEL_SOURCEDIR"] = f"{INNER_WORKDIR}/sources"
    if recipe_dir:
        env["KEL_RECIPEDIR"] = INNER_RECIPEDIR
        ro_binds.append((recipe_dir, INNER_RECIPEDIR))
    if config_site:
        env["CONFIG_SITE"] = INNER_CONFIG_SITE
        ro_binds.append((config_site, INNER_CONFIG_SITE))
    return bwrap_root_command(argv, root=root, chdir=env.get("KEL_SRCDIR", INNER_WORKDIR),
                              env=env, binds=[(workdir, INNER_WORKDIR)], ro_binds=ro_binds,
                              readonly=True)


def run_in_root(root: Path, script: str, workdir: Path, env: dict[str, str], logfile: Path,
                recipe_dir: Path | None = None, config_site: Path | None = None) -> None:
    """Run a step script with build_command(); its output goes to logfile."""
    (workdir / ".home").mkdir(exist_ok=True)
    argv = ["/bin/bash", "-e", "-u", "-o", "pipefail", "-c", SCRIPT_PRELUDE + script]
    rc = _run_logged(build_command(argv, root=root, workdir=workdir, env=env,
                                   recipe_dir=recipe_dir, config_site=config_site), logfile)
    if rc != 0:
        raise KelError(f"failed (exit {rc}); log: {logfile}\n{_tail(logfile)}")


def rebuild_package(tool: ApkTool, root: Path, recipe: Recipe, arch: Arch, workdir: Path,
                    env0: dict[str, str], logfile: Path, repo: Path, key: Path, pub: Path,
                    description: str, config_site: Path | None = None,
                    run_check: bool = True) -> list[PackagePart]:
    """Build [build] in the read-only root, then package it into repo with tool.

    The packaging checks are those of stage 3 (bootstrap.package_into_repo).
    Unlike there, nothing is installed anywhere: every step of a stage builds
    in the same root, which only changes when it is composed again.
    """
    assert recipe.build is not None
    (workdir / "pkg").mkdir()
    run_in_root(root, build_script(recipe, run_check), workdir, package_env(env0, recipe, arch),
                logfile, recipe.path.parent, config_site)
    return package_into_repo(tool, recipe, arch, workdir, repo, key, pub, description)


def tools_apk(layout: Layout, arch: Arch, stage: Stage) -> ApkTool:
    root = layout.arch_root(arch) / stage.tools_root
    if not (root / TOOLS_APK.relative_to("/")).is_file():
        raise KelError(f"tools root {root} has no {TOOLS_APK} (KEL's apk-tools package)")
    return ApkTool(TOOLS_APK, root=root)


def signing_key(layout: Layout) -> tuple[Path, Path]:
    """The development key that signed the input repository; it signs the output too."""
    priv, _ = dev_key_paths(layout.keys())
    if not priv.exists():
        raise KelError(f"no signing key {priv}; it is created with the stage 3 repository")
    return ensure_dev_key(layout.keys())


def _stamp_key(stamp: Path) -> str | None:
    try:
        return json.loads(stamp.read_text()).get("key")
    except (OSError, ValueError, AttributeError):
        return None


def _root_key(arch: Arch, index: Path, packages: list[str] | None) -> str:
    """Identity of a composed root: its signed index lists every package's hash."""
    h = hashlib.sha256()
    names = "*" if packages is None else " ".join(packages)
    for part in (__version__, arch.name, sha256_file(index), names):
        h.update(part.encode() + b"\0")
    return h.hexdigest()


def prepare_build_root(layout: Layout, arch: Arch, stage: Stage, tool: ApkTool,
                       force: bool = False) -> tuple[Path, str]:
    """Compose the stage's build root unless it is up to date; return (root, its key).

    The output repository may only hold packages built in this root: if it
    was filled in a root of another input (or nobody knows), it is emptied.
    """
    in_repo = layout.repository(arch, stage.input_repo)
    root = layout.buildroots(arch) / stage.name
    stamps = layout.stamps(arch) / stage.name
    stamps.mkdir(parents=True, exist_ok=True)
    stamp = stamps / "buildroot.json"  # the root on disk
    key = _root_key(arch, in_repo / "Packages.adb", None)
    if not force and _stamp_key(stamp) == key and root.is_dir():
        log(f"build root {root}: up to date")
    else:
        stamp.unlink(missing_ok=True)
        remove_tree(root)
        logfile = layout.logs(arch) / stage.name / "buildroot.log"
        log(f"composing build root {root} from {in_repo} (log: {logfile})")
        _, pub = dev_key_paths(layout.keys())
        with Timer() as t:
            packages = compose_root(tool, root, arch, in_repo, pub.parent, logfile=logfile)
        stamp.write_text(json.dumps({"key": key, "packages": packages,
                                     "seconds": round(t.elapsed)}, indent=2) + "\n")
        log(f"build root: {len(packages)} packages in {format_duration(t.elapsed)}")
    origin = stamps / "output.json"  # the root the output repository was built in
    out = layout.repository(arch, stage.output_repo).parent
    if _stamp_key(origin) != key:
        if out.exists():
            log(f"removing {out}: it was not built in this root")
            remove_tree(out)
        origin.write_text(json.dumps({"key": key}) + "\n")
    return root, key


def run_rebuild_stage(layout: Layout, arch: Arch, stage: Stage, *, jobs: int,
                      force: bool = False, keep: bool = False, only: str | None = None,
                      offline: bool = False) -> None:
    """Run a kind = "rebuild" stage: one composed root, every step rebuilt in it.

    Resumes like bootstrap.run_stage: a step is skipped when its stamp
    matches its inputs, which include the build root, and its packages are
    in the output repository.
    """
    recipes: dict[str, Recipe] = {}
    for step in stage.steps:
        if step.recipe not in recipes:
            recipes[step.recipe] = load_recipe(layout.recipes, layout.upstream_keys, step.recipe)
            if recipes[step.recipe].build is None:
                raise KelError(f"{step.recipe} has no [build] section")
    if only and only not in {s.label for s in stage.steps}:
        raise KelError(f"stage {stage.name} has no step {only}")
    tool = tools_apk(layout, arch, stage)
    in_index = layout.repository(arch, stage.input_repo) / "Packages.adb"
    if not in_index.is_file():
        raise KelError(f"no input repository index {in_index}")
    key, pub = signing_key(layout)
    out_repo = layout.repository(arch, stage.output_repo)

    log(f"stage {stage.name} ({arch.name}): {stage.summary}")
    sources = {name: fetch_recipe(layout.sources, layout.upstream_keys, r, offline)
               for name, r in recipes.items()}
    env0 = base_env(layout, arch, jobs, recipes, stage.root)
    config_site = None
    if stage.config_site:
        config_site = layout.arch_root(arch) / "config.site"
        config_site.write_text(CONFIG_SITE_VALUES)
    root, root_key = prepare_build_root(layout, arch, stage, tool, force)
    stamps = layout.stamps(arch) / stage.name

    for n, step in enumerate(stage.steps, 1):
        if only and step.label != only:
            continue
        recipe = recipes[step.recipe]
        # Built in another root, a step is out of date even if its recipe is not.
        step_id = hashlib.sha256(
            f"{step_key(stage, step, recipe, arch)}\0{root_key}".encode()).hexdigest()
        stamp = stamps / f"{step.recipe}-{step.profile}.json"
        packaged = (out_repo.parent / "manifests" / f"{recipe.name}.json").is_file()
        if not force and packaged and _stamp_key(stamp) == step_id:
            log(f"[{n}/{len(stage.steps)}] {step.label}: up to date")
            continue
        workdir = layout.builds(arch) / stage.name / f"{step.recipe}-{step.profile}"
        shutil.rmtree(workdir, ignore_errors=True)
        workdir.mkdir(parents=True)
        unpack_sources(recipe, sources[step.recipe], workdir)
        logfile = layout.logs(arch) / stage.name / f"{step.recipe}-{step.profile}.log"
        log(f"[{n}/{len(stage.steps)}] {step.label} {recipe.version}: building (log: {logfile})")
        with Timer() as t:
            try:
                rebuild_package(tool, root, recipe, arch, workdir, env0, logfile, out_repo,
                                key, pub, f"KEL bootstrap ({stage.name})", config_site)
            except KelError as e:
                raise KelError(f"{step.label}: {e}")
        stamp.write_text(json.dumps({"key": step_id, "version": recipe.pkgver,
                                     "seconds": round(t.elapsed)}, indent=2) + "\n")
        log(f"[{n}/{len(stage.steps)}] {step.label}: done in {format_duration(t.elapsed)}")
        if not keep:
            shutil.rmtree(workdir, ignore_errors=True)

    if stage.verify and not only:  # as in bootstrap.run_stage
        verify_rebuild_stage(layout, arch, stage, env0, keep=keep)


def verify_rebuild_stage(layout: Layout, arch: Arch, stage: Stage, env: dict[str, str],
                         keep: bool = False) -> None:
    """Install the whole output repository into an empty root and run [verify] in it.

    Installing shows that the rebuilt packages form a complete set that KEL's
    apk accepts; the script, run inside that root, shows that the system they
    make works. The root is removed afterwards unless keep is set.
    """
    require_bwrap()
    tool = tools_apk(layout, arch, stage)
    _, pub = signing_key(layout)
    in_repo = layout.repository(arch, stage.input_repo)
    out_repo = layout.repository(arch, stage.output_repo)
    if not (out_repo / "Packages.adb").is_file():
        raise KelError(f"nothing to verify: no {out_repo / 'Packages.adb'}")
    if (in_repo / "Packages.adb").is_file():
        missing = sorted(set(index_packages(tool, in_repo)) - set(index_packages(tool, out_repo)))
        if missing:
            warn(f"in {stage.input_repo} but not rebuilt: {' '.join(missing)}")
    root = layout.buildroots(arch) / f"{stage.name}-verify"
    remove_tree(root)
    logfile = layout.logs(arch) / stage.name / "verify-root.log"
    log(f"verifying stage {stage.name}: installing {out_repo} into {root} (log: {logfile})")
    packages = compose_root(tool, root, arch, out_repo, pub.parent, logfile=logfile)
    log(f"stage {stage.name}: all {len(packages)} packages installed")
    if stage.verify:
        workdir = layout.builds(arch) / stage.name / "verify"
        shutil.rmtree(workdir, ignore_errors=True)
        workdir.mkdir(parents=True)
        logfile = layout.logs(arch) / stage.name / "verify.log"
        log(f"running [verify] inside the new root (log: {logfile})")
        run_in_root(root, stage.verify, workdir, env, logfile)
        print(_tail(logfile, 20))
    log(f"stage {stage.name}: verification passed")
    if not keep:
        remove_tree(root)
