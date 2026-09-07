"""One BOQ line-generating rule, replacing a block of enumerated rows in
boq_format.JSON.

The validation here exists because the rules are edited by hand: a template
naming a field that no dimension declares, or an aggregate that is not JSON,
would otherwise surface as a silently missing BOQ line rather than an error.
"""

import json
import re

import frappe
from frappe import _
from frappe.model.document import Document

PLACEHOLDER = re.compile(r"\{([^{}]+)\}")


class BOQRule(Document):
	def validate(self):
		self.validate_identifier()
		self.validate_placeholders()
		self.validate_logic()
		self.validate_aggregate()
		self.validate_uom()
		self.validate_sourced_literal()

	def validate_logic(self):
		"""Dimensions contribute their values to the filter as eq conditions,
		so they can only be combined with the guards under 'and'. Under 'or'
		they would widen the filter instead of narrowing it, and the line would
		be measured against cart rows it does not describe.
		"""
		if(self.dimensions and (self.condition_logic or "and") != "and"):
			frappe.throw(_("A rule with Dimensions must use Condition Logic 'and'. "
						   "Move the alternatives into a separate rule."))

	def validate_identifier(self):
		if(not self.identifier_template and not self.identifier_literal):
			frappe.throw(_("Set an Identifier Template or an Identifier Literal."))

	def validate_placeholders(self):
		"""Every {field} in the template has to be a declared dimension.

		Substitution is driven by the dimension list, not by scanning the
		template, so an undeclared placeholder would survive into the item code
		as literal braces.
		"""
		if(not self.identifier_template): return
		declared = {(d.field or "").strip() for d in (self.dimensions or [])}
		used = {p.strip() for p in PLACEHOLDER.findall(self.identifier_template)}
		unknown = sorted(used - declared)
		if(unknown):
			frappe.throw(_("Identifier Template uses {0}, which {1} not declared as a Dimension.").format(
				", ".join("{" + u + "}" for u in unknown),
				"is" if len(unknown) == 1 else "are"))

	def validate_aggregate(self):
		try:
			parsed = json.loads(self.aggregate or "")
		except ValueError as e:
			frappe.throw(_("Aggregate is not valid JSON: {0}").format(e))
		if(not isinstance(parsed, dict) or "logic" not in parsed):
			frappe.throw(_("Aggregate must be an object carrying a 'logic' key."))

	def validate_uom(self):
		"""A Templated rule names its own UOM; a Sourced rule takes it from the
		cost row, so carrying one here would be a second source of truth."""
		if(self.source_type == "Templated" and not self.uom):
			frappe.throw(_("A Templated rule needs a UOM."))
		if(self.source_type == "Sourced" and self.uom):
			self.uom = None

	def validate_sourced_literal(self):
		"""A literal identifier on a Sourced rule can be checked now. A
		templated one cannot - it only resolves against a cart."""
		if(self.source_type != "Sourced" or not self.identifier_literal): return
		if(not frappe.db.exists("FTOCountryWiseCost", {"boq_identifier": self.identifier_literal})):
			frappe.msgprint(
				_("No FTOCountryWiseCost row carries the BOQ Identifier {0}. "
				  "This rule will be skipped until one does.").format(
					frappe.bold(self.identifier_literal)),
				indicator="orange", title=_("Identifier not found"))
