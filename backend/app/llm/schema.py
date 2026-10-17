"""Convert Pydantic models into JSON Schemas OpenAI's strict mode accepts.

Strict structured outputs guarantee the response matches the schema, but only
for a subset of JSON Schema, and with two rules of their own: every object must
list *all* of its properties as ``required``, and every object must set
``additionalProperties: false``. Pydantic emits keywords outside that subset
and, for nested models, ``$ref`` pointers into a ``$defs`` block. So:

* **References are inlined.** A self-contained schema removes any question of
  how the API follows pointers.
* **Unsupported keywords are dropped**, then re-applied client-side by
  validating the response with the same Pydantic model. The model stays the
  single definition of the contract.
* **Every object is closed and fully required.** An optional field stays
  optional by being nullable (``X | None``), which strict mode does express.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from pydantic import BaseModel

#: Keywords strict mode does not accept. Constraints such as ranges and lengths
#: are still enforced — client side, when the response is validated.
_UNSUPPORTED_KEYS = frozenset(
    {
        "default",
        "examples",
        "title",
        "$comment",
        "$schema",
        "$id",
        "minimum",
        "maximum",
        "exclusiveMinimum",
        "exclusiveMaximum",
        "multipleOf",
        "minLength",
        "maxLength",
        "pattern",
        "format",
        "minItems",
        "maxItems",
        "uniqueItems",
        "minProperties",
        "maxProperties",
        "patternProperties",
        "readOnly",
        "writeOnly",
        "deprecated",
        "discriminator",
        # Re-added below for every object, with the value strict mode requires.
        "additionalProperties",
    }
)


class SchemaTooDeepError(ValueError):
    """A model nests deeper than the API is willing to accept."""


def _resolve(ref: str, defs: dict[str, Any]) -> dict[str, Any]:
    name = ref.rsplit("/", 1)[-1]
    if name not in defs:
        raise ValueError(f"unresolvable schema reference: {ref}")
    return defs[name]


def _inline(node: Any, defs: dict[str, Any], seen: tuple[str, ...] = ()) -> Any:
    """Replace every ``$ref`` with the definition it points at."""
    if isinstance(node, list):
        return [_inline(item, defs, seen) for item in node]
    if not isinstance(node, dict):
        return node

    if "$ref" in node:
        ref = node["$ref"]
        if ref in seen:
            # Inlining a recursive schema never terminates. Say so here rather
            # than recurse until Python gives up.
            raise ValueError(
                f"recursive schema reference {ref}; model a tree as a flat list "
                "with parent-id references instead"
            )
        target = _inline(_resolve(ref, defs), defs, (*seen, ref))
        # Keywords alongside a $ref (usually `description`) override the target's.
        extras = {k: _inline(v, defs, seen) for k, v in node.items() if k != "$ref"}
        return {**target, **extras}

    return {k: _inline(v, defs, seen) for k, v in node.items()}


#: Keys whose value is a mapping of *name* -> schema. The names are user data —
#: a field may legitimately be called "title" or "default" — so they must never
#: be filtered as if they were schema keywords.
_SCHEMA_MAPS = frozenset({"properties", "$defs", "definitions"})

#: Keys whose value is a list of schemas.
_SCHEMA_LISTS = frozenset({"anyOf", "allOf", "oneOf", "prefixItems"})

#: Keys whose value is a single schema.
_SCHEMA_VALUES = frozenset({"items", "not", "contains", "additionalItems"})


def _clean(node: Any, depth: int = 0, max_depth: int = 12) -> Any:
    """Strip unsupported keywords, without confusing keywords for field names.

    The distinction matters: under ``properties`` the keys are the model's own
    field names. Filtering those by keyword name silently deletes any field
    called ``title``, ``default``, ``format`` and so on, while ``required`` goes
    on demanding them — which the API rejects.
    """
    if depth > max_depth:
        raise SchemaTooDeepError(f"schema nests deeper than {max_depth} levels")
    if not isinstance(node, dict):
        return node

    out: dict[str, Any] = {}
    for key, value in node.items():
        if key in _UNSUPPORTED_KEYS:
            continue
        if key in _SCHEMA_MAPS and isinstance(value, dict):
            out[key] = {name: _clean(sub, depth + 1, max_depth) for name, sub in value.items()}
        elif key in _SCHEMA_LISTS and isinstance(value, list):
            out[key] = [_clean(item, depth + 1, max_depth) for item in value]
        elif key in _SCHEMA_VALUES:
            out[key] = _clean(value, depth + 1, max_depth)
        else:
            out[key] = value

    # Strict mode: every object closed, every property required.
    if "properties" in out:
        out.setdefault("type", "object")
        out["required"] = list(out["properties"].keys())
        out["additionalProperties"] = False

    return out


def to_output_schema(model: type[BaseModel]) -> dict[str, Any]:
    """Return a strict-mode JSON Schema for ``model``."""
    schema = deepcopy(model.model_json_schema(ref_template="#/$defs/{model}"))
    defs = schema.pop("$defs", {})
    return _clean(_inline(schema, defs))


def to_response_format(model: type[BaseModel]) -> dict[str, Any]:
    """Return the ``response_format`` value that constrains output to ``model``."""
    return {
        "type": "json_schema",
        "json_schema": {
            "name": model.__name__,
            "strict": True,
            "schema": to_output_schema(model),
        },
    }
