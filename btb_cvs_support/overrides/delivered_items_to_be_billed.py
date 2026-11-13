"""Delivered Items To Be Billed: list non-stock items again.

ERPNext (Nov 2025, "show only stock items in delivered items to be billed and
received items to be billed reports") added an Item join and an
``is_stock_item == 1`` filter to ``non_billed_report.get_ordered_to_be_billed_data``.
CVS bills service / non-stock items off Delivery Notes too, so the custom report
"CVS Delivered Item to be billed (N)" (built on the standard report) lost most
of its rows after the move to v16.

This module rebinds the name the Delivered Items report calls to a copy of the
upstream query without that filter. Only the Delivered Items report is touched;
"Received Items To Be Billed" keeps upstream behaviour.

Applied via ``before_request`` / ``before_job`` (see hooks.py). Re-applying is
harmless: it just binds the same function again.
"""

import frappe
from frappe.model.meta import get_field_precision
from frappe.query_builder.functions import IfNull, Round

from erpnext import get_default_currency
from erpnext.accounts.report.non_billed_report import get_project_field


def get_ordered_to_be_billed_data(args, filters=None):
	"""Upstream query, minus the Item join and the stock-item filter."""
	doctype, party = args.get("doctype"), args.get("party")
	child_tab = doctype + " Item"
	precision = (
		get_field_precision(
			frappe.get_meta(child_tab).get_field("billed_amt"), currency=get_default_currency()
		)
		or 2
	)

	doctype = frappe.qb.DocType(doctype)
	child_doctype = frappe.qb.DocType(child_tab)

	docname = filters.get(args.get("reference_field"), None)
	project_field = get_project_field(doctype, child_doctype, party)

	query = (
		frappe.qb.from_(doctype)
		.inner_join(child_doctype)
		.on(doctype.name == child_doctype.parent)
		.select(
			doctype.name,
			doctype[args.get("date")].as_("date"),
			doctype[party],
			doctype[party + "_name"],
			child_doctype.item_code,
			child_doctype.base_amount.as_("amount"),
			(child_doctype.billed_amt * IfNull(doctype.conversion_rate, 1)).as_("billed_amount"),
			(child_doctype.base_rate * IfNull(child_doctype.returned_qty, 0)).as_("returned_amount"),
			(
				child_doctype.base_amount
				- (child_doctype.billed_amt * IfNull(doctype.conversion_rate, 1))
				- (child_doctype.base_rate * IfNull(child_doctype.returned_qty, 0))
			).as_("pending_amount"),
			child_doctype.item_name,
			child_doctype.description,
			project_field,
			doctype.company,
		)
		.where(
			(doctype.docstatus == 1)
			& (doctype.status.notin(["Closed", "Completed"]))
			& (doctype.company == filters.get("company"))
			& (doctype.posting_date <= filters.get("posting_date"))
			& (child_doctype.amount > 0)
			& (
				child_doctype.base_amount
				- Round(child_doctype.billed_amt * IfNull(doctype.conversion_rate, 1), precision)
				- (child_doctype.base_rate * IfNull(child_doctype.returned_qty, 0))
			)
			> 0
		)
		.orderby(doctype[args.get("order")], order=args.get("order_by"))
	)

	if docname:
		query = query.where(doctype.name == docname)

	return query.run(as_dict=True)


def apply(*args, **kwargs):
	"""``before_request`` / ``before_job`` hook. Accepts and ignores hook kwargs."""
	from erpnext.accounts.report.delivered_items_to_be_billed import delivered_items_to_be_billed

	delivered_items_to_be_billed.get_ordered_to_be_billed_data = get_ordered_to_be_billed_data
