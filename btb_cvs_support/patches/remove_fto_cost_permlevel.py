"""The FTO cost fields were briefly moved to permlevel 1, but configuration needs every OneCPQ user
to read them, so they are back at level 0. Drop the level-1 rules an earlier version of this
change added to sites with customised FTO permissions."""

import frappe

COST_DOCTYPES = ("FTOCountryWiseCost", "FTOCVSSpring", "FTOCVSActuator")


def execute():
	frappe.db.delete("Custom DocPerm", {"parent": ("in", COST_DOCTYPES), "permlevel": 1})
	frappe.clear_cache()
