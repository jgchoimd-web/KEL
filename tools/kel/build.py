"""Turn a recipe's [build] section into the shell script that builds it.

The script runs inside the sandbox with:
  KEL_SRCDIR     unpacked sources (each phase starts here)
  KEL_RECIPEDIR  the recipe directory, read-only (patches/, files/)
  DESTDIR        where the install phase must put the files
Phases run in order: patch, prepare, configure, compile, test, install,
post_install, finish. Each style supplies defaults that a recipe can
replace phase by phase (docs/DESIGN.md section 4.3).
"""

from __future__ import annotations

import shlex

from kel.recipe import BUILD_PHASES, BuildSpec, Recipe

# Merged /usr with bin and sbin merged (DESIGN.md 4.7).
GNU_CONFIGURE_ARGS = (
    "--prefix=/usr", "--sysconfdir=/etc", "--localstatedir=/var",
    "--sbindir=/usr/bin", "--mandir=/usr/share/man", "--infodir=/usr/share/info",
)
MESON_ARGS = (
    "--prefix=/usr", "--sysconfdir=/etc", "--localstatedir=/var", "--sbindir=bin",
    "--buildtype=release", "--wrap-mode=nodownload",
)
CMAKE_ARGS = (
    "-DCMAKE_INSTALL_PREFIX=/usr", "-DCMAKE_INSTALL_SBINDIR=bin",
    "-DCMAKE_INSTALL_LIBDIR=lib", "-DCMAKE_BUILD_TYPE=Release",
)


def _q(args) -> str:
    return " ".join(shlex.quote(a) for a in args)


def default_phases(spec: BuildSpec) -> dict[str, str]:
    make_args = _q(spec.make_args)
    if spec.style == "gnu-configure":
        enter = "cd build\n" if spec.out_of_tree else ""
        configure = (("mkdir -p build\ncd build\n../configure " if spec.out_of_tree else "./configure ")
                     + _q(GNU_CONFIGURE_ARGS + spec.configure_args))
        return {
            "configure": configure,
            "compile": f"{enter}make {make_args}".rstrip(),
            "test": f"{enter}make check",
            "install": f'{enter}make DESTDIR="$DESTDIR" install',
        }
    if spec.style == "meson":
        return {
            "configure": "meson setup build " + _q(MESON_ARGS + spec.configure_args),
            "compile": "meson compile -C build",
            "test": "meson test -C build --print-errorlogs",
            "install": 'DESTDIR="$DESTDIR" meson install -C build --no-rebuild',
        }
    if spec.style == "cmake":
        return {
            "configure": "cmake -B build " + _q(CMAKE_ARGS + spec.configure_args),
            "compile": "cmake --build build",
            "test": "ctest --test-dir build --output-on-failure",
            "install": 'DESTDIR="$DESTDIR" cmake --install build',
        }
    if spec.style == "make":
        return {
            "compile": f"make {make_args}".rstrip(),
            "test": "make check",
            "install": f'make DESTDIR="$DESTDIR" install {make_args}'.rstrip(),
        }
    return {}  # custom: everything comes from the recipe


# Runs last, in $DESTDIR: fold non-merged paths into /usr, drop libtool
# archives and the info index, strip debug info, and make sure the license
# texts are shipped (DESIGN.md 4.16).
FINISH = r'''
kel_finish() {
    cd "$DESTDIR"
    local d f
    for d in bin sbin usr/sbin; do
        if [ -d "$d" ] && [ ! -L "$d" ]; then
            mkdir -p usr/bin
            cp -a "$d"/. usr/bin/
            rm -rf "$d"
        fi
    done
    for d in lib lib64 usr/lib64; do
        if [ -d "$d" ] && [ ! -L "$d" ]; then
            mkdir -p usr/lib
            cp -a "$d"/. usr/lib/
            rm -rf "$d"
        fi
    done
    if [ "$KEL_KEEP_LA" != 1 ]; then
        find . -name '*.la' -type f -delete
    fi
    rm -f usr/share/info/dir
    if [ "$KEL_STRIP" = 1 ]; then
        find . -type f \( -perm -u+x -o -name '*.so*' -o -name '*.a' -o -name '*.o' \) -print0 |
        while IFS= read -r -d '' f; do
            if readelf -h "$f" >/dev/null 2>&1; then
                strip --strip-debug "$f" 2>/dev/null || true
            fi
        done
    fi
    if [ ! -d "usr/share/licenses/$KEL_PKGNAME" ]; then
        for f in "$KEL_SRCDIR"/COPYING* "$KEL_SRCDIR"/LICENSE* "$KEL_SRCDIR"/LICENCE* \
                 "$KEL_SRCDIR"/COPYRIGHT* "$KEL_SRCDIR"/NOTICE*; do
            [ -f "$f" ] || continue
            install -Dm644 "$f" "usr/share/licenses/$KEL_PKGNAME/$(basename "$f")"
        done
    fi
}
'''

PATCH = r'''
kel_patch() {
    cd "$KEL_SRCDIR"
    local p
    for p in "$KEL_RECIPEDIR"/patches/*.patch; do
        [ -e "$p" ] || continue
        echo "applying $(basename "$p")"
        patch -Np1 -i "$p"
    done
}
'''


def build_script(recipe: Recipe, run_check: bool = True) -> str:
    spec = recipe.build
    assert spec is not None
    phases = default_phases(spec)
    phases.update(spec.phases)
    parts = [PATCH, FINISH]
    for phase in BUILD_PHASES:
        body = phases.get(phase, ":")
        parts.append(f'kel_{phase}() {{\n    cd "$KEL_SRCDIR"\n{body}\n}}\n')
    order = ["patch", "prepare", "configure", "compile"]
    if spec.check and run_check:
        order.append("test")
    order += ["install", "post_install", "finish"]
    parts.append("\n".join(f'echo "==> kel: {p}"\nkel_{p}' for p in order) + "\n")
    return "\n".join(parts)
