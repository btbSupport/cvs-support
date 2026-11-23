"""Repairs OneCPQ bundle rules whose option references drifted from the data.

A constraint or action keeps its expression twice: `constraint`, readable, with
option labels ('$[GI]'), and `formula`, what the configurator runs, with option
ids ('$[FTV825]'). The admin screen turns one into the other on save and writes
'$[undefined]' for a label it cannot find. After options and cost rows were
renamed, some formulas were left with '$[undefined]', and others with readable
text that no longer matches the option. The second kind runs correctly but
turns into '$[undefined]' the next time someone saves it.

Fixes (agreed 2026-11-21):
  Access doors      material density: drop the non-existent '$[EAL]' option
  Curtain Fire      width/height check: the 6 renamed model names
  Dampers           Hide Group: drop deleted 'BG21-Product Cost'; delete the
                    unused 'Test' group
  Silencer, Fire &  readable text of sealant cost and fusible-link spring cost
  Smoke Dampers     set to the current option text (stored formula unchanged)
  Fire & Smoke      blade-slit rows get a blade_size ('4 Inch'..'7 Inch') that
  Dampers           becomes the option text, so the blade area rules resolve;
                    drop non-existent fields from Disable Field; delete the
                    empty action row
  UL True Round     Hide Group: drop deleted 'BG13-Options'

Added 2026-11-23 after dry runs on copies of the 4 prod sites:
  Access doors      frame strip width / door depth formulas hold $[undefined]
                    on prod (always 0): recompiled from the readable text
  UL True Round     Hide Group: drop 'BG12-Btb Check' where it no longer
                    exists; readable text of the jack shaft kit cost synced
                    (a non-breaking space in the carriage bolt label)
  Fire & Smoke      Hide Group: drop 'BG16-Btb Check', 'BG17-Options' where
  Dampers           they no longer exist
  Rectangular VCD   delete inactive Change Value actions with no target field
                    and an $[undefined] formula (UAE: one stray action)

The Silencer casing premium (a cost row whose name and item code carry a double
space) is left to the FTOCountryWiseCost cleanup; this patch changes no cost row.

Records are found by bundle label and content, not by id, because ids may
differ between sites. Every step changes a record only while it is still in its
old state, and a recompiled formula is written only when it differs from the
stored one exactly where the old one was broken. Anything not found is
reported and skipped. Runs after the FTOCountryWiseCost item code patches,
because item codes are the option text of some cost feature types. Idempotent.
"""

import re

import frappe

TOKEN = re.compile(r"\$\[([^\]]*)\]")
OPTION_FUNCS = {"CONTAINS", "OBJECTATTRIBUTEV"}

CURTAIN_MODELS = {
	"FD-SLA Slimline Curtain Fire Damper Type A – Static – Optional Sleeve":
		"FD-SL-A Slimline Curtain Fire Damper Type A - Static - Optional Sleeve",
	"FDA Curtain Fire Damper Type A – Static - Optional Sleeve":
		"FD-A Curtain Fire Damper Type A - Static - Optional Sleeve",
	"FDA-I Curtain Fire Damper Type A – Static - Integral Sleeve":
		"FD-A-I Curtain Fire Damper Type A - Static - Integral Sleeve",
	"FDD-SLA Slimline Curtain Fire Damper Type A – Dynamic – Optional Sleeve":
		"FDD-SL-A Slimline Curtain Fire Damper Type A - Dynamic - Optional Sleeve",
	"FDDA Curtain Fire Damper Type A – Dynamic - Optional Sleeve":
		"FDD-A Curtain Fire Damper Type A - Dynamic - Optional Sleeve",
	"FDDA-I Curtain Fire Damper Type A – Dynamic – Integral Sleeve":
		"FDD-A-I Curtain Fire Damper Type A - Dynamic - Integral Sleeve",
}

