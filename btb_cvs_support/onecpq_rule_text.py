"""Helpers for OneCPQ rule text (BtbImplementationConstraint / -Action).

A rule stores two texts: the readable one (`constraint`, options written by their text: '$[GI]') and the
compiled one (`formula`, options written by FeatureTypeItem id: '$[FTV825]'). Nothing on the server compiles
one into the other; the admin UI does it on save. These helpers let patches keep both in step.
Same logic as btb_cvs_support.patches.fix_onecpq_bundle_rule_drift.
"""

import re

import frappe

TOKEN = re.compile(r"\$\[([^\]]*)\]")
OPTION_FUNCS = {"CONTAINS", "OBJECTATTRIBUTEV"}


def norm(text):
	"""Stored formulas often differ from the readable text in whitespace only."""
	return re.sub(r"\s+", "", text or "")


def rule_rows(bundle_name):
	"""Constraints and actions of a bundle as uniform rows (readable = `constraint`, formula = `formula`)."""
	names = frappe.get_all("BtbImplementationConstraint", filters={"bundle": bundle_name}, pluck="name") or [""]
	rows = []
	for c in frappe.get_all("BtbImplementationConstraint", filters={"name": ["in", names]},
			fields=["name", "constraint", "formula"]):
		rows.append(frappe._dict(doctype="BtbImplementationConstraint", name=c.name, readable=c.constraint,
			formula=c.formula))
	for a in frappe.get_all("BtbImplementationConstraintAction", filters={"implementation_constraint": ["in", names]},
			fields=["name", "constraint", "formula"]):
		rows.append(frappe._dict(doctype="BtbImplementationConstraintAction", name=a.name, readable=a.constraint,
			formula=a.formula))
	return rows


class OptionIndex:
	"""Feature field -> options (id, text) for one bundle; text = value, or the object's data_text_field."""

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
				if meta and meta.data_type == "Object List" and it.object:
					text = frappe.db.get_value(it.object_type or meta.object_type, it.object, meta.data_text_field or "name")
				text = "" if text is None else str(text)
				self.opts[ft].append((it.name, text))
				self.text[it.name] = text

	def resolve(self, field, label):
		matches = []
		for ft in self.field_fts.get(field, []):
			for oid, text in self.opts.get(ft, []):
				if label == oid:
					return oid
				if text == label:
					matches.append(oid)
		return matches[0] if len(set(matches)) == 1 else "undefined"


def scan(expr):
	"""Yield (start, end, label, field) per '$[...]' token; field = first argument of the enclosing
	CONTAINS/OBJECTATTRIBUTEV (or nearest call)."""
	stack, i, quote = [], 0, None
	while i < len(expr):
		ch = expr[i]
		if expr.startswith("$[", i):
			j = expr.find("]", i)
			if j == -1:
				break
			field = next((a for f, a in reversed(stack) if f in OPTION_FUNCS and a), None) \
				or next((a for f, a in reversed(stack) if a), None)
			yield i, j + 1, expr[i + 2:j], field
			i = j + 1
			continue
		if quote:
			if ch == quote:
				quote = None
		elif ch in "'\"":
			quote = ch
		elif ch == "(":
			m = re.search(r"([A-Za-z_][A-Za-z0-9_]*)\s*$", expr[:i])
			a = re.match(r"\s*([A-Za-z_][A-Za-z0-9_]*)\s*[,)]", expr[i + 1:])
			stack.append(((m.group(1).upper() if m else ""), (a.group(1) if a else None)))
		elif ch == ")" and stack:
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


def relabel(readable, formula, new_text, old_text=None):
	"""Readable text where each label whose stored id is in `new_text` gets that id's new text.
	With `old_text`, a label is only replaced while it still reads the old text (or 'undefined').
	Returns None when labels and ids do not line up one to one."""
	labels = list(scan(readable or ""))
	ids = TOKEN.findall(formula or "")
	if len(labels) != len(ids):
		return None
	out, last = [], 0
	for (s, e, label, _field), oid in zip(labels, ids):
		out.append(readable[last:s])
		if oid in new_text and (old_text is None or norm(label) in (norm(old_text.get(oid)), "undefined")):
			out.append(f"$[{new_text[oid]}]")
		else:
			out.append(readable[s:e])
		last = e
	out.append(readable[last:])
	return "".join(out)


def fill_undefined(formula, readable, index):
	"""Stored formula with its '$[undefined]' ids filled from the readable text, or None when the readable text
	does not compile to the same formula apart from those tokens."""
	compiled = compile_expr(readable, index)
	old_ids, new_ids = TOKEN.findall(formula or ""), TOKEN.findall(compiled or "")
	if norm(TOKEN.sub("", formula or "")) != norm(TOKEN.sub("", compiled or "")) or len(old_ids) != len(new_ids):
		return None
	if any(o == "undefined" and n == "undefined" for o, n in zip(old_ids, new_ids)):
		return None
	if not all(o == n or o == "undefined" for o, n in zip(old_ids, new_ids)):
		return None
	ids = iter(new_ids)

	def token(m):
		new_id = next(ids)
		return f"$[{new_id}]" if m.group(1) == "undefined" else m.group(0)

	return TOKEN.sub(token, formula)
