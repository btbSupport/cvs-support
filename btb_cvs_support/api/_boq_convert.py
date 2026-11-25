"""Converts a product family's block of boq_format.JSON into `BOQ Rule` specs (Phase 2, decided 2026-11-25).

Read-only developer tool. Decisions it implements:

  P1  lines that come from a cost row are Sourced: the BOQ prints the row's item code, product name and unit.
  P2  a line without a cost row uses a cost lookup of the bundle when one exists, else the JSON text as a
      fixed (Templated, literal) identifier. Lines that can't be expressed go to the review list.
  P3  contiguous lines with the same quantity formula and filter fields become one rule with dimensions;
      `static_check` proves the rules expand back to the JSON lines (text, filter, quantity, order).

Shapes produced (the same spec shape seed_ad_boq_rules uses):

  weight blocks   Templated, dimensions = the filter fields, template from the item code
                  ('{frameMaterialType} Frame {frameThicknessLookup}', thickness '1.00' -> '1.0')
  cost key lines  Sourced, one dimension on the filtered field whose values are row identifiers
                  ('{fuseLink}', '{actuatorItemCode}')
  fixed lines     Sourced literal = the identifier of the cost row with the line's item code (rows of the
                  bundle first); else Templated literal when item code == description

Run (bench console or execute):
    from btb_cvs_support.api._boq_convert import main
    main("ULRD", "BUN4", "/path/ULRD.json")
"""

import json
import re
from collections import OrderedDict
from typing import Dict, List, Optional, Tuple

import frappe

COST = "FTOCountryWiseCost"


# ------------------------------------------------------------------ reading


def family_lines(family: str) -> List[Dict]:
	with open(frappe.get_app_path("btb_cvs_support", "api", "boq_format.JSON")) as f:
		return json.load(f)[family]


def flat_eq_filter(line: Dict) -> Optional[Tuple[str, List[Tuple[str, str]]]]:
	"""(logic, [(field, value)]) when the filter is a flat list of eq conditions; None otherwise."""
	f = (line.get("formula") or {}).get("filter")
	if(not f): return ("and", [])
	if("filter" in f): return None
	conds = f.get("conditions") or []
	if(not all(isinstance(c, dict) and c.get("operator") == "eq" and "field" in c for c in conds)): return None
	return (f.get("logic") or "and", [(c["field"], str(c["value"])) for c in conds])


def trim(v: str) -> str:
	"""Same rule as boq_rules.format_value('Trim trailing zero')."""
	if(not re.match(r"^-?\d+\.\d{2,}$", v or "")): return v
	t = v.rstrip("0")
	return t + "0" if t.endswith(".") else t


class Rows:
	"""Cost rows: identifiers, item codes and the bundles that use them."""

	def __init__(self, bundle: str):
		self.rows = {r.name: r for r in frappe.get_all(COST, fields=["name", "item_code", "product_name",
			"boq_identifier", "unit"])}
		self.ids = {(r.boq_identifier or "").strip(): r for r in self.rows.values() if r.boq_identifier}
		linked = frappe.get_all("FTOCostBundle", filters={"bundle": bundle}, pluck="parent")
		self.in_bundle = set(linked)
		# price actions of the bundle: formula text, to find the row a quantity is priced with
		ics = frappe.get_all("BtbImplementationConstraint", filters={"bundle": bundle}, pluck="name") or [""]
		self.price_formulas = frappe.get_all("BtbImplementationConstraintAction",
			filters={"implementation_constraint": ["in", ics]}, pluck="formula")
		self.option_object = {i.name: i.object for i in frappe.get_all("BtbFeatureTypeItem",
			filters={"object": ["is", "set"]}, fields=["name", "object"], limit_page_length=0)}

	def priced_with(self, fields: List[str]) -> List:
		"""Cost rows the bundle's price rules read for these quantity fields:
		NUMBER(field) * CFLOAT(OBJECTATTRIBUTEV(countryWiseCost, '$[option]', 'cost'))."""
		found = set()
		for formula in self.price_formulas:
			if(not formula or "OBJECTATTRIBUTEV" not in formula): continue
			if(not any(re.search(rf"NUMBER\(\s*{re.escape(f)}\s*\)", formula) for f in fields)): continue
			for opt in re.findall(r"OBJECTATTRIBUTEV\([^,]+,\s*'\$\[([^\]]+)\]'\s*,\s*'cost'\)", formula):
				if(self.option_object.get(opt) in self.rows): found.add(self.option_object[opt])
		return [self.rows[n] for n in found]

	def by_code(self, code: str) -> List:
		codes = [c.strip() for c in code.split("/")]
		hits = [r for r in self.rows.values() if (r.item_code or "").strip() in codes]
		own = [r for r in hits if r.name in self.in_bundle]
		return own

	def by_text(self, *texts) -> List:
		texts = {t.strip() for t in texts if t}
		hits = [r for r in self.rows.values() if (r.boq_identifier or "").strip() in texts
			or (r.product_name or "").strip() in texts]
		return [r for r in hits if r.name in self.in_bundle]


