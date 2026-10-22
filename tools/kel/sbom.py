"""SPDX 3.0.1 SBOM for each built package (docs/DESIGN.md 4.17, D-017).

`kel sbom` writes one SPDX 3.0.1 JSON-LD document per binary package from
the recipe (name, version, license, homepage, sources with sha256 and
signature, patches), the manifest kel wrote when packaging (the file list)
and the .apk file itself (its sha256, build time and per-file hashes, read
with `apk adbdump`).

Model, with element types and relationship directions as SPDX 3.0.1
defines them ("from <relationship> to"):

  SpdxDocument --rootElement--> software_Sbom (sbomType "build")
  software_Sbom --rootElement--> software_Package <name> <version>-r<rev>
  binary package --hasDistributionArtifact--> software_File <name>-<pkgver>.apk
  binary package --contains--> software_File for every file and symlink
  binary package --hasDeclaredLicense--> simplelicensing_LicenseExpression
  upstream source (software_Package) --generates--> binary package
  first source --patchedBy--> software_File for each recipe patch
  CreationInfo: createdBy the KEL Organization, createdUsing the kel Tool

SPDX 3.0.1 has no "generatedFrom": the source "generates" the binary
("The from Element generates each to Element"), as in example4 of the
SPDX examples. The declared license is the recipe's SPDX expression, which
the package metadata also carries; no concluded license is asserted.

Reproducible output: the only timestamp is the package build time (the
SOURCE_DATE_EPOCH it was built with), element IDs are derived from name,
version, architecture and paths, and the document is written in the
canonical serialization of the spec (chapter 6: keys sorted, no whitespace).

Sources (read 2026-10-22):
- https://spdx.github.io/spdx-spec/v3.0.1/ (model/Core, model/Software,
  model/SimpleLicensing; model/Core/Vocabularies/RelationshipType/;
  serializations/ for JSON-LD and the canonical form)
- https://spdx.org/rdf/3.0.1/spdx-context.jsonld (the JSON-LD term names)
- https://spdx.org/schema/3.0.1/spdx-json-schema.json (the structure)
- https://github.com/spdx/spdx-examples (software/example4, software/example12
  and ai/example02, spdx3.0 directories)
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from kel import __version__
from kel.config import Arch, Layout
from kel.pkg import package_entries, package_metadata
from kel.recipe import Recipe
from kel.util import KelError, sha256_file

SPEC_VERSION = "3.0.1"
CONTEXT = "https://spdx.org/rdf/3.0.1/spdx-context.jsonld"
# Element IDs live under the project's home page (os-release HOME_URL,
# DESIGN.md 4.7). They are identifiers; nothing has to be served there.
NAMESPACE = "https://github.com/jgchoimd-web/KEL/spdx"
ORGANIZATION_ID = f"{NAMESPACE}/Organization/KEL"
ORGANIZATION_NAME = "KEL (Kelp Enterprise Linux)"
CREATION_INFO = "_:creationinfo"
# License of the SPDX data itself (spec: Core/Properties/dataLicense).
DATA_LICENSE = "CC0-1.0"
PROFILES = ["core", "simpleLicensing", "software"]

SIGNATURES = {
    "detached": "OpenPGP signature of the file",
    "detached-uncompressed": "OpenPGP signature of the decompressed file",
    "clearsigned-checksums": "OpenPGP clearsigned checksum list naming the file and its sha256",
}


@dataclass(frozen=True)
class PackageFile:
    path: str  # absolute path as installed
    sha256: str = ""  # regular files
    link_target: str = ""  # symbolic links


@dataclass(frozen=True)
class BuiltPackage:
    name: str
    version: str  # <version>-r<revision>
    arch: str
    summary: str
    license: str
    filename: str  # the .apk file
    sha256: str  # of the .apk file
    build_time: int  # SOURCE_DATE_EPOCH the package was built with
    files: tuple[PackageFile, ...] = ()


def iso_time(epoch: int) -> str:
    return datetime.fromtimestamp(epoch, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _q(text: str) -> str:
    return quote(text, safe="")


def package_url(name: str, version: str, arch: str) -> str:
    """purl of a KEL binary package (purl type "apk", namespace = distribution)."""
    return f"pkg:apk/kel/{_q(name)}@{_q(version)}?arch={_q(arch)}"


def _sha256(value: str) -> dict:
    return {"type": "Hash", "algorithm": "sha256", "hashValue": value}


def recipe_patches(recipe: Recipe) -> list[tuple[str, str]]:
    """(file name, sha256) of recipes/<name>/patches/*.patch in the order kel applies them."""
    if not recipe.path.name:
        return []
    patches = recipe.path.parent / "patches"
    if not patches.is_dir():
        return []
    return [(p.name, sha256_file(p)) for p in sorted(patches.glob("*.patch")) if p.is_file()]


def build_sbom(recipe: Recipe, pkg: BuiltPackage, patches: list[tuple[str, str]] = ()) -> dict:
    """The SPDX 3.0.1 JSON-LD document (as a dict) for one built package."""
    base = f"{NAMESPACE}/{_q(pkg.arch)}/{_q(pkg.name)}-{_q(pkg.version)}"
    created = iso_time(pkg.build_time)
    elements: list[dict] = []

    def ref(fragment: str) -> str:
        return f"{base}#{quote(fragment, safe='/')}"

    def element(spdx_type: str, spdx_id: str, **props) -> str:
        elements.append({"type": spdx_type, "spdxId": spdx_id, "creationInfo": CREATION_INFO,
                         **props})
        return spdx_id

    def relationship(kind: str, spdx_id: str, source: str, targets: list[str], **props) -> None:
        element("Relationship", spdx_id, relationshipType=kind, to=targets, **{"from": source},
                **props)

    organization = element("Organization", ORGANIZATION_ID, name=ORGANIZATION_NAME)
    tool = element("Tool", f"{NAMESPACE}/Tool/kel-{_q(__version__)}",
                   name=f"kel {__version__}")
    data_license = element("simplelicensing_LicenseExpression", ref("DataLicense"),
                           simplelicensing_licenseExpression=DATA_LICENSE)

    package = element("software_Package", ref("Package"), name=pkg.name,
                      software_packageVersion=pkg.version,
                      software_packageUrl=package_url(pkg.name, pkg.version, pkg.arch),
                      software_homePage=recipe.homepage, software_primaryPurpose="install",
                      description=pkg.summary, builtTime=created, suppliedBy=organization,
                      verifiedUsing=[_sha256(pkg.sha256)])
    artifact = element("software_File", ref("DistributionArtifact"), name=pkg.filename,
                       software_primaryPurpose="archive", builtTime=created,
                       suppliedBy=organization, verifiedUsing=[_sha256(pkg.sha256)])
    relationship("hasDistributionArtifact", ref("Relationship/hasDistributionArtifact"),
                 package, [artifact], completeness="complete")

    files = []
    for f in pkg.files:
        props: dict = {"name": f.path}
        if f.sha256:
            props["verifiedUsing"] = [_sha256(f.sha256)]
        if f.link_target:
            props["comment"] = f"symbolic link to {f.link_target}"
        files.append(element("software_File", ref("File" + f.path), **props))
    if files:
        relationship("contains", ref("Relationship/contains"), package, files,
                     comment="every file and symbolic link of the package (directories are "
                             "not listed)")

    declared = element("simplelicensing_LicenseExpression", ref("DeclaredLicense"),
                       simplelicensing_licenseExpression=pkg.license)
    relationship("hasDeclaredLicense", ref("Relationship/hasDeclaredLicense"), package,
                 [declared])

    sources = []
    for i, s in enumerate(recipe.sources):
        props = {"name": s.filename, "software_downloadLocation": s.url,
                 "software_primaryPurpose": "source", "verifiedUsing": [_sha256(s.sha256)]}
        if i == 0:
            # The main source tree is the upstream release the recipe packages.
            props.update(software_packageVersion=recipe.version, software_homePage=recipe.homepage)
        if s.signature:
            props["externalRef"] = [{
                "type": "ExternalRef", "externalRefType": "securityOther", "locator": [s.signature],
                "comment": (f"{SIGNATURES[s.signature_type]}; kel verifies it before every build "
                            f"and accepts only the pinned signing key fingerprint(s) "
                            f"{', '.join(s.signing_keys)}"),
            }]
        source = element("software_Package", ref(f"Source/{s.filename}"), **props)
        relationship("generates", ref(f"Relationship/generates/{s.filename}"), source, [package])
        sources.append(source)
    if sources and patches:
        patch_ids = [element("software_File", ref(f"Patch/{name}"),
                             name=f"recipes/{recipe.name}/patches/{name}",
                             software_primaryPurpose="patch", verifiedUsing=[_sha256(sha)])
                     for name, sha in patches]
        relationship("patchedBy", ref("Relationship/patchedBy"), sources[0], patch_ids,
                     completeness="complete")

    described = sorted(e["spdxId"] for e in elements
                       if e["spdxId"] not in (organization, tool, data_license))
    sbom = element("software_Sbom", ref("Sbom"), rootElement=[package], element=described,
                   software_sbomType=["build"])
    everything = sorted(e["spdxId"] for e in elements)
    element("SpdxDocument", ref("SpdxDocument"), name=f"{pkg.name}-{pkg.version} ({pkg.arch})",
            rootElement=[sbom], element=everything, dataLicense=data_license,
            profileConformance=list(PROFILES))
    creation = {"type": "CreationInfo", "@id": CREATION_INFO, "specVersion": SPEC_VERSION,
                "created": created, "createdBy": [organization], "createdUsing": [tool]}
    return {"@context": CONTEXT,
            "@graph": [creation] + sorted(elements, key=lambda e: e["spdxId"])}


def serialize(doc: dict) -> bytes:
    """The canonical serialization (SPDX 3.0.1 chapter 6): sorted keys, no whitespace."""
    text = json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    try:
        return text.encode("utf-8")
    except UnicodeEncodeError:
        raise KelError("SPDX JSON must be UTF-8: the package has file names that are not UTF-8")


def read_built_package(apk: Path, manifest: Path, repodir: Path) -> BuiltPackage:
    """What kel recorded for a built package (manifest), checked against the .apk file."""
    data = json.loads(manifest.read_text())
    name, version = data["name"], data["version"]
    package = repodir / f"{name}-{version}.apk"
    if not package.is_file():
        raise KelError(f"{package} is missing (listed by {manifest})")
    meta = package_metadata(apk, package)
    info = meta["info"]
    if (info.get("name"), info.get("version")) != (name, version):
        raise KelError(f"{package.name} is {info.get('name')}-{info.get('version')}, "
                       f"not {name}-{version}")
    build_time = info.get("build-time")
    if not isinstance(build_time, int):
        raise KelError(f"{package.name} has no build-time")
    entries = package_entries(meta)
    shipped = {path for path, e in entries.items() if e.type != "dir"}
    listed = set(data["files"])
    if shipped != listed:
        extra = sorted(shipped - listed)[:5] + sorted(listed - shipped)[:5]
        raise KelError(f"{manifest} does not match {package.name} (e.g. {', '.join(extra)})")
    files = []
    for path in sorted(listed):
        e = entries[path]
        files.append(PackageFile(
            path,
            sha256=e.digest if e.type in ("file", "hardlink") and len(e.digest) == 64 else "",
            link_target=e.target if e.type == "symlink" else ""))
    return BuiltPackage(name=name, version=version, arch=info.get("arch", ""),
                        summary=info.get("description", ""), license=info.get("license", ""),
                        filename=package.name, sha256=sha256_file(package),
                        build_time=build_time, files=tuple(files))


def write_sboms(layout: Layout, arch: Arch, recipe: Recipe, apk: Path, outdir: Path) -> list[Path]:
    """Write <outdir>/<package>-<pkgver>.spdx.json for the recipe's package and subpackages."""
    if recipe.build is None:
        raise KelError(f"{recipe.name} has no [build] section, so no packages")
    repodir = layout.repository(arch)
    manifests = repodir.parent / "manifests"
    patches = recipe_patches(recipe)
    written = []
    for name in [recipe.name] + [f"{recipe.name}-{s.suffix}" for s in recipe.subpackages]:
        manifest = manifests / f"{name}.json"
        if not manifest.is_file():
            raise KelError(f"{name} has not been built for {arch.name} (no {manifest})")
        pkg = read_built_package(apk, manifest, repodir)
        if pkg.version != recipe.pkgver:
            raise KelError(f"{pkg.filename} is {pkg.version} but the recipe is {recipe.pkgver}; "
                           f"rebuild it first")
        if pkg.license != recipe.license or pkg.arch != arch.name:
            raise KelError(f"{pkg.filename} (license {pkg.license!r}, arch {pkg.arch}) does not "
                           f"match the recipe (license {recipe.license!r}, arch {arch.name})")
        outdir.mkdir(parents=True, exist_ok=True)
        out = outdir / f"{name}-{pkg.version}.spdx.json"
        out.write_bytes(serialize(build_sbom(recipe, pkg, patches)))
        written.append(out)
    return written
