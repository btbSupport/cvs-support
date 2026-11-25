import frappe
from frappe import _
from frappe.model.document import Document
from frappe.modules.patch_handler import executed

IDENTIFIER_PATCH = "btb_cvs_support.patches.fto_boq_identifiers"


def identifiers_live():
	"""True once this site has run the patch that gives every cost row its identifier."""
	return bool(executed(IDENTIFIER_PATCH))


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
		"""Required and unique, checked here rather than by the field's reqd flag or a database index.

		Cost feature types show rows by this identifier and rules and the BOQ name rows by it, so every
		row needs one (fto_boq_identifiers filled all rows). The field is set_only_once: renames go through
		a repo patch that also rewrites the rules.

		Required is not a doctype flag because older patches (fto_cost_*) still save cost rows that have
		no identifier yet on a site that migrates them before fto_boq_identifiers runs; a reqd flag synced
		with the doctype would stop those patches. Patches are let through here for the same reason, and
		so is a site that has the code but has not migrated yet (one bench serves several sites).
		"""
		identifier = (self.boq_identifier or "").strip()
		self.boq_identifier = identifier
		if(not identifier):
			if(frappe.flags.in_patch or not identifiers_live()): return
			frappe.throw(_("BOQ Identifier is required: cost options show the row by it and rules name the row by it."),
						 frappe.MandatoryError, title=_("Missing BOQ Identifier"))

		clash = frappe.db.get_value(
			"FTOCountryWiseCost",
			{"boq_identifier": identifier, "name": ("!=", self.name)},
			["name", "product_name"], as_dict=True)
		if(clash):
			frappe.throw(_("BOQ Identifier {0} is already used by {1} ({2}). "
						   "It has to identify exactly one row.").format(
				frappe.bold(identifier), clash.name, clash.product_name))
