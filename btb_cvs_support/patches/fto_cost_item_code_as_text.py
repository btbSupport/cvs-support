"""Turns FTOCountryWiseCost item codes that were imported as formatted numbers
back into the plain codes they are: 2,230,101.00 -> 2230101.

item_code is a Data field, but a spreadsheet import with the code column
formatted as a number stored the display text - thousands separators and all.
Such a code matches nothing that spells it plainly (the Item master,
boq_format.JSON, the same item in another bundle), and Feature Types labelled
by item_code show it to configurator users in that form.

Only values that are entirely a formatted whole number change. Codes such as
'2290128/2290129', 'SS304L' or 'Hourly Cost' are left alone.

Each row is saved as a document so the change lands in its Version history.
Link checks are skipped: a stale UOM or bundle link elsewhere on the row is not
this patch's business and must not block the code fix. Idempotent - a second
run finds nothing to convert.
"""

import re

import frappe

FORMATTED = re.compile(r"^\d{1,3}(,\d{3})+\.0+$|^\d{1,3}\.0+$")


def plain(code: str) -> str:
	return code.replace(",", "").split(".")[0]


def execute():
	rows = frappe.get_all("FTOCountryWiseCost",
						  filters={"item_code": ("like", "%.0%")},
						  fields=["name", "item_code"])
	converted, failed = 0, []
	for row in rows:
		current = (row.item_code or "").strip()
		if(not FORMATTED.match(current)): continue
		try:
			doc = frappe.get_doc("FTOCountryWiseCost", row.name)
			doc.item_code = plain(current)
			doc.flags.ignore_links = True
			doc.flags.ignore_permissions = True
			doc.save()
			converted += 1
		except Exception as e:
			failed.append((row.name, current, str(e)))

	print(f"FTOCountryWiseCost: {converted} item code(s) converted to plain text codes")
	for name, code, error in failed:
		print(f"  NOT CONVERTED {name} {code!r}: {error}")