# (3V slit size, AF slit size) -> blade size, as used by the Fire & Smoke Dampers rules
BLADE_SIZES = {(127.0, 0.0): "4 Inch", (153.0, 263.0): "5 Inch", (178.0, 312.0): "6 Inch", (203.0, 359.0): "7 Inch"}

report = []


def note(message):
	report.append(message)


def execute():
	report.clear()
	access = bundle("Access doors")
	silencer = bundle("Silencer")
	curtain = bundle("Curtain Fire Dampers")
	fsd = bundle("Fire & Smoke Dampers")
	ulrd = bundle("UL True Round Dampers")
	rvcd = bundle("Rectangular Volume Control Dampers")

	if(access): drop_eal(access)
	if(access): fill_undefined(access, "Access doors", lambda r: True)
	if(curtain): fix_curtain_models(curtain)
	if(silencer): sync_readable(silencer, "sealantCost")
	if(fsd): sync_readable(fsd, "fusibleLinkWithSpringMechanismCost")
	if(fsd): fix_blade_sizes(fsd)
	if(ulrd): sync_readable(ulrd, "jackShaftKitUnitCost")
	if(ulrd): drop_dead_names(ulrd, "Hide Group", ["BG13-Options", "BG12-Btb Check"])
	if(fsd): drop_dead_names(fsd, "Hide Group", ["BG16-Btb Check", "BG17-Options"])
	if(curtain): drop_dead_names(curtain, "Hide Group", ["BG21-Product Cost"])
	if(fsd): drop_dead_names(fsd, "Disable Field", ["quotedPricePerUnit", "totalQuotedPrice"])
	if(fsd): delete_blank_actions(fsd)
	if(curtain): delete_test_group(curtain)
	if(rvcd): delete_stray_actions(rvcd)

	print("OneCPQ bundle rule repair:")
	for line in report:
		print(f"  {line}")


# ---------------------------------------------------------------------------
# steps
# ---------------------------------------------------------------------------
def drop_eal(bundle_name):
	pattern = re.compile(r"\s*,\s*'\$\[EAL\]'")
	broken = re.compile(r"\s*,\s*'\$\[undefined\]'")
	done = 0
	for row in rule_rows(bundle_name):
		if(not pattern.search(row.readable or "")): continue
		readable = pattern.sub("", row.readable, count=1)
		formula = compile_expr(readable, OptionIndex(bundle_name))
		expected = broken.sub("", row.formula or "", count=1)
		if(norm(formula) != norm(expected)):
			note(f"SKIPPED Access doors {row.label}: recompiled formula differs beyond the EAL option")
			continue
		save_rule(row, readable, expected)
		done += 1
	note(f"Access doors: '$[EAL]' removed from {done} rule(s)")


def fix_curtain_models(bundle_name):
	def rewrite(text):
		for old, new in CURTAIN_MODELS.items():
			text = text.replace(f"$[{old}]", f"$[{new}]")
		return text
	fill_undefined(bundle_name, "Curtain Fire Dampers",
				   lambda r: any(f"$[{old}]" in (r.readable or "") for old in CURTAIN_MODELS), rewrite)


def fill_undefined(bundle_name, title, selects, rewrite=None):
	"""Recompile rules that carry '$[undefined]'; accept the result only when
	the undefined tokens are all that changed."""
	done = 0
	index = OptionIndex(bundle_name)
	for row in rule_rows(bundle_name):
		if("$[undefined]" not in (row.formula or "") or not selects(row)): continue
		readable = rewrite(row.readable) if rewrite else row.readable
		formula = compile_expr(readable, index)
		if(not only_undefined_filled(row.formula, formula)):
			note(f"SKIPPED {title} {row.label}: recompiled formula differs beyond the undefined options")
			continue
		save_rule(row, readable, fill_into(row.formula, formula))
		done += 1
	note(f"{title}: {done} rule(s) with undefined options repaired")


