"""Seeds the BOQ Rules of one product family from patches/boq_rules/<FAMILY>.json (Phase 2, 2026-11-25).

The rule files are made by api/_boq_convert.py from the family's block of boq_format.JSON and checked to
reproduce it (same lines, quantities and order on the carts of all four sites). A family whose rules exist
switches from the JSON to its rules (api/boq.py); unticking Active on its rules switches it back while the
JSON block is still shipped.

Seeded once: a family that already has rules on this site keeps them, so a re-migrate never overwrites
edits made in the UI (decision Q7). Each family has its own patch line (seed_boq_rules_<family>).
"""

import json
import os

import frappe

DATA = ("patches", "boq_rules")
SPEC_KEYS = ("sequence", "source_type", "identifier_template", "identifier_literal", "description_template", "uom",
	"condition_logic", "filter_json", "aggregate", "notes")


def log(family, msg):
	print(f"[seed_boq_rules {family}] {msg}")


def seed(family):
	if frappe.db.count("BOQ Rule", {"product_family": family}):
		log(family, "BOQ rules for this family already exist on this site - nothing seeded")
		return
	# os.path.join, not get_app_path(..., name): get_app_path lowercases every part, and the files are
	# named in capitals (ULRD.json), which a case-sensitive filesystem does not find as ulrd.json.
	with open(os.path.join(frappe.get_app_path("btb_cvs_support", *DATA), f"{family}.json")) as f:
		rules = json.load(f)["rules"]
	uoms = {u.lower(): u for u in frappe.get_all("UOM", pluck="name")}

	missing = sorted({r["uom"] for r in rules if r.get("uom") and r["uom"].lower() not in uoms})
	if missing:
		frappe.throw(f"seed_boq_rules {family}: UOM {', '.join(missing)} missing on this site")
	unresolved = [r["identifier_literal"] for r in rules if r["source_type"] == "Sourced"
		and r.get("identifier_literal") and not frappe.db.exists("FTOCountryWiseCost",
			{"boq_identifier": r["identifier_literal"]})]
	if unresolved:
		frappe.throw(f"seed_boq_rules {family}: no cost row carries the BOQ identifier "
			+ ", ".join(repr(i) for i in unresolved))

	for spec in rules:
		doc = frappe.new_doc("BOQ Rule")
		doc.product_family = family
		doc.active = 1
		for key in SPEC_KEYS:
			if spec.get(key) is not None:
				doc.set(key, spec[key])
		if doc.uom:
			doc.uom = uoms[doc.uom.lower()]
		for row in spec.get("conditions") or []:
			doc.append("conditions", row)
		for row in spec.get("dimensions") or []:
			doc.append("dimensions", row)
		doc.insert(ignore_permissions=True)
	log(family, f"{len(rules)} BOQ rules seeded; {family} BOQs now come from BOQ Rule")
