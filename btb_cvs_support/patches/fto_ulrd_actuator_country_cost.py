"""ULRD (BUN4) actuators: price from the country-wise cost table instead of FTOCVSActuator.ulrd_valuation_rate.

Until now BUN4 priced an actuator as `ulrd_valuation_rate + 15`. That rate is one number on every site, whatever
the currency, so Egypt costed ULRD actuators at about 1/25 of their EGP price. The country-wise cost table
already holds one actuator row per model (code-model item code, e.g. '229090-FSLF230-S US'), read by the
VCD Actuator Cost feature type (FT139, data_text_field item_code).

What this patch does, matched by content so it works on every site, and changes only what is still in its old
state (safe to run twice):
1. FTOCVSActuator.item_code := the code-model of the actuator's cost row (matched by unique_id).
2. BUN4 gets a hidden dropdown feature `actuatorCostLookup` (VCD Actuator Cost) in its Factors section.
3. The BUN4 actuator rule (the one that includes `actuator`) gets an Include Value action that selects the cost
   row whose item code equals the actuator's item code.
4. The actuatorCost action reads the cost from that lookup only; the fixed +15 is dropped (decided 2026-11-23).
5. The new field joins BUN4's lock list.

Step 4 only runs when every actuator resolves to a cost row, so ULRD never falls back to a 0 price.
ulrd_valuation_rate itself is left in place; it goes with the main cost cleanup.
Existing saved quotes are not touched.
"""

import re

import frappe

BUNDLE_LABEL = "UL True Round Dampers"
COST_FEATURE_TYPE = "VCD Actuator Cost"  # FT139 on all sites
NEW_FIELD = "actuatorCostLookup"
FEATURE_NAME = "FTR-ULRD-ACTCOST"  # fixed name, identical on all sites
ACTION_NAME = "fto-ulrd-actcost-lookup"
NEW_COST_EXPR = f"CFLOAT(OBJECTATTRIBUTEF({NEW_FIELD},'cost'))"
# old rate + 15, or a half-switched formula that still adds 15
OLD_COST = re.compile(r"CFLOAT\(\s*OBJECTATTRIBUTEF\(\s*(actuator\s*,\s*'ulrd_valuation_rate'|"
	+ NEW_FIELD + r"\s*,\s*'cost')\s*\)\s*\)(\s*\+\s*15)?")

# FTOCVSActuator.unique_id -> item code of its cost row (customer reply 2026-11-23: code-model everywhere)
ACTUATOR_CODES = {
	"Belimo24Vw/o Aux175lbin-20Nm": "2290503-FSAFB24-SR",
	"Belimo24V2 Aux175lbin-20Nm": "2290468-FSAFB24-SR-S",
	"Belimo230V2 Aux30lbin-3.5Nm": "229090-FSLF230-S US",
	"Belimo230Vw/o Aux30lbin-3.5Nm": "2290263-FSLF230 US",
	"Belimo24V2 Aux30lbin-3.5Nm": "229091-FSLF24-S US",
	"Belimo24Vw/o Aux30lbin-3.5Nm": "2290283-FSLF24 US",
	"Belimo230V2 Aux80lbin-9Nm": "229089-FSNF230-S US",
	"Belimo230Vw/o Aux80lbin-9Nm": "2290280-FSNF230 US",
	"Belimo24V2 Aux80lbin-9Nm": "229088-FSNF24-S US",
	"Belimo24Vw/o Aux80lbin-9Nm": "2290281-FSNF24 US",
	"Belimo230V2 Aux18lbin-2Nm": "229092-FSTF230-S US",
	"Belimo230Vw/o Aux18lbin-2Nm": "2290501-FSTF230 US",
	"Belimo24V2 Aux18lbin-2Nm": "229093-FSTF24-S US",
	"Belimo24Vw/o Aux18lbin-2Nm": "2290502-FSTF24 US",
	"Honeywell230Vw/o Aux30lbin-3.5Nm": "229100-MS4604F1010/B",
	"Honeywell230V2 Aux30lbin-3.5Nm": "229101-MS4604F1210/B",
	"Honeywell230Vw/o Aux80lbin-9Nm": "229106-MS4609F1010/B",
	"Honeywell230V2 Aux80lbin-9Nm": "229107-MS4609F1210/B",
	"Honeywell230Vw/o Aux175lbin-20Nm": "229111-MS4620F1005/B",
	"Honeywell230V2 Aux175lbin-20Nm": "229110-MS4620F1203/B",
	"Honeywell24Vw/o Aux30lbin-3.5Nm": "229102-MS8104F1010/B",
	"Honeywell24V2 Aux30lbin-3.5Nm": "229103-MS8104F1210/B",
	"Honeywell24Vw/o Aux80lbin-9Nm": "229104-MS8109F1010/B",
	"Honeywell24V2 Aux80lbin-9Nm": "229105-MS8109F1210/B",
	"Honeywell24Vw/o Aux175lbin-20Nm": "229108-MS8120F1002/B",
	"Honeywell24V2 Aux175lbin-20Nm": "229109-MS8120F1200/B",
}


