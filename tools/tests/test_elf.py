import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from kel.elf import read_elf, read_sections


@unittest.skipUnless(shutil.which("cc"), "no C compiler")
class ElfTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="kelelf"))
        # Use a libc function so libc.so.6 stays in DT_NEEDED with --as-needed.
        (cls.tmp / "lib.c").write_text(
            "#include <stdio.h>\nint kel_answer(void) { puts(\"kel\"); return 42; }\n")
        (cls.tmp / "main.c").write_text(
            "int kel_answer(void);\nint main(void) { return kel_answer() == 42 ? 0 : 1; }\n")
        subprocess.run(["cc", "-shared", "-fPIC", "-Wl,-soname,libkeltest.so.1",
                        "-o", "libkeltest.so.1", "lib.c"], cwd=cls.tmp, check=True)
        subprocess.run(["cc", "-o", "prog", "main.c", "-L.", "-l:libkeltest.so.1",
                        "-Wl,-rpath,/opt/kel-test/lib"], cwd=cls.tmp, check=True)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_shared_library(self):
        info = read_elf(self.tmp / "libkeltest.so.1")
        self.assertEqual(info.soname, "libkeltest.so.1")
        self.assertIn("libc.so.6", info.needed)

    def test_executable(self):
        info = read_elf(self.tmp / "prog")
        self.assertIsNotNone(info.interpreter)
        self.assertIn("libkeltest.so.1", info.needed)
        self.assertEqual(info.rpath + info.runpath, ["/opt/kel-test/lib"])

    def test_not_elf(self):
        self.assertIsNone(read_elf(self.tmp / "lib.c"))
        self.assertIsNone(read_sections((self.tmp / "lib.c").read_bytes()))

    def test_sections(self):
        sections = {s.name: s for s in read_sections((self.tmp / "prog").read_bytes())}
        self.assertIn(".text", sections)
        self.assertIn(".dynamic", sections)
        self.assertGreater(sections[".text"].size, 0)


if __name__ == "__main__":
    unittest.main()
