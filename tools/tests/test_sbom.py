import contextlib
import hashlib
import io
import json
import os
import re
import shutil
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from jsonschema_subset import SchemaValidator
from kel import __version__, cli
from kel.config import REPO_ROOT, Layout, get_arch
from kel.pkg import PackagePart, ensure_dev_key, make_apk, write_manifests
from kel.recipe import BuildSpec, Recipe, Source, Subpackage, load_recipe
from kel.sbom import (CONTEXT, BuiltPackage, PackageFile, build_sbom, package_url, recipe_patches,
                      serialize, write_sboms)
from kel.util import KelError

FPR = "A" * 40
EPOCH = 1767225600

# SPDX 3.0.1 RelationshipType entries
# (https://spdx.github.io/spdx-spec/v3.0.1/model/Core/Vocabularies/RelationshipType/).
RELATIONSHIP_TYPES = {
    "affects", "amendedBy", "ancestorOf", "availableFrom", "configures", "contains",
    "coordinatedBy", "copiedTo", "delegatedTo", "dependsOn", "descendantOf", "describes",
    "doesNotAffect", "expandsTo", "exploitCreatedBy", "fixedBy", "fixedIn", "foundBy",
    "generates", "hasAddedFile", "hasAssessmentFor", "hasAssociatedVulnerability",
    "hasConcludedLicense", "hasDataFile", "hasDeclaredLicense", "hasDeletedFile",
    "hasDependencyManifest", "hasDistributionArtifact", "hasDocumentation", "hasDynamicLink",
    "hasEvidence", "hasExample", "hasHost", "hasInput", "hasMetadata", "hasOptionalComponent",
    "hasOptionalDependency", "hasOutput", "hasPrerequisite", "hasProvidedDependency",
    "hasRequirement", "hasSpecification", "hasStaticLink", "hasTest", "hasTestCase", "hasVariant",
    "invokedBy", "modifiedBy", "other", "packagedBy", "patchedBy", "publishedBy", "reportedBy",
    "republishedBy", "serializedInArtifact", "testedOn", "trainedOn", "underInvestigationFor",
    "usesTool",
}
# Properties whose values are references to other elements.
REFERENCES = ("rootElement", "element", "from", "to", "dataLicense", "suppliedBy", "originatedBy")
DATETIME = re.compile(r"^\d\d\d\d-\d\d-\d\dT\d\d:\d\d:\d\dZ$")


def check_spdx(doc: dict) -> list[str]:
    """Structure an SPDX 3.0.1 JSON-LD document must have (independent of kel.sbom)."""
    problems = []
    if doc.get("@context") != CONTEXT:
        problems.append("@context is not the SPDX 3.0.1 context")
    graph = doc.get("@graph", [])
    creation = {n["@id"]: n for n in graph if n.get("type") == "CreationInfo"}
    elements = [n for n in graph if n.get("type") != "CreationInfo"]
    ids = [e.get("spdxId") for e in elements]
    if len(set(ids)) != len(ids):
        problems.append("duplicate spdxId")
    known = set(ids)
    for cid, ci in creation.items():
        if not cid.startswith("_:"):
            problems.append(f"{cid}: CreationInfo should be a blank node")
        if ci.get("specVersion") != "3.0.1" or not DATETIME.match(ci.get("created", "")):
            problems.append(f"{cid}: bad specVersion or created")
        if not ci.get("createdBy"):
            problems.append(f"{cid}: createdBy is required")
        for ref in ci.get("createdBy", []) + ci.get("createdUsing", []):
            if ref not in known:
                problems.append(f"{cid}: unresolved reference {ref}")
    documents = [e for e in elements if e["type"] == "SpdxDocument"]
    if len(documents) != 1:
        problems.append(f"{len(documents)} SpdxDocument elements")
    for e in elements:
        sid = e.get("spdxId", "")
        if not re.match(r"^(?!_:).+:.+", sid):
            problems.append(f"{sid!r}: spdxId must be an IRI")
        if e.get("creationInfo") not in creation:
            problems.append(f"{sid}: creationInfo does not resolve")
        for key in REFERENCES:
            refs = e.get(key, [])
            for ref in [refs] if isinstance(refs, str) else refs:
                if ref not in known:
                    problems.append(f"{sid}: {key} {ref} does not resolve")
        if e["type"] in ("software_Package", "software_File") and not e.get("name"):
            problems.append(f"{sid}: name is required")
        if e["type"] == "Relationship":
            if e.get("relationshipType") not in RELATIONSHIP_TYPES:
                problems.append(f"{sid}: unknown relationshipType {e.get('relationshipType')}")
            if not isinstance(e.get("from"), str) or not e.get("to"):
                problems.append(f"{sid}: from and to are required")
        if e["type"] in ("SpdxDocument", "software_Sbom"):
            if e.get("element") and not e.get("rootElement"):
                problems.append(f"{sid}: a collection with elements needs a rootElement")
            if any(r in {d["spdxId"] for d in documents}
                   for r in e.get("element", []) + e.get("rootElement", [])):
                problems.append(f"{sid}: element/rootElement must not be the SpdxDocument")
        for h in e.get("verifiedUsing", []):
            if h.get("type") != "Hash" or h.get("algorithm") != "sha256" or \
                    not re.fullmatch(r"[0-9a-f]{64}", h.get("hashValue", "")):
                problems.append(f"{sid}: bad hash {h}")
    if documents:
        listed = set(documents[0].get("element", []))
        if listed != known - {documents[0]["spdxId"]}:
            problems.append("the SpdxDocument does not list every element")
    return problems


