import tempfile
import textwrap
import unittest
from pathlib import Path

from kel.config import REPO_ROOT
from kel.recipe import all_recipe_names, load_recipe, parse_recipe, validate_spdx
from kel.util import KelError

FPR = "A" * 40
SHA = "0" * 64

GOOD = f'''
[package]
name = "demo"
version = "1.2.3"
revision = 1
summary = "Demo"
license = "MIT OR (Apache-2.0 AND BSD-2-Clause)"
homepage = "https://example.org/"

[[source]]
url = "https://example.org/demo-1.2.3.tar.xz"
sha256 = "{SHA}"
signature = "https://example.org/demo-1.2.3.tar.xz.sig"
signing_keys = ["{FPR}"]

[[source]]
url = "https://example.org/extra-2.0.tar.gz"
sha256 = "{"1" * 64}"
dest = "extra"

[bootstrap.pass1]
script = "make"
'''


class RecipeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.keys = root / "keys"
        self.keys.mkdir()
        (self.keys / f"{FPR}.asc").write_text("dummy")
        self.recipes = root / "recipes"
        (self.recipes / "demo").mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, text: str) -> Path:
        path = self.recipes / "demo" / "recipe.toml"
        path.write_text(textwrap.dedent(text))
        return path

    def test_good_recipe(self):
        r = parse_recipe(self.write(GOOD), self.keys)
        self.assertEqual(r.pkgver, "1.2.3-r1")
        self.assertEqual(r.sources[0].filename, "demo-1.2.3.tar.xz")
        self.assertEqual(r.sources[1].dest, "extra")
        self.assertEqual(r.bootstrap["pass1"].script, "make")
        self.assertEqual(r.env_name, "DEMO")
        self.assertEqual(len(r.digest), 64)

    def test_digest_changes_with_patches(self):
        path = self.write(GOOD)
        d1 = parse_recipe(path, self.keys).digest
        (path.parent / "patches").mkdir()
        (path.parent / "patches" / "fix.patch").write_text("--- a\n+++ b\n")
        self.assertNotEqual(d1, parse_recipe(path, self.keys).digest)

    def assertRejected(self, text: str, fragment: str):
        with self.assertRaises(KelError) as cm:
            parse_recipe(self.write(text), self.keys)
        self.assertIn(fragment, str(cm.exception))

    def test_rejects_http_url(self):
        self.assertRejected(GOOD.replace("https://example.org/demo", "http://example.org/demo"), "https")

    def test_rejects_bad_sha256(self):
        self.assertRejected(GOOD.replace(SHA, "abc"), "sha256")

    def test_rejects_missing_key_file(self):
        self.assertRejected(GOOD.replace(FPR, "B" * 40), "is missing")

    def test_rejects_unknown_key(self):
        self.assertRejected(GOOD.replace('revision = 1', 'revison = 1'), "unknown key")

    def test_rejects_bad_license(self):
        self.assertRejected(GOOD.replace('license = "MIT OR', 'license = "MIT or'), "SPDX")

    def test_rejects_name_mismatch(self):
        self.assertRejected(GOOD.replace('name = "demo"', 'name = "other"'), "does not match")

    def test_rejects_signature_without_keys(self):
        self.assertRejected(GOOD.replace(f'signing_keys = ["{FPR}"]', ""), "signing_keys")

    def test_rejects_dest_escape(self):
        self.assertRejected(GOOD.replace('dest = "extra"', 'dest = "../x"'), "bad dest")


class SpdxTests(unittest.TestCase):
    def test_valid(self):
        for expr in ("MIT", "GPL-2.0-only WITH Linux-syscall-note",
                     "GPL-3.0-or-later AND GPL-3.0-or-later WITH GCC-exception-3.1",
                     "(MIT OR Apache-2.0) AND BSD-3-Clause", "LicenseRef-kel-firmware"):
            self.assertTrue(validate_spdx(expr), expr)

    def test_invalid(self):
        for expr in ("", "MIT OR", "AND MIT", "(MIT", "MIT)", "MIT Apache-2.0", "MIT or GPL-2.0-only"):
            self.assertFalse(validate_spdx(expr), expr)


class RepositoryRecipesTests(unittest.TestCase):
    """Every recipe committed to the repository must validate."""

    def test_all_recipes_validate(self):
        recipes = REPO_ROOT / "recipes"
        names = all_recipe_names(recipes)
        self.assertTrue(names)
        for name in names:
            load_recipe(recipes, REPO_ROOT / "keys" / "upstream", name)


if __name__ == "__main__":
    unittest.main()
