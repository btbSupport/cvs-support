"""Curtain Fire Damper springs are priced from the cost table (decided 2026-11-27, S1-S9).

FTOCVSSpring keeps what describes a spring (label, length, width, spring force); its cost and item code move to
FTOCountryWiseCost, like every other cost of the configurator:

- S1/S8 one cost row per spring row, 18 in all (NA included, cost 0), under the same names on every site
  (FTO00025-FTO00042, after FRAD's FTO00001-FTO00024).
- S2 item code and product name are what the BOQ printed from boq_format.JSON: 2290225 / H10J14 ... , VSpring1 /
  VSpring1 ... , NA / NA. S3 BOQ identifier '<label> (Spring)'. S4 cost: the site's own spring cost, unchanged.
  Cost type Country Specific, category Springs, unit Ea (site spelling), bundle BUN7.
- S6 the rows become options of the CFD cost feature type FT40 (FTI00088-FTI00105). A hidden CFD feature springCost
  (FTR00073, type FT40) gets '<selected spring> (Spring)' from a new Include Value action at sequence 46 of rule 965;
  springsCost (4682) moves from 46 to 48 and reads that row's cost instead of the spring row's cost. Nothing reads
  springsCost before 48 (only materialCostUnit, at 65). springCost joins the Disable Field (4718) and Lock Field
  (26fpc9m1g1) lists that hold springs.
- S7 the 12 CFD spring BOQ rules (11 fixed H-spring lines + one VSpring line) become one Sourced rule on
  '{springs} (Spring)' that skips NA: same codes, texts, quantities and order. Sites seeded from the new CFD.json
  have it already.
- S5 FT28 (CVS Springs) stops listing item_code and cost; the columns go from FTOCVSSpring with their property
  setters (the doctype no longer has the fields).

Existing carts are not changed: their prices are stored, and their BOQ reads the spring from the cart. Every record
is checked before it is used; a site that differs (another spring label, an action that was edited) stops the patch
before the columns are dropped. Safe to run again.
"""

import json
import os

import frappe

COST, SPRING = "FTOCountryWiseCost", "FTOCVSSpring"
BUNDLE, COST_TYPE, SPRING_TYPE = "BUN7", "FT40", "FT28"
SPRINGS_FEATURE, STRUCTURE, RULE = "2462", "ST70", "965"
FEATURE, ACTION = "FTR00073", "CFDSPRINGCOST"
PICK, PICK_SEQ = "4880", 45  # Include Value springs
SPRINGS_COST, OLD_SEQ, NEW_SEQ = "4682", 46, 48
DISABLE, LOCK = "4718", "26fpc9m1g1"
OLD_COST_READ, NEW_COST_READ = "OBJECTATTRIBUTEF(springs,'cost')", "OBJECTATTRIBUTEF(springCost,'cost')"
PICK_FORMULA = "CONCAT(SELECTEDVALUE(springs),' (Spring)')"
DROP_FIELDS = ("item_code", "cost")

# spring row, label, item code (as boq_format.JSON printed it), cost row, option
ROWS = [(f"FTOCVSSpring{76 + i}", label, code, f"FTO{25 + i:05d}", f"FTI{88 + i:05d}") for i, (label, code) in enumerate([
	("H10J14", "2290225"), ("H10J26", "2290226"), ("H10J36", "2290227"), ("H10J42", "2290228"),
	("H12J50", "2290229"), ("H12K14", "2290222"), ("H12K26", "2290223"), ("H12K36", "2290224"),
	("H12P14", "2290230"), ("H12P26", "2290231"), ("H12P36", "2290232"), ("NA", "NA"),
	("VSpring1", "VSpring1"), ("VSpring2", "VSpring2"), ("VSpring3", "VSpring3"),
	("VSpring4", "VSpring4"), ("VSpring5", "VSpring5"), ("VSpring6", "VSpring6"),
])]
OLD_BOQ = {190: "2290225", 200: "2290226", 210: "2290227", 220: "2290228", 230: "2290229", 240: "2290222",
	250: "2290223", 260: "2290224", 270: "2290230", 280: "2290231", 290: "2290232", 300: "{springs}"}


