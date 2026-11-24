"""FTOCountryWiseCost cleanup (customer Final Activities reply + 4-site analysis, 2026-11-23).

Reads the plan of the current site from patches/fto_cost_cleanup_plans/<site>.json (cvsuae, cvsqatar, cvsksa,
badregypt; site_config "cvs_country" or the start of the site name picks it). A site with no plan stops the migrate.

Rules agreed for this cleanup:
- Rows only. The cost field is never written: each site maintains its own costs. A surviving row keeps its own cost.
- Names are kept (they are already identical on all four sites). A merge keeps the row holding the highest UAE
  cost; the other rows' options are repointed to it and the rows are deleted.
- Target codes / names / units = UAE values + the customer's decisions, with plain single spaces.
- Every step matches by content, changes only what is still in its old state, and logs what it skips.

Steps:
 1. field updates (product_name, item_code, unit) on surviving rows, guarded by the expected current name
 2. blank country -> the site's country
 3. merges: repoint options (BtbFeatureTypeItem.object) to the survivor, delete the merged rows
 4. options that now point twice at one row in the same feature type: keep the oldest, move rule references,
    delete the duplicate unless a saved quote uses it
 5. bundles (Table MultiSelect) filled from option usage; rows no bundle uses keep their old product_family
 6. Fire & Smoke picks its actuator cost row by the actuator's code-model item code (was: bare model)
 7. readable rule text follows the renamed options; '$[undefined]' ids are filled where the text now resolves
 8. FT62 stops listing ulrd_valuation_rate; old custom fields cost_type / country (+ their column breaks) go;
    property setters of fields that no longer exist are deleted and the field_order setter is trimmed;
    columns cost_type, country, test, product_family (FTOCountryWiseCost) and ulrd_valuation_rate (FTOCVSActuator)
    are dropped last (DDL cannot be rolled back; execute(drop_columns=False) for dry runs).
"""

import json
import os
import re

import frappe

from btb_cvs_support.onecpq_rule_text import TOKEN, OptionIndex, fill_undefined, norm, relabel, rule_rows, scan

COST = "FTOCountryWiseCost"
OLD_FIELDS = ("cost_type", "country")
OLD_BREAKS = ("custom_column_break_qvzri", "custom_column_break_5ex8r")
DROP_COLUMNS = {COST: ("cost_type", "country", "test", "product_family"), "FTOCVSActuator": ("ulrd_valuation_rate",)}
BUN5_ACTUATOR_SELECTS = {
	"actModel1": ("OBJECTATTRIBUTEF(actUnique1,'model')", "OBJECTATTRIBUTEF(actUnique1,'item_code')"),
	"actModel2": ("OBJECTATTRIBUTEF(actUnique2,'model')", "OBJECTATTRIBUTEF(actUnique2,'item_code')"),
	"actuatorModel": ("OBJECTATTRIBUTEF(actuator,'model')", "OBJECTATTRIBUTEF(actuator,'item_code')"),
}

report = []


def log(msg):
	report.append(msg)


def clean(v):
	if v is None:
		return None
	s = str(v).replace("Â\xa0", " ").replace("\xa0", " ")
	return re.sub(r"\s+", " ", s).strip()


def execute(drop_columns=True):
	report.clear()
	plan = load_plan()
	if plan:
		prepare_schema()
		before = cost_option_texts()
		apply_updates(plan)
		fill_country(plan)
		apply_merges(plan)
		dedupe_options()
		fill_bundles()
		switch_fsd_actuator_select()
		rewrite_rule_text(before)
		retire_old_fields()
		clean_property_setters()
		if drop_columns:
			drop_old_columns()
	print("FTOCountryWiseCost cleanup:")
	for line in report:
		print(f"  {line}")


def prepare_schema():
	"""Schema changes first: DDL commits implicitly, so nothing of the data steps may run before it."""
	frappe.reload_doc("btb_cvs_support", "doctype", "ftocostbundle")
	frappe.reload_doc("btb_cvs_support", "doctype", "ftocountrywisecost")
	frappe.reload_doc("btb_cvs_support", "doctype", "ftocvsactuator")
	cf = frappe.db.get_value("Custom Field", {"dt": COST, "fieldname": "custom_product_family_description"},
		["name", "fieldtype"], as_dict=True)
	if cf and cf.fieldtype == "Data":  # several bundle names do not fit 140 characters
		doc = frappe.get_doc("Custom Field", cf.name)
		doc.fieldtype = "Small Text"
		doc.label = "Bundles Description"
		doc.fetch_from = None
		doc.read_only = 1
		doc.save(ignore_permissions=True)
		log("custom_product_family_description: Data -> Small Text, read-only, no fetch")


