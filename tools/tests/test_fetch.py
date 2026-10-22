import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from kel.fetch import fetch_source, gpg_verify, parse_gpg_status
from kel.recipe import Source
from kel.util import KelError, sha256_file

PIN = "647F28654894E3BD457199BE38DBBDC86092693E"
OTHER = "B" * 40


def validsig(primary: str, sub: str | None = None) -> str:
    return f"[GNUPG:] VALIDSIG {sub or primary} 2026-10-21 1792571611 0 4 0 1 10 00 {primary}\n"


class StatusParsingTests(unittest.TestCase):
    def test_pinned_primary_key(self):
        r = parse_gpg_status("[GNUPG:] GOODSIG X name\n" + validsig(PIN, "C" * 40), (PIN,))
        self.assertTrue(r.ok)
        self.assertEqual(r.fingerprint, PIN)

    def test_unpinned_key_rejected(self):
        self.assertFalse(parse_gpg_status(validsig(OTHER), (PIN,)).ok)

    def test_expired_key_copy_accepted(self):
        r = parse_gpg_status("[GNUPG:] EXPKEYSIG X name\n" + validsig(PIN), (PIN,))
        self.assertTrue(r.ok)
        self.assertTrue(any("expired" in n for n in r.notes))

    def test_bad_or_revoked_rejected(self):
        for kw in ("BADSIG X name", "REVKEYSIG X name", "ERRSIG X 1 10 00 0 9 " + PIN):
            self.assertFalse(parse_gpg_status(f"[GNUPG:] {kw}\n" + validsig(PIN), (PIN,)).ok, kw)

    def test_no_signature(self):
        self.assertFalse(parse_gpg_status("", (PIN,)).ok)


@unittest.skipUnless(shutil.which("gpg"), "gpg not installed")
class RealGpgTests(unittest.TestCase):
    """Sign with a throwaway key and verify through kel's code path."""

    @classmethod
    def setUpClass(cls):
        # Short path: gpg-agent sockets must fit in sun_path.
        cls.home = tempfile.mkdtemp(prefix="kelgpg", dir="/tmp")
        os.chmod(cls.home, 0o700)
        cls.base = ["gpg", "--batch", "--homedir", cls.home, "--pinentry-mode", "loopback",
                    "--passphrase", ""]
        subprocess.run(cls.base + ["--quick-gen-key", "kel-test <test@kel.invalid>",
                                   "ed25519", "sign", "1d"], check=True, capture_output=True)
        out = subprocess.run(["gpg", "--batch", "--homedir", cls.home, "--with-colons",
                              "--list-keys"], check=True, capture_output=True, text=True).stdout
        cls.fpr = next(l.split(":")[9] for l in out.splitlines() if l.startswith("fpr:"))
        cls.work = Path(tempfile.mkdtemp(prefix="kelfetch"))
        cls.keyfile = cls.work / f"{cls.fpr}.asc"
        cls.keyfile.write_bytes(subprocess.run(
            ["gpg", "--batch", "--homedir", cls.home, "--armor", "--export", cls.fpr],
            check=True, capture_output=True).stdout)

    @classmethod
    def tearDownClass(cls):
        subprocess.run(["gpgconf", "--homedir", cls.home, "--kill", "all"], capture_output=True)
        shutil.rmtree(cls.home, ignore_errors=True)
        shutil.rmtree(cls.work, ignore_errors=True)

    def sign(self, data: Path) -> Path:
        sig = data.with_name(data.name + ".sig")
        subprocess.run(self.base + ["--detach-sign", "--output", str(sig), str(data)],
                       check=True, capture_output=True)
        return sig

    def test_good_and_tampered(self):
        data = self.work / "payload.txt"
        data.write_text("hello kel\n")
        sig = self.sign(data)
        self.assertTrue(gpg_verify([self.keyfile], (self.fpr,), sig, data).ok)
        self.assertFalse(gpg_verify([self.keyfile], (OTHER,), sig, data).ok)
        data.write_text("hello kel, tampered\n")
        self.assertFalse(gpg_verify([self.keyfile], (self.fpr,), sig, data).ok)

    def test_signature_over_uncompressed_data(self):
        raw = self.work / "archive.tar"
        raw.write_bytes(b"pretend tar content\n" * 100)
        sig = self.sign(raw)
        subprocess.run(["xz", "-kf", str(raw)], check=True)
        r = gpg_verify([self.keyfile], (self.fpr,), sig, raw.with_suffix(".tar.xz"), uncompressed=True)
        self.assertTrue(r.ok)


class CacheTests(unittest.TestCase):
    def test_offline_uses_cache_and_checks_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp)
            content = b"source bytes"
            probe = cache / "probe"
            probe.write_bytes(content)
            sha = sha256_file(probe)
            src = Source(url="https://example.org/a.tar.gz", sha256=sha, filename="a.tar.gz")
            (cache / sha).mkdir()
            (cache / sha / "a.tar.gz").write_bytes(content)
            self.assertEqual(fetch_source(cache, cache, src, offline=True).read_bytes(), content)
            (cache / sha / "a.tar.gz").write_bytes(b"corrupted")
            with self.assertRaises(KelError):
                fetch_source(cache, cache, src, offline=True)


if __name__ == "__main__":
    unittest.main()
