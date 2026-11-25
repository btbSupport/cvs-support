"""Converts a product family's block of boq_format.JSON into `BOQ Rule` specs (Phase 2, decided 2026-11-25).

Read-only developer tool. Decisions it implements:

  P1  lines that come from a cost row are Sourced: the BOQ prints the row's item code, product name and unit.
  P2  a line without a cost row of the bundle keeps the JSON text as a fixed (Templated) identifier when item
      code and description are the same; otherwise it goes to the review list.
  P3  contiguous lines of the same shape become one rule with dimensions; `static_check` proves the rules give
      the JSON's lines, quantities and order (computed on synthetic carts, line by line).

How a JSON line is read:

  filter conditions   an eq condition whose value appears in the line's identifier is a dimension
                      ('GI Casing 1.0' <- materialType GI, casingThickness 1); every other condition
                      (productCategory eq Normal, infillType neq Standard-Fibreglass) is a guard
  identifier          the item code when it equals the description (Templated, unless the rendered names are
                      all cost rows - then Sourced); else the identifier of the cost row with that item code
                      (rows of the bundle), e.g. 2020101 -> row 'GI 20mm' -> '{flangeSizeLookup}'
  fixed lines         the cost row with the item code, else the row the bundle prices the line's quantity with
  overrides           patches/boq_rules/<FAMILY>.overrides.json: hand-written rules for JSON lines no generated
                      shape can express (pooled slots: halfBaffleSlit|fullBaffleSlit). Listed by JSON line index.

Run (bench execute):
    btb_cvs_support.api._boq_convert.main --args '["SIL", "BUN6", "/path/SIL.json"]'
"""

import json
import os
import random
import re
from collections import OrderedDict
from typing import Dict, List, Optional, Tuple

import frappe

COST = "FTOCountryWiseCost"


# ------------------------------------------------------------------ reading


def family_lines(family: str) -> List[Dict]:
	with open(frappe.get_app_path("btb_cvs_support", "api", "boq_format.JSON")) as f:
		return json.load(f)[family]


def overrides_for(family: str) -> List[Dict]:
	path = frappe.get_app_path("btb_cvs_support", "patches", "boq_rules", f"{family}.overrides.json")
	if(not os.path.exists(path)): return []
	with open(path) as f:
		return json.load(f)["overrides"]


def read_filter(line: Dict):
	"""(logic, [(field, operator, value)], extra): the flat conditions, and a nested filter (or a whole
	or-filter) kept as the rule's Extra Filter."""
	f = (line.get("formula") or {}).get("filter")
	if(not f): return ("and", [], None)
	conds = f.get("conditions") or []
	if(not all(isinstance(c, dict) and "field" in c for c in conds)): return ("and", [], f)
	logic = f.get("logic") or "and"
	if(logic != "and" and len(conds) > 1): return ("and", [], f)
	return ("and", [(c["field"], c.get("operator") or "eq", str(c["value"])) for c in conds], f.get("filter"))


def one_decimal(value: str) -> str:
	"""Same rule as boq_rules.format_value('One decimal')."""
	if(re.match(r"^-?\d+$", value)): return value + ".0"
	if(re.match(r"^-?\d+\.\d{2,}$", value)):
		t = value.rstrip("0")
		return t + "0" if t.endswith(".") else t
	return value


def formats_of(value: str) -> List[Tuple[str, str]]:
	"""How a stored value may be spelled in an item code: as is, trimmed (0.60 -> 0.6), one decimal (1 -> 1.0)."""
	out = [(value, "As is")]
	if(re.match(r"^-?\d+\.\d{2,}$", value)):
		t = value.rstrip("0")
		out.append((t + "0" if t.endswith(".") else t, "Trim trailing zero"))
	if(re.match(r"^-?\d+$", value)):
		out.append((value + ".0", "One decimal"))
	if(re.match(r"^-?\d+(\.\d+)?$", value)):
		out.append((one_decimal(value), "One decimal"))
	return out