def by_id(doc: dict) -> dict[str, dict]:
    return {n.get("spdxId", n.get("@id")): n for n in doc["@graph"]}


def relationships(doc: dict, kind: str) -> list[dict]:
    return [n for n in doc["@graph"] if n.get("type") == "Relationship"
            and n["relationshipType"] == kind]


class SbomTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        rdir = Path(self.tmp.name) / "recipes" / "demo"
        (rdir / "patches").mkdir(parents=True)
        (rdir / "patches" / "0002-later.patch").write_text("--- b\n+++ b\n")
        (rdir / "patches" / "0001-first.patch").write_text("--- a\n+++ a\n")
        self.patch_sha = hashlib.sha256(b"--- a\n+++ a\n").hexdigest()
        self.recipe = Recipe(
            name="demo", version="1.2.3", revision=1, summary="Demo", license="MIT OR Apache-2.0",
            homepage="https://example.org/demo", path=rdir / "recipe.toml",
            build=BuildSpec(style="make"), sources=(
                Source("https://example.org/demo-1.2.3.tar.xz", "a" * 64, "demo-1.2.3.tar.xz",
                       signature="https://example.org/demo-1.2.3.tar.xz.sig",
                       signing_keys=(FPR,)),
                Source("https://example.org/extra-2.0.tar.gz", "b" * 64, "extra-2.0.tar.gz",
                       dest="extra")))
        self.pkg = BuiltPackage(
            name="demo", version="1.2.3-r1", arch="x86_64", summary="Demo",
            license="MIT OR Apache-2.0", filename="demo-1.2.3-r1.apk", sha256="c" * 64,
            build_time=EPOCH, files=(
                PackageFile("/usr/bin/demo", "d" * 64),
                PackageFile("/usr/lib/libdemo.so", link_target="libdemo.so.1"),
                PackageFile("/usr/lib/libdemo.so.1", "e" * 64),
                PackageFile("/usr/share/doc/demo/read me+.txt", "f" * 64)))

    def tearDown(self):
        self.tmp.cleanup()

    def sbom(self, **changes) -> dict:
        return build_sbom(self.recipe, replace(self.pkg, **changes), recipe_patches(self.recipe))

    def test_structure(self):
        self.assertEqual(check_spdx(self.sbom()), [])

    def test_package_and_files(self):
        doc = self.sbom()
        nodes = by_id(doc)
        sbom = next(n for n in doc["@graph"] if n["type"] == "software_Sbom")
        self.assertEqual(sbom["software_sbomType"], ["build"])
        package = nodes[sbom["rootElement"][0]]
        self.assertEqual((package["type"], package["name"], package["software_packageVersion"]),
                         ("software_Package", "demo", "1.2.3-r1"))
        self.assertEqual(package["software_packageUrl"], "pkg:apk/kel/demo@1.2.3-r1?arch=x86_64")
        self.assertEqual(package["software_homePage"], "https://example.org/demo")
        self.assertEqual(package["verifiedUsing"][0]["hashValue"], "c" * 64)
        self.assertEqual(package["builtTime"], "2026-01-01T00:00:00Z")
        self.assertEqual(nodes[package["suppliedBy"]]["type"], "Organization")
        (dist,) = relationships(doc, "hasDistributionArtifact")
        self.assertEqual(dist["from"], package["spdxId"])
        self.assertEqual(nodes[dist["to"][0]]["name"], "demo-1.2.3-r1.apk")
        (contains,) = relationships(doc, "contains")
        files = {nodes[t]["name"]: nodes[t] for t in contains["to"]}
        self.assertEqual(sorted(files), [f.path for f in self.pkg.files])
        self.assertEqual(files["/usr/bin/demo"]["verifiedUsing"][0]["hashValue"], "d" * 64)
        link = files["/usr/lib/libdemo.so"]
        self.assertNotIn("verifiedUsing", link)
        self.assertEqual(link["comment"], "symbolic link to libdemo.so.1")
        (declared,) = relationships(doc, "hasDeclaredLicense")
        self.assertEqual(declared["from"], package["spdxId"])
        license_ = nodes[declared["to"][0]]
        self.assertEqual((license_["type"], license_["simplelicensing_licenseExpression"]),
                         ("simplelicensing_LicenseExpression", "MIT OR Apache-2.0"))
        document = next(n for n in doc["@graph"] if n["type"] == "SpdxDocument")
        self.assertEqual(nodes[document["dataLicense"]]["simplelicensing_licenseExpression"],
                         "CC0-1.0")
        self.assertEqual(document["rootElement"], [sbom["spdxId"]])

    def test_sources_and_patches(self):
        doc = self.sbom()
        nodes = by_id(doc)
        package = nodes[next(n for n in doc["@graph"]
                             if n["type"] == "software_Sbom")["rootElement"][0]]
        generates = relationships(doc, "generates")
        self.assertEqual(len(generates), 2)
        sources = [nodes[r["from"]] for r in generates]
        self.assertTrue(all(r["to"] == [package["spdxId"]] for r in generates))
        main = next(s for s in sources if s["name"] == "demo-1.2.3.tar.xz")
        self.assertEqual(main["software_downloadLocation"], "https://example.org/demo-1.2.3.tar.xz")
        self.assertEqual(main["software_packageVersion"], "1.2.3")
        self.assertEqual(main["software_primaryPurpose"], "source")
        self.assertEqual(main["verifiedUsing"][0]["hashValue"], "a" * 64)
        (sig,) = main["externalRef"]
        self.assertEqual(sig["locator"], ["https://example.org/demo-1.2.3.tar.xz.sig"])
        self.assertIn(FPR, sig["comment"])
        extra = next(s for s in sources if s["name"] == "extra-2.0.tar.gz")
        self.assertNotIn("externalRef", extra)
        self.assertNotIn("software_packageVersion", extra)
        (patched,) = relationships(doc, "patchedBy")
        self.assertEqual(patched["from"], main["spdxId"])
        patches = [nodes[t] for t in patched["to"]]
        self.assertEqual([p["name"] for p in patches], ["recipes/demo/patches/0001-first.patch",
                                                        "recipes/demo/patches/0002-later.patch"])
        self.assertEqual(patches[0]["verifiedUsing"][0]["hashValue"], self.patch_sha)

    def test_creation_info(self):
        doc = self.sbom()
        (ci,) = [n for n in doc["@graph"] if n["type"] == "CreationInfo"]
        nodes = by_id(doc)
        self.assertEqual(ci["created"], "2026-01-01T00:00:00Z")
        self.assertEqual(nodes[ci["createdUsing"][0]]["name"], f"kel {__version__}")
        self.assertEqual(nodes[ci["createdBy"][0]]["type"], "Organization")

    def test_reproducible(self):
        first = serialize(self.sbom())
        self.assertEqual(first, serialize(self.sbom()))
        # Canonical serialization (spec chapter 6): sorted keys, no whitespace.
        canonical = json.dumps(json.loads(first), sort_keys=True, separators=(",", ":"),
                               ensure_ascii=False).encode()
        self.assertEqual(first, canonical)
        self.assertNotIn(b"\n", first)
        # IDs depend on names, versions and paths only, not on hashes.
        ids = sorted(by_id(self.sbom()))
        self.assertEqual(ids, sorted(by_id(self.sbom(sha256="9" * 64))))
        later = serialize(self.sbom(build_time=EPOCH + 86400))
        self.assertIn(b'"created":"2026-01-02T00:00:00Z"', later)
        self.assertNotIn(b"2026-01-01", later)

    def test_ids_name_the_package(self):
        ids = by_id(self.sbom(version="1.2.3-r2", arch="aarch64"))
        self.assertTrue(any(i.endswith("/aarch64/demo-1.2.3-r2#Package") for i in ids))
        self.assertTrue(any("#File/usr/share/doc/demo/read%20me%2B.txt" in i for i in ids))

    def test_package_url_escapes(self):
        self.assertEqual(package_url("libstdc++", "16.2.0-r0", "x86_64"),
                         "pkg:apk/kel/libstdc%2B%2B@16.2.0-r0?arch=x86_64")

    def test_package_without_sources(self):
        recipe = Recipe(name="base", version="0.1", revision=0, summary="Base", license="MIT",
                        homepage="https://example.org/", sources=())
        pkg = BuiltPackage(name="base", version="0.1-r0", arch="x86_64", summary="Base",
                           license="MIT", filename="base-0.1-r0.apk", sha256="c" * 64,
                           build_time=EPOCH, files=(PackageFile("/etc/issue", "d" * 64),))
        doc = build_sbom(recipe, pkg, recipe_patches(recipe))
        self.assertEqual(check_spdx(doc), [])
        self.assertEqual(relationships(doc, "generates"), [])
        self.assertEqual(relationships(doc, "patchedBy"), [])

    @unittest.skipUnless(os.environ.get("KEL_SPDX_SCHEMA"),
                         "set KEL_SPDX_SCHEMA to a copy of "
                         "https://spdx.org/schema/3.0.1/spdx-json-schema.json")
    def test_official_json_schema(self):
        schema = json.loads(Path(os.environ["KEL_SPDX_SCHEMA"]).read_text())
        validator = SchemaValidator(schema)
        doc = self.sbom()
        self.assertEqual(validator.errors(doc), [])
        bad = json.loads(json.dumps(doc))
        next(n for n in bad["@graph"] if n["type"] == "Relationship")["relationshipType"] = \
            "generatedFrom"
        self.assertTrue(validator.errors(bad))