def log(msg):
	print(f"[cfd_spring_costs] {msg}")


def identifier(label):
	return f"{label} (Spring)"


def execute():
	if not frappe.db.exists("BtbBundle", BUNDLE) or not frappe.db.exists("BtbFeature", SPRINGS_FEATURE):
		log("no Curtain Fire Dampers bundle on this site: nothing to do")
		return
	costs = spring_costs()
	cost_rows(costs)
	options()
	feature()
	actions()
	boq_rules()
	spring_type()
	drop_spring_columns()


def spring_costs():
	"""label and cost of each spring row, checked against ROWS (cost from the column while it still exists)."""
	has_cost = frappe.db.has_column(SPRING, "cost")
	fields = "name, custom_label" + (", cost" if has_cost else "")
	rows = {r.name: r for r in frappe.db.sql(f"select {fields} from `tab{SPRING}`", as_dict=True)}
	wrong = [f"{name}: {getattr(rows.get(name), 'custom_label', None)!r} (expected {label!r})"
		for name, label, _c, _r, _o in ROWS if (rows.get(name) or frappe._dict()).custom_label != label]
	if wrong:
		frappe.throw("cfd_spring_costs: spring rows differ from the plan, nothing changed: " + "; ".join(wrong))
	extra = sorted(set(rows) - {r[0] for r in ROWS})
	if extra:
		log(f"spring rows outside the plan, left as they are (no cost row): {', '.join(extra)}")
	missing_cost = [row for _s, _l, _c, row, _o in ROWS if not frappe.db.exists(COST, row)]
	if missing_cost and not has_cost:
		frappe.throw(f"cfd_spring_costs: FTOCVSSpring has no cost column any more but cost rows {missing_cost} are missing")
	return {name: (r.get("cost") or 0) for name, r in rows.items()}


def cost_rows(costs):
	unit = frappe.db.get_value("UOM", "Ea") or next(
		(u for u in frappe.get_all("UOM", pluck="name") if u.lower() == "ea"), None)
	if not unit:
		frappe.throw("cfd_spring_costs: UOM Ea is missing on this site")
	made, kept = [], 0
	for spring, label, code, row, _o in ROWS:
		ident = identifier(label)
		if frappe.db.exists(COST, row):
			have = frappe.db.get_value(COST, row, "boq_identifier")
			if have != ident:
				frappe.throw(f"cfd_spring_costs: {row} exists with BOQ identifier {have!r}, expected {ident!r}")
			kept += 1
			continue
		clash = frappe.db.get_value(COST, {"boq_identifier": ident})
		if clash:
			frappe.throw(f"cfd_spring_costs: BOQ identifier {ident!r} is already used by {clash}")
		doc = frappe.get_doc({"doctype": COST, "item_code": code, "product_name": label, "boq_identifier": ident,
			"category": "Springs", "unit": unit, "cost": costs[spring], "custom_cost_type": "Country Specific",
			"bundles": [{"bundle": BUNDLE}]})
		doc.insert(set_name=row, ignore_permissions=True)
		made.append(f"{label} {costs[spring]:g}")
	log(f"{len(made)} spring cost rows created ({', '.join(made)})" if made else "spring cost rows exist already")
	if made and kept:
		log(f"{kept} spring cost rows existed already")


def options():
	seq = frappe.db.sql("select coalesce(max(sequence), 0) from `tabBtbFeatureTypeItem` where feature_type=%s",
		COST_TYPE)[0][0]
	made = 0
	for _s, _l, _c, row, option in ROWS:
		if frappe.db.exists("BtbFeatureTypeItem", option):
			have = frappe.db.get_value("BtbFeatureTypeItem", option, ["feature_type", "object"])
			if tuple(have) != (COST_TYPE, row):
				frappe.throw(f"cfd_spring_costs: option {option} exists as {have}, expected ({COST_TYPE}, {row})")
			continue
		seq += 1
		frappe.get_doc({"doctype": "BtbFeatureTypeItem", "feature_type": COST_TYPE, "object": row,
			"price_editable": 0, "override_notes": 0, "sequence": seq}).insert(set_name=option, ignore_permissions=True)
		made += 1
	if made:
		log(f"{made} options added to {COST_TYPE} (CFD Cost)")


