"""The FRAD product item SKU41 gets item code FRAD (found on the test server, 2026-11-26).

add_fire_rated_access_doors created SKU41 under its fixed name, and the site's item naming copied that name into
the item code: SKU41 had item code SKU41 instead of FRAD. Quotation Format, BOQ and Production Sheet find a cart's
product family by the item code (like SKU40 = AD), so all three failed for FRAD quotes (KeyError 'SKU41').

Only the Item's item_code field changes; carts and quotation lines link the item by its name SKU41, which stays.
The patch changes nothing where SKU41 already has FRAD, and stops if SKU41 is not the FRAD item or another item
already uses the code FRAD. Safe to run again.
"""

import frappe

ITEM, CODE = "SKU41", "FRAD"


def log(msg):
	print(f"[fix_frad_item_code] {msg}")


def execute():
	item = frappe.db.get_value("Item", ITEM, ["item_code", "item_name"], as_dict=True)
	if not item:
		log(f"no item {ITEM}: nothing to do")
		return
	if item.item_code == CODE:
		log(f"{ITEM} already has item code {CODE}: nothing to do")
		return
	if item.item_code != ITEM or item.item_name != "Fire Rated Access Doors":
		frappe.throw(f"fix_frad_item_code: {ITEM} is {item.item_code!r} / {item.item_name!r}, not the FRAD item "
					 "the release created - check it by hand")
	other = frappe.db.get_value("Item", {"item_code": CODE, "name": ("!=", ITEM)})
	if other:
		frappe.throw(f"fix_frad_item_code: item {other} already has item code {CODE}")
	frappe.db.set_value("Item", ITEM, "item_code", CODE, update_modified=False)
	log(f"{ITEM}: item code {ITEM} -> {CODE}")