PLAN_OF_COUNTRY = {"UAE": "cvsuae", "Qatar": "cvsqatar", "KSA": "cvsksa", "Egypt": "badregypt"}


def load_plan():
	"""The plan of this site: site_config "cvs_country" if set, else the site name (cvsqatarprod -> cvsqatar).

	A site that matches no plan stops the migrate. Marking the patch done without running it would leave the
	site uncleaned for good."""
	site = frappe.local.site or ""
	country = frappe.conf.get("cvs_country")
	if country:
		key = PLAN_OF_COUNTRY.get(country)
	else:
		key = next((k for k in PLAN_OF_COUNTRY.values() if site.startswith(k)), None)
	path = key and frappe.get_app_path("btb_cvs_support", "patches", "fto_cost_cleanup_plans", f"{key}.json")
	if not path or not os.path.exists(path):
		frappe.throw(f"fto_cost_cleanup: no cleanup plan for site {site!r} (cvs_country {country!r}). Set "
			"\"cvs_country\" (UAE, Qatar, KSA or Egypt) in its site_config.json and migrate again.")
	with open(path) as f:
		plan = json.load(f)
	log(f"plan {key}.json: {len(plan['updates'])} updates, {len(plan['merges'])} merges")
	return plan


# --------------------------------------------------------------------------- data
def cost_option_texts():
	"""Option id -> its display text (the cost row's data_text_field) for every cost feature type."""
	texts = {}
	for ft in frappe.get_all("BtbFeatureType", {"object_type": COST}, ["name", "data_text_field"]):
		field = ft.data_text_field or "name"
		for it in frappe.db.sql(f"""select i.name, c.`{field}` from `tabBtbFeatureTypeItem` i
				left join `tab{COST}` c on c.name = i.object where i.feature_type = %s""", ft.name):
			texts[it[0]] = "" if it[1] is None else str(it[1])
	return texts


def apply_updates(plan):
	done = skipped = 0
	for u in plan["updates"]:
		cur = frappe.db.get_value(COST, u["row"], ["product_name", "item_code", "unit"], as_dict=True)
		if not cur:
			log(f"SKIPPED update {u['row']}: row not found")
			skipped += 1
			continue
		target_name = u["set"].get("product_name", u["expect_name"])
		if clean(cur.product_name) not in (clean(u["expect_name"]), clean(target_name)):
			log(f"SKIPPED update {u['row']}: name is {cur.product_name!r}, expected {u['expect_name']!r}")
			skipped += 1
			continue
		changes = {k: v for k, v in u["set"].items() if cur.get(k) != v}
		if "unit" in changes:  # UOM names differ in case per site (Sqm / sqm): use this site's record name
			unit = changes["unit"]
			if unit and (cur.unit or "").lower() == unit.lower():
				del changes["unit"]
			elif unit:
				site_uom = frappe.db.get_value("UOM", unit, "name")
				if site_uom:
					changes["unit"] = site_uom
				else:
					log(f"SKIPPED unit of {u['row']}: UOM {unit!r} does not exist on this site")
					del changes["unit"]
		if changes:
			frappe.db.set_value(COST, u["row"], changes, update_modified=False)
			done += 1
	log(f"field updates: {done} rows changed, {skipped} skipped")


def fill_country(plan):
	n = 0
	for row in plan["fill_country"]:
		if frappe.db.exists(COST, row) and not frappe.db.get_value(COST, row, "custom_country"):
			frappe.db.set_value(COST, row, "custom_country", plan["country"], update_modified=False)
			n += 1
	log(f"country set to {plan['country']} on {n} rows")


def apply_merges(plan):
	deleted = repointed = skipped = 0
	for m in plan["merges"]:
		s = m["survivor"]
		if not frappe.db.exists(COST, s):
			log(f"SKIPPED merge into {s}: survivor not found")
			skipped += 1
			continue
		for member in m["members"]:
			if not frappe.db.exists(COST, member):
				continue  # already merged
			name = frappe.db.get_value(COST, member, "product_name")
			if clean(name) != clean(m["expect"].get(member)):
				log(f"SKIPPED merge {member} -> {s}: name is {name!r}, expected {m['expect'].get(member)!r}")
				skipped += 1
				continue
			boq = frappe.db.get_value(COST, member, "boq_identifier")
			if boq and not frappe.db.get_value(COST, s, "boq_identifier"):
				frappe.db.set_value(COST, member, "boq_identifier", "", update_modified=False)
				frappe.db.set_value(COST, s, "boq_identifier", boq, update_modified=False)
				log(f"BOQ identifier {boq} moved {member} -> {s}")
			repointed += frappe.db.sql("update `tabBtbFeatureTypeItem` set object = %s where object = %s",
				(s, member)) or 0
			frappe.db.sql(f"delete from `tab{COST}` where name = %s", member)
			deleted += 1
	log(f"merges: {deleted} rows deleted, {skipped} skipped")


