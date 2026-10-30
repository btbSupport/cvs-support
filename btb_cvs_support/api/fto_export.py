"""FTO cost tables: only OneCPQ Admin (and Administrator) may export them.

Export permission alone can't do this: Frappe lets every System Manager export any doctype, and
Data Import's template download only asks for read, which every OneCPQ user has because
configuration reads these tables. So the three endpoints that write table data to a file are
wrapped, and refuse these doctypes for anyone else. All other doctypes pass straight through."""

import frappe
from frappe import _
from frappe.core.doctype.data_export import exporter
from frappe.core.doctype.data_import import data_import
from frappe.desk import reportview

COST_DOCTYPES = {"FTOCountryWiseCost", "FTOCVSSpring", "FTOCVSActuator"}
ADMIN_ROLE = "OneCPQ Admin"


def check_cost_export(*doctypes):
	if frappe.session.user == "Administrator" or ADMIN_ROLE in frappe.get_roles():
		return
	for doctype in doctypes:
		if doctype in COST_DOCTYPES:
			frappe.throw(_("Only OneCPQ Admin can export {0}.").format(doctype), frappe.PermissionError)


@frappe.whitelist()
@frappe.read_only()
def export_query():
	check_cost_export(frappe.form_dict.get("doctype"))
	return reportview.export_query()


@frappe.whitelist()
def export_data(**kwargs):
	doctype = kwargs.get("doctype")
	names = [d if isinstance(d, str) else d.get("doctype") for d in doctype] if isinstance(doctype, list) else [doctype]
	check_cost_export(kwargs.get("parent_doctype"), *names)
	# the request carries extras such as `cmd`; pass on only what the original accepts
	return exporter.export_data(**frappe.get_newargs(exporter.export_data, kwargs))


@frappe.whitelist()
def download_template(**kwargs):
	if kwargs.get("export_records") != "blank_template":
		check_cost_export(kwargs.get("doctype"))
	return data_import.download_template(**frappe.get_newargs(data_import.download_template, kwargs))
