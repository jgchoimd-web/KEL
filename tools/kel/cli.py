"""Command line interface: ./kel <command> ..."""

from __future__ import annotations

import argparse
import os
import sys

from kel import __version__
from kel.bootstrap import base_env, load_stage, run_stage, verify_stage
from kel.config import ARCHES, Layout, get_arch
from kel.fetch import fetch_recipe
from kel.hostcheck import check_host
from kel.recipe import all_recipe_names, load_recipe
from kel.util import KelError, log


def cmd_check_host(args: argparse.Namespace, layout: Layout) -> int:
    failed = 0
    for r in check_host():
        mark = "ok " if r.ok else "BAD"
        print(f"[{mark}] {r.label:20} {r.found}")
        failed += not r.ok
    if failed:
        log(f"{failed} host requirement(s) not met")
        return 1
    log("host meets all requirements")
    return 0


def _recipes(layout: Layout, names: list[str]):
    names = names or all_recipe_names(layout.recipes)
    if not names:
        raise KelError("no recipes found")
    return [load_recipe(layout.recipes, layout.upstream_keys, n) for n in names]


def cmd_lint(args: argparse.Namespace, layout: Layout) -> int:
    for r in _recipes(layout, args.names):
        profiles = ", ".join(r.bootstrap) or "-"
        print(f"{r.name:16} {r.pkgver:16} {r.license:32} sources={len(r.sources)} bootstrap={profiles}")
    return 0


def cmd_fetch(args: argparse.Namespace, layout: Layout) -> int:
    for r in _recipes(layout, args.names):
        for path in fetch_recipe(layout.sources, layout.upstream_keys, r, offline=args.offline):
            print(path)
    return 0


def cmd_bootstrap(args: argparse.Namespace, layout: Layout) -> int:
    arch = get_arch(args.arch)
    if args.verify_only:
        stage = load_stage(layout, args.stage)
        recipes = {s.recipe: load_recipe(layout.recipes, layout.upstream_keys, s.recipe)
                   for s in stage.steps}
        verify_stage(layout, arch, stage, base_env(layout, arch, args.jobs, recipes, stage.root))
        return 0
    run_stage(layout, arch, args.stage, jobs=args.jobs, force=args.force, keep=args.keep,
              only=args.step, offline=args.offline)
    return 0


def cmd_paths(args: argparse.Namespace, layout: Layout) -> int:
    arch = get_arch(args.arch)
    print(f"repo     {layout.repo}")
    print(f"workdir  {layout.workdir}")
    print(f"sources  {layout.sources}")
    print(f"sysroot  {layout.sysroot(arch)}")
    print(f"tools    {layout.tools(arch)}")
    print(f"logs     {layout.logs(arch)}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="kel", description="KEL build tool")
    p.add_argument("--version", action="version", version=f"kel {__version__}")
    p.add_argument("--workdir", help="build work directory (env KEL_WORKDIR, default ./work)")
    p.add_argument("--cachedir", help="download cache (env KEL_CACHEDIR, default ./cache)")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("check-host", help="check bootstrap host requirements (stage 0)")
    s.set_defaults(func=cmd_check_host)

    s = sub.add_parser("lint", help="validate recipes")
    s.add_argument("names", nargs="*")
    s.set_defaults(func=cmd_lint)

    s = sub.add_parser("fetch", help="download and verify recipe sources")
    s.add_argument("names", nargs="*")
    s.add_argument("--offline", action="store_true", help="only use the cache")
    s.set_defaults(func=cmd_fetch)

    s = sub.add_parser("bootstrap", help="run a bootstrap stage (bootstrap/<stage>.toml)")
    s.add_argument("stage")
    s.add_argument("--arch", default="x86_64", choices=sorted(ARCHES))
    s.add_argument("--jobs", "-j", type=int, default=os.cpu_count() or 1)
    s.add_argument("--force", action="store_true", help="rebuild steps even if up to date")
    s.add_argument("--keep", action="store_true", help="keep build directories")
    s.add_argument("--step", help="run only this step (recipe:profile)")
    s.add_argument("--offline", action="store_true", help="only use the download cache")
    s.add_argument("--verify-only", action="store_true", help="only run the stage verification")
    s.set_defaults(func=cmd_bootstrap)

    s = sub.add_parser("paths", help="show directories kel uses")
    s.add_argument("--arch", default="x86_64", choices=sorted(ARCHES))
    s.set_defaults(func=cmd_paths)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    layout = Layout.from_env(args.workdir, args.cachedir)
    try:
        return args.func(args, layout)
    except KelError as e:
        print(f"kel: error: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("kel: interrupted", file=sys.stderr)
        return 130