def dedupe_options():
	dups = frappe.db.sql("""select i.feature_type, i.object from `tabBtbFeatureTypeItem` i
		join `tabBtbFeatureType` t on t.name = i.feature_type and t.object_type = %s
		group by i.feature_type, i.object having count(*) > 1""", COST, as_dict=True)
	for d in dups:
		items = frappe.get_all("BtbFeatureTypeItem", {"feature_type": d.feature_type, "object": d.object},
			pluck="name", order_by="creation asc")
		keep, drops = items[0], items[1:]
		for drop in drops:
			in_quotes = frappe.db.sql("select count(*) from `tabBtbCartItemFeature` where value = %s", drop)[0][0]
			moved = move_option_refs(drop, keep)
			if in_quotes:
				log(f"duplicate option {drop} ({d.feature_type} -> {d.object}) kept: used in {in_quotes} saved quote lines")
				continue
			frappe.db.sql("delete from `tabBtbFeatureTypeItem` where name = %s", drop)
			log(f"duplicate option {drop} deleted ({d.feature_type} -> {d.object}); kept {keep}; {moved} rule refs moved")


def move_option_refs(old, new):
	n = 0
	for dt in ("BtbImplementationConstraint", "BtbImplementationConstraintAction"):
		for r in frappe.db.sql(f"select name, formula from `tab{dt}` where formula like %s", f"%$[{old}]%", as_dict=True):
			frappe.db.set_value(dt, r.name, "formula", r.formula.replace(f"$[{old}]", f"$[{new}]"), update_modified=False)
			n += 1
	for r in frappe.db.sql("select name, impact_options from `tabBtbImplementationConstraintAction` "
			"where impact_options like %s", f"%{old}%", as_dict=True):
		opts = [new if o.strip() == old else o.strip() for o in (r.impact_options or "").split(",")]
		frappe.db.set_value("BtbImplementationConstraintAction", r.name, "impact_options", ",".join(dict.fromkeys(opts)),
			update_modified=False)
		n += 1
	for side in ("left", "right"):  # option-compatibility tables point at options too
		n += frappe.db.count("BtbMappingConstraintEntry", {side: old})
		frappe.db.sql(f"update `tabBtbMappingConstraintEntry` set `{side}` = %s where `{side}` = %s", (new, old))
	return n


def fill_bundles():
	usage = {}
	for obj, bundle in frappe.db.sql("""select distinct i.object, s.bundle from `tabBtbFeatureTypeItem` i
			join `tabBtbFeatureType` t on t.name = i.feature_type and t.object_type = %s
			join `tabBtbFeatureLink` l on l.feature_type = i.feature_type
			join `tabBtbFeature` f on f.name = l.parent
			join `tabBtbStructure` s on s.name = f.structure""", COST):
		usage.setdefault(obj, set()).add(bundle)
	has_old = frappe.db.has_column(COST, "product_family")
	changed = unused = 0
	for name in frappe.get_all(COST, pluck="name"):
		bundles = usage.get(name)
		if not bundles:
			old = frappe.db.sql(f"select product_family from `tab{COST}` where name = %s", name)[0][0] if has_old else None
			bundles = {old} if old else set()
			unused += 1
		order = {"BUN4": 4, "BUN5": 5, "BUN6": 6, "BUN7": 7, "BUN8": 8, "BUN9": 9, "BUN10": 10}
		want = sorted(bundles, key=lambda b: (order.get(b, 99), b))
		doc = frappe.get_doc(COST, name)
		if [r.bundle for r in doc.bundles] == want:
			continue
		doc.set("bundles", [{"bundle": b} for b in want])
		doc.flags.ignore_permissions = True
		doc.save()
		changed += 1
	log(f"bundles filled on {changed} rows ({unused} rows used by no option kept their old product_family)")


