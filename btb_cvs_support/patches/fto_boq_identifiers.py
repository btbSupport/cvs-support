"""BOQ Identifier Phase 1: every cost row gets a fixed, unique BOQ identifier and every cost option shows it.

Decided 2026-11-24/25 (BOQ_Identifier_Review.xlsx). After this patch item code and product name of a cost row
can be edited freely: options, rules and the BOQ name the row by its identifier, which is set once.

Steps, all in the migrate's transaction (any stop leaves the site unchanged):
1. The site's FTOCountryWiseCost rows must be exactly the rows in fto_boq_identifiers.json (504 on every site,
   the 24 FRAD rows included: runs after add_fire_rated_access_doors). Missing or extra rows stop the migrate.
2. A row that already has a different identifier stops the migrate (AD/FRAD identifiers are kept as they are).
3. Readable rule texts (`constraint` of BtbImplementationConstraint / -Action) follow the new option text:
   '$[Profit]' -> '$[Profit (SIL)]'. The compiled `formula` names options by id and does not change, so prices
   are not affected; this keeps the readable text compiling to the same formula when a rule is saved in the UI.
4. Identifiers are written, and every feature type over FTOCountryWiseCost shows boq_identifier.
5. SIL: the corner options no longer share the flange text ('GI 20mm' -> 'GI 20mm (Corners)'), so the two
   actions that pick the corner from the flange add the suffix (decision O1).

Safe to run again: a second run finds nothing to change.
"""

import json

import frappe

from btb_cvs_support.onecpq_rule_text import TOKEN, norm, relabel

COST = "FTOCountryWiseCost"
DATA = ("patches", "fto_boq_identifiers.json")
FLANGE = "SELECTEDVALUE(flangeSizeLookup)"
CORNER_SUFFIX = {"cornersUniq": " (Corners)", "fireRatedCorners": " (Fire rated Corners)"}


def log(msg):
	print(f"[fto_boq_identifiers] {msg}")


def execute():
	with open(frappe.get_app_path("btb_cvs_support", *DATA)) as f:
		identifiers = json.load(f)["identifiers"]
	rows = {r.name: r for r in frappe.get_all(COST, fields=["name", "boq_identifier"])}
	check_rows(rows, identifiers)

	fts = frappe.get_all("BtbFeatureType", filters={"object_type": COST}, fields=["name", "label", "data_text_field"])
	old_text, new_text = option_texts(fts, identifiers)
	changed = {oid: text for oid, text in new_text.items() if old_text[oid] != text}

	rules, tokens, skipped = rewrite_rules(changed, old_text)

	filled = 0
	for name, value in identifiers.items():
		if (rows[name].boq_identifier or "").strip() != value:
			frappe.db.set_value(COST, name, "boq_identifier", value, update_modified=False)
			filled += 1
	switched = []
	for ft in fts:
		if ft.data_text_field != "boq_identifier":
			frappe.db.set_value("BtbFeatureType", ft.name, "data_text_field", "boq_identifier", update_modified=False)
			switched.append(f"{ft.name} {ft.label} ({ft.data_text_field})")
	corners = fix_corner_actions()

	check_unique()
	frappe.clear_cache()
	log(f"{len(identifiers)} cost rows checked, {filled} identifiers set; {len(switched)} feature types now show "
		f"boq_identifier; {len(changed)} option texts changed; {tokens} rule tokens rewritten in {rules} rules; "
		f"{corners} SIL corner actions updated")
	if switched:
		log("feature types switched: " + "; ".join(switched))
	for msg in skipped:
		log("NOT rewritten (readable text and formula do not line up; the formula is unchanged): " + msg)


def check_rows(rows, identifiers):
	missing = sorted(set(identifiers) - set(rows))
	extra = sorted(set(rows) - set(identifiers))
	if missing or extra:
		frappe.throw("fto_boq_identifiers: the cost rows of this site differ from patches/fto_boq_identifiers.json "
			f"(every site must hold the same {len(identifiers)} rows). Missing: {', '.join(missing) or '-'}. "
			f"Not in the list: {', '.join(extra) or '-'}. Align the site and migrate again.")
	differ = [f"{n} has {rows[n].boq_identifier!r}, expected {v!r}" for n, v in identifiers.items()
		if (rows[n].boq_identifier or "").strip() not in ("", v)]
	if differ:
		frappe.throw("fto_boq_identifiers: rows already carry a different BOQ identifier: " + "; ".join(differ))


def option_texts(fts, identifiers):
	"""Option id -> text shown today, and -> text after the switch (the row's identifier)."""
	old_text, new_text = {}, {}
	by_ft = {ft.name: ft for ft in fts}
	items = frappe.get_all("BtbFeatureTypeItem", filters={"feature_type": ["in", list(by_ft) or [""]]},
		fields=["name", "feature_type", "object"])
	fields = {ft.data_text_field or "name" for ft in fts}
	values = {r.name: r for r in frappe.get_all(COST, fields=list(fields | {"name"}))}
	for it in items:
		if not it.object or it.object not in values:
			continue
		dtf = by_ft[it.feature_type].data_text_field or "name"
		old_text[it.name] = str(values[it.object].get(dtf) or "")
		new_text[it.name] = identifiers[it.object]
	return old_text, new_text


def rewrite_rules(changed, old_text):
	"""Swap '$[old text]' for '$[new text]' in readable rule texts, paired with the formula's option ids."""
	if not changed:
		return 0, 0, []
	rules = tokens = 0
	skipped = []
	for doctype in ("BtbImplementationConstraint", "BtbImplementationConstraintAction"):
		for r in frappe.get_all(doctype, fields=["name", "constraint", "formula"]):
			ids = [i for i in TOKEN.findall(r.formula or "") if i in changed]
			if not ids:
				continue
			readable = relabel(r.constraint, r.formula, changed, old_text)
			if readable is None:
				skipped.append(f"{doctype} {r.name}")
				continue
			if readable != r.constraint:
				frappe.db.set_value(doctype, r.name, "constraint", readable, update_modified=False)
				rules += 1
				tokens += sum(1 for a, b in zip(TOKEN.findall(r.constraint), TOKEN.findall(readable)) if a != b)
	return rules, tokens, skipped


def fix_corner_actions():
	"""O1: the corner option = flange text + suffix. Matches the action by what it does, not by its name."""
	done = 0
	for a in frappe.get_all("BtbImplementationConstraintAction", filters={"impact_fields": ["in", list(CORNER_SUFFIX)]},
			fields=["name", "impact_fields", "constraint", "formula"]):
		if norm(a.formula) != norm(FLANGE) or norm(a.constraint) != norm(FLANGE):
			continue
		expr = (f"IIF((COUNT(flangeSizeLookup) > 0), "
			f"CONCAT({FLANGE}, '{CORNER_SUFFIX[a.impact_fields]}'), '')")
		frappe.db.set_value("BtbImplementationConstraintAction", a.name, {"constraint": expr, "formula": expr},
			update_modified=False)
		log(f"SIL corner action {a.name} ({a.impact_fields}): {expr}")
		done += 1
	return done


def check_unique():
	dup = frappe.db.sql(f"""select boq_identifier, group_concat(name) from `tab{COST}`
		group by boq_identifier having count(*) > 1 or ifnull(boq_identifier, '') = ''""")
	if dup:
		frappe.throw("fto_boq_identifiers: BOQ identifiers missing or not unique: "
			+ "; ".join(f"{v!r}: {n}" for v, n in dup))
