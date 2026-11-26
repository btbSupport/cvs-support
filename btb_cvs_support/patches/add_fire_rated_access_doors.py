"""Adds the Fire Rated Access Doors bundle (BUN11) on every site, under the same record names everywhere.

The bundle was built once on a copy of UAE (decided 2026-11-23) and exported to
bundle_specs/fire_rated_access_doors/records.json: every record it needs, in insertion order, with fixed names
(BUN11, FTY00001, FTI00001, FTO00001...) that no site's own counter produces. spec.json next to it is the
readable design the records were built from.

Operations in the file, applied in order:
- ensure Item: create the item only if it is missing (existing items such as RAPI are left as they are). The
  product item keeps the document name SKU41 with item code FRAD, the product code that BOQ, Quotation
  Format and Production Sheet are keyed by (like SKU40 = AD).
- insert: create the record under its name. If the name already exists with the same content it is skipped;
  with different content the patch stops (nothing of this patch is committed) and reports what differs.
- add_bundle: add BUN11 to the Bundles list of a shared cost row that FRAD reuses (its cost is not touched).
- set_if_empty: fill a field of a shared row only where it is still empty: the BOQ identifier of the 13 shared
  cost rows FRAD reuses. FRAD's cost feature type shows rows by BOQ identifier (product name and item code can be
  edited in the UI), so a different identifier already on a site stops the patch.
- item_bundle_link: link the bundle to its anchor item (SKU41).

New cost rows get the cost of the site's own country from the FRAD workbook (UAE, Qatar, KSA, Egypt). The
country comes from site_config "cvs_country", else from the site name; a site that matches neither stops the
patch with a message instead of silently getting another country's prices. Units are matched to the site's own
UOM spelling. Safe to run again: a second run finds everything identical and changes nothing.
"""

import json

import frappe

RECORDS = ("bundle_specs", "fire_rated_access_doors", "records.json")
SITE_COUNTRY = {"cvsuae": "UAE", "cvsqatar": "Qatar", "cvsksa": "KSA", "badregypt": "Egypt"}
COMPARE_SKIP = {"product_family_description", "custom_product_family_description"}  # filled by the site itself


def log(msg):
	print(f"[add_fire_rated_access_doors] {msg}")


def execute():
	path = frappe.get_app_path("btb_cvs_support", *RECORDS)
	with open(path) as f:
		data = json.load(f)
	country = site_country()
	uoms = {u.lower(): u for u in frappe.get_all("UOM", pluck="name")}
	done = {"inserted": 0, "identical": 0, "items created": 0, "items kept": 0, "bundle added to shared rows": 0}
	priced = []
	for rec in data["records"]:
		op = rec["op"]
		if op == "ensure":
			if frappe.db.exists(rec["doctype"], rec["name"]):
				done["items kept"] += 1
			else:
				item = frappe.get_doc(dict(site_uoms(dict(rec["doc"]), uoms), doctype=rec["doctype"])).insert(
					set_name=rec["name"], ignore_permissions=True)
				# Inserted under a fixed name, the item gets that name as item code too (SKU41, not FRAD) on
				# sites that name items by series; the outputs are keyed by the product code, so set it back.
				code = rec["doc"].get("item_code")
				if code and item.item_code != code:
					frappe.db.set_value("Item", item.name, "item_code", code, update_modified=False)
				done["items created"] += 1
		elif op == "insert":
			doc = site_uoms(dict(rec["doc"]), uoms)
			if rec["doctype"] == "FTOCountryWiseCost":
				doc = site_cost_row(doc, rec.get("site_costs"), country, uoms)
				priced.append(f"{rec['name']} {doc.get('product_name')}: {doc.get('cost')}")
			if frappe.db.exists(rec["doctype"], rec["name"]):
				check_identical(rec["doctype"], rec["name"], doc)
				done["identical"] += 1
				continue
			frappe.get_doc(dict(doc, doctype=rec["doctype"])).insert(set_name=rec["name"], ignore_permissions=True)
			done["inserted"] += 1
		elif op == "add_bundle":
			row = frappe.get_doc(rec["doctype"], rec["name"])
			if rec["bundle"] not in [b.bundle for b in row.bundles]:
				row.append("bundles", {"bundle": rec["bundle"]})
				row.save(ignore_permissions=True)
				done["bundle added to shared rows"] += 1
		elif op == "set_if_empty":
			for field, value in rec["values"].items():
				current = (frappe.db.get_value(rec["doctype"], rec["name"], field) or "").strip()
				if not current:
					frappe.db.set_value(rec["doctype"], rec["name"], field, value, update_modified=False)
					log(f"{rec['doctype']} {rec['name']}: {field} set to {value!r}")
				elif current != value:  # FRAD's cost options show this text and its rules name it
					frappe.throw(f"add_fire_rated_access_doors: {rec['doctype']} {rec['name']} has {field} {current!r}, "
						f"FRAD expects {value!r} - align it on this site and migrate again.")
		elif op == "item_bundle_link":
			link_item(rec["item"], rec["bundle"])
		else:
			frappe.throw(f"add_fire_rated_access_doors: unknown operation {op!r}")
	log(f"{data['bundle']} '{data['label']}' ({country} prices): " + ", ".join(f"{k} {v}" for k, v in done.items()))
	if done["inserted"]:
		log("new cost rows priced from the workbook's " + country + " column: " + "; ".join(priced))