def find_apk() -> Path | None:
    path = Layout.from_env().host_tools(get_arch("x86_64")) / "bin" / "apk"
    if path.exists():
        return path
    found = shutil.which("apk")
    return Path(found) if found else None


APK = find_apk()


@unittest.skipUnless(APK and shutil.which("bwrap") and shutil.which("openssl"),
                     "needs apk, bwrap and openssl")
class BuiltPackageSbomTests(unittest.TestCase):
    """SBOMs of packages made with the host apk."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="kelsbom"))
        self.layout = Layout(repo=REPO_ROOT, workdir=self.tmp / "work", cachedir=self.tmp / "cache")
        self.arch = get_arch("x86_64")
        self.key, _ = ensure_dev_key(self.layout.keys())

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def build(self, recipe: Recipe, parts: list[PackagePart]) -> None:
        repo = self.layout.repository(self.arch)
        for part in parts:
            make_apk(APK, part, recipe, self.arch.name, repo, self.key, str(EPOCH))
        write_manifests(parts, repo.parent / "manifests", recipe.pkgver)

    def tree(self, name: str, files: dict[str, str]) -> Path:
        root = self.tmp / "roots" / name
        for rel, text in files.items():
            (root / rel).parent.mkdir(parents=True, exist_ok=True)
            (root / rel).write_text(text)
        return root

    def test_package_and_subpackage(self):
        recipe = Recipe(name="demo", version="1.0", revision=0, summary="Demo", license="MIT",
                        homepage="https://example.org/", build=BuildSpec(style="make"),
                        subpackages=(Subpackage("dev", "Demo headers", ("usr/include",)),),
                        sources=(Source("https://example.org/demo-1.0.tar.gz", "a" * 64,
                                        "demo-1.0.tar.gz"),))
        main = self.tree("main", {"usr/lib/libdemo.so.1": "library\n"})
        (main / "usr/lib/libdemo.so").symlink_to("libdemo.so.1")
        dev = self.tree("dev", {"usr/include/demo.h": "int demo(void);\n"})
        self.build(recipe, [PackagePart("demo", "Demo", main),
                            PackagePart("demo-dev", "Demo headers", dev)])
        outdir = self.tmp / "sbom"
        written = write_sboms(self.layout, self.arch, recipe, APK, outdir)
        self.assertEqual([p.name for p in written],
                         ["demo-1.0-r0.spdx.json", "demo-dev-1.0-r0.spdx.json"])
        doc = json.loads(written[0].read_text())
        self.assertEqual(check_spdx(doc), [])
        nodes = by_id(doc)
        files = {nodes[t]["name"]: nodes[t] for t in relationships(doc, "contains")[0]["to"]}
        self.assertEqual(sorted(files), ["/usr/lib/libdemo.so", "/usr/lib/libdemo.so.1"])
        self.assertEqual(files["/usr/lib/libdemo.so.1"]["verifiedUsing"][0]["hashValue"],
                         hashlib.sha256(b"library\n").hexdigest())
        apk_file = self.layout.repository(self.arch) / "demo-1.0-r0.apk"
        package = nodes[relationships(doc, "hasDistributionArtifact")[0]["from"]]
        self.assertEqual(package["verifiedUsing"][0]["hashValue"],
                         hashlib.sha256(apk_file.read_bytes()).hexdigest())
        self.assertEqual(package["builtTime"], "2026-01-01T00:00:00Z")
        dev_doc = json.loads(written[1].read_text())
        dev_package = by_id(dev_doc)[relationships(dev_doc, "hasDeclaredLicense")[0]["from"]]
        self.assertEqual((dev_package["name"], dev_package["description"]),
                         ("demo-dev", "Demo headers"))
        # The same package always gives the same bytes.
        again = write_sboms(self.layout, self.arch, recipe, APK, self.tmp / "again")
        self.assertEqual(written[0].read_bytes(), again[0].read_bytes())

    def test_inconsistent_inputs(self):
        recipe = Recipe(name="demo", version="1.0", revision=0, summary="Demo", license="MIT",
                        homepage="https://example.org/", build=BuildSpec(style="make"), sources=())
        self.build(recipe, [PackagePart("demo", "Demo", self.tree("main", {"etc/demo": "x\n"}))])
        with self.assertRaisesRegex(KelError, "rebuild"):
            write_sboms(self.layout, self.arch, replace(recipe, revision=1), APK, self.tmp / "sbom")
        manifest = self.layout.repository(self.arch).parent / "manifests" / "demo.json"
        data = json.loads(manifest.read_text())
        data["files"].append("/etc/other")
        manifest.write_text(json.dumps(data))
        with self.assertRaisesRegex(KelError, "does not match"):
            write_sboms(self.layout, self.arch, recipe, APK, self.tmp / "sbom")
        with self.assertRaisesRegex(KelError, "has not been built"):
            write_sboms(self.layout, self.arch, replace(recipe, name="other"), APK,
                        self.tmp / "sbom")

    def test_cli_with_repository_recipe(self):
        recipe = load_recipe(self.layout.recipes, self.layout.upstream_keys, "zlib")
        root = self.tree("zlib", {"usr/include/zlib.h": "/* zlib */\n"})
        self.build(recipe, [PackagePart(recipe.name, recipe.summary, root)])
        tools = self.layout.host_tools(self.arch) / "bin"
        tools.mkdir(parents=True)
        (tools / "apk").symlink_to(APK)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = cli.main(["--workdir", str(self.layout.workdir), "sbom", "zlib"])
        self.assertEqual(rc, 0)
        path = Path(out.getvalue().strip())
        self.assertEqual(path, self.layout.repository(self.arch).parent / "sbom"
                         / f"zlib-{recipe.pkgver}.spdx.json")
        doc = json.loads(path.read_text())
        self.assertEqual(check_spdx(doc), [])
        (generates,) = relationships(doc, "generates")
        self.assertEqual(by_id(doc)[generates["from"]]["software_downloadLocation"],
                         recipe.sources[0].url)
        # Without names: every recipe that has built packages.
        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(cli.main(["--workdir", str(self.layout.workdir), "sbom",
                                       "--output", str(self.tmp / "all")]), 0)
        self.assertEqual(out.getvalue().split(), [str(self.tmp / "all" / path.name)])


if __name__ == "__main__":
    unittest.main()
