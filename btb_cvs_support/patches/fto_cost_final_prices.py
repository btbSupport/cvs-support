"""Set the final costs the customer gave per site after the cost cleanup (2026-11-25).

fto_cost_cleanup merges rows whose costs could differ between bundles ('BUN5=4.03 / BUN8=4.38').
The customer answered with one final cost per row and site, and updated some material prices
(fto_cost_final_prices.json). Only the listed rows change; every other row keeps the site's cost.

The site's country comes from site_config "cvs_country", else from the site name; a site that matches
neither stops the migrate instead of taking another country's prices. A listed row that does not exist
stops it too (the cleanup must have run). Safe to run again: a second run finds the costs set already.
"""

import json

import frappe

COST = "FTOCountryWiseCost"
DATA = ("patches", "fto_cost_final_prices.json")
SITE_COUNTRY = {"cvsuae": "UAE", "cvsqatar": "Qatar", "cvsksa": "KSA", "badregypt": "Egypt"}


def log(msg):
	print(f"[fto_cost_final_prices] {msg}")


def execute():
	with open(frappe.get_app_path("btb_cvs_support", *DATA)) as f:
		costs = json.load(f)["costs"]
	country = site_country()
	if country not in costs:
		frappe.throw(f"fto_cost_final_prices: no final costs for country {country!r} (cvs_country must be one of "
			f"{', '.join(costs)}).")
	wanted = costs[country]

	current = {r.name: r.cost for r in frappe.get_all(COST, filters={"name": ["in", list(wanted)]}, fields=["name", "cost"])}
	missing = sorted(set(wanted) - set(current))
	if missing:
		frappe.throw(f"fto_cost_final_prices: cost rows not found on this site: {', '.join(missing)}. "
			"fto_cost_cleanup must run first.")

	changed = 0
	for name, cost in wanted.items():
		if abs((current[name] or 0) - cost) < 1e-9:
			continue
		frappe.db.set_value(COST, name, "cost", cost)
		log(f"{name}: {current[name]} -> {cost}")
		changed += 1
	log(f"{country}: {len(wanted)} final costs, {changed} changed")


def site_country():
	if frappe.conf.get("cvs_country"):
		return frappe.conf.get("cvs_country")
	site = frappe.local.site or ""
	country = next((c for p, c in SITE_COUNTRY.items() if site.startswith(p)), None)
	if not country:
		frappe.throw(f"fto_cost_final_prices: cannot tell the country of site {site!r}. Set \"cvs_country\" "
			"(UAE, Qatar, KSA or Egypt) in its site_config.json and migrate again.")
	return country
