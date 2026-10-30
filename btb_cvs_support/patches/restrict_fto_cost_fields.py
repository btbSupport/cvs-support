"""FTO cost fields (FTOCountryWiseCost.cost, FTOCVSSpring.cost, FTOCVSActuator.ulrd_valuation_rate)
moved to permlevel 1 so only OneCPQ Admin (and Administrator) see them in the desk, exports, prints
and the REST API. The doctypes ship that rule, but a site with customised FTO permissions reads
Custom DocPerm instead, so add it there too. Bundle setups and BOQ read these tables with plain
SQL, which permissions don't touch."""

import frappe
from frappe.permissions import add_permission, update_permission_property

COST_DOCTYPES = ("FTOCountryWiseCost", "FTOCVSSpring", "FTOCVSActuator")
ROLE = "OneCPQ Admin"


def execute():
	if not frappe.db.exists("Role", ROLE):
		return
	for doctype in COST_DOCTYPES:
		if not frappe.db.exists("Custom DocPerm", {"parent": doctype}):
			continue  # standard permissions apply, and the doctype ships the rule
		add_permission(doctype, ROLE, permlevel=1)
		update_permission_property(doctype, ROLE, 1, "write", 1)
	frappe.clear_cache()