def place(text: str, conds: List[Tuple[str, str, str]]):
	"""Replace the values of eq conditions found in `text` by {field}.
	Returns (template, {field: format}, guards) - guards are the conditions not placed."""
	tpl, fmt, guards = text, {}, []
	for field, op, value in sorted(conds, key=lambda c: -len(c[2])):
		placed = False
		if(op == "eq" and value):
			for candidate, how in formats_of(value):
				pattern = rf"(?<![\w.]){re.escape(candidate)}(?![\w.])"
				if(re.search(pattern, tpl)):
					tpl = re.sub(pattern, "{" + field + "}", tpl, count=1)
					# numbers: the most general spelling that still gives this text, so 0.6 and 1 -> 1.0 share a rule
					if(re.match(r"^-?\d+(\.\d+)?$", value) and one_decimal(value) == candidate): how = "One decimal"
					fmt[field] = how
					placed = True
					break
		if(not placed): guards.append((field, op, value))
	return tpl, fmt, sorted(guards)


class Rows:
	"""Cost rows: identifiers, item codes, the bundles that use them, the rows the bundle prices quantities with."""

	def __init__(self, bundle: str):
		self.rows = {r.name: r for r in frappe.get_all(COST, fields=["name", "item_code", "product_name",
			"boq_identifier", "unit"])}
		self.ids = {(r.boq_identifier or "").strip() for r in self.rows.values() if r.boq_identifier}
		self.in_bundle = set(frappe.get_all("FTOCostBundle", filters={"bundle": bundle}, pluck="parent"))
		ics = frappe.get_all("BtbImplementationConstraint", filters={"bundle": bundle}, pluck="name") or [""]
		self.price_formulas = frappe.get_all("BtbImplementationConstraintAction",
			filters={"implementation_constraint": ["in", ics]}, pluck="formula")
		self.option_object = {i.name: i.object for i in frappe.get_all("BtbFeatureTypeItem",
			filters={"object": ["is", "set"]}, fields=["name", "object"], limit_page_length=0)}

	def own(self, hits):
		return [r for r in hits if r.name in self.in_bundle]

	def by_code(self, code: str) -> List:
		codes = {c.strip() for c in code.split("/")}
		return self.own([r for r in self.rows.values() if (r.item_code or "").strip() in codes])

	def by_text(self, *texts) -> List:
		texts = {t.strip() for t in texts if t}
		return self.own([r for r in self.rows.values() if (r.boq_identifier or "").strip() in texts
			or (r.product_name or "").strip() in texts])

	def priced_with(self, fields: List[str]) -> List:
		"""Rows the bundle's price rules read for these quantity fields:
		NUMBER(field) * CFLOAT(OBJECTATTRIBUTEV(countryWiseCost, '$[option]', 'cost'))."""
		found = set()
		for formula in self.price_formulas:
			if(not formula or "OBJECTATTRIBUTEV" not in formula): continue
			if(not any(re.search(rf"NUMBER\(\s*{re.escape(f)}\s*\)", formula) for f in fields)): continue
			for opt in re.findall(r"OBJECTATTRIBUTEV\([^,]+,\s*'\$\[([^\]]+)\]'\s*,\s*'cost'\)", formula):
				if(self.option_object.get(opt) in self.rows): found.add(self.option_object[opt])
		return self.own([self.rows[n] for n in found])


def quantity_fields(line: Dict) -> List[str]:
	out = []

	def walk(node):
		if(isinstance(node, dict)):
			out.extend(f for f in node.get("fields") or [] if f != "cartQty")
			for child in node.get("aggregate") or []: walk(child)

	walk((line.get("formula") or {}).get("aggregate"))
	return out


# --------------------------------------------------------------- classifying


def render(template: str, conds, fmt: Dict[str, str]) -> str:
	out = template
	for field, op, value in conds:
		if(field in fmt):
			out = out.replace("{" + field + "}", dict((h, c) for c, h in formats_of(value))[fmt[field]])
	return out


