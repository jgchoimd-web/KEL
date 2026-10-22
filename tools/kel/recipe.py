"""Recipe loading and validation.

A recipe is recipes/<name>/recipe.toml: declarative metadata that can be read
without running any code, plus short shell scripts for the build steps.
See docs/DESIGN.md section 4.3.
"""

from __future__ import annotations

import hashlib
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from urllib.parse import urlparse

from kel.util import KelError

NAME_RE = re.compile(r"^[a-z0-9][a-z0-9+._-]*$")
VERSION_RE = re.compile(r"^[0-9][0-9A-Za-z._+~]*$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
FINGERPRINT_RE = re.compile(r"^[0-9A-F]{40}$")
PROFILE_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
SPDX_TOKEN_RE = re.compile(r"\(|\)|[A-Za-z0-9][A-Za-z0-9.+-]*(?::[A-Za-z0-9.+-]+)?")

SIGNATURE_TYPES = ("detached", "detached-uncompressed")

TOP_LEVEL_KEYS = {"schema", "package", "source", "bootstrap", "build", "subpackages"}
PACKAGE_KEYS = {"name", "version", "revision", "summary", "license", "homepage"}
SOURCE_KEYS = {"url", "sha256", "filename", "signature", "signature_type", "signing_keys", "dest"}
PROFILE_KEYS = {"script"}


@dataclass(frozen=True)
class Source:
    url: str
    sha256: str
    filename: str
    signature: str | None = None
    signature_type: str = "detached"
    signing_keys: tuple[str, ...] = ()
    # If set, the extracted top-level directory of this source is moved to
    # this path inside the main (first) source tree, e.g. GCC's "gmp".
    dest: str | None = None


@dataclass(frozen=True)
class Profile:
    name: str
    script: str


@dataclass(frozen=True)
class Recipe:
    name: str
    version: str
    revision: int
    summary: str
    license: str
    homepage: str
    sources: tuple[Source, ...]
    bootstrap: dict[str, Profile] = field(default_factory=dict)
    path: Path = Path()
    digest: str = ""

    @property
    def pkgver(self) -> str:
        return f"{self.version}-r{self.revision}"

    @property
    def env_name(self) -> str:
        """Suffix used for KEL_VERSION_<NAME> variables (e.g. GCC, LINUX)."""
        return re.sub(r"[^A-Z0-9]", "_", self.name.upper())


def _fail(where: str, msg: str) -> KelError:
    return KelError(f"{where}: {msg}")


def _check_keys(where: str, table: dict, allowed: set[str]) -> None:
    unknown = sorted(set(table) - allowed)
    if unknown:
        raise _fail(where, f"unknown key(s): {', '.join(unknown)}")


def _require_str(where: str, table: dict, key: str) -> str:
    value = table.get(key)
    if not isinstance(value, str) or not value.strip():
        raise _fail(where, f"'{key}' must be a non-empty string")
    return value


def validate_spdx(expr: str) -> bool:
    """Light check of an SPDX license expression (tokens and parentheses)."""
    pos, depth, tokens = 0, 0, []
    for m in SPDX_TOKEN_RE.finditer(expr):
        if expr[pos:m.start()].strip():
            return False
        pos = m.end()
        tok = m.group(0)
        if tok == "(":
            depth += 1
        elif tok == ")":
            depth -= 1
            if depth < 0:
                return False
        tokens.append(tok)
    if expr[pos:].strip() or depth != 0 or not tokens:
        return False
    # Operators must sit between operands.
    expect_operand = True
    for tok in tokens:
        if tok == "(":
            if not expect_operand:
                return False
        elif tok == ")":
            if expect_operand:
                return False
        elif tok in ("AND", "OR", "WITH"):
            if expect_operand:
                return False
            expect_operand = True
        else:
            if not expect_operand:
                return False
            expect_operand = False
    return not expect_operand


def _parse_source(where: str, raw: dict, keydir: Path) -> Source:
    if not isinstance(raw, dict):
        raise _fail(where, "must be a table")
    _check_keys(where, raw, SOURCE_KEYS)
    url = _require_str(where, raw, "url")
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.netloc:
        raise _fail(where, f"url must be https: {url}")
    sha256 = _require_str(where, raw, "sha256")
    if not SHA256_RE.match(sha256):
        raise _fail(where, "sha256 must be 64 lowercase hex digits")
    filename = raw.get("filename") or PurePosixPath(parsed.path).name
    if not filename or "/" in filename or filename.startswith("."):
        raise _fail(where, f"bad filename {filename!r}")
    signature = raw.get("signature")
    sig_type = raw.get("signature_type", "detached")
    keys = raw.get("signing_keys", [])
    if signature is not None:
        sig_url = urlparse(_require_str(where, raw, "signature"))
        if sig_url.scheme != "https" or not sig_url.netloc:
            raise _fail(where, f"signature must be an https url: {signature}")
        if sig_type not in SIGNATURE_TYPES:
            raise _fail(where, f"signature_type must be one of {', '.join(SIGNATURE_TYPES)}")
        if not isinstance(keys, list) or not keys:
            raise _fail(where, "a signature needs a non-empty 'signing_keys' list")
        for fpr in keys:
            if not isinstance(fpr, str) or not FINGERPRINT_RE.match(fpr):
                raise _fail(where, f"signing key {fpr!r} must be a 40-digit uppercase fingerprint")
            if not (keydir / f"{fpr}.asc").is_file():
                raise _fail(where, f"public key keys/upstream/{fpr}.asc is missing")
    elif keys or "signature_type" in raw:
        raise _fail(where, "'signing_keys'/'signature_type' given without 'signature'")
    dest = raw.get("dest")
    if dest is not None:
        if not isinstance(dest, str) or not dest or dest.startswith("/") or ".." in PurePosixPath(dest).parts:
            raise _fail(where, f"bad dest {dest!r}")
    return Source(
        url=url,
        sha256=sha256,
        filename=filename,
        signature=signature,
        signature_type=sig_type,
        signing_keys=tuple(keys),
        dest=dest,
    )


def recipe_digest(recipe_dir: Path) -> str:
    """Hash every file in the recipe directory, so patch edits invalidate builds."""
    h = hashlib.sha256()
    for path in sorted(p for p in recipe_dir.rglob("*") if p.is_file()):
        rel = path.relative_to(recipe_dir).as_posix()
        h.update(rel.encode() + b"\0")
        h.update(hashlib.sha256(path.read_bytes()).digest())
    return h.hexdigest()


def parse_recipe(path: Path, keydir: Path) -> Recipe:
    where = str(path)
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise KelError(f"{where}: no such recipe")
    except tomllib.TOMLDecodeError as e:
        raise _fail(where, f"TOML error: {e}")
    _check_keys(where, data, TOP_LEVEL_KEYS)
    if data.get("schema", 1) != 1:
        raise _fail(where, "unsupported schema version")

    pkg = data.get("package")
    if not isinstance(pkg, dict):
        raise _fail(where, "missing [package] table")
    pw = f"{where}: [package]"
    _check_keys(pw, pkg, PACKAGE_KEYS)
    name = _require_str(pw, pkg, "name")
    if not NAME_RE.match(name):
        raise _fail(pw, f"bad name {name!r}")
    if path.parent.name != name:
        raise _fail(pw, f"name {name!r} does not match directory {path.parent.name!r}")
    version = _require_str(pw, pkg, "version")
    if not VERSION_RE.match(version):
        raise _fail(pw, f"bad version {version!r}")
    revision = pkg.get("revision", 0)
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 0:
        raise _fail(pw, "revision must be a non-negative integer")
    license_expr = _require_str(pw, pkg, "license")
    if not validate_spdx(license_expr):
        raise _fail(pw, f"license {license_expr!r} is not a valid SPDX expression")
    summary = _require_str(pw, pkg, "summary")
    homepage = _require_str(pw, pkg, "homepage")

    # KEL's own packages (base filesystem, os-release, ...) have no upstream
    # source; their files live in recipes/<name>/files/.
    raw_sources = data.get("source", [])
    if not isinstance(raw_sources, list):
        raise _fail(where, "[[source]] must be an array of tables")
    sources = tuple(
        _parse_source(f"{where}: source[{i}]", raw, keydir) for i, raw in enumerate(raw_sources)
    )
    if sources and sources[0].dest is not None:
        raise _fail(where, "the first source is the main tree and cannot have 'dest'")
    names = [s.filename for s in sources]
    if len(set(names)) != len(names):
        raise _fail(where, "source filenames must be unique")

    profiles: dict[str, Profile] = {}
    raw_boot = data.get("bootstrap", {})
    if not isinstance(raw_boot, dict):
        raise _fail(where, "[bootstrap] must be a table of profiles")
    for pname, raw in raw_boot.items():
        bw = f"{where}: [bootstrap.{pname}]"
        if not PROFILE_RE.match(pname):
            raise _fail(bw, "bad profile name")
        if not isinstance(raw, dict):
            raise _fail(bw, "must be a table")
        _check_keys(bw, raw, PROFILE_KEYS)
        profiles[pname] = Profile(name=pname, script=_require_str(bw, raw, "script"))

    return Recipe(
        name=name,
        version=version,
        revision=revision,
        summary=summary,
        license=license_expr,
        homepage=homepage,
        sources=sources,
        bootstrap=profiles,
        path=path,
        digest=recipe_digest(path.parent),
    )


def load_recipe(recipes_dir: Path, keydir: Path, name: str) -> Recipe:
    if not NAME_RE.match(name):
        raise KelError(f"bad recipe name {name!r}")
    return parse_recipe(recipes_dir / name / "recipe.toml", keydir)


def all_recipe_names(recipes_dir: Path) -> list[str]:
    if not recipes_dir.is_dir():
        return []
    return sorted(p.parent.name for p in recipes_dir.glob("*/recipe.toml"))