def site_country():
	if frappe.conf.get("cvs_country"):
		return frappe.conf.get("cvs_country")
	site = frappe.local.site or ""
	country = next((c for p, c in SITE_COUNTRY.items() if site.startswith(p)), None)
	if not country:
		frappe.throw(f"add_fire_rated_access_doors: cannot tell the country of site {site!r}. Set \"cvs_country\" "
			"(UAE, Qatar, KSA or Egypt) in its site_config.json and migrate again.")
	return country


def site_uoms(doc, uoms):
	"""UOM fields in the site's own spelling (Egypt has 'sqm' where UAE has 'Sqm')."""
	for field in ("uom", "stock_uom"):
		if doc.get(field):
			doc[field] = uoms.get(doc[field].lower(), doc[field])
	return doc


def site_cost_row(doc, site_costs, country, uoms):
	doc = dict(doc)
	if site_costs:
		doc["cost"] = site_costs[country]
	if doc.get("unit"):
		unit = uoms.get(doc["unit"].lower())
		if not unit:
			frappe.throw(f"add_fire_rated_access_doors: UOM {doc['unit']!r} is missing on this site")
		doc["unit"] = unit
	return doc


def check_identical(doctype, name, doc):
	"""The record exists already: fine if it is the same record, otherwise stop before anything is kept."""
	current = frappe.get_doc(doctype, name)
	diff = []
	for field, value in doc.items():
		if field.startswith("__") or field in COMPARE_SKIP or (doctype == "FTOCountryWiseCost" and field == "cost"):
			continue  # costs are each site's own once the row exists
		if isinstance(value, list):
			mine = [{k: v for k, v in row.items() if not k.startswith("__")} for row in value]
			theirs = [{k: row.get(k) for k in mine_row} for row, mine_row in zip(current.get(field) or [], mine)]
			if len(mine) != len(current.get(field) or []) or any(norm(a) != norm(b) for a, b in zip(mine, theirs)):
				diff.append(field)
		elif norm(value) != norm(current.get(field)):
			diff.append(field)
	if diff:
		frappe.throw(f"add_fire_rated_access_doors: {doctype} {name} already exists with different {', '.join(diff)} "
			"- another record uses this name; nothing was changed.")


def norm(v):
	if isinstance(v, dict):
		return {k: norm(x) for k, x in v.items()}
	if v in (None, ""):
		return None
	try:
		f = float(v)
		return int(f) if f == int(f) else round(f, 9)
	except (TypeError, ValueError):
		return " ".join(str(v).split())


def link_item(item, bundle):
	if frappe.db.exists("BtbBundleLink", {"parent": item, "parenttype": "Item", "parentfield": "custom_bundles",
			"bundle": bundle}):
		return
	idx = (frappe.db.sql("""select max(idx) from `tabBtbBundleLink`
		where parent=%s and parentfield='custom_bundles'""", item)[0][0] or 0) + 1
	frappe.get_doc({"doctype": "BtbBundleLink", "parent": item, "parenttype": "Item", "parentfield": "custom_bundles",
		"bundle": bundle, "sequence": 0, "idx": idx}).db_insert()
	log(f"Item {item} linked to {bundle}")
