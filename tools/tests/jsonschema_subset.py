"""Validate JSON against the official SPDX 3.0.1 JSON schema without third-party modules.

A small JSON Schema (draft 2020-12) validator for exactly the keywords that
https://spdx.org/schema/3.0.1/spdx-json-schema.json uses: $ref (local),
allOf, anyOf, not, if/then/else, type, const, enum, pattern, minimum, items,
minItems, properties, required and unevaluatedProperties (with the 2020-12
annotation rules: properties evaluated by valid in-place subschemas count).
Test helper only; kel itself does not validate (D-011: standard library).
"""

from __future__ import annotations

import re

_TYPES = {
    "object": lambda v: isinstance(v, dict),
    "array": lambda v: isinstance(v, list),
    "string": lambda v: isinstance(v, str),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "boolean": lambda v: isinstance(v, bool),
    "null": lambda v: v is None,
}


def _equal(a, b) -> bool:
    if isinstance(a, bool) or isinstance(b, bool):
        return isinstance(a, bool) and isinstance(b, bool) and a == b
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(_equal(a[k], b[k]) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(_equal(x, y) for x, y in zip(a, b))
    return type(a) is type(b) and a == b or (
        _TYPES["number"](a) and _TYPES["number"](b) and a == b)


class SchemaValidator:
    def __init__(self, schema: dict):
        self.root = schema
        self._regex: dict[str, re.Pattern] = {}

    def errors(self, instance) -> list[str]:
        ok, _, err = self._check(instance, self.root, "$")
        return [] if ok else [err]

    def _resolve(self, ref: str):
        if not ref.startswith("#/"):
            raise ValueError(f"only local $ref is supported: {ref}")
        node = self.root
        for part in ref[2:].split("/"):
            node = node[part.replace("~1", "/").replace("~0", "~")]
        return node

    def _check(self, inst, schema, path: str) -> tuple[bool, set, str]:
        """(valid, names of the properties evaluated, first error)."""
        if schema is True:
            return True, set(), ""
        if schema is False:
            return False, set(), f"{path}: not allowed"
        evaluated: set = set()

        def sub(s, p=path):
            return self._check(inst, s, p)

        if "$ref" in schema:
            ok, ev, err = sub(self._resolve(schema["$ref"]))
            if not ok:
                return False, set(), err
            evaluated |= ev
        for s in schema.get("allOf", ()):
            ok, ev, err = sub(s)
            if not ok:
                return False, set(), err
            evaluated |= ev
        if "anyOf" in schema:
            results = [sub(s) for s in schema["anyOf"]]
            valid = [r for r in results if r[0]]
            if not valid:
                # The error with the deepest path is usually from the branch
                # that matched the element's type (the others fail with
                # "is not 'Not a <class>'").
                return False, set(), max((r[2] for r in results),
                                         key=lambda e: (len(e.split(": ", 1)[0]), "'Not a " not in e))
            for r in valid:
                evaluated |= r[1]
        if "not" in schema and sub(schema["not"])[0]:
            return False, set(), f"{path}: must not match {schema['not']}"
        if "if" in schema:
            ok, ev, _ = sub(schema["if"])
            branch = schema.get("then") if ok else schema.get("else")
            if ok:
                evaluated |= ev
            if branch is not None:
                ok, ev, err = sub(branch)
                if not ok:
                    return False, set(), err
                evaluated |= ev
        if "type" in schema:
            types = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
            if not any(_TYPES[t](inst) for t in types):
                return False, set(), f"{path}: {inst!r:.80} is not of type {schema['type']}"
        if "const" in schema and not _equal(inst, schema["const"]):
            return False, set(), f"{path}: {inst!r:.80} is not {schema['const']!r}"
        if "enum" in schema and not any(_equal(inst, e) for e in schema["enum"]):
            return False, set(), f"{path}: {inst!r:.80} is not one of {schema['enum']}"
        if isinstance(inst, str) and "pattern" in schema:
            regex = self._regex.setdefault(schema["pattern"], re.compile(schema["pattern"]))
            if not regex.search(inst):
                return False, set(), f"{path}: {inst!r} does not match {schema['pattern']}"
        if _TYPES["number"](inst) and "minimum" in schema and inst < schema["minimum"]:
            return False, set(), f"{path}: {inst} is less than {schema['minimum']}"
        if isinstance(inst, list):
            if len(inst) < schema.get("minItems", 0):
                return False, set(), f"{path}: fewer than {schema['minItems']} items"
            if "items" in schema:
                for i, item in enumerate(inst):
                    ok, _, err = self._check(item, schema["items"], f"{path}[{i}]")
                    if not ok:
                        return False, set(), err
        if isinstance(inst, dict):
            missing = [k for k in schema.get("required", ()) if k not in inst]
            if missing:
                return False, set(), f"{path}: missing {missing}"
            for key, s in schema.get("properties", {}).items():
                if key in inst:
                    ok, _, err = self._check(inst[key], s, f"{path}.{key}")
                    if not ok:
                        return False, set(), err
                    evaluated.add(key)
            if "unevaluatedProperties" in schema:
                extra = sorted(set(inst) - evaluated)
                rule = schema["unevaluatedProperties"]
                for key in extra:
                    ok, _, err = self._check(inst[key], rule, f"{path}.{key}")
                    if not ok:
                        return False, set(), (f"{path}: unexpected property {key!r}"
                                              if rule is False else err)
                evaluated |= set(inst)
        return True, evaluated, ""
