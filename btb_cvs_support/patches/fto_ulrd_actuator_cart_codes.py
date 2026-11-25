"""ULRD (BUN4) carts: stored actuator item codes in the new code-model form (decided 2026-11-25).

`actuatorItemCode` is a text feature filled from the chosen actuator's item code
(OBJECTATTRIBUTEF(actuator,'item_code')). fto_ulrd_actuator_country_cost turns those item codes into the
code-model form ('229101' -> '229101-MS4604F1210/B'), so new carts store that form while existing carts keep
the plain code. The BOQ names the actuator by this value, so both forms would need handling everywhere.
This patch rewrites the stored plain codes to the code-model form, taken from FTOCVSActuator.

Only values that are exactly a plain code with one code-model actuator change. Safe to run again.
"""

from collections import defaultdict

import frappe

BUNDLE = "BUN4"
FIELD = "actuatorItemCode"


def log(msg):
	print(f"[fto_ulrd_actuator_cart_codes] {msg}")


def execute():
	features = frappe.db.sql("""select f.name from `tabBtbFeature` f join `tabBtbStructure` s on s.name = f.structure
		where s.bundle = %s and f.field = %s""", (BUNDLE, FIELD), pluck=True)
	if not features:
		log(f"no {FIELD} feature in {BUNDLE}: nothing to do")
		return

	full = defaultdict(set)
	for code in frappe.get_all("FTOCVSActuator", filters={"item_code": ["like", "%-%"]}, pluck="item_code"):
		full[code.split("-", 1)[0].strip()].add(code)
	ambiguous = sorted(p for p, codes in full.items() if len(codes) > 1)
	mapping = {p: next(iter(codes)) for p, codes in full.items() if len(codes) == 1}

	changed, unknown = defaultdict(int), defaultdict(int)
	for name, value in frappe.db.sql("""select name, value from `tabBtbCartItemFeature`
			where feature in %s and ifnull(value, '') != ''""", (features,)):
		value = value.strip()
		if "-" in value:
			continue  # already the code-model form
		if value in mapping:
			frappe.db.set_value("BtbCartItemFeature", name, "value", mapping[value], update_modified=False)
			changed[value] += 1
		else:
			unknown[value] += 1

	log(f"{sum(changed.values())} stored actuator codes rewritten: "
		+ (", ".join(f"{p} -> {mapping[p]} x{n}" for p, n in sorted(changed.items())) or "-"))
	if unknown:
		log("left as they are (no single code-model actuator): " + ", ".join(f"{v} x{n}" for v, n in sorted(unknown.items())))
	if ambiguous:
		log("plain codes with more than one code-model actuator: " + ", ".join(ambiguous))
