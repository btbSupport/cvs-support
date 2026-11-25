"""Expands `BOQ Rule` records into the row shape the BOQ engine consumes.

The engine in boq.py walks a list of rows shaped
``{itemCode, description, uom, formula{filter, aggregate}}`` and evaluates each
against the cart models of one sub-category. Until now that list came from
boq_format.JSON, where every combination of material, thickness and size was
written out by hand.

A rule replaces a block of those rows with two ideas the JSON has no way to
express:

    conditions  guards - a cart line must satisfy these for the rule to apply
    dimensions  group-by - one row is emitted per distinct combination the
                cart actually contains

Expansion happens per sub-category, because the combinations depend on the cart
models in it, and it emits exactly the row shape described above. `exec_formula`
never learns that rules exist, which is what makes quantities identical by
construction rather than by testing.
"""

import itertools
import json
import re
from typing import Dict, List, Optional

import frappe
from frappe import _

from .btb_constraint import exec_filter

PLACEHOLDER = re.compile(r"\{([^{}]+)\}")


# ------------------------------------------------------------------ loading


def families_with_rules() -> set:
    """Product families that have taken over from boq_format.JSON.

    Returns nothing if the doctype has not been migrated yet. A deploy that
    lands the code before `bench migrate` runs then keeps generating BOQs from
    the JSON, instead of failing every generation on a missing table.
    """
    if(not frappe.db.table_exists("BOQ Rule")): return set()
    # distinct as a keyword: v16 rejects "distinct ..." inside a field name
    rows = frappe.get_all("BOQ Rule", filters={"active": 1},
                          fields=["product_family as pf"], distinct=True)
    return {r.pf for r in rows}


def load_rules(product_family: str) -> List[Dict]:
    """Read the active rules of one family.

    A rule that cannot be read names itself in the error. Without that, a bad
    aggregate surfaces as a bare TypeError from json.loads with nothing to say
    which of thirteen rules produced it - and because provide() builds the BOQ
    before it removes the previous attachment, the generation aborts leaving
    yesterday's PDF in place, looking current. Failing by name is what makes
    that recoverable instead of a hunt.
    """
    names = frappe.get_all("BOQ Rule",
                           filters={"product_family": product_family, "active": 1},
                           order_by="sequence asc, name asc", pluck="name")
    rules = []
    for name in names:
        try:
            doc = frappe.get_doc("BOQ Rule", name)
            rules.append({
                "name": doc.name,
                "sourceType": doc.source_type,
                "identifierTemplate": doc.identifier_template,
                "identifierLiteral": doc.identifier_literal,
                "descriptionTemplate": doc.get("description_template"),
                "filterJson": json.loads(doc.filter_json) if doc.get("filter_json") else None,
                "uom": doc.uom,
                "conditionLogic": doc.condition_logic or "and",
                "conditions": [
                    {"field": c.field, "operator": c.operator, "value": c.value}
                    for c in (doc.conditions or [])
                ],
                "dimensions": [
                    {"field": d.field, "format": d.value_format or "As is",
                     "order": d.value_order or ""}
                    for d in (doc.dimensions or [])
                ],
                "aggregate": json.loads(doc.aggregate),
            })
        except Exception as e:
            frappe.throw(
                _("BOQ Rule {0} ({1}) could not be read: {2}. "
                  "Correct the rule, or untick Active on it to leave it out of the BOQ.").format(
                    frappe.bold(name), product_family, e),
                title=_("BOQ Rule is not usable"))
    return rules


# ------------------------------------------------------------ value handling


def feature_value(model: Dict, field: str) -> Optional[str]:
    entry = model.get(field)
    if(not isinstance(entry, dict)): return None
    value = entry.get("value")
    return None if value is None else str(value)


def slot_fields(dim: Dict) -> List[str]:
    """A dimension can pool several fields - 'halfBaffleSlit|fullBaffleSlit',
    'actModel1|actModel2': one line per value found in any of them, measured
    over every slot that holds it (aggregate nodes tagged with "slot")."""
    return [f.strip() for f in dim["field"].split("|") if f.strip()]


