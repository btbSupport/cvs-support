"""BOQ parity harness - captures BOQ output and diffs two captures.

Used twice by the BOQ Rule Engine migration:

  Phase 0  capture a baseline while the rule book is still boq_format.JSON
  Phase 4  capture again once the family reads `BOQ Rule`, and diff

Quantities carry the whole risk: the rules change only how a line is *named*,
never how it is measured, so any numeric difference is a bug rather than an
intended change. Emit order is captured too - it is the printed line order on
the BOQ, so a reordering is a real regression even when every line survives.

Read-only. Nothing here writes to the database.

Run:
    cd frappe-bench/sites && ../env/bin/python -c "
    import sys; sys.path.insert(0,'/workspace/development/frappe-bench/apps/btb_cvs_support')
    import frappe; frappe.init(site='cvsuae.localhost', sites_path='.'); frappe.connect()
    from btb_cvs_support.api._boq_parity import main; main('capture', 'AD', '/tmp/ad_before.json')
    frappe.destroy()"
"""

import io
import json
import os
from contextlib import redirect_stdout
from typing import Dict, List

import frappe


def cart_items_for_family(product_family: str) -> List[str]:
    """Every cart item configured against one product family (Item.item_code)."""
    rows = frappe.db.sql(
        """
        select ci.name
        from `tabBtbCartItem` ci
        join `tabItem` i on i.name = ci.item
        where i.item_code = %s
        order by ci.name
        """,
        product_family,
        as_dict=1,
    )
    return [r.name for r in rows]


def capture_one(cart_item: str) -> Dict:
    """BOQ output for a single cart item, normalised for diffing.

    The engine prints a running commentary of every aggregate step; it is
    swallowed here so a 151-item run stays readable.
    """
    # imported lazily - the engine pulls in pandas and the whole quotation
    # module, which is not wanted at import time of this harness
    from .boq import populate_cart_detail
    from .btb_quotation import populate_cart_item_model_by_cart_items

    buf = io.StringIO()
    with redirect_stdout(buf):
        models = populate_cart_item_model_by_cart_items([cart_item])
        detail = populate_cart_detail(models) if models else {}

    groups = []
    for key in detail:
        node = detail[key]
        groups.append({
            "productName": node["productName"],
            "subCategory": node["subCategory"],
            "pageBreak": node["pageBreak"],
            "items": [
                {
                    "itemCode": it["itemCode"],
                    "description": it["description"],
                    "uom": it["uom"],
                    "value": it["value"],
                }
                for it in node["items"]
            ],
        })
    return {"cartItem": cart_item, "groups": groups}


def capture(product_family: str) -> Dict:
    cart_items = cart_items_for_family(product_family)
    captures = [capture_one(ci) for ci in cart_items]
    return {
        "productFamily": product_family,
        "cartItemCount": len(cart_items),
        "lineCount": sum(len(g["items"]) for c in captures for g in c["groups"]),
        "captures": captures,
    }


def write_capture(product_family: str, path: str) -> Dict:
    data = capture(product_family)
    with open(path, "w") as f:
        json.dump(data, f, indent=1, sort_keys=False)
    return data


# ---------------------------------------------------------------- diffing


def _pair_lines(b_lines: List[Dict], a_lines: List[Dict]):
    """Pair before-lines with after-lines.

    Item code is the natural key, but sourcing a line from the cost table can
    legitimately change it - a line printed as "SS Handle Cost (per PC)" starts
    printing as its part number 2290437. That is a renaming, not a line
    disappearing and another appearing, so anything left unmatched by code is
    paired by description before being called missing or added.
    """
    pairs, b_left, a_left = [], list(b_lines), list(a_lines)

    for key in ("itemCode", "description"):
        b_index = {}
        for it in b_left: b_index.setdefault(it[key], []).append(it)
        still_a, matched_b = [], set()
        for it in a_left:
            bucket = b_index.get(it[key]) or []
            match = next((x for x in bucket if id(x) not in matched_b), None)
            if(match):
                matched_b.add(id(match))
                pairs.append((match, it))
            else:
                still_a.append(it)
        b_left = [x for x in b_left if id(x) not in matched_b]
        a_left = still_a

    return pairs, b_left, a_left