def classify(i: int, line: Dict, rows: Rows) -> Dict:
	agg = json.dumps((line.get("formula") or {}).get("aggregate"), sort_keys=True)
	base = {"index": i, "line": line, "aggregate": agg, "uom": line.get("uom") or ""}
	logic, conds, extra = read_filter(line)
	base["extra"] = extra
	code, desc = line["itemCode"].strip(), line["description"].strip()

	same = code == desc
	if(same):
		tpl, fmt, guards = place(code, conds)
		named = render(tpl, conds, fmt)
		hit = named in rows.ids and rows.by_text(named)
		if(not hit and not conds):
			# a fixed line with no row of its name: the row the bundle prices its quantity with (Blade Switch)
			priced = rows.priced_with(quantity_fields(line))
			if(len(priced) == 1):
				return dict(base, kind="sourced", template=priced[0].boq_identifier, formats={}, guards=[],
					conds=conds, literal=True, row=priced[0].name)
		return dict(base, kind="sourced" if hit else "templated", template=tpl, formats=fmt, guards=guards,
			conds=conds, literal=not fmt)

	# the filtered value is itself a row's key ('MFL 165F', '229101-MS4604F1210/B'): one rule per key field
	eq = [(f, o, v) for f, o, v in conds if o == "eq"]
	keyed = (rows.own([r for r in rows.rows.values() if (r.boq_identifier or "").strip() == eq[0][2]])
		if len(eq) == 1 and eq[0][2] in rows.ids else [])
	# ... but only when that row is this line's item: 'GI' (materialType) is also the GI material row's key
	if(keyed and any((r.item_code or "").strip() in (code, ) or (r.item_code or "").strip().startswith(code + "-")
			or (r.product_name or "").strip() == desc for r in keyed)):
		guards = sorted(c for c in conds if c != eq[0])
		return dict(base, kind="sourced", template="{" + eq[0][0] + "}", formats={eq[0][0]: "As is"},
			guards=guards, conds=conds, literal=False)

	hits = rows.by_code(code) or rows.by_text(code, desc)
	if(not hits and not conds):
		hits = rows.priced_with(quantity_fields(line))
	if(len(hits) == 1):
		tpl, fmt, guards = place(hits[0].boq_identifier, conds)
		# checked again in build(): an eq filter left out of the identifier must not be a field other lines
		# use as a dimension ('2025221 SS316L S4 20mm Corner' is row 'SS304L S4 30mm (Fire rated Corners)')
		return dict(base, kind="sourced", template=tpl, formats=fmt, guards=guards, conds=conds,
			literal=not fmt, row=hits[0].name, by_code=True)
	if(not hits):
		tpl, fmt, guards = place(code, conds)
		if(fmt and not any(o == "eq" for _f, o, _v in guards)):
			# the item code names the line, the description doesn't (CFD 'SS304L Frame 0.8 X 145' described as
			# '... 1.0 X 145'): print the code, the description fix is listed as a text change - unless a
			# neighbour's cost-row template fits (SIL 'GI Angle 25' -> row 'GI 25 mm Angle')
			return dict(base, kind="neighbour", conds=conds, why="no cost row of this bundle",
				fallback=dict(base, kind="templated", template=tpl, formats=fmt, guards=guards, conds=conds,
					literal=False))
	return dict(base, kind="neighbour" if conds else "fixed-text", conds=conds,
		why=("no cost row of this bundle" if not hits else f"{len(hits)} cost rows match"))


def shape(c: Dict):
	if(c["kind"] not in ("sourced", "templated")): return (c["kind"], c["index"])
	if(c["literal"]): return ("literal", c["index"])
	return (c["kind"], c["template"], tuple(sorted(c["formats"].items())),
		c["uom"] if c["kind"] == "templated" else "", tuple(c["guards"]), json.dumps(c.get("extra"), sort_keys=True))


