"""Replaces the Cost Type 'Country Specific-Currency' on FTOCountryWiseCost with
'Country Specific'.

'Country Specific-Currency' is not one of the field's options (Country Specific,
% of UAE), so every row carrying it failed validation and could not be saved
from the form. Nothing reads the value - no feature type, constraint or code -
so the rows simply take the listed option they mean.

Runs before fto_cost_fill_blank_item_code so those rows can be saved normally
there. Each row is saved as a document so the change lands in its Version
history. Idempotent.
"""

import frappe

OLD, NEW = "Country Specific-Currency", "Country Specific"


def execute():
	names = frappe.get_all("FTOCountryWiseCost", filters={"custom_cost_type": OLD}, pluck="name")
	changed, failed = 0, []
	for name in names:
		try:
			doc = frappe.get_doc("FTOCountryWiseCost", name)
			doc.custom_cost_type = NEW
			doc.flags.ignore_links = True
			doc.flags.ignore_permissions = True
			doc.save()
			changed += 1
		except Exception as e:
			failed.append((name, str(e)))

	print(f"FTOCountryWiseCost: Cost Type set to {NEW!r} on {changed} row(s)")
	for name, error in failed:
		print(f"  NOT CHANGED {name}: {error}")
