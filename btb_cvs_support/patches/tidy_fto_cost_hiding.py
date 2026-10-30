"""FTO costs stay readable by every OneCPQ user, because configuration reads them, but are kept out
of sight for everyone except OneCPQ Admin:

- Forms hide them with a display rule (the cost_info sections, and FTOCVSActuator's valuation rate).
- The FTOCountryWiseCost list used to drop its Cost column with three identical client scripts,
  which failed together ("FIELD_TO_HIDE has already been declared"). The column is simply no longer
  a list column, and the scripts (plus two disabled form scripts the display rule replaces) go.
- Only OneCPQ Admin exports these tables: System Manager loses export.

Fixture sync never deletes or rewrites records outside the fixtures, so this does it on the site."""

import frappe
from frappe.custom.doctype.property_setter.property_setter import make_property_setter
from frappe.permissions import update_permission_property

COST_DOCTYPES = ("FTOCountryWiseCost", "FTOCVSSpring", "FTOCVSActuator")
OLD_SCRIPTS = (
	"CustomScript0001",
	"CustomScript0003",
	"CustomScript0009",
	"CustomScript0010",
	"countrywisecost_controller",
	"springcost_controller",
)


def execute():
	for name in OLD_SCRIPTS:
		if frappe.db.exists("Client Script", name):
			frappe.delete_doc("Client Script", name, ignore_permissions=True, force=True)

	make_property_setter("FTOCountryWiseCost", "cost", "in_list_view", 0, "Check")

	for doctype in COST_DOCTYPES:
		if frappe.db.exists("Custom DocPerm", {"parent": doctype, "role": "System Manager", "permlevel": 0}):
			update_permission_property(doctype, "System Manager", 0, "export", 0)

	frappe.clear_cache()