def log(msg):
	print(f"[fto_ulrd_actuator_country_cost] {msg}")


def execute():
	bundle = frappe.db.get_value("BtbBundle", {"label": BUNDLE_LABEL}, "name")
	cost_ft = frappe.db.get_value("BtbFeatureType",
		{"label": COST_FEATURE_TYPE, "object_type": "FTOCountryWiseCost"}, "name")
	if not bundle or not cost_ft:
		log(f"skipped: bundle {BUNDLE_LABEL!r} or feature type {COST_FEATURE_TYPE!r} not found")
		return

	resolved = set_actuator_codes(cost_ft)
	feature_ready = ensure_lookup_feature(bundle, cost_ft)
	rule = ensure_lookup_action(bundle)
	add_to_lock_list(bundle)
	total = frappe.db.count("FTOCVSActuator")
	if feature_ready and rule and resolved == total:
		switch_cost_formula(bundle)
	else:
		log(f"actuatorCost NOT switched: {resolved}/{total} actuators resolved, feature={feature_ready}, rule={rule}")


def set_actuator_codes(cost_ft):
	"""Step 1. Returns how many actuators resolve to an FT139 option."""
	options = {frappe.db.get_value("FTOCountryWiseCost", o, "item_code")
		for o in frappe.get_all("BtbFeatureTypeItem", {"feature_type": cost_ft}, pluck="object") if o}
	resolved = 0
	for a in frappe.get_all("FTOCVSActuator", fields=["name", "unique_id", "item_code"]):
		target = ACTUATOR_CODES.get(a.unique_id)
		if not target:
			log(f"no code known for actuator {a.name} ({a.unique_id})")
			continue
		if target not in options:
			log(f"actuator {a.name}: no {COST_FEATURE_TYPE} option with item code {target!r}")
			continue
		resolved += 1
		if a.item_code != target:
			frappe.db.set_value("FTOCVSActuator", a.name, "item_code", target, update_modified=False)
			log(f"actuator {a.name}: item_code {a.item_code!r} -> {target!r}")
	return resolved


def ensure_lookup_feature(bundle, cost_ft):
	"""Step 2: hidden dropdown in BUN4's Factors section, next to `actuator`."""
	actuator = frappe.db.sql("""select f.name, f.structure from `tabBtbFeature` f
		join `tabBtbStructure` s on s.name = f.structure
		where s.bundle = %s and f.field = 'actuator'""", bundle, as_dict=True)
	if not actuator:
		log("BUN4 feature 'actuator' not found")
		return False
	structure = actuator[0].structure
	exists = frappe.db.sql("""select f.name from `tabBtbFeature` f join `tabBtbStructure` s on s.name = f.structure
		where s.bundle = %s and f.field = %s""", (bundle, NEW_FIELD))
	if exists:
		return True
	if frappe.db.exists("BtbFeature", FEATURE_NAME):
		log(f"name {FEATURE_NAME} already used by another feature - stopped")
		return False
	seq = frappe.db.sql("select max(sequence) from `tabBtbFeature` where structure = %s", structure)[0][0] or 0
	doc = frappe.get_doc({
		"doctype": "BtbFeature",
		"structure": structure,
		"field": NEW_FIELD,
		"label": "Actuator Cost Lookup",
		"control_type": "Dropdown",
		"sequence": int(seq) + 1,
		"settings": '{"displayFormat":"1.0-2"}',
		"feature_types": [{"feature_type": cost_ft}],
	})
	doc.insert(set_name=FEATURE_NAME, ignore_permissions=True)
	log(f"feature {FEATURE_NAME} ({NEW_FIELD}) added to structure {structure}")
	return True


