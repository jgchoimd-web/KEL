"""Bootstrap stages (docs/DESIGN.md section 5).

A stage is bootstrap/<name>.toml: an ordered list of (recipe, profile) steps
plus an optional verification script. Each step runs the recipe's
[bootstrap.<profile>] script inside the sandbox, with the sources already
fetched, verified and unpacked. Finished steps leave a stamp so an
interrupted bootstrap resumes where it stopped.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import tomllib
from dataclasses import dataclass
from pathlib import Path

from kel import __version__
from kel.config import Arch, Layout
from kel.fetch import fetch_recipe
from kel.recipe import NAME_RE, PROFILE_RE, Recipe, load_recipe
from kel.sandbox import bwrap_command, bwrap_root_command, require_bwrap
from kel.util import KelError, Timer, format_duration, log

# Fixed timestamp for builds until recipes carry their own (2026-01-01 UTC).
SOURCE_DATE_EPOCH = "1767225600"

SCRIPT_PRELUDE = "set +h\numask 022\nset -x\n"

# Where the step's work directory appears inside a "sysroot" stage sandbox.
INNER_WORKDIR = "/kel/build"

# "host": run on the host with a read-only view of it (stages 1-2, which use
# host tools to build the cross toolchain). "sysroot": the sysroot becomes /
# (stage 3 onwards, nothing from the host is used).
STAGE_ROOTS = ("host", "sysroot")


@dataclass(frozen=True)
class Step:
    recipe: str
    profile: str

    @property
    def label(self) -> str:
        return f"{self.recipe}:{self.profile}"


@dataclass(frozen=True)
class Stage:
    name: str
    summary: str
    steps: tuple[Step, ...]
    verify: str | None
    digest: str
    root: str = "host"


def load_stage(layout: Layout, name: str) -> Stage:
    if not PROFILE_RE.match(name):
        raise KelError(f"bad stage name {name!r}")
    path = layout.bootstrap_defs / f"{name}.toml"
    try:
        raw_text = path.read_bytes()
    except FileNotFoundError:
        raise KelError(f"no such stage: {path}")
    try:
        data = tomllib.loads(raw_text.decode("utf-8"))
    except tomllib.TOMLDecodeError as e:
        raise KelError(f"{path}: TOML error: {e}")
    unknown = set(data) - {"stage", "step", "verify"}
    if unknown:
        raise KelError(f"{path}: unknown key(s): {', '.join(sorted(unknown))}")
    meta = data.get("stage", {})
    steps = []
    for i, raw in enumerate(data.get("step", [])):
        if set(raw) != {"recipe", "profile"}:
            raise KelError(f"{path}: step[{i}] needs exactly 'recipe' and 'profile'")
        if not NAME_RE.match(raw["recipe"]) or not PROFILE_RE.match(raw["profile"]):
            raise KelError(f"{path}: step[{i}] has a bad recipe or profile name")
        steps.append(Step(raw["recipe"], raw["profile"]))
    if not steps:
        raise KelError(f"{path}: no steps")
    verify = data.get("verify", {}).get("script")
    root = meta.get("root", "host")
    if root not in STAGE_ROOTS:
        raise KelError(f"{path}: stage root must be one of {', '.join(STAGE_ROOTS)}")
    return Stage(
        name=meta.get("name", name),
        summary=meta.get("summary", ""),
        steps=tuple(steps),
        verify=verify,
        digest=hashlib.sha256(raw_text).hexdigest(),
        root=root,
    )


def prepare_sysroot(layout: Layout, arch: Arch) -> Path:
    """Create the merged-/usr skeleton (docs/DESIGN.md section 4.7)."""
    root = layout.sysroot(arch)
    for d in ("usr/bin", "usr/lib", "usr/include", "usr/share", "etc", "var", "tools"):
        (root / d).mkdir(parents=True, exist_ok=True)
    links = {"bin": "usr/bin", "sbin": "usr/bin", "lib": "usr/lib",
             "usr/sbin": "bin", "usr/lib64": "lib"}
    if arch.name == "x86_64":
        # The x86-64 ABI loader path is /lib64/ld-linux-x86-64.so.2.
        links["lib64"] = "usr/lib"
    for name, target in links.items():
        link = root / name
        if link.is_symlink():
            if os.readlink(link) != target:
                raise KelError(f"{link} points to {os.readlink(link)}, expected {target}")
        elif link.exists():
            raise KelError(f"{link} exists and is not the expected symlink to {target}")
        else:
            link.symlink_to(target)
    return root


def _extract(archive: Path, into: Path) -> Path:
    """Unpack an archive with a single top-level directory; return that directory."""
    into.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(dir=into, prefix=".x-"))
    try:
        subprocess.run(["tar", "-xf", str(archive), "-C", str(tmp), "--no-same-owner"],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    except subprocess.CalledProcessError as e:
        shutil.rmtree(tmp, ignore_errors=True)
        raise KelError(f"cannot unpack {archive.name}: {e.stderr.decode(errors='replace').strip()}")
    entries = list(tmp.iterdir())
    if len(entries) != 1 or not entries[0].is_dir():
        shutil.rmtree(tmp, ignore_errors=True)
        raise KelError(f"{archive.name} does not have a single top-level directory")
    return entries[0]


def unpack_sources(recipe: Recipe, paths: list[Path], workdir: Path) -> Path:
    """Unpack the main source as workdir/src and extra sources inside it.

    A recipe without upstream sources (KEL's own packages such as the base
    filesystem) gets a copy of its files/ directory instead.
    """
    srcdir = workdir / "src"
    if not recipe.sources:
        files = recipe.path.parent / "files"
        if files.is_dir():
            shutil.copytree(files, srcdir, symlinks=True)
        else:
            srcdir.mkdir()
        return srcdir
    main = _extract(paths[0], workdir)
    main.rename(srcdir)
    shutil.rmtree(main.parent, ignore_errors=True)
    for source, path in zip(recipe.sources[1:], paths[1:]):
        if source.dest is None:
            continue
        top = _extract(path, workdir)
        target = srcdir / source.dest
        if target.exists():
            raise KelError(f"{recipe.name}: {source.dest} already exists in the source tree")
        target.parent.mkdir(parents=True, exist_ok=True)
        top.rename(target)
        shutil.rmtree(top.parent, ignore_errors=True)
    return srcdir


def step_key(stage: Stage, step: Step, recipe: Recipe, arch: Arch) -> str:
    h = hashlib.sha256()
    for part in (__version__, stage.name, step.label, arch.name, recipe.digest):
        h.update(part.encode() + b"\0")
    return h.hexdigest()


def base_env(layout: Layout, arch: Arch, jobs: int, recipes: dict[str, Recipe],
             root: str = "host") -> dict[str, str]:
    env = {
        "TERM": "dumb",
        "LC_ALL": "POSIX",
        "TZ": "UTC",
        "SOURCE_DATE_EPOCH": SOURCE_DATE_EPOCH,
        "MAKEFLAGS": f"-j{jobs}",
        "KEL_ARCH": arch.name,
        "KEL_TARGET": arch.triplet,
        "KEL_KERNEL_ARCH": arch.kernel_arch,
        "KEL_JOBS": str(jobs),
    }
    if root == "host":
        sysroot = layout.sysroot(arch)
        tools = layout.tools(arch)
        env.update({
            "PATH": f"{tools}/bin:/usr/bin:/bin",
            "CONFIG_SITE": f"{sysroot}/usr/share/config.site",
            "KEL_SYSROOT": str(sysroot),
            "KEL_TOOLS": str(tools),
            "KEL_HOSTTOOLS": str(layout.host_tools(arch)),
        })
    else:
        env.update({"PATH": "/usr/bin:/usr/sbin", "HOME": "/root", "KEL_SYSROOT": "/"})
    for r in recipes.values():
        env[f"KEL_VERSION_{r.env_name}"] = r.version
    return env


def _run_logged(cmd: list[str], logfile: Path) -> int:
    logfile.parent.mkdir(parents=True, exist_ok=True)
    with open(logfile, "wb") as out:
        return subprocess.run(cmd, stdout=out, stderr=subprocess.STDOUT).returncode


def _tail(path: Path, lines: int = 40) -> str:
    try:
        return "\n".join(path.read_text(errors="replace").splitlines()[-lines:])
    except OSError:
        return ""


def run_script(layout: Layout, arch: Arch, root: str, script: str, workdir: Path,
               env: dict[str, str], logfile: Path) -> None:
    """Run a step script in the sandbox; workdir/src (if any) is the start directory."""
    argv = ["/bin/bash", "-e", "-u", "-o", "pipefail", "-c", SCRIPT_PRELUDE + script]
    has_src = (workdir / "src").is_dir()
    if root == "host":
        home = workdir / ".home"
        home.mkdir(parents=True, exist_ok=True)
        env = dict(env, HOME=str(home), KEL_WORKDIR=str(workdir))
        if has_src:
            env["KEL_SRCDIR"] = str(workdir / "src")
        cmd = bwrap_command(argv, chdir=workdir / "src" if has_src else workdir, env=env,
                            rw_binds=[layout.arch_root(arch)], sh_is_bash=True)
    else:
        env = dict(env, KEL_WORKDIR=INNER_WORKDIR)
        if has_src:
            env["KEL_SRCDIR"] = f"{INNER_WORKDIR}/src"
        cmd = bwrap_root_command(argv, root=layout.sysroot(arch),
                                 chdir=env.get("KEL_SRCDIR", INNER_WORKDIR), env=env,
                                 binds=[(workdir, INNER_WORKDIR)])
    rc = _run_logged(cmd, logfile)
    if rc != 0:
        raise KelError(f"failed (exit {rc}); log: {logfile}\n{_tail(logfile)}")


def run_stage(layout: Layout, arch: Arch, stage_name: str, *, jobs: int, force: bool = False,
              keep: bool = False, only: str | None = None, offline: bool = False) -> None:
    if os.geteuid() == 0 and not os.environ.get("KEL_ALLOW_ROOT"):
        raise KelError("refusing to build as root; run kel as an unprivileged user")
    require_bwrap()
    stage = load_stage(layout, stage_name)
    recipes: dict[str, Recipe] = {}
    for step in stage.steps:
        if step.recipe not in recipes:
            recipes[step.recipe] = load_recipe(layout.recipes, layout.upstream_keys, step.recipe)
        if step.profile not in recipes[step.recipe].bootstrap:
            raise KelError(f"{step.recipe} has no [bootstrap.{step.profile}] profile")
    if only and only not in {s.label for s in stage.steps}:
        raise KelError(f"stage {stage.name} has no step {only}")

    log(f"stage {stage.name} ({arch.name}): {stage.summary}")
    sources = {name: fetch_recipe(layout.sources, layout.upstream_keys, r, offline)
               for name, r in recipes.items()}
    prepare_sysroot(layout, arch)
    env0 = base_env(layout, arch, jobs, recipes, stage.root)
    stamps = layout.stamps(arch) / stage.name
    stamps.mkdir(parents=True, exist_ok=True)

    for n, step in enumerate(stage.steps, 1):
        if only and step.label != only:
            continue
        recipe = recipes[step.recipe]
        key = step_key(stage, step, recipe, arch)
        stamp = stamps / f"{step.recipe}-{step.profile}.json"
        if not force and stamp.exists():
            try:
                if json.loads(stamp.read_text()).get("key") == key:
                    log(f"[{n}/{len(stage.steps)}] {step.label}: up to date")
                    continue
            except ValueError:
                pass
        workdir = layout.builds(arch) / stage.name / f"{step.recipe}-{step.profile}"
        shutil.rmtree(workdir, ignore_errors=True)
        workdir.mkdir(parents=True)
        unpack_sources(recipe, sources[step.recipe], workdir)
        logfile = layout.logs(arch) / stage.name / f"{step.recipe}-{step.profile}.log"
        log(f"[{n}/{len(stage.steps)}] {step.label} {recipe.version}: building (log: {logfile})")
        with Timer() as t:
            try:
                run_script(layout, arch, stage.root, recipe.bootstrap[step.profile].script,
                           workdir, env0, logfile)
            except KelError as e:
                raise KelError(f"{step.label}: {e}")
        stamp.write_text(json.dumps({"key": key, "version": recipe.pkgver,
                                     "seconds": round(t.elapsed)}, indent=2) + "\n")
        log(f"[{n}/{len(stage.steps)}] {step.label}: done in {format_duration(t.elapsed)}")
        if not keep:
            shutil.rmtree(workdir, ignore_errors=True)

    if stage.verify and not only:
        verify_stage(layout, arch, stage, env0)


def verify_stage(layout: Layout, arch: Arch, stage: Stage, env: dict[str, str]) -> None:
    if not stage.verify:
        raise KelError(f"stage {stage.name} has no [verify] script")
    workdir = layout.builds(arch) / stage.name / "verify"
    shutil.rmtree(workdir, ignore_errors=True)
    workdir.mkdir(parents=True)
    logfile = layout.logs(arch) / stage.name / "verify.log"
    log(f"verifying stage {stage.name} (log: {logfile})")
    run_script(layout, arch, stage.root, stage.verify, workdir, env, logfile)
    log(f"stage {stage.name}: verification passed")
    print(_tail(logfile, 20))
