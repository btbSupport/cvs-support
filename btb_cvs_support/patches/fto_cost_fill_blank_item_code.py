"""Fills a blank FTOCountryWiseCost item code with the row's product name.

Pricing parameters (GI, Profit, Cost per Hour, wastage, minutes...) were loaded
with no item code in some bundles and with their name as the code in others,
so the same parameter looked different across bundles. Using the product name
gives every row a code and makes those rows compare equal.

Rows with no product name either are left as they are. Each row is saved as a
document so the change lands in its Version history; link checks are skipped
so an unrelated stale link on the row cannot block it. Idempotent - a second
run finds nothing blank.
"""

import frappe


def execute():
	rows = frappe.get_all("FTOCountryWiseCost",
						  or_filters=[["item_code", "is", "not set"], ["item_code", "=", ""]],
						  fields=["name", "item_code", "product_name"])
	filled, direct, failed = 0, [], []
	for row in rows:
		name_text = (row.product_name or "").strip()
		if((row.item_code or "").strip() or not name_text): continue
		try:
			doc = frappe.get_doc("FTOCountryWiseCost", row.name)
			doc.item_code = name_text
			doc.flags.ignore_links = True
			doc.flags.ignore_permissions = True
			doc.save()
			filled += 1
		except frappe.ValidationError:
			# the row fails validation for a reason unrelated to its item code
			# (e.g. a Cost Type outside the field's options); write the code
			# alone rather than leave it blank or rewrite the other field
			frappe.clear_last_message()
			frappe.db.set_value("FTOCountryWiseCost", row.name, "item_code", name_text)
			direct.append(row.name)
		except Exception as e:
			failed.append((row.name, name_text, str(e)))

	print(f"FTOCountryWiseCost: {filled + len(direct)} blank item code(s) filled from product name")
	if(direct):
		print(f"  {len(direct)} written without re-validating the row (row fails validation elsewhere): "
			  + ", ".join(direct))
	for name, text, error in failed:
		print(f"  NOT FILLED {name} {text!r}: {error}")