def switch_fsd_actuator_select():
	"""BUN5 selects the actuator cost row by text. After the merge those rows carry the code-model item code."""
	bundle = frappe.db.get_value("BtbBundle", {"label": "Fire & Smoke Dampers"}, "name")
	if not bundle:
		return
	codes = frappe.get_all("FTOCVSActuator", pluck="item_code")
	if not codes or any(not c or "-" not in c for c in codes):
		log("SKIPPED Fire & Smoke actuator select: FTOCVSActuator item codes are not code-model yet "
			"(run fto_ulrd_actuator_country_cost first)")
		return
	n = 0
	for a in frappe.db.sql("""select a.name, a.impact_fields, a.formula, a.`constraint` from `tabBtbImplementationConstraintAction` a
			join `tabBtbImplementationConstraint` c on c.name = a.implementation_constraint
			where c.bundle = %s and a.type = 'Include Value'""", bundle, as_dict=True):
		old_new = BUN5_ACTUATOR_SELECTS.get((a.impact_fields or "").strip())
		if not old_new or old_new[0] not in (a.formula or "") + (a.constraint or ""):
			continue
		frappe.db.set_value("BtbImplementationConstraintAction", a.name, {
			"formula": (a.formula or "").replace(*old_new),
			"constraint": (a.constraint or "").replace(*old_new)}, update_modified=False)
		n += 1
	log(f"Fire & Smoke: {n} actuator select action(s) now match on item code")


def rewrite_rule_text(before):
	after = cost_option_texts()
	changed = {i: t for i, t in after.items() if i in before and before[i] != t}
	old_by_text = {norm(before[i]): after[i] for i in changed}
	relabelled = filled = skipped = 0
	for bundle in frappe.get_all("BtbBundle", pluck="name"):
		index = None
		for row in rule_rows(bundle):
			ids = TOKEN.findall(row.formula or "")
			has_changed = any(i in changed for i in ids)
			has_undefined = "undefined" in ids and any(norm(lbl) in old_by_text for _s, _e, lbl, _f in scan(row.readable or ""))
			if not (has_changed or has_undefined):
				continue
			readable = relabel(row.readable, row.formula, changed, before)
			if readable is None:
				log(f"SKIPPED rule text {row.doctype} {row.name}: labels and ids do not line up")
				skipped += 1
				continue
			formula = row.formula
			if has_undefined:
				readable = relabel_undefined(readable, row.formula, old_by_text)
				index = index or OptionIndex(bundle)
				filled_formula = fill_undefined(row.formula, readable, index)
				if filled_formula:
					formula = filled_formula
					filled += 1
				else:
					log(f"undefined option in {row.doctype} {row.name} not resolved")
			if readable != row.readable or formula != row.formula:
				frappe.db.set_value(row.doctype, row.name, {"constraint": readable, "formula": formula},
					update_modified=False)
				relabelled += 1
	log(f"rule text: {relabelled} rules updated ({filled} undefined options filled), {skipped} skipped")


def relabel_undefined(readable, formula, old_by_text):
	"""At positions whose stored id is 'undefined', a label equal to a renamed option's old text gets the new text."""
	labels = list(scan(readable or ""))
	ids = TOKEN.findall(formula or "")
	if len(labels) != len(ids):
		return readable
	out, last = [], 0
	for (s, e, label, _f), oid in zip(labels, ids):
		out.append(readable[last:s])
		new = old_by_text.get(norm(label)) if oid == "undefined" else None
		out.append(f"$[{new}]" if new else readable[s:e])
		last = e
	out.append(readable[last:])
	return "".join(out)


