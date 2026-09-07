"""Seeds the Access Door rule set, replacing 104 enumerated rows in
boq_format.JSON with 13 `BOQ Rule` records.

Two things are seeded:

  1. `boq_identifier` on the 19 FTOCountryWiseCost rows the AD BOQ names. Each
     is set to the row's own product_name, which is already what the JSON spells
     as its item code, so the sourced lines resolve unchanged.

  2. The 13 rules themselves, sequenced to reproduce the JSON's emit order:
     doors, frames, round fittings, safety wire, handles, cam locks, insulation,
     hinges, gaskets.

Idempotent: it does nothing if AD rules already exist, so a re-migrate never
overwrites edits made in the UI.
"""

import json

import frappe

FAMILY = "AD"

# emit order of materials in boq_format.JSON - neither alphabetical nor
# derivable, so it has to be declared to keep the printed order unchanged
MATERIALS = "GI,AL,AZ,SS304L,SS316L"

# product_name on FTOCountryWiseCost, which is also the identifier the rules
# resolve by, and (for 14 of the 19) the item code the BOQ prints today
IDENTIFIERS = [
	"Safety Wire",
	"GI & AZ Handle Cost (per PC)",
	"SS Handle Cost (per PC)",
	"AL Handle Cost (per PC)",
	"GI & AZ Cam Lock Cost (per PC)",
	"SS Cam Lock Cost (per PC)",
	"AL Cam Lock Cost (per PC)",
	"Rockwool 1 Inch (25mm)",
	"Rockwool 2 Inch (50mm)",
	"Fiberglass 1 Inch (25mm)",
	"Fiberglass 2 Inch (50mm)",
	"SS Standard Hinge",
	"SS Continuous Hinge",
	"Brass Standard Hinge",
	"Brass Continuous Hinge",
	"AL Standard Hinge",
	"AL Continuous Hinge",
	"Neoprene Gasket",
	"Polyurethane Gasket",
]


def aggregate(*fields):
	"""The aggregate shape the BOQ engine already consumes, copied from the
	JSON rows this rule replaces."""
	return json.dumps({"logic": "SUM",
					   "aggregate": [{"logic": "MUL", "fields": list(fields)}]})


def rule(sequence, source_type, identifier, uom, dimensions, fields,
		 conditions=None, logic="and", literal=False, notes=None):
	return {
		"sequence": sequence,
		"source_type": source_type,
		"identifier_literal" if literal else "identifier_template": identifier,
		"uom": uom,
		"condition_logic": logic,
		"conditions": conditions or [],
		"dimensions": dimensions,
		"aggregate": aggregate(*fields),
		"notes": notes,
	}


def material_group(sequence, identifier, values, fields):
	"""Handles and cam locks are named for a material *group* - "GI & AZ" is not
	a value any feature holds - so the identifier is literal and the group is
	expressed as an or-guard."""
	logic = "or" if len(values) > 1 else "and"
	conditions = [{"field": "material", "operator": "eq", "value": v} for v in values]
	return rule(sequence, "Sourced", identifier, None, [], fields,
				conditions=conditions, logic=logic, literal=True)