def dim_values(model: Dict, dim: Dict) -> List[str]:
    """Values a model contributes to one dimension; [] if it names none."""
    fields = slot_fields(dim)
    if(len(fields) == 1):
        v = feature_value(model, fields[0])
        return [] if v is None else [v]
    out = []
    for f in fields:
        v = feature_value(model, f)
        if(v not in (None, "") and v not in out): out.append(v)
    return out


def format_value(raw: str, fmt: str) -> str:
    """Render a stored feature value the way the item code spells it.

    The configurator stores door and frame gauges with two decimals - 0.60,
    1.00 - while the item codes drop the redundant zero: GI Door 0.6, GI Door
    1.0. One decimal is always kept, so 1.00 does not collapse to 1.
    """
    if(fmt == "One decimal"):
        # casing gauges are stored as 1 or 1.2 but spelled 1.0 / 1.2
        if(re.match(r"^-?\d+$", raw or "")): return raw + ".0"
        fmt = "Trim trailing zero"
    if(fmt != "Trim trailing zero"): return raw
    if(not re.match(r"^-?\d+\.\d{2,}$", raw or "")): return raw
    trimmed = raw.rstrip("0")
    return trimmed + "0" if trimmed.endswith(".") else trimmed


def order_key(value: str, declared: str):
    """Sort by the declared emit order first, then naturally.

    boq_format.JSON emits materials as GI, AL, AZ, SS304L, SS316L - neither
    alphabetical nor any other derivable order. Declaring it keeps the printed
    line order unchanged instead of trading it for a sign-off.
    """
    listed = [v.strip() for v in (declared or "").split(",") if v.strip()]
    if(value in listed): return (0, listed.index(value), "")
    return (1, 0, value)


# -------------------------------------------------------------- expansion


def guard_filter(rule: Dict) -> Optional[Dict]:
    extra = rule.get("filterJson")
    if(not rule["conditions"]): return extra
    out = {"logic": rule["conditionLogic"], "conditions": rule["conditions"]}
    if(extra): out["filter"] = extra
    return out


def passes_guards(model: Dict, rule: Dict) -> bool:
    """Evaluated with the engine's own exec_filter, not a reimplementation, so
    a guard behaves during expansion exactly as it will during evaluation."""
    f = guard_filter(rule)
    return True if f is None else exec_filter(f, model)


def combinations(rule: Dict, models: List[Dict]) -> List[List[str]]:
    """Distinct dimension-value tuples present on the guarded cart models."""
    dims = rule["dimensions"]
    if(not dims): return [[]]

    seen = {}
    for model in models:
        if(not passes_guards(model, rule)): continue
        per_dim = [dim_values(model, d) for d in dims]
        # a model missing one of the dimensions cannot name a line
        if(any(not v for v in per_dim)): continue
        for raw in itertools.product(*per_dim):
            seen[tuple(raw)] = list(raw)

    combos = list(seen.values())
    combos.sort(key=lambda raw: tuple(
        order_key(format_value(v, d["format"]), d["order"])
        for v, d in zip(raw, dims)))
    return combos


def render_identifier(rule: Dict, combo: List[str]) -> str:
    if(rule["identifierLiteral"]): return rule["identifierLiteral"]
    return render_text(rule["identifierTemplate"] or "", rule, combo)


def render_text(text: str, rule: Dict, combo: List[str]) -> str:
    for value, dim in zip(combo, rule["dimensions"]):
        text = text.replace("{" + dim["field"] + "}", format_value(value, dim["format"]))
    return text