def feature():
	if frappe.db.exists("BtbFeature", FEATURE):
		have = frappe.db.get_value("BtbFeature", FEATURE, ["field", "structure"])
		if tuple(have) != ("springCost", STRUCTURE):
			frappe.throw(f"cfd_spring_costs: feature {FEATURE} exists as {have}")
		return
	if frappe.db.exists("BtbFeature", {"field": "springCost", "structure": STRUCTURE}):
		frappe.throw("cfd_spring_costs: CFD already has another springCost feature")
	seq = frappe.db.sql("select coalesce(max(sequence), 0) from `tabBtbFeature` where structure=%s", STRUCTURE)[0][0]
	frappe.get_doc({"doctype": "BtbFeature", "label": "Spring Cost", "field": "springCost", "control_type": "Dropdown",
		"structure": STRUCTURE, "sequence": seq + 1, "settings": "{}",
		"feature_types": [{"feature_type": COST_TYPE}]}).insert(set_name=FEATURE, ignore_permissions=True)
	log(f"feature {FEATURE} springCost added to CFD")


def actions():
	pick = frappe.db.get_value("BtbImplementationConstraintAction", PICK, ["implementation_constraint", "sequence",
		"type", "impact_fields"], as_dict=True)
	if not pick or (pick.implementation_constraint, pick.sequence, pick.type, pick.impact_fields) != (
			RULE, PICK_SEQ, "Include Value", "springs"):
		frappe.throw(f"cfd_spring_costs: action {PICK} is not the spring selection at {RULE}/{PICK_SEQ}: {pick}")

	if not frappe.db.exists("BtbImplementationConstraintAction", ACTION):
		frappe.get_doc({"doctype": "BtbImplementationConstraintAction", "active": 1, "result": 1,
			"type": "Include Value", "implementation_constraint": RULE, "impact_fields": "springCost",
			"formula": PICK_FORMULA, "constraint": PICK_FORMULA, "sequence": OLD_SEQ}).insert(
			set_name=ACTION, ignore_permissions=True)
		log(f"action {ACTION}: springCost = {PICK_FORMULA} at {RULE}/{OLD_SEQ}")

	cost = frappe.db.get_value("BtbImplementationConstraintAction", SPRINGS_COST,
		["implementation_constraint", "sequence", "formula", "constraint", "impact_fields"], as_dict=True)
	if not cost or cost.implementation_constraint != RULE or cost.impact_fields != "springsCost":
		frappe.throw(f"cfd_spring_costs: action {SPRINGS_COST} is not springsCost of rule {RULE}: {cost}")
	formula = cost.formula or ""
	if NEW_COST_READ not in formula:
		if formula.count(OLD_COST_READ) != 1:
			frappe.throw(f"cfd_spring_costs: action {SPRINGS_COST} does not read {OLD_COST_READ} once: {formula!r}")
		formula = formula.replace(OLD_COST_READ, NEW_COST_READ)
		frappe.db.set_value("BtbImplementationConstraintAction", SPRINGS_COST,
			{"formula": formula, "constraint": formula}, update_modified=False)
		log(f"action {SPRINGS_COST} springsCost reads {NEW_COST_READ}")
	if cost.sequence != NEW_SEQ:
		taken = frappe.db.get_value("BtbImplementationConstraintAction",
			{"implementation_constraint": RULE, "sequence": NEW_SEQ, "name": ("!=", SPRINGS_COST)})
		if taken:
			frappe.throw(f"cfd_spring_costs: sequence {NEW_SEQ} of rule {RULE} is taken by {taken}")
		frappe.db.set_value("BtbImplementationConstraintAction", SPRINGS_COST, "sequence", NEW_SEQ, update_modified=False)
		log(f"action {SPRINGS_COST} springsCost moved from sequence {cost.sequence} to {NEW_SEQ}")

	for name in (DISABLE, LOCK):
		fields = frappe.db.get_value("BtbImplementationConstraintAction", name, "impact_fields") or ""
		listed = [f.strip() for f in fields.split(",") if f.strip()]
		if "springs" not in listed:
			frappe.throw(f"cfd_spring_costs: action {name} does not list springs: {fields!r}")
		if "springCost" not in listed:
			frappe.db.set_value("BtbImplementationConstraintAction", name, "impact_fields",
				",".join(listed + ["springCost"]), update_modified=False)
			log(f"action {name}: springCost added to its fields")