# --------------------------------------------------------------- classifying


def quantity_fields(line: Dict) -> List[str]:
	"""Feature fields the line's quantity multiplies (cartQty left out)."""
	out = []

	def walk(node):
		if(isinstance(node, dict)):
			out.extend(f for f in node.get("fields") or [] if f != "cartQty")
			for child in node.get("aggregate") or []: walk(child)

	walk((line.get("formula") or {}).get("aggregate"))
	return out


def template_for(line: Dict, conds: List[Tuple[str, str]]) -> Optional[Tuple[str, Dict[str, str]]]:
	"""Item code with each filter value replaced by its {field}; also the value format each field needs."""
	code = line["itemCode"]
	fmt = {}
	tpl = code
	# longer values first so '1.20' is not partly replaced by '1.2'
	for field, value in sorted(conds, key=lambda c: -len(c[1])):
		for candidate, how in ((value, "As is"), (trim(value), "Trim trailing zero")):
			if(candidate and re.search(rf"(?<![\w.]){re.escape(candidate)}(?![\w.])", tpl)):
				tpl = re.sub(rf"(?<![\w.]){re.escape(candidate)}(?![\w.])", "{" + field + "}", tpl, count=1)
				fmt[field] = how
				break
		else:
			return None
	return tpl, fmt


def classify(line: Dict, rows: Rows) -> Dict:
	agg = json.dumps((line.get("formula") or {}).get("aggregate"), sort_keys=True)
	f = flat_eq_filter(line)
	base = {"line": line, "aggregate": agg, "uom": line.get("uom") or ""}
	if(f is None):
		return dict(base, kind="review", why="nested filter (needs a hand-made rule)")
	logic, conds = f

	if(not conds):
		hits = rows.by_code(line["itemCode"]) or rows.by_text(line["itemCode"], line["description"])
		if(not hits):
			hits = rows.priced_with(quantity_fields(line))
		if(len(hits) == 1):
			return dict(base, kind="src-literal", identifier=hits[0].boq_identifier, row=hits[0].name)
		if(line["itemCode"].strip() == line["description"].strip()):
			return dict(base, kind="tpl-literal", identifier=line["itemCode"].strip(),
				why="no cost row of this bundle" if not hits else f"{len(hits)} cost rows match")
		return dict(base, kind="review", why=("no cost row of this bundle" if not hits else
			f"{len(hits)} cost rows match ({', '.join(h.name for h in hits)})")
			+ "; item code and description differ, so a fixed text can't print both")

	# a template first: 'GI Motor Holding Plate 1.2' filters on material 'GI', which is also a cost row's key
	t = template_for(line, conds)
	if(t and line["itemCode"].strip() == line["description"].strip()):
		return dict(base, kind="tpl-dim", template=t[0], formats=t[1], conds=conds, logic=logic)
	if(len(conds) == 1 and conds[0][1] in rows.ids and logic == "and"):
		return dict(base, kind="src-dim", field=conds[0][0], value=conds[0][1])
	return dict(base, kind="review", why="filtered line that is neither a cost key nor a template")


def group_key(c: Dict):
	if(c["kind"] == "tpl-dim"):
		return ("tpl-dim", c["template"], tuple(sorted(c["formats"].items())), c["aggregate"], c["uom"], c["logic"])
	if(c["kind"] == "src-dim"):
		return ("src-dim", c["field"], c["aggregate"])
	return (c["kind"], id(c))   # single-line rules


# ----------------------------------------------------------------- building


