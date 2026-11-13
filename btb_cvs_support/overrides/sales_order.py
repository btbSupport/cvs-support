from erpnext.selling.doctype.sales_order.sales_order import SalesOrder


class CustomSalesOrder(SalesOrder):
	"""Allow Sales Order qty to exceed the linked Quotation qty.

	ERPNext v16 added `target_ref_field` to the Quotation Item status updater,
	which makes StatusUpdater.validate_qty() block over-ordering against a Quotation.
	We still update Quotation Item.ordered_qty, but skip the over-qty validation.
	"""

	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)
		for args_ in self.status_updater:
			if args_.get("target_dt") == "Quotation Item":
				args_["validate_qty"] = False