def sync_readable(bundle_name, impact_field):
	"""Set the readable labels to the current option text. The stored formula
	must compile back unchanged, otherwise nothing is written."""
	index = OptionIndex(bundle_name)
	done = 0
	for row in rule_rows(bundle_name, impact_field=impact_field):
		readable = readable_from_formula(row.readable, row.formula, index)
		if(readable is None or readable == row.readable): continue
		if(norm(compile_expr(readable, index)) != norm(row.formula)):
			note(f"SKIPPED {impact_field}: readable text does not compile back to the stored formula")
			continue
		save_rule(row, readable, row.formula)
		done += 1
	note(f"{frappe.db.get_value('BtbBundle', bundle_name, 'label')}: readable text of {impact_field} synced on {done} rule(s)")


def fix_blade_sizes(bundle_name):
	filled = 0
	for row in frappe.get_all("FTOBtbBladeSlits", fields=["name", "blade_size", "btb3_v_slit_size", "af_slit_size"]):
		size = BLADE_SIZES.get((float(row.btb3_v_slit_size or 0), float(row.af_slit_size or 0)))
		if(size and not row.blade_size):
			frappe.db.set_value("FTOBtbBladeSlits", row.name, "blade_size", size, update_modified=False)
			filled += 1
	labelled = {r.blade_size for r in frappe.get_all("FTOBtbBladeSlits", fields=["blade_size"])}
	if(not set(BLADE_SIZES.values()) <= labelled):
		note(f"SKIPPED blade slits: not every blade size could be matched by slit sizes ({filled} filled)")
		return
	switched = 0
	for ft in frappe.get_all("BtbFeatureType",
							 filters={"object_type": "FTOBtbBladeSlits", "data_text_field": "name"}, pluck="name"):
		doc = frappe.get_doc("BtbFeatureType", ft)
		doc.data_text_field = "blade_size"
		doc.flags.ignore_permissions = True
		doc.save()
		switched += 1
	note(f"Blade slits: blade_size filled on {filled} row(s), {switched} feature type(s) now show blade_size")
	index = OptionIndex(bundle_name)
	broken = [r.label for r in rule_rows(bundle_name) if "Inch]" in (r.readable or "")
			  and norm(compile_expr(r.readable, index)) != norm(r.formula)]
	if(broken):
		note(f"CHECK Fire & Smoke Dampers: blade rules still differ from their readable text: {broken}")


def drop_dead_names(bundle_name, action_type, names):
	exists = existing_targets(bundle_name, action_type)
	dead = [n for n in names if n not in exists]
	done = 0
	for row in frappe.get_all("BtbImplementationConstraintAction",
							  filters={"implementation_constraint": ["in", constraints_of(bundle_name)], "type": action_type},
							  fields=["name", "impact_fields"]):
		current = [x.strip() for x in (row.impact_fields or "").split(",") if x.strip()]
		kept = [x for x in current if x not in dead]
		if(kept == current): continue
		frappe.db.set_value("BtbImplementationConstraintAction", row.name, "impact_fields", ",".join(kept))
		done += 1
	label = frappe.db.get_value("BtbBundle", bundle_name, "label")
	note(f"{label}: {', '.join(dead) or 'nothing'} removed from {done} {action_type} action(s)")


def delete_blank_actions(bundle_name):
	rows = frappe.get_all("BtbImplementationConstraintAction",
						  filters={"implementation_constraint": ["in", constraints_of(bundle_name)]},
						  fields=["name", "type", "impact_fields", "impact_options", "constraint", "formula", "description"])
	blank = [r.name for r in rows if not any((r.get(k) or "").strip() for k in
											 ("type", "impact_fields", "impact_options", "constraint", "formula", "description"))]
	for name in blank:
		frappe.delete_doc("BtbImplementationConstraintAction", name, ignore_permissions=True, force=True)
	note(f"Fire & Smoke Dampers: {len(blank)} empty action row(s) deleted")