def row_filter(rule: Dict, combo: List[str]) -> Optional[Dict]:
    """Guards plus one eq condition per dimension value - which is precisely
    the filter the hand-written JSON row carried. A pooled dimension adds a
    nested or-filter over its slots (field eq value in any of them)."""
    conditions = list(rule["conditions"])
    pooled = []
    for value, dim in zip(combo, rule["dimensions"]):
        fields = slot_fields(dim)
        if(len(fields) == 1):
            conditions.append({"field": fields[0], "operator": "eq", "value": value})
        else:
            pooled.append({"logic": "or", "conditions": [
                {"field": f, "operator": "eq", "value": value} for f in fields]})
    if(rule.get("filterJson")): pooled.append(json.loads(json.dumps(rule["filterJson"])))
    # exec_filter ands a nested "filter" onto the flat conditions; with no flat
    # condition it would evaluate to False, so the first or-filter stands alone
    if(not conditions):
        if(not pooled): return None
        out = pooled.pop(0)
    else:
        out = {"logic": rule["conditionLogic"], "conditions": conditions}
    node = out
    for f in pooled:
        while("filter" in node): node = node["filter"]
        node["filter"] = f
        node = f
    return out


def slot_aggregate(aggregate: Dict, rule: Dict, combo: List[str]) -> Dict:
    """Aggregate nodes tagged {"slot": field} measure only the slot holding the
    line's value: the tag becomes a filter field eq value (as the JSON wrote it)."""
    value_of = {}
    for value, dim in zip(combo, rule["dimensions"]):
        for f in slot_fields(dim): value_of[f] = value
    if(not any(len(slot_fields(d)) > 1 for d in rule["dimensions"])): return aggregate

    def walk(node):
        if(isinstance(node, list)): return [walk(n) for n in node]
        if(not isinstance(node, dict)): return node
        out = {k: walk(v) for k, v in node.items() if k != "slot"}
        if("slot" in node):
            out["filter"] = {"logic": "and", "conditions": [
                {"field": node["slot"], "operator": "eq", "value": value_of.get(node["slot"], "")}]}
        return out

    return walk(aggregate)


# ------------------------------------------------------------- resolution


def cost_rows_by_identifier(identifiers: List[str]) -> Dict[str, Dict]:
    if(not identifiers): return {}
    rows = frappe.get_all(
        "FTOCountryWiseCost",
        filters={"boq_identifier": ("in", list(set(identifiers)))},
        fields=["boq_identifier", "item_code", "product_name", "unit"])
    return {r.boq_identifier: r for r in rows}


def expand(rules: List[Dict], models: List[Dict]) -> List[Dict]:
    """Rules -> engine rows, in emit order.

    A Sourced line whose identifier matches no cost row is dropped rather than
    printed under a name nobody can buy against; the skip is logged so it
    surfaces in the parity run instead of silently shrinking a BOQ.
    """
    planned = []
    for rule in rules:
        # named the same way load_rules does - a dimension pointing at a field
        # no cart model carries, or a condition with an operator the filter
        # does not know, fails here rather than at load time
        try:
            for combo in combinations(rule, models):
                planned.append((rule, combo, render_identifier(rule, combo)))
        except Exception as e:
            frappe.throw(
                _("BOQ Rule {0} could not be applied: {1}. "
                  "Check its Dimensions and Conditions, or untick Active on it.").format(
                    frappe.bold(rule.get("name") or "?"), e),
                title=_("BOQ Rule is not usable"))

    wanted = [ident for rule, _c, ident in planned if rule["sourceType"] == "Sourced"]
    resolved = cost_rows_by_identifier(wanted)

    rows, skipped = [], []
    for rule, combo, identifier in planned:
        if(rule["sourceType"] == "Sourced"):
            cost = resolved.get(identifier)
            if(not cost):
                skipped.append((rule["name"], identifier))
                continue
            item_code = cost.item_code or identifier
            description = cost.product_name or identifier
            uom = cost.unit or ""
        else:
            item_code = description = identifier
            if(rule.get("descriptionTemplate")):
                description = render_text(rule["descriptionTemplate"], rule, combo)
            uom = rule["uom"] or ""

        rows.append({
            "itemCode": item_code,
            "description": description,
            "uom": uom,
            "formula": {"filter": row_filter(rule, combo),
                        "aggregate": slot_aggregate(rule["aggregate"], rule, combo)},
        })

    if(skipped):
        frappe.logger("boq").warning(
            "BOQ: no FTOCountryWiseCost row carries these BOQ Identifiers, "
            "lines skipped: %s" % ", ".join(f"{r} -> {i!r}" for r, i in skipped))
    return rows