def split_quantities(group: List[Dict]) -> List[List[Dict]]:
	"""One quantity formula per group - or one rule whose quantity picks the formula by a dimension's value
	(VCDR axles: round bars measure axleRoundBar, the square pin axle3_8Inch10mmSquarePin, same names)."""
	aggs = list(OrderedDict.fromkeys(c["aggregate"] for c in group))
	if(len(aggs) == 1): return [group]
	value = lambda c, f: next(v for fld, _op, v in c["conds"] if fld == f)
	for f in group[0]["formats"]:
		sets = [{value(c, f) for c in group if c["aggregate"] == a} for a in aggs]
		if(all(not (x & y) for i, x in enumerate(sets) for y in sets[i + 1:])):
			combined = {"logic": "SUM", "aggregate": [dict(json.loads(a), filter={"logic": "or", "conditions": [
				{"field": f, "operator": "eq", "value": v} for v in sorted(vals)]}) for a, vals in zip(aggs, sets)]}
			return [[dict(c, aggregate=json.dumps(combined, sort_keys=True)) for c in group]]
	runs = []
	for c in group:
		if(runs and runs[-1][-1]["aggregate"] == c["aggregate"]): runs[-1].append(c)
		else: runs.append([c])
	return runs


# ----------------------------------------------------------------- building


def dims_for(group: List[Dict]) -> List[Dict]:
	"""Outer dimension first (the field whose value changes least often in JSON order)."""
	fields = list(group[0]["formats"])
	value = lambda c, f: next(v for fld, _op, v in c["conds"] if fld == f)
	changes = {f: sum(1 for a, b in zip(group, group[1:]) if value(a, f) != value(b, f)) for f in fields}
	out = []
	for f in sorted(fields, key=lambda x: (changes[x], fields.index(x))):
		how = group[0]["formats"][f]
		spelled = lambda c: dict((h, s) for s, h in formats_of(value(c, f)))[how]
		order = list(OrderedDict.fromkeys(spelled(c) for c in group))
		out.append({"field": f, "value_format": how, "value_order": ",".join(order)})
	return out