def diff(before: Dict, after: Dict) -> Dict:
    """Compare two captures, split by severity - the categories are not equally
    acceptable. A quantity change fails the migration outright; a renaming is
    reviewed and signed off."""
    out = {
        "quantity": [],      # blocking - a value moved
        "missing": [],       # blocking - a line stopped being emitted
        "added": [],         # blocking - a line appeared
        "order": [],         # blocking - lines emitted in a new sequence
        "code": [],          # reviewable - same line, new item code
        "naming": [],        # reviewable - description or uom changed
    }

    b_by_item = {c["cartItem"]: c for c in before["captures"]}
    a_by_item = {c["cartItem"]: c for c in after["captures"]}

    for cart_item in sorted(set(b_by_item) | set(a_by_item)):
        b = b_by_item.get(cart_item)
        a = a_by_item.get(cart_item)
        if(not b or not a):
            out["missing" if not a else "added"].append(
                {"cartItem": cart_item, "reason": "whole cart item"})
            continue

        b_lines = [it for g in b["groups"] for it in g["items"]]
        a_lines = [it for g in a["groups"] for it in g["items"]]
        pairs, b_left, a_left = _pair_lines(b_lines, a_lines)

        for it in b_left:
            out["missing"].append({"cartItem": cart_item,
                                   "itemCode": it["itemCode"], "value": it["value"]})
        for it in a_left:
            out["added"].append({"cartItem": cart_item,
                                 "itemCode": it["itemCode"], "value": it["value"]})

        for bi, ai in pairs:
            if(bi["value"] != ai["value"]):
                out["quantity"].append({
                    "cartItem": cart_item, "itemCode": bi["itemCode"],
                    "before": bi["value"], "after": ai["value"]})
            if(bi["itemCode"] != ai["itemCode"]):
                out["code"].append({
                    "cartItem": cart_item, "description": bi["description"],
                    "before": {"description": bi["itemCode"], "uom": bi["uom"]},
                    "after": {"description": ai["itemCode"], "uom": ai["uom"]}})
            if(bi["description"] != ai["description"] or bi["uom"] != ai["uom"]):
                out["naming"].append({
                    "cartItem": cart_item, "itemCode": bi["itemCode"],
                    "before": {"description": bi["description"], "uom": bi["uom"]},
                    "after": {"description": ai["description"], "uom": ai["uom"]}})

        # order is compared over the paired lines, using each after-line's
        # position in the before-list; a pure renaming must not read as a
        # reordering
        position = {id(ai): i for i, (bi, ai) in enumerate(
            sorted(pairs, key=lambda p: b_lines.index(p[0])))}
        seen = [position[id(it)] for it in a_lines if id(it) in position]
        if(seen != sorted(seen)):
            out["order"].append({
                "cartItem": cart_item,
                "before": [it["itemCode"] for it in b_lines],
                "after": [it["itemCode"] for it in a_lines]})

    return out


def _dedupe_naming(naming: List[Dict]) -> List[Dict]:
    """The same renaming recurs on every cart item that carries the line; the
    reviewer only needs each distinct change once, with a count."""
    seen: Dict[str, Dict] = {}
    for n in naming:
        key = json.dumps([n["itemCode"], n["before"], n["after"]], sort_keys=True)
        if(key not in seen):
            seen[key] = {"itemCode": n["itemCode"], "before": n["before"],
                         "after": n["after"], "cartItems": 0}
        seen[key]["cartItems"] += 1
    return sorted(seen.values(), key=lambda d: d["itemCode"])


def report(before_path: str, after_path: str) -> bool:
    """Print a verdict. Returns True when the migration is clean, meaning no
    blocking category has any entry."""
    with open(before_path) as f: before = json.load(f)
    with open(after_path) as f: after = json.load(f)

    d = diff(before, after)
    blocking = d["quantity"] + d["missing"] + d["added"] + d["order"]

    print("=" * 68)
    print(f"BOQ parity - {before.get('productFamily')}")
    print(f"  before : {before['cartItemCount']} cart items, {before['lineCount']} lines")
    print(f"  after  : {after['cartItemCount']} cart items, {after['lineCount']} lines")
    print("=" * 68)

    for label, key in (("QUANTITY CHANGED", "quantity"), ("LINE MISSING", "missing"),
                       ("LINE ADDED", "added"), ("ORDER CHANGED", "order")):
        rows = d[key]
        print(f"\n{label:<20} {len(rows)}")
        for r in rows[:15]:
            print("   ", json.dumps(r)[:150])
        if(len(rows) > 15): print(f"    ... and {len(rows) - 15} more")

    for label, key, field in (("ITEM CODE CHANGED", "code", "description"),
                              ("NAMING CHANGED", "naming", "itemCode")):
        rows = _dedupe_naming([{**r, "itemCode": r[field]} for r in d[key]])
        print(f"\n{label:<20} {len(rows)} distinct "
              f"({len(d[key])} line instances) - review, not blocking")
        for r in rows:
            print(f"    {r['itemCode']}")
            print(f"        was  {r['before']['description']!r} [{r['before']['uom']}]")
            print(f"        now  {r['after']['description']!r} [{r['after']['uom']}]")
            print(f"        on {r['cartItems']} cart item(s)")

    ok = not blocking
    print("\n" + "=" * 68)
    print("PARITY CLEAN" if ok else f"PARITY FAILED - {len(blocking)} blocking difference(s)")
    print("=" * 68)
    return ok


def main(action: str, product_family: str, path: str, path2: str = None):
    if(action == "capture"):
        data = write_capture(product_family, path)
        print(f"captured {data['cartItemCount']} cart items, "
              f"{data['lineCount']} lines -> {path}")
        return data
    if(action == "report"):
        return report(path, path2)
    raise ValueError(f"unknown action {action!r}")