def delete_stray_actions(bundle_name):
	"""Inactive Change Value actions that change no field and whose formula is broken."""
	rows = frappe.get_all("BtbImplementationConstraintAction",
						  filters={"implementation_constraint": ["in", constraints_of(bundle_name)], "type": "Change Value",
								   "active": 0},
						  fields=["name", "impact_fields", "formula"])
	stray = [r.name for r in rows if not (r.impact_fields or "").strip() and "$[undefined]" in (r.formula or "")]
	for name in stray:
		frappe.delete_doc("BtbImplementationConstraintAction", name, ignore_permissions=True, force=True)
	label = frappe.db.get_value("BtbBundle", bundle_name, "label")
	note(f"{label}: {len(stray)} inactive Change Value action(s) without target deleted" + (f" ({', '.join(stray)})" if stray else ""))


def delete_test_group(bundle_name):
	groups = frappe.get_all("BtbBundleGroup",
							filters={"bundle": bundle_name, "label": "Test", "features": "fittingType"}, pluck="name")
	deleted = 0
	for name in groups:
		used = frappe.get_all("BtbImplementationConstraintAction",
							  filters={"implementation_constraint": ["in", constraints_of(bundle_name)],
									   "impact_fields": ["like", f"%{name}%"]}, pluck="name")
		if(used):
			note(f"SKIPPED Curtain Fire Dampers group {name}: still referenced by {used}")
			continue
		frappe.delete_doc("BtbBundleGroup", name, ignore_permissions=True, force=True)
		deleted += 1
	note(f"Curtain Fire Dampers: {deleted} 'Test' group(s) deleted")


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def bundle(label):
	names = frappe.get_all("BtbBundle", filters={"label": label}, pluck="name")
	if(len(names) != 1):
		note(f"SKIPPED bundle {label!r}: found {len(names)} bundle(s) with that label")
		return None
	return names[0]


def constraints_of(bundle_name):
	return frappe.get_all("BtbImplementationConstraint", filters={"bundle": bundle_name}, pluck="name") or [""]


def rule_rows(bundle_name, impact_field=None):
	"""Constraints and actions of a bundle as uniform rows."""
	rows = []
	names = constraints_of(bundle_name)
	if(not impact_field):
		for c in frappe.get_all("BtbImplementationConstraint", filters={"name": ["in", names]},
								fields=["name", "constraint", "formula"]):
			rows.append(frappe._dict(doctype="BtbImplementationConstraint", name=c.name,
									 label=f"constraint {c.name}", readable=c.constraint, formula=c.formula))
	filters = {"implementation_constraint": ["in", names]}
	if(impact_field): filters["impact_fields"] = impact_field
	for a in frappe.get_all("BtbImplementationConstraintAction", filters=filters,
							fields=["name", "implementation_constraint", "sequence", "type", "constraint", "formula"]):
		rows.append(frappe._dict(doctype="BtbImplementationConstraintAction", name=a.name,
								 label=f"constraint {a.implementation_constraint} action {a.sequence} {a.type}",
								 readable=a.constraint, formula=a.formula))
	return rows


def save_rule(row, readable, formula):
	frappe.db.set_value(row.doctype, row.name, {"constraint": readable, "formula": formula})


def existing_targets(bundle_name, action_type):
	if("Group" in action_type):
		return set(frappe.get_all("BtbBundleGroup", filters={"bundle": bundle_name}, pluck="name"))
	structures = frappe.get_all("BtbStructure", filters={"bundle": bundle_name}, pluck="name") or [""]
	return set(frappe.get_all("BtbFeature", filters={"structure": ["in", structures]}, pluck="field"))


def norm(text):
	"""Stored formulas often differ from the readable text in whitespace only."""
	return re.sub(r"\s+", "", text or "")


def fill_into(old_formula, compiled):
	"""The stored formula with its '$[undefined]' tokens replaced by the ids
	the readable text compiles to - the rest of the stored text is kept."""
	ids = iter(TOKEN.findall(compiled or ""))

	def token(m):
		new_id = next(ids)
		return f"$[{new_id}]" if m.group(1) == "undefined" else m.group(0)

	return TOKEN.sub(token, old_formula)