def boq_rules():
	"""The 12 seeded spring rules -> one Sourced rule (sites that seeded CFD before this change)."""
	rules = frappe.get_all("BOQ Rule", {"product_family": "CFD"}, ["name", "sequence", "source_type",
		"identifier_literal", "identifier_template"])
	if not rules:
		log("CFD has no BOQ rules on this site (BOQ from boq_format.JSON): nothing to replace")
		return
	if any(r.source_type == "Sourced" and r.identifier_template == "{springs} (Spring)" for r in rules):
		log("CFD spring BOQ rule is Sourced already")
		return
	old = [r for r in rules if OLD_BOQ.get(r.sequence) and OLD_BOQ[r.sequence] == (r.identifier_literal or r.identifier_template)]
	if len(old) != len(OLD_BOQ):
		frappe.throw(f"cfd_spring_costs: expected the {len(OLD_BOQ)} CFD spring BOQ rules, found {len(old)} - "
			"they were edited; replace them by hand")
	# os.path.join keeps the capital file name (get_app_path lowercases its parts)
	with open(os.path.join(frappe.get_app_path("btb_cvs_support", "patches", "boq_rules"), "CFD.json")) as f:
		spec = next(r for r in json.load(f)["rules"] if r.get("identifier_template") == "{springs} (Spring)")
	for r in old:
		frappe.delete_doc("BOQ Rule", r.name, ignore_permissions=True, force=True)
	doc = frappe.new_doc("BOQ Rule")
	doc.product_family = "CFD"
	doc.active = 1
	for key in ("sequence", "source_type", "identifier_template", "identifier_literal", "description_template", "uom",
			"condition_logic", "filter_json", "aggregate", "notes"):
		if spec.get(key) is not None:
			doc.set(key, spec[key])
	for row in spec.get("conditions") or []:
		doc.append("conditions", row)
	for row in spec.get("dimensions") or []:
		doc.append("dimensions", row)
	doc.insert(ignore_permissions=True)
	log(f"{len(old)} CFD spring BOQ rules replaced by one Sourced rule ({doc.name})")


def spring_type():
	fields = frappe.db.get_value("BtbFeatureType", SPRING_TYPE, "additional_fields") or ""
	listed = [f.strip() for f in fields.split(",") if f.strip()]
	keep = [f for f in listed if f not in DROP_FIELDS]
	if keep != listed:
		frappe.db.set_value("BtbFeatureType", SPRING_TYPE, "additional_fields", ",".join(keep), update_modified=False)
		log(f"{SPRING_TYPE} additional fields: {','.join(keep)}")


def drop_spring_columns():
	"""Last: ALTER TABLE commits, so everything above is in place before the columns go."""
	for ps in frappe.get_all("Property Setter", {"doc_type": SPRING, "field_name": ["in", DROP_FIELDS]}, pluck="name"):
		frappe.delete_doc("Property Setter", ps, ignore_permissions=True, force=True)
	dropped = [c for c in DROP_FIELDS if frappe.db.has_column(SPRING, c)]
	for column in dropped:
		frappe.db.sql_ddl(f"alter table `tab{SPRING}` drop column `{column}`")
	if dropped:
		log(f"FTOCVSSpring columns dropped: {', '.join(dropped)}")
	frappe.clear_cache(doctype=SPRING)