def build(family: str, bundle: str) -> Tuple[List[Dict], List[Dict]]:
	rows = Rows(bundle)
	lines = family_lines(family)
	overrides = overrides_for(family)
	overridden = {i: o for o in overrides for i in o["lines"]}

	classified = {i: classify(i, line, rows) for i, line in enumerate(lines) if i not in overridden}
	dim_fields = {f for c in classified.values() if c["kind"] in ("sourced", "templated") for f in c.get("formats", {})}
	for i, c in classified.items():
		row = rows.rows.get(c.get("row")) if c.get("by_code") else None
		names = f"{row.product_name or ''} {row.boq_identifier or ''}" if row else ""
		if(row and any(o == "eq" and f in dim_fields and v in c["line"]["description"] and v not in names
				for f, o, v in c["guards"])):
			classified[i] = dict(c, kind="neighbour", why="the cost row with this item code names other values")
	# a line with no row of its own takes the template of the nearest same-shaped line around it
	for i, c in list(classified.items()):
		if(c["kind"] != "neighbour"): continue
		for j in sorted(classified, key=lambda j: abs(j - i)):
			n = classified[j]
			if(j == i or n["kind"] != "sourced" or n["literal"] or n["aggregate"] != c["aggregate"]): continue
			if({f for f, _o, _v in n["conds"]} != {f for f, _o, _v in c["conds"]}): continue
			named = render(n["template"], c["conds"], n["formats"])
			if(named in rows.ids):
				classified[i] = dict(n, index=i, line=lines[i], conds=c["conds"], row=None)
				break

	groups: List[List[Dict]] = []
	by_shape: Dict = {}
	for i, line in enumerate(lines):
		if(i in overridden):
			o = overridden[i]
			if(i == o["lines"][0]): groups.append([{"index": i, "kind": "override", "override": o, "line": line}])
			else: groups[-1].append({"index": i, "kind": "override", "override": o, "line": line})
			continue
		c = classified[i]
		if(c["kind"] == "neighbour" and c.get("fallback")):
			c = classified[i] = c["fallback"]
		if(c["kind"] in ("neighbour", "fixed-text")):
			# no cost row and no template: keep the JSON's item code and description (decision P2)
			c = dict(c, kind="templated", template=c["line"]["itemCode"].strip(), formats={},
				guards=sorted(c["conds"]), literal=True, description=c["line"]["description"].strip())
		# lines of the same shape form one rule even when other lines sit between them (VCDA blades: the
		# JSON lists widths 4..7" per thickness in no fixed order); the static check proves the order per cart
		key = shape(c)
		if(key in by_shape and key[0] in ("sourced", "templated")):
			by_shape[key].append(c)
		else:
			by_shape[key] = [c]
			groups.append(by_shape[key])

	groups = [part for g in groups for part in (split_quantities(g) if g[0]["kind"] in ("sourced", "templated") else [g])]
	specs, review = [], []
	for n, g in enumerate(groups):
		first = g[0]
		covers = [c["index"] for c in g]
		if(first["kind"] == "override"):
			spec = dict(first["override"]["rule"], sequence=(n + 1) * 10, covers=covers)
			spec.setdefault("conditions", []); spec.setdefault("condition_logic", "and")
			specs.append(spec)
			continue
		if(first["kind"] == "review"):
			review.append({"index": first["index"], "itemCode": first["line"]["itemCode"],
				"description": first["line"]["description"], "why": first["why"]})
			continue
		if(not first["literal"] and first["kind"] in ("sourced", "templated")):
			# a field with one value in the whole group is a guard, not a dimension: 'GI Blade AF 5" 0.8 X 263'
			# names the AF blade only - as a dimension it would also print '... 3V 5" 0.8 X 263'
			value = lambda c, f: next(v for fld, _op, v in c["conds"] if fld == f)
			single = [f for f in first["formats"] if len({value(c, f) for c in g}) == 1]
			if(single and len(single) < len(first["formats"])):
				tpl = first["template"]
				for f in single:
					tpl = tpl.replace("{" + f + "}", dict((h, sp) for sp, h in formats_of(value(first, f)))[first["formats"][f]])
				g = [dict(c, template=tpl, formats={k: v for k, v in c["formats"].items() if k not in single},
					guards=sorted(set(c["guards"]) | {(f, "eq", value(c, f)) for f in single})) for c in g]
				first = g[0]
		if(len(g) == 1 and not first["literal"]):
			# one JSON line: a dimension would also print for values other lines (or nothing) cover - keep it
			# a fixed line, its filter values as guards
			first = dict(first, literal=True, template=render(first["template"], first["conds"], first["formats"]),
				guards=sorted(first["conds"]))
		spec = {"sequence": (n + 1) * 10, "source_type": "Sourced" if first["kind"] == "sourced" else "Templated",
			"condition_logic": "and", "aggregate": json.dumps(json.loads(first["aggregate"])),
			"uom": first["uom"] if first["kind"] == "templated" else None,
			"conditions": [{"field": f, "operator": op, "value": v} for f, op, v in first["guards"]],
			"dimensions": dims_for(g) if not first["literal"] else [], "covers": covers}
		key = "identifier_literal" if first["literal"] else "identifier_template"
		spec[key] = first["template"]
		if(first.get("extra")): spec["filter_json"] = json.dumps(first["extra"])
		if(first.get("description") and first["description"] != first["template"]):
			spec["description_template"] = first["description"]
		spec["notes"] = (f"cost row {first['row']}" if first.get("row") and first["literal"] else
			f"{len(g)} JSON lines" + ("; item code, name and unit from the cost row" if first["kind"] == "sourced" else ""))
		specs.append(spec)
	review += exclude_claimed(specs, rows)
	return specs, review


