
import frappe
from frappe import _
from frappe.model.document import Document


class FTOCVSUnique(Document):
	def validate(self):
		self.validate_unique_id()

	def validate_unique_id(self):
		"""custom_unique_id is the option text the configurator's feature types
		match on, so it has to name exactly one row within its product family.
		The same id may exist in another family (another bundle)."""
		self.custom_unique_id = (self.custom_unique_id or "").strip()
		if(not self.custom_unique_id or not self.product_family): return

		clash = frappe.db.get_value(
			"FTOCVSUnique",
			{"product_family": self.product_family, "custom_unique_id": self.custom_unique_id,
			 "name": ("!=", self.name)},
			"name")
		if(clash):
			frappe.throw(_("Unique Id {0} is already used by {1} in product family {2}.").format(
				frappe.bold(self.custom_unique_id), clash, self.product_family))