def ad_rules():
	rules = [
		rule(10, "Templated", "{material} Door {doorThickness}", "kg",
			 [{"field": "material", "value_format": "As is", "value_order": MATERIALS},
			  {"field": "doorThickness", "value_format": "Trim trailing zero"}],
			 ["doorWeight", "cartQty"]),
		rule(20, "Templated", "{material} Frame {frameThickness}", "kg",
			 [{"field": "material", "value_format": "As is", "value_order": MATERIALS},
			  {"field": "frameThickness", "value_format": "Trim trailing zero"}],
			 ["frameWeight", "cartQty"]),
		rule(30, "Templated", "{material} Round Fitting 0.8", "kg",
			 [{"field": "material", "value_format": "As is", "value_order": MATERIALS}],
			 ["roundFittingWeight", "cartQty"]),
		rule(40, "Sourced", "Safety Wire", None, [], ["safetyWire", "cartQty"],
			 literal=True),

		material_group(50, "GI & AZ Handle Cost (per PC)", ["GI", "AZ"], ["cartQty"]),
		material_group(51, "SS Handle Cost (per PC)", ["SS304L", "SS316L"], ["cartQty"]),
		material_group(52, "AL Handle Cost (per PC)", ["AL"], ["cartQty"]),

		material_group(60, "GI & AZ Cam Lock Cost (per PC)", ["GI", "AZ"],
					   ["camLockQty", "cartQty"]),
		material_group(61, "SS Cam Lock Cost (per PC)", ["SS304L", "SS316L"],
					   ["camLockQty", "cartQty"]),
		material_group(62, "AL Cam Lock Cost (per PC)", ["AL"],
					   ["camLockQty", "cartQty"]),

		rule(70, "Sourced", "{insulation} {doorDepthSelect}", None,
			 [{"field": "insulation", "value_format": "As is",
			   "value_order": "Rockwool,Fiberglass"},
			  {"field": "doorDepthSelect", "value_format": "As is",
			   "value_order": "1 Inch (25mm),2 Inch (50mm)"}],
			 ["insulationArea", "cartQty"],
			 notes="Insulation 'Packless' has no cost row, so it emits no line - "
				   "which is what the JSON did by having no Packless row."),
		rule(80, "Sourced", "{hingeMaterial} {hingeType} Hinge", None,
			 [{"field": "hingeMaterial", "value_format": "As is",
			   "value_order": "SS,Brass,AL"},
			  {"field": "hingeType", "value_format": "As is",
			   "value_order": "Standard,Continuous"}],
			 ["hingeQty", "cartQty"],
			 notes="One rule for all six hinges: UOM differs per variant "
				   "(Standard is Ea, Continuous is m) and comes from the cost "
				   "row. hingeType 'NA' resolves to no row and emits nothing."),
		rule(90, "Sourced", "{gasket} Gasket", None,
			 [{"field": "gasket", "value_format": "As is",
			   "value_order": "Neoprene,Polyurethane"}],
			 ["safetyWire", "cartQty"],
			 notes="Quantity field is safetyWire, copied verbatim from "
				   "boq_format.JSON. It looks like a copy-paste error - a gasket "
				   "length in metres measured off the safety wire count - but it "
				   "is current behaviour and changing it is a separate decision."),
	]
	return rules


def seed_identifiers():
	set_count, skipped = 0, []
	for identifier in IDENTIFIERS:
		rows = frappe.get_all("FTOCountryWiseCost",
							  filters={"product_name": identifier},
							  fields=["name", "boq_identifier"])
		if(len(rows) != 1):
			skipped.append((identifier, f"{len(rows)} rows carry this product name"))
			continue
		if((rows[0].boq_identifier or "").strip()):
			continue
		frappe.db.set_value("FTOCountryWiseCost", rows[0].name,
							"boq_identifier", identifier, update_modified=False)
		set_count += 1
	return set_count, skipped


def seed_rules():
	for spec in ad_rules():
		doc = frappe.new_doc("BOQ Rule")
		doc.product_family = FAMILY
		doc.active = 1
		for key, value in spec.items():
			if(key in ("conditions", "dimensions")):
				for row in value:
					doc.append(key, row)
			elif(value is not None):
				doc.set(key, value)
		doc.insert(ignore_permissions=True)


def execute():
	if(frappe.db.count("BOQ Rule", {"product_family": FAMILY})):
		print(f"BOQ rules for {FAMILY} already exist - nothing seeded")
		return

	set_count, skipped = seed_identifiers()
	print(f"BOQ Identifier set on {set_count} FTOCountryWiseCost row(s)")
	for identifier, reason in skipped:
		print(f"  SKIPPED {identifier!r}: {reason}")

	seed_rules()
	print(f"seeded {len(ad_rules())} BOQ Rule record(s) for {FAMILY}")