def exclude_claimed(specs: List[Dict], rows: Rows) -> List[Dict]:
	"""A dimension rule must not print a combination another rule of the same quantity prints as its own fixed
	line (CFD: VSpring1..6 by {springs}, H10J14.. as fixed lines with their item codes). A Sourced rule only
	prints combinations that name a cost row, so only those conflict. One dimension: add field neq value;
	more than one can't be expressed - reported for review."""
	review = []
	for s in specs:
		dims = s.get("dimensions") or []
		if(not dims or any("|" in d["field"] for d in dims)): continue
		fields = [d["field"] for d in dims]
		for o in specs:
			if(o is s or o["aggregate"] != s["aggregate"]): continue
			eq = {c["field"]: c["value"] for c in o.get("conditions") or [] if c["operator"] == "eq"}
			if(not all(f in eq for f in fields)): continue
			# guards that contradict (bladeType eq 3V vs bladeType eq EAL) never meet on one cart
			mine = {c["field"]: c["value"] for c in s.get("conditions") or [] if c["operator"] == "eq"}
			if(any(f in eq and eq[f] != v for f, v in mine.items())): continue
			named = s.get("identifier_template") or ""
			for d in dims:
				named = named.replace("{" + d["field"] + "}", dict((h, c) for c, h in formats_of(eq[d["field"]]))
					.get(d["value_format"], eq[d["field"]]))
			if(s["source_type"] == "Sourced" and named not in rows.ids): continue
			if(len(fields) == 1):
				g = {"field": fields[0], "operator": "neq", "value": eq[fields[0]]}
				if(g not in s["conditions"]): s["conditions"].append(g)
			else:
				review.append({"rule": s["sequence"], "why": f"also prints {named!r}, which rule {o['sequence']} "
					"prints as a fixed line"})
	return review


# ------------------------------------------------------------- static check


def as_loaded(specs: List[Dict], family: str) -> List[Dict]:
	out = []
	for s in sorted(specs, key=lambda x: x["sequence"]):
		out.append({"name": f"CONV-{family}-{s['sequence']:05d}", "sourceType": s["source_type"],
			"identifierTemplate": s.get("identifier_template"), "identifierLiteral": s.get("identifier_literal"),
			"descriptionTemplate": s.get("description_template"),
			"filterJson": json.loads(s["filter_json"]) if s.get("filter_json") else None,
			"uom": s.get("uom"), "conditionLogic": s.get("condition_logic") or "and",
			"conditions": [dict(c) for c in s.get("conditions") or []],
			"dimensions": [{"field": d["field"], "format": d.get("value_format") or "As is",
				"order": d.get("value_order") or ""} for d in s.get("dimensions") or []],
			"aggregate": json.loads(s["aggregate"])})
	return out


def synthetic_model(line: Dict, numbers: Dict[str, float]) -> Dict:
	"""A cart model that satisfies the line's filter (first branch of an or), with numbers for every field."""
	model = {k: {"value": v} for k, v in numbers.items()}

	def satisfy(f, first_only):
		if(not f): return
		conds = f.get("conditions") or []
		for c in (conds[:1] if first_only else conds):
			if("field" not in c): continue
			model[c["field"]] = {"value": str(c["value"]) if c.get("operator", "eq") == "eq" else "__other__"}
		satisfy(f.get("filter"), (f.get("filter") or {}).get("logic") == "or")

	f = (line.get("formula") or {}).get("filter")
	satisfy(f, (f or {}).get("logic") == "or")
	return model