def ensure_lookup_action(bundle):
	"""Step 3: Include Value actuatorCostLookup <- actuator item code, in the rule that includes `actuator`."""
	rule = frappe.db.sql("""select a.implementation_constraint, a.sequence from `tabBtbImplementationConstraintAction` a
		join `tabBtbImplementationConstraint` c on c.name = a.implementation_constraint
		where c.bundle = %s and a.type = 'Include Value' and a.impact_fields = 'actuator'
		and a.formula like %s""", (bundle, "%CONCAT(SELECTEDVALUE(actuatorBrand)%"), as_dict=True)
	if len(rule) != 1:
		log(f"BUN4 'Include Value actuator' rule: expected 1, found {len(rule)}")
		return None
	ic = rule[0].implementation_constraint
	if frappe.db.exists("BtbImplementationConstraintAction",
			{"implementation_constraint": ic, "impact_fields": NEW_FIELD, "type": "Include Value"}):
		return ic
	seq = frappe.db.sql("select max(sequence) from `tabBtbImplementationConstraintAction` "
		"where implementation_constraint = %s", ic)[0][0] or 0
	expr = "OBJECTATTRIBUTEF(actuator,'item_code')"
	doc = frappe.get_doc({
		"doctype": "BtbImplementationConstraintAction",
		"implementation_constraint": ic,
		"type": "Include Value",
		"active": 1,
		"result": 1,
		"impact_fields": NEW_FIELD,
		"sequence": int(seq) + 1,
		"formula": expr,
		"constraint": expr,
		"description": "Country-wise actuator cost row (same item code as the selected actuator)",
	})
	doc.insert(set_name=ACTION_NAME, ignore_permissions=True)
	log(f"action {ACTION_NAME} added to rule {ic}")
	return ic


def add_to_lock_list(bundle):
	"""Step 5. 'Lock Field' is not yet a valid option of the action type, so write the field directly."""
	for a in frappe.db.sql("""select a.name, a.impact_fields from `tabBtbImplementationConstraintAction` a
			join `tabBtbImplementationConstraint` c on c.name = a.implementation_constraint
			where c.bundle = %s and a.type = 'Lock Field'""", bundle, as_dict=True):
		fields = [f.strip() for f in (a.impact_fields or "").split(",") if f.strip()]
		if "actuator" in fields and NEW_FIELD not in fields:
			fields.append(NEW_FIELD)
			frappe.db.set_value("BtbImplementationConstraintAction", a.name, "impact_fields", ",".join(fields),
				update_modified=False)
			log(f"lock action {a.name}: {NEW_FIELD} added")


def switch_cost_formula(bundle):
	"""Step 4: actuatorCost reads the country-wise cost (stored formula and readable text)."""
	rows = frappe.db.sql("""select a.name, a.formula, a.`constraint` from `tabBtbImplementationConstraintAction` a
		join `tabBtbImplementationConstraint` c on c.name = a.implementation_constraint
		where c.bundle = %s and a.type = 'Change Value' and a.impact_fields = 'actuatorCost'""", bundle, as_dict=True)
	for a in rows:
		formula = OLD_COST.sub(NEW_COST_EXPR, a.formula or "")
		readable = OLD_COST.sub(NEW_COST_EXPR, a.constraint or "")
		if formula == (a.formula or "") and readable == (a.constraint or ""):
			continue
		frappe.db.set_value("BtbImplementationConstraintAction", a.name, {"formula": formula, "constraint": readable},
			update_modified=False)
		log(f"action {a.name}: actuatorCost now reads {NEW_COST_EXPR} (no +15)")
