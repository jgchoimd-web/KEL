"""Download sources into a content-addressed cache and verify them.

Every source is pinned by sha256 in its recipe. If the upstream publishes an
OpenPGP signature, it is verified with gpg against public keys stored in
keys/upstream/<FINGERPRINT>.asc, and only signatures whose primary key
fingerprint is listed in the recipe are accepted. A signature from an
expired key copy is accepted (the fingerprint pin and the sha256 pin are what
we trust); a revoked key or a bad signature is rejected.
"""

from __future__ import annotations

import bz2
import gzip
import json
import lzma
import os
import shutil
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from urllib.parse import urlparse

from kel import __version__
from kel.recipe import Recipe, Source
from kel.util import KelError, log, sha256_file, warn

USER_AGENT = f"kel/{__version__} (+https://github.com/jgchoimd-web/KEL)"
RETRY_DELAYS = (2, 4, 8, 16)


def download(url: str, dest: Path, timeout: int = 60) -> None:
    """Download url to dest atomically, retrying transient network errors."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    last_error: Exception | None = None
    for attempt, delay in enumerate((0, *RETRY_DELAYS)):
        if delay:
            warn(f"retrying {url} in {delay}s ({last_error})")
            time.sleep(delay)
        fd, tmp = tempfile.mkstemp(dir=dest.parent, prefix=".part-")
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=timeout) as resp, os.fdopen(fd, "wb") as out:
                shutil.copyfileobj(resp, out, 1 << 20)
            os.replace(tmp, dest)
            return
        except urllib.error.HTTPError as e:
            os.unlink(tmp)
            if e.code < 500:
                raise KelError(f"download failed: {url}: HTTP {e.code}")
            last_error = e
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
            if os.path.exists(tmp):
                os.unlink(tmp)
            last_error = e
    raise KelError(f"download failed: {url}: {last_error}")


def source_dir(cache: Path, source: Source) -> Path:
    return cache / source.sha256


def source_path(cache: Path, source: Source) -> Path:
    return source_dir(cache, source) / source.filename


@dataclass
class SignatureResult:
    ok: bool
    fingerprint: str | None
    notes: list[str]


def parse_gpg_status(status: str, pinned: tuple[str, ...]) -> SignatureResult:
    """Decide from gpg --status-file output whether a pinned key signed."""
    notes: list[str] = []
    fingerprint = None
    fatal = False
    for line in status.splitlines():
        if not line.startswith("[GNUPG:] "):
            continue
        fields = line[len("[GNUPG:] "):].split()
        if not fields:
            continue
        kw = fields[0]
        if kw in ("BADSIG", "ERRSIG", "REVKEYSIG", "NO_PUBKEY"):
            fatal = True
            notes.append(line)
        elif kw == "EXPKEYSIG":
            notes.append("signing key copy is expired (accepted: fingerprint is pinned)")
        elif kw == "VALIDSIG" and len(fields) >= 2:
            primary = fields[-1] if len(fields) >= 11 else fields[1]
            if primary in pinned or fields[1] in pinned:
                fingerprint = primary
            else:
                notes.append(f"valid signature from unpinned key {primary}")
    return SignatureResult(ok=fingerprint is not None and not fatal, fingerprint=fingerprint, notes=notes)


def _decompressor(filename: str):
    if filename.endswith(".xz"):
        return lzma.open
    if filename.endswith(".gz"):
        return gzip.open
    if filename.endswith(".bz2"):
        return bz2.open
    raise KelError(f"don't know how to decompress {filename} for signature check")


def gpg_verify(keyfiles: list[Path], pinned: tuple[str, ...], sig: Path, data: Path,
               uncompressed: bool = False) -> SignatureResult:
    if shutil.which("gpg") is None:
        raise KelError("gpg is required to verify upstream signatures")
    with tempfile.TemporaryDirectory(prefix="kel-gpg-") as home:
        os.chmod(home, 0o700)
        base = ["gpg", "--batch", "--no-tty", "--no-autostart", "--homedir", home]
        imp = subprocess.run(base + ["--quiet", "--import", *map(str, keyfiles)],
                             capture_output=True, text=True)
        if imp.returncode != 0:
            raise KelError(f"gpg could not import keys: {imp.stderr.strip()}")
        status_file = Path(home) / "status"
        cmd = base + ["--status-file", str(status_file), "--verify", str(sig)]
        if uncompressed:
            opener = _decompressor(data.name)
            # The status file is authoritative; gpg's human-readable output is not needed.
            proc = subprocess.Popen(cmd + ["-"], stdin=subprocess.PIPE,
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            assert proc.stdin is not None
            try:
                with opener(data, "rb") as f:
                    while chunk := f.read(1 << 20):
                        proc.stdin.write(chunk)
            except BrokenPipeError:
                pass
            finally:
                proc.stdin.close()
            proc.wait()
        else:
            subprocess.run(cmd + [str(data)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        status = status_file.read_text() if status_file.exists() else ""
    return parse_gpg_status(status, pinned)


def fetch_source(cache: Path, keydir: Path, source: Source, offline: bool = False) -> Path:
    """Make sure the source is in the cache with the right hash and signature."""
    path = source_path(cache, source)
    if path.exists() and sha256_file(path) != source.sha256:
        warn(f"cached {path.name} has the wrong sha256, fetching again")
        path.unlink()
    if not path.exists():
        if offline:
            raise KelError(f"{source.filename} is not in the cache and --offline was given")
        log(f"downloading {source.url}")
        download(source.url, path)
        actual = sha256_file(path)
        if actual != source.sha256:
            path.unlink()
            raise KelError(f"sha256 mismatch for {source.url}: expected {source.sha256}, got {actual}")
    if source.signature:
        verify_source_signature(cache, keydir, source, path, offline)
    return path


def verify_source_signature(cache: Path, keydir: Path, source: Source, path: Path,
                            offline: bool) -> None:
    assert source.signature is not None
    stamp = source_dir(cache, source) / ".verified.json"
    if stamp.exists():
        try:
            info = json.loads(stamp.read_text())
            if info.get("sha256") == source.sha256 and info.get("fingerprint") in source.signing_keys:
                return
        except (ValueError, OSError):
            pass
    sig_name = PurePosixPath(urlparse(source.signature).path).name
    sig_path = source_dir(cache, source) / sig_name
    if not sig_path.exists():
        if offline:
            raise KelError(f"signature {sig_name} is not in the cache and --offline was given")
        download(source.signature, sig_path)
    keyfiles = [keydir / f"{fpr}.asc" for fpr in source.signing_keys]
    result = gpg_verify(keyfiles, source.signing_keys, sig_path, path,
                        uncompressed=source.signature_type == "detached-uncompressed")
    for note in result.notes:
        warn(f"{source.filename}: {note}")
    if not result.ok:
        raise KelError(f"signature check failed for {source.filename}")
    stamp.write_text(json.dumps({
        "sha256": source.sha256,
        "signature": sig_name,
        "fingerprint": result.fingerprint,
        "verified_at": int(time.time()),
    }, indent=2) + "\n")
    log(f"{source.filename}: signature OK ({result.fingerprint})")


def fetch_recipe(cache: Path, keydir: Path, recipe: Recipe, offline: bool = False) -> list[Path]:
    return [fetch_source(cache, keydir, s, offline) for s in recipe.sources]
