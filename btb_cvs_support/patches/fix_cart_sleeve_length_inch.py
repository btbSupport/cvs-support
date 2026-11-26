"""Carts that stored the word 'Inch' as sleeve length (decided 2026-11-26).

Between 30 Jun and 11 Jul 2025 the configurator action that fills `sleeveLength` from `sleeveSelection`
('16 Inch 406mm') took the second word of the option text instead of the third, so those carts store
sleeveLength = 'Inch' (UAE 115, Qatar 58, Egypt 29, KSA none). The sleeve weight and price were computed
right; only the stored length text is wrong, and the BOQ printed 'GI Sleeve 1.0 X Inch' (old JSON: no line).

This patch sets sleeveLength to the mm value of the same cart's sleeveSelection, as the corrected action
(5031: replace("mm","").split(" ")[2]) does today. Only values that are exactly 'Inch' change, and only when
the selection reads '<n> Inch <mm>mm'. Safe to run again.
"""

import re

import frappe

SELECTION = re.compile(r"^\s*\d+(?:\.\d+)?\s+Inch\s+(\d+(?:\.\d+)?)\s*mm\s*$", re.I)


def log(msg):
	print(f"[fix_cart_sleeve_length_inch] {msg}")


def execute():
	rows = frappe.db.sql("""
		select l.name, l.parent, fti.value selection
		from `tabBtbCartItemFeature` l
		join `tabBtbFeature` bl on bl.name = l.feature and bl.field = 'sleeveLength'
		left join (`tabBtbCartItemFeature` s join `tabBtbFeature` bs on bs.name = s.feature and bs.field = 'sleeveSelection')
			on s.parent = l.parent
		left join `tabBtbFeatureTypeItem` fti on fti.name = s.value
		where l.value = 'Inch'
	""", as_dict=1)
	if not rows:
		log("no cart stores 'Inch' as sleeve length: nothing to do")
		return

	changed, unreadable = {}, []
	for r in rows:
		m = SELECTION.match(r.selection or "")
		if not m:
			unreadable.append(f"{r.parent} ({r.selection!r})")
			continue
		frappe.db.set_value("BtbCartItemFeature", r.name, "value", m.group(1), update_modified=False)
		changed[m.group(1)] = changed.get(m.group(1), 0) + 1

	log(f"{sum(changed.values())} carts: sleeve length 'Inch' set from the sleeve selection ("
		+ ", ".join(f"{mm} x{n}" for mm, n in sorted(changed.items())) + ")")
	if unreadable:
		log(f"{len(unreadable)} carts left as 'Inch', selection not readable: " + ", ".join(unreadable[:10]))