# --------------------------------------------------------------------------- schema
def retire_old_fields():
	# FT62 (Actuator) must stop listing the rate once no rule reads it
	still_used = frappe.db.sql("""select count(*) from `tabBtbImplementationConstraintAction`
		where formula like '%%ulrd_valuation_rate%%' or `constraint` like '%%ulrd_valuation_rate%%'""")[0][0]
	if still_used:
		log(f"ulrd_valuation_rate still read by {still_used} rule(s) - FT62 and column left in place")
		DROP_COLUMNS.pop("FTOCVSActuator", None)
	else:
		for ft in frappe.get_all("BtbFeatureType", {"object_type": "FTOCVSActuator"}, ["name", "additional_fields"]):
			fields = [f.strip() for f in (ft.additional_fields or "").split(",") if f.strip()]
			if "ulrd_valuation_rate" in fields:
				fields.remove("ulrd_valuation_rate")
				frappe.db.set_value("BtbFeatureType", ft.name, "additional_fields", ",".join(fields), update_modified=False)
				log(f"{ft.name}: ulrd_valuation_rate removed from additional fields")
	# old custom fields: keep any value the custom_* field lacks, then delete by fieldname (record names differ per site)
	for old, new in (("cost_type", "custom_cost_type"), ("country", "custom_country")):
		if frappe.db.has_column(COST, old):
			copied = frappe.db.sql(f"""update `tab{COST}` set `{new}` = `{old}`
				where coalesce(`{new}`, '') = '' and coalesce(`{old}`, '') != ''""") or 0
			conflicts = frappe.db.sql(f"""select name, `{old}`, `{new}` from `tab{COST}`
				where coalesce(`{old}`, '') != '' and `{old}` != `{new}`""")
			for c in conflicts:
				log(f"{c[0]}: old {old}={c[1]!r} differs from {new}={c[2]!r} - kept {new}")
	for cf in frappe.get_all("Custom Field", {"dt": COST, "fieldname": ["in", OLD_FIELDS + OLD_BREAKS]}, ["name", "fieldname"]):
		frappe.delete_doc("Custom Field", cf.name, ignore_permissions=True, force=True)
		log(f"custom field {cf.name} ({cf.fieldname}) deleted")
	remove_duplicate_custom_fields()
	frappe.clear_cache(doctype=COST)


def remove_duplicate_custom_fields():
	"""Custom Field records left behind when custom_cost_type / custom_country moved into the doctype (Qatar, KSA,
	Egypt). The field stays (standard DocField); its list-view setting is kept as a plain property setter."""
	standard = set(frappe.get_all("DocField", {"parent": COST, "parenttype": "DocType"}, pluck="fieldname"))
	for cf in frappe.get_all("Custom Field", {"dt": COST, "fieldname": ["in", ["custom_cost_type", "custom_country"]]},
			["name", "fieldname"]):
		if cf.fieldname not in standard:
			continue
		keep = frappe.get_all("Property Setter", {"doc_type": COST, "field_name": cf.fieldname},
			["property", "value", "property_type"])
		frappe.delete_doc("Custom Field", cf.name, ignore_permissions=True, force=True)
		for ps in keep:
			frappe.make_property_setter({"doctype": COST, "fieldname": cf.fieldname, "property": ps.property,
				"value": ps.value, "property_type": ps.property_type or "Data"}, validate_fields_for_doctype=False)
		log(f"duplicate custom field {cf.name} deleted (standard field {cf.fieldname} kept"
			+ (f"; {len(keep)} setting(s) kept)" if keep else ")"))


def clean_property_setters():
	"""Site-local list/filter/order settings that name removed fields."""
	for dt in (COST, "FTOCVSActuator"):
		frappe.clear_cache(doctype=dt)
		meta = frappe.get_meta(dt)
		fields = {f.fieldname for f in meta.fields}
		for ps in frappe.get_all("Property Setter", {"doc_type": dt}, ["name", "field_name", "property", "value"]):
			if ps.field_name and ps.field_name not in fields:
				frappe.db.delete("Property Setter", {"name": ps.name})
				log(f"property setter {ps.name} deleted ({dt}.{ps.field_name} no longer exists)")
			elif not ps.field_name and ps.property == "field_order":
				try:
					order = json.loads(ps.value or "[]")
				except ValueError:
					continue
				kept = [f for f in order if f in fields]
				if kept != order:
					frappe.db.set_value("Property Setter", ps.name, "value", json.dumps(kept), update_modified=False)
					log(f"{dt} field_order setter: removed {sorted(set(order) - set(kept))}")
		frappe.clear_cache(doctype=dt)
	# site-local custom fields placed after a removed field (e.g. a column break after product_family)
	fields = {f.fieldname for f in frappe.get_meta(COST).fields}
	for cf in frappe.get_all("Custom Field", {"dt": COST}, ["name", "insert_after"]):
		if cf.insert_after and cf.insert_after not in fields:
			frappe.db.set_value("Custom Field", cf.name, "insert_after", "bundles", update_modified=False)
			log(f"custom field {cf.name}: insert_after {cf.insert_after!r} -> 'bundles'")
	frappe.clear_cache(doctype=COST)


def drop_old_columns():
	for dt, cols in DROP_COLUMNS.items():
		meta = frappe.get_meta(dt)
		for col in cols:
			if meta.has_field(col) or not frappe.db.has_column(dt, col):
				continue
			frappe.db.sql_ddl(f"alter table `tab{dt}` drop column `{col}`")
			log(f"column {dt}.{col} dropped")
