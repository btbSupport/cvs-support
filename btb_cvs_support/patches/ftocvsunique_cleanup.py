"""Tidies FTOCVSUnique, the model/variant table the configurator reads through
Object List feature types (Fire & Smoke, Curtain Fire and Rectangular Volume
Control Dampers). custom_unique_id is the key those feature types match on.

Agreed 2026-11-21:
  1. Delete the rows with no product family and model '#N/A' - old Curtain
     Fire Damper ids from before the model rename, left behind as options of
     the Fire & Smoke feature type - together with those options. A row stays
     if any rule or saved cart line on this site still refers to it.
  2. product_family_description is fetched from the bundle label but was never
     filled for most rows: fill it for every row with a product family.
  3. Remove the custom fields custom_label (a copy of custom_unique_id that
     nothing reads) and custom_product_family_description (a copy of the
     bundle label, replaced by step 2).
  4. Drop the leftover column unique_id (no longer a field; a copy of
     custom_unique_id) and the columns of the removed custom fields.

Agreed 2026-11-23 (prod copies):
  5. custom_unique_id is a doctype field; UAE and KSA also have a site-made
     Custom Field record with that fieldname. Delete the record only: the
     column and values stay, its property setters are kept.
  6. Empty Column/Section/Tab Break custom fields left anchored on a removed
     field (KSA: after custom_label) are deleted when no other field is
     placed after them.

Before a duplicate field or column is removed, its values are checked against
what they duplicate; if any differ on this site it is kept and reported.
Columns are dropped last, after all data changes. Idempotent.
"""

import json
import re

import frappe

DOCTYPE = "FTOCVSUnique"
TABLE = f"tab{DOCTYPE}"
TOKEN = re.compile(r"\$\[([^\]]*)\]")

report = []


def note(message):
	report.append(message)


def execute(drop_columns=True):
	report.clear()
	delete_orphan_rows()
	backfill_family_description()
	removable = removable_duplicates()
	remove_custom_fields(removable)
	remove_duplicate_unique_id()
	remove_dangling_breaks()
	tidy_field_order(removable)
	if(drop_columns):
		drop_leftover_columns(removable)
	else:
		note(f"columns that would be dropped: {', '.join(planned_drops(removable)) or 'none'}")

	print("FTOCVSUnique cleanup:")
	for line in report:
		print(f"  {line}")


# ---------------------------------------------------------------------------
def delete_orphan_rows():
	rows = frappe.get_all(DOCTYPE, filters=[["product_family", "is", "not set"], ["model_no", "=", "#N/A"]],
						  fields=["name", "custom_unique_id"])
	if(not rows):
		note("orphan rows: none found")
		return
	options = frappe.get_all("BtbFeatureTypeItem", filters={"object": ["in", [r.name for r in rows]]},
							 fields=["name", "object", "feature_type"])
	options_of = {}
	for o in options:
		options_of.setdefault(o.object, []).append(o.name)

	used_ids, used_texts = rule_references()
	in_carts = set()
	if(options):
		in_carts = {r[0] for r in frappe.db.sql(
			"select distinct value from `tabBtbCartItemFeature` where value in %(ids)s",
			{"ids": tuple(o.name for o in options)})}

	deleted, kept = 0, []
	for row in rows:
		ids = options_of.get(row.name, [])
		if(any(i in used_ids or i in in_carts for i in ids) or (row.custom_unique_id or "") in used_texts):
			kept.append(row.name)
			continue
		for option in ids:
			frappe.delete_doc("BtbFeatureTypeItem", option, ignore_permissions=True, force=True)
		frappe.delete_doc(DOCTYPE, row.name, ignore_permissions=True, force=True)
		deleted += 1
	note(f"orphan rows: {deleted} deleted with {sum(len(options_of.get(r.name, [])) for r in rows if r.name not in kept)} "
		 f"feature type option(s)")
	if(kept):
		note(f"orphan rows KEPT because a rule or cart line still uses them: {', '.join(kept)}")


def rule_references():
	"""Option ids used by any rule (stored formula or option list) and option
	texts used in any readable expression."""
	ids, texts = set(), set()
	sources = frappe.db.sql("select `constraint`, formula, impact_options from `tabBtbImplementationConstraintAction`") + \
		frappe.db.sql("select `constraint`, formula, '' from `tabBtbImplementationConstraint`")
	for readable, formula, options in sources:
		ids.update(TOKEN.findall(formula or ""))
		ids.update(x.strip() for x in (options or "").split(",") if x.strip())
		texts.update(TOKEN.findall(readable or ""))
	return ids, texts


def backfill_family_description():
	stale = frappe.db.sql(f"""select count(*) from `{TABLE}` u join `tabBtbBundle` b on b.name = u.product_family
		where ifnull(u.product_family_description, '') <> ifnull(b.label, '')""")[0][0]
	frappe.db.sql(f"""update `{TABLE}` u join `tabBtbBundle` b on b.name = u.product_family
		set u.product_family_description = b.label
		where ifnull(u.product_family_description, '') <> ifnull(b.label, '')""")
	note(f"product_family_description filled from the bundle label on {stale} row(s)")


