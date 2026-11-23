import frappe
from frappe import _
from frappe.model.document import Document


class FTOCountryWiseCost(Document):
	def validate(self):
		self.validate_boq_identifier()
		self.set_bundle_description()

	def set_bundle_description(self):
		"""Read-only text of the bundles using this row (replaces the old product_family fetch)."""
		if(not self.meta.has_field("custom_product_family_description")): return
		names = [row.bundle for row in (self.get("bundles") or []) if row.bundle]
		labels = [frappe.db.get_value("BtbBundle", n, "label") or n for n in names]
		self.custom_product_family_description = ", ".join(labels)

	def validate_boq_identifier(self):
		"""Uniqueness is enforced here rather than by a database index.

		Frappe stores an empty Data field as '' and not NULL, so a unique index
		would collide across every row that carries no identifier - which is
		most of them. Checking in code lets blanks stay blank.
		"""
		identifier = (self.boq_identifier or "").strip()
		self.boq_identifier = identifier
		if(not identifier): return

		clash = frappe.db.get_value(
			"FTOCountryWiseCost",
			{"boq_identifier": identifier, "name": ("!=", self.name)},
			["name", "product_name"], as_dict=True)
		if(clash):
			frappe.throw(_("BOQ Identifier {0} is already used by {1} ({2}). "
						   "It has to identify exactly one row.").format(
				frappe.bold(identifier), clash.name, clash.product_name))
