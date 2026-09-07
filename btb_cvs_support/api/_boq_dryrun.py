"""Dry-runs the seeded rules without migrating or writing anything.

Phase 4 needs the rules in the database, and the database is migrated by the
user, not from here. This harness closes that gap: it builds the rule set from
the patch's own definitions - not a copy of them - feeds it straight to the
expander, and resolves identifiers against the column the patch will populate
(`boq_identifier` = `product_name` for the seeded rows).

That exercises everything except the doctype schema sync itself, so the parity
verdict is real rather than deferred.

Read-only. Nothing here writes to the database.
"""

import json
from typing import Dict, List

import frappe

from . import boq_rules
from ..patches.seed_ad_boq_rules import IDENTIFIERS, ad_rules


def as_loaded(specs: List[Dict], family: str) -> List[Dict]:
    """Convert patch specs into the shape load_rules() returns from the doctype."""
    rules = []
    for i, spec in enumerate(sorted(specs, key=lambda s: s["sequence"])):
        rules.append({
            "name": f"DRYRUN-{family}-{spec['sequence']:05d}",
            "sourceType": spec["source_type"],
            "identifierTemplate": spec.get("identifier_template"),
            "identifierLiteral": spec.get("identifier_literal"),
            "uom": spec.get("uom"),
            "conditionLogic": spec.get("condition_logic") or "and",
            "conditions": [dict(c) for c in spec.get("conditions") or []],
            "dimensions": [
                {"field": d["field"],
                 "format": d.get("value_format") or "As is",
                 "order": d.get("value_order") or ""}
                for d in spec.get("dimensions") or []
            ],
            "aggregate": json.loads(spec["aggregate"]),
        })
    return rules


def resolve_by_product_name(identifiers: List[str]) -> Dict[str, Dict]:
    """Stands in for cost_rows_by_identifier while boq_identifier is unset.

    Only the rows the patch will actually key are eligible, so this cannot
    resolve something the real lookup would not.
    """
    wanted = [i for i in set(identifiers) if i in IDENTIFIERS]
    if(not wanted): return {}
    rows = frappe.get_all("FTOCountryWiseCost",
                          filters={"product_name": ("in", wanted)},
                          fields=["product_name", "item_code", "product_name as pn",
                                  "unit"])
    out = {}
    for r in rows:
        out[r.product_name] = frappe._dict(
            {"item_code": r.item_code, "product_name": r.pn, "unit": r.unit})
    return out


def install(family: str = "AD"):
    """Point the engine at the in-memory rule set for one family."""
    loaded = as_loaded(ad_rules(), family)
    boq_rules.families_with_rules = lambda: {family}
    boq_rules.load_rules = lambda pf: loaded if pf == family else []
    boq_rules.cost_rows_by_identifier = resolve_by_product_name

    # boq.py imported these by name, so its module globals need rebinding too
    from . import boq
    boq.families_with_rules = boq_rules.families_with_rules
    boq.load_rules = boq_rules.load_rules
    return loaded


def main(family: str, out_path: str):
    loaded = install(family)
    from ._boq_parity import write_capture
    data = write_capture(family, out_path)
    print(f"dry run: {len(loaded)} rules -> {data['cartItemCount']} cart items, "
          f"{data['lineCount']} lines -> {out_path}")
    return data