def removable_duplicates():
	"""Columns that may go: each must exist and hold nothing beyond the value it duplicates."""
	checks = {
		"custom_label": "ifnull(u.custom_label, '') not in ('', ifnull(u.custom_unique_id, ''))",
		"unique_id": "ifnull(u.unique_id, '') not in ('', ifnull(u.custom_unique_id, ''))",
		"custom_product_family_description":
			"ifnull(u.custom_product_family_description, '') not in ('', ifnull(b.label, ''))",
	}
	removable = []
	for column, differs in checks.items():
		if(not frappe.db.has_column(DOCTYPE, column)):
			continue
		count = frappe.db.sql(f"""select count(*) from `{TABLE}` u left join `tabBtbBundle` b on b.name = u.product_family
			where {differs}""")[0][0]
		if(count):
			note(f"KEPT {column}: {count} row(s) hold a value that differs from what it duplicates")
			continue
		removable.append(column)
	return removable


def remove_custom_fields(removable):
	for fieldname in ("custom_label", "custom_product_family_description"):
		name = frappe.db.get_value("Custom Field", {"dt": DOCTYPE, "fieldname": fieldname})
		if(not name):
			continue
		if(fieldname not in removable and frappe.db.has_column(DOCTYPE, fieldname)):
			continue
		frappe.delete_doc("Custom Field", name, ignore_permissions=True)
		note(f"custom field {fieldname} removed (with its property setters)")
	frappe.clear_cache(doctype=DOCTYPE)


def remove_duplicate_unique_id():
	standard = set(frappe.get_all("DocField", {"parent": DOCTYPE, "parenttype": "DocType"}, pluck="fieldname"))
	if("custom_unique_id" not in standard):
		return
	for name in frappe.get_all("Custom Field", {"dt": DOCTYPE, "fieldname": "custom_unique_id"}, pluck="name"):
		keep = frappe.get_all("Property Setter", {"doc_type": DOCTYPE, "field_name": "custom_unique_id"},
							  ["property", "value", "property_type"])
		frappe.delete_doc("Custom Field", name, ignore_permissions=True, force=True)
		for ps in keep:
			frappe.make_property_setter({"doctype": DOCTYPE, "fieldname": "custom_unique_id", "property": ps.property,
				"value": ps.value, "property_type": ps.property_type or "Data"}, validate_fields_for_doctype=False)
		note(f"duplicate custom field {name} deleted (doctype field custom_unique_id kept"
			 + (f"; {len(keep)} setting(s) kept)" if keep else ")"))
	frappe.clear_cache(doctype=DOCTYPE)


def remove_dangling_breaks():
	"""Empty breaks anchored on a field that no longer exists (or on such a break), with nothing placed
	after them."""
	fields = frappe.get_all("Custom Field", {"dt": DOCTYPE}, ["name", "fieldname", "fieldtype", "insert_after"])
	existing = set(frappe.get_all("DocField", {"parent": DOCTYPE, "parenttype": "DocType"}, pluck="fieldname")) | \
		{f.fieldname for f in fields}
	breaks = {f.fieldname: f for f in fields if f.fieldtype in ("Column Break", "Section Break", "Tab Break")}
	dangling = {n for n, f in breaks.items() if f.insert_after and f.insert_after not in existing}
	while True:
		more = {n for n, f in breaks.items() if f.insert_after in dangling} - dangling
		if(not more):
			break
		dangling |= more
	if(any(f.insert_after in dangling and f.fieldname not in dangling for f in fields)):
		note(f"breaks KEPT (a field is placed after them): {', '.join(sorted(dangling))}")
		return
	for n in sorted(dangling):
		frappe.delete_doc("Custom Field", breaks[n].name, ignore_permissions=True, force=True)
		note(f"empty break {breaks[n].name} deleted (anchored on a removed field)")
	frappe.clear_cache(doctype=DOCTYPE)


def tidy_field_order(removable):
	setter = frappe.db.get_value("Property Setter", {"doc_type": DOCTYPE, "property": "field_order"},
								 ["name", "value"], as_dict=True)
	if(not setter or not setter.value):
		return
	order = frappe.parse_json(setter.value)
	kept = [f for f in order if f not in removable]
	if(kept != order):
		frappe.db.set_value("Property Setter", setter.name, "value", json.dumps(kept))
		note(f"field order: removed {', '.join(f for f in order if f not in kept)}")


def planned_drops(removable):
	meta = frappe.get_meta(DOCTYPE)
	return [c for c in removable if frappe.db.has_column(DOCTYPE, c) and not meta.has_field(c)]


def drop_leftover_columns(removable):
	"""DDL commits the transaction, so this runs after every data change."""
	dropped = planned_drops(removable)
	for column in dropped:
		frappe.db.sql_ddl(f"alter table `{TABLE}` drop column `{column}`")
	note(f"columns dropped: {', '.join(dropped) or 'none'}")
