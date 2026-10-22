import unittest

from kel.build import build_script
from kel.recipe import BuildSpec, Recipe


def recipe(spec: BuildSpec) -> Recipe:
    return Recipe(name="demo", version="1.0", revision=0, summary="s", license="MIT",
                  homepage="https://example.org/", sources=(), build=spec)


class BuildScriptTests(unittest.TestCase):
    def test_gnu_configure_defaults(self):
        script = build_script(recipe(BuildSpec(style="gnu-configure",
                                               configure_args=("--disable-static",))))
        self.assertIn("../configure --prefix=/usr", script)
        self.assertIn("--sbindir=/usr/bin", script)
        self.assertIn("--disable-static", script)
        self.assertIn('make DESTDIR="$DESTDIR" install', script)
        order = [line for line in script.splitlines() if line.startswith("kel_")]
        self.assertEqual(order, ["kel_patch", "kel_prepare", "kel_configure", "kel_compile",
                                 "kel_test", "kel_install", "kel_post_install", "kel_finish"])

    def test_override_and_skip_check(self):
        spec = BuildSpec(style="meson", check=False, phases={"post_install": "echo extra"})
        script = build_script(recipe(spec))
        self.assertIn("meson setup build --prefix=/usr", script)
        self.assertIn("echo extra", script)
        self.assertNotIn("\nkel_test\n", script)
        script = build_script(recipe(BuildSpec(style="make")), run_check=False)
        self.assertNotIn("\nkel_test\n", script)

    def test_custom_uses_recipe_phases(self):
        spec = BuildSpec(style="custom", phases={"install": 'install -Dm644 f "$DESTDIR/etc/f"'})
        script = build_script(recipe(spec))
        self.assertIn('install -Dm644 f "$DESTDIR/etc/f"', script)
        self.assertNotIn("./configure", script)


if __name__ == "__main__":
    unittest.main()