def static_check(family: str, specs: List[Dict]) -> Dict:
	"""For a synthetic cart line per JSON line: the JSON's lines (value > 0, JSON order) must equal the rules'
	lines (value > 0, rule order) - same quantities; Templated also the same item code and description."""
	from . import boq_rules
	from .btb_constraint import exec_formula
	lines = family_lines(family)
	rules = as_loaded(specs, family)
	fields = sorted({f for l in lines for f in quantity_fields(l)})
	rnd = random.Random(7)
	report = {"lines": len(lines), "rules": len(specs), "checked": 0, "problems": [], "text_changes": {}}
	import io
	from contextlib import redirect_stdout
	for i, line in enumerate(lines):
		model = synthetic_model(line, {f: round(rnd.uniform(1, 9), 3) for f in fields} | {"cartQty": 2})
		with redirect_stdout(io.StringIO()):
			want = [(l["itemCode"], l["description"], round(exec_formula(l["formula"], [model]), 6)) for l in lines]
			want = [w for w in want if w[2] > 0]
			got = [(r["itemCode"], r["description"], round(exec_formula(r["formula"], [model]), 6), r["uom"], r["_rule"])
				for r in expand_named(boq_rules, rules, [model])]
			got = [g for g in got if g[2] > 0]
		report["checked"] += 1
		if([w[2] for w in want] != [g[2] for g in got]):
			wv, gv = [(w[0], w[2]) for w in want], [(g[0], g[2]) for g in got]
			only_json = [x for x in wv if x[1] not in [y[1] for y in gv]]
			only_rules = [x for x in gv if x[1] not in [y[1] for y in wv]]
			if(only_rules and not only_json and [x[1] for x in gv if x not in only_rules] == [x[1] for x in wv]):
				for x in only_rules: report.setdefault("added", {})[x[0]] = report.get("added", {}).get(x[0], 0) + 1
				continue
			what = (f"JSON only {only_json} / rules only {only_rules}" if only_json or only_rules else
				f"order JSON {[x[0] for x in wv]} vs rules {[x[0] for x in gv]}")
			report["problems"].append(f"line {i} {line['itemCode']}: {what}")
			continue
		for w, g in zip(want, got):
			if(g[4] == "Templated" and w[0] != g[0]):
				report["problems"].append(f"line {i}: text {w[0]!r}/{w[1]!r} vs {g[0]!r}/{g[1]!r}")
			elif((w[0], w[1]) != (g[0], g[1])):
				report["text_changes"][(w[0], w[1])] = (g[0], g[1], g[3])
	report["text_changes"] = [{"json": list(k), "rule": list(v)} for k, v in report["text_changes"].items()]
	covered = {i for s in specs for i in s["covers"]}
	report["not_covered"] = [f"{i} {l['itemCode']}" for i, l in enumerate(lines) if i not in covered]
	return report


def expand_named(boq_rules, rules, models):
	"""expand(), keeping which kind of rule made each line."""
	out = []
	for rule in rules:
		for row in boq_rules.expand([rule], models):
			out.append(dict(row, _rule=rule["sourceType"]))
	return out


def main(family: str, bundle: str, out_path: str):
	specs, review = build(family, bundle)
	report = static_check(family, specs)
	with open(out_path, "w") as f:
		json.dump({"family": family, "bundle": bundle, "rules": specs, "review": review, "check": report},
			f, indent=1, ensure_ascii=False)
	print(f"{family}: {report['lines']} JSON lines -> {len(specs)} rules; {report['checked']} synthetic cart lines "
		f"checked, {len(report['problems'])} problems; {len(report['text_changes'])} text changes (P1); "
		f"added (JSON gaps) {report.get('added', {})}; "
		f"{len(review)} for review; not covered: {len(report['not_covered'])}")
	for p in report["problems"][:25]: print("  PROBLEM", p[:400])
	for r in review: print("  REVIEW", r)
	return report


# ------------------------------------------------------------------ parity


def install(specs: List[Dict], family: str):
	"""Point the engine at the in-memory rules of one family (nothing is written)."""
	from . import boq
	loaded = as_loaded(specs, family)
	boq.families_with_rules = lambda: {family}
	boq.load_rules = lambda pf: loaded if pf == family else []


def uninstall():
	from . import boq, boq_rules
	boq.families_with_rules = boq_rules.families_with_rules
	boq.load_rules = boq_rules.load_rules


def parity(family: str, spec_path: str, out_path: str, limit: int = 1000):
	"""BOQ of every cart line of the family, JSON vs rules; diff in _boq_parity's categories."""
	from ._boq_parity import capture_one, cart_items_for_family, diff
	with open(spec_path) as f:
		specs = json.load(f)["rules"]
	items = cart_items_for_family(family)
	if(limit and len(items) > limit):
		# the newest 60% of the sample plus a fixed random draw of older cart lines (same sample every run)
		newest = frappe.get_all("BtbCartItem", filters={"name": ["in", items]}, order_by="creation desc",
			pluck="name", limit_page_length=int(limit * 0.6))
		older = sorted(set(items) - set(newest))
		items = newest + random.Random(11).sample(older, min(len(older), limit - len(newest)))

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