def only_undefined_filled(old, new):
	old_tokens, new_tokens = TOKEN.findall(old or ""), TOKEN.findall(new or "")
	if(norm(TOKEN.sub("", old or "")) != norm(TOKEN.sub("", new or "")) or len(old_tokens) != len(new_tokens)):
		return False
	if("undefined" in new_tokens):
		return False
	return all(o == n or o == "undefined" for o, n in zip(old_tokens, new_tokens))


class OptionIndex:
	"""Feature field -> options (id, text) for one bundle."""

	def __init__(self, bundle_name):
		self.field_fts, self.opts, self.text = {}, {}, {}
		structures = frappe.get_all("BtbStructure", filters={"bundle": bundle_name}, pluck="name") or [""]
		for f in frappe.get_all("BtbFeature", filters={"structure": ["in", structures]}, fields=["name", "field"]):
			self.field_fts[f.field] = frappe.get_all("BtbFeatureLink", filters={"parent": f.name}, pluck="feature_type")
		for ft in {ft for fts in self.field_fts.values() for ft in fts}:
			meta = frappe.db.get_value("BtbFeatureType", ft, ["data_type", "object_type", "data_text_field"], as_dict=True)
			self.opts[ft] = []
			for it in frappe.get_all("BtbFeatureTypeItem", filters={"feature_type": ft},
									 fields=["name", "value", "object", "object_type"]):
				text = it.value
				if(meta.data_type == "Object List" and it.object):
					text = frappe.db.get_value(it.object_type or meta.object_type, it.object, meta.data_text_field or "name")
				text = "" if text is None else str(text)
				self.opts[ft].append((it.name, text))
				self.text[it.name] = text

	def resolve(self, field, label):
		matches = []
		for ft in self.field_fts.get(field, []):
			for oid, text in self.opts.get(ft, []):
				if(label == oid): return oid
				if(text == label): matches.append(oid)
		return matches[0] if len(set(matches)) == 1 else "undefined"


def scan(expr):
	"""Yield (start, end, label, field) per '$[...]' token; field = first
	argument of the enclosing CONTAINS/OBJECTATTRIBUTEV (or nearest call)."""
	stack, i, quote = [], 0, None
	while i < len(expr):
		ch = expr[i]
		if(expr.startswith("$[", i)):
			j = expr.find("]", i)
			if(j == -1): break
			field = next((a for f, a in reversed(stack) if f in OPTION_FUNCS and a), None) \
				or next((a for f, a in reversed(stack) if a), None)
			yield i, j + 1, expr[i + 2:j], field
			i = j + 1
			continue
		if(quote):
			if(ch == quote): quote = None
		elif(ch in "'\""):
			quote = ch
		elif(ch == "("):
			m = re.search(r"([A-Za-z_][A-Za-z0-9_]*)\s*$", expr[:i])
			a = re.match(r"\s*([A-Za-z_][A-Za-z0-9_]*)\s*[,)]", expr[i + 1:])
			stack.append(((m.group(1).upper() if m else ""), (a.group(1) if a else None)))
		elif(ch == ")" and stack):
			stack.pop()
		i += 1


def compile_expr(expr, index):
	out, last = [], 0
	for s, e, label, field in scan(expr or ""):
		out.append(expr[last:s])
		out.append(f"$[{index.resolve(field, label) if field else 'undefined'}]")
		last = e
	out.append((expr or "")[last:])
	return "".join(out)


def readable_from_formula(readable, formula, index):
	"""Readable text with each label replaced by the current text of the option
	the stored formula uses at the same position."""
	labels = list(scan(readable or ""))
	ids = TOKEN.findall(formula or "")
	if(len(labels) != len(ids) or any(i not in index.text for i in ids)):
		return None
	out, last = [], 0
	for (s, e, _label, _field), oid in zip(labels, ids):
		out.append(readable[last:s])
		out.append(f"$[{index.text[oid]}]")
		last = e
	out.append(readable[last:])
	return "".join(out)