def dims_for(group: List[Dict]) -> List[Dict]:
	"""Outer dimension first (the field whose value changes least often in JSON order)."""
	fields = [f for f, _v in group[0]["conds"]]
	changes = {}
	for f in fields:
		vals = [dict(c["conds"])[f] for c in group]
		changes[f] = sum(1 for a, b in zip(vals, vals[1:]) if a != b)
	out = []
	for f in sorted(fields, key=lambda x: (changes[x], fields.index(x))):
		fmt = group[0]["formats"][f]
		order = list(OrderedDict.fromkeys(
			(trim(dict(c["conds"])[f]) if fmt == "Trim trailing zero" else dict(c["conds"])[f]) for c in group))
		out.append({"field": f, "value_format": fmt, "value_order": ",".join(order)})
	return out


def build(family: str, bundle: str) -> Tuple[List[Dict], List[Dict]]:
	rows = Rows(bundle)
	classified = [classify(l, rows) for l in family_lines(family)]
	groups: List[List[Dict]] = []
	for c in classified:
		if(groups and group_key(groups[-1][-1]) == group_key(c)):
			groups[-1].append(c)
		else:
			groups.append([c])

	specs, review = [], []
	for i, g in enumerate(groups):
		first = g[0]
		spec = {"sequence": (i + 1) * 10, "condition_logic": "and", "conditions": [], "dimensions": [],
			"aggregate": json.dumps(json.loads(first["aggregate"])), "uom": None,
			"covers": [c["line"]["itemCode"] for c in g]}
		kind = first["kind"]
		if(kind == "tpl-dim"):
			spec.update(source_type="Templated", identifier_template=first["template"], uom=first["uom"],
				dimensions=dims_for(g), notes=f"{len(g)} JSON lines")
		elif(kind == "src-dim"):
			order = ",".join(OrderedDict.fromkeys(c["value"] for c in g))
			spec.update(source_type="Sourced", identifier_template="{" + first["field"] + "}",
				dimensions=[{"field": first["field"], "value_format": "As is", "value_order": order}],
				notes=f"{len(g)} JSON lines; item code, name and unit from the cost row")
		elif(kind == "src-literal"):
			spec.update(source_type="Sourced", identifier_literal=first["identifier"],
				notes=f"cost row {first['row']}")
		elif(kind == "tpl-literal"):
			spec.update(source_type="Templated", identifier_literal=first["identifier"], uom=first["uom"],
				notes="JSON text (" + first.get("why", "") + ")")
		else:
			review.append({"itemCode": first["line"]["itemCode"], "description": first["line"]["description"],
				"why": first["why"]})
			continue
		specs.append(spec)
	return specs, review


# ------------------------------------------------------------- static check


def as_loaded(specs: List[Dict], family: str) -> List[Dict]:
	out = []
	for s in sorted(specs, key=lambda x: x["sequence"]):
		out.append({"name": f"CONV-{family}-{s['sequence']:05d}", "sourceType": s["source_type"],
			"identifierTemplate": s.get("identifier_template"), "identifierLiteral": s.get("identifier_literal"),
			"uom": s.get("uom"), "conditionLogic": s.get("condition_logic") or "and",
			"conditions": [dict(c) for c in s.get("conditions") or []],
			"dimensions": [{"field": d["field"], "format": d.get("value_format") or "As is",
				"order": d.get("value_order") or ""} for d in s.get("dimensions") or []],
			"aggregate": json.loads(s["aggregate"])})
	return out


def static_check(family: str, specs: List[Dict]) -> Dict:
	"""Expand the rules on synthetic carts built from the JSON filters; compare with the JSON lines.

	One synthetic cart model per JSON line carries exactly that line's filter values. A rule must emit,
	for its covered lines and in JSON order, the same filter and aggregate; Templated rules also the same
	item code and description. Sourced lines print the cost row, listed as text changes (P1).
	"""
	from . import boq_rules
	lines = family_lines(family)
	report = {"lines": len(lines), "rules": len(specs), "covered": 0, "problems": [], "text_changes": []}
	covered = {}
	for s in specs:
		for code in s["covers"]: covered.setdefault(code, []).append(s)

	for s, rule in zip(sorted(specs, key=lambda x: x["sequence"]), as_loaded(specs, family)):
		want = [l for l in lines if l["itemCode"] in s["covers"]]
		models = []
		for l in want:
			f = flat_eq_filter(l)
			models.append({fld: {"value": v} for fld, v in (f[1] if f else [])})
		got = boq_rules.expand([rule], models or [{}])
		if(len(got) != len(want)):
			report["problems"].append(f"{rule['name']}: {len(got)} lines emitted for {len(want)} JSON lines "
				f"({', '.join(g['itemCode'] for g in got)} vs {', '.join(l['itemCode'] for l in want)})")
			continue
		for l, g in zip(want, got):
			report["covered"] += 1
			lf = flat_eq_filter(l)
			gf = g["formula"]["filter"]
			gconds = sorted((c["field"], str(c["value"])) for c in (gf or {}).get("conditions", []))
			if(sorted(lf[1] if lf else []) != gconds):
				report["problems"].append(f"{l['itemCode']}: filter {lf} vs {gconds}")
			if(json.dumps(g["formula"]["aggregate"], sort_keys=True)
					!= json.dumps((l.get("formula") or {}).get("aggregate"), sort_keys=True)):
				report["problems"].append(f"{l['itemCode']}: quantity formula differs")
			if(rule["sourceType"] == "Templated"):
				if(g["itemCode"] != l["itemCode"] or g["description"] != l["description"]):
					report["problems"].append(f"{l['itemCode']}: text {g['itemCode']!r}/{g['description']!r}")
				if((g["uom"] or "").lower() != (l.get("uom") or "").lower()):
					report["problems"].append(f"{l['itemCode']}: uom {g['uom']!r} vs {l.get('uom')!r}")
			elif((g["itemCode"], g["description"], (g["uom"] or "").lower())
					!= (l["itemCode"], l["description"], (l.get("uom") or "").lower())):
				report["text_changes"].append({"json": [l["itemCode"], l["description"], l.get("uom")],
					"rule": [g["itemCode"], g["description"], g["uom"]]})
	report["not_covered"] = [l["itemCode"] for l in lines if l["itemCode"] not in covered]
	return report


def main(family: str, bundle: str, out_path: str):
	specs, review = build(family, bundle)
	report = static_check(family, specs)
	with open(out_path, "w") as f:
		json.dump({"family": family, "bundle": bundle, "rules": specs, "review": review, "check": report},
			f, indent=1, ensure_ascii=False)
	print(f"{family}: {report['lines']} JSON lines -> {len(specs)} rules; {report['covered']} lines reproduced; "
		f"{len(report['problems'])} problems; {len(report['text_changes'])} text changes (P1); "
		f"{len(review)} for review; not covered: {len(report['not_covered'])}")
	for p in report["problems"][:30]: print("  PROBLEM", p)
	for r in review: print("  REVIEW", r)
	return report


# ------------------------------------------------------------------ parity


def install(specs: List[Dict], family: str):
	"""Point the engine at the in-memory rules of one family (nothing is written)."""
	from . import boq, boq_rules
	loaded = as_loaded(specs, family)
	boq.families_with_rules = lambda: {family}
	boq.load_rules = lambda pf: loaded if pf == family else []


def uninstall():
	from . import boq, boq_rules
	boq.families_with_rules = boq_rules.families_with_rules
	boq.load_rules = boq_rules.load_rules


def parity(family: str, spec_path: str, out_path: str, limit: int = 0):
	"""BOQ of every cart line of the family, JSON vs rules; diff in _boq_parity's categories."""
	from ._boq_parity import capture_one, cart_items_for_family, diff
	with open(spec_path) as f:
		specs = json.load(f)["rules"]
	items = cart_items_for_family(family)
	if(limit): items = items[-limit:]
	def safe(ci):
		try:
			return capture_one(ci)
		except Exception as e:  # noqa: BLE001 - a cart the engine can't read either way
			return {"cartItem": ci, "groups": [], "error": repr(e)[:200]}

	uninstall()
	before = {"captures": [safe(ci) for ci in items]}
	install(specs, family)
	try:
		after = {"captures": [safe(ci) for ci in items]}
	finally:
		uninstall()
	errors = [(b["cartItem"], b.get("error"), a.get("error")) for b, a in zip(before["captures"], after["captures"])
		if b.get("error") or a.get("error")]
	if(errors):
		print(f"{len(errors)} cart lines the engine can't read (JSON / rules): "
			+ "; ".join(f"{c} {e1 or '-'} / {e2 or '-'}" for c, e1, e2 in errors[:5]))
	d = diff(before, after)
	with open(out_path, "w") as f:
		json.dump({"family": family, "site": frappe.local.site, "cart_items": len(items), "diff": d,
			"before": before, "after": after}, f, indent=1, ensure_ascii=False)
	print(f"{frappe.local.site} {family}: {len(items)} cart lines; " + ", ".join(f"{k} {len(v)}" for k, v in d.items()))
	return {k: len(v) for k, v in d.items()}
