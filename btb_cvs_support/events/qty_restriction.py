"""Over-qty restrictions for CVS.

ERPNext only validates delivered/received qty for stock items, and only validates
invoices on amount, never on qty. CVS needs qty restricted in these flows:

    Sales Order    -> Delivery Note     (non-stock items; stock items are standard)
    Purchase Order -> Purchase Receipt  (non-stock items; stock items are standard)
    Purchase Order -> Purchase Invoice with Update Stock (same as above)
    Delivery Note  -> Sales Invoice     (all items, qty)
    Sales Order    -> Sales Invoice     (all items, qty)
    Purchase Receipt -> Purchase Invoice (all items, qty)
    Purchase Order -> Purchase Invoice  (all items, qty)

Tolerance and bypass come from the over-delivery settings: "Over Delivery/Receipt
Allowance" (Item, else Stock Settings) and "Role Allowed to Over Deliver/Receive"
(Stock Settings). Users with that role get a warning instead of an error.

Invoice qty is compared in stock UOM and is net of credit/debit notes (their qty
is negative). Returns themselves are never blocked. Only submitted documents plus
the current one are counted.
"""

import frappe
from frappe import _
from frappe.utils import flt

from erpnext.controllers.status_updater import get_allowance_for

PRECISION_TOLERANCE = 0.001


# ---------------------------------------------------------------------------
# Hook entry points (doc_events -> validate)
# ---------------------------------------------------------------------------


def validate_delivery_note(doc, method=None):
    if doc.is_return:
        return
    checker = OverQtyChecker(doc)
    checker.check_non_stock_receipt(
        link_field="so_detail",
        qty_field="qty",
        ref_doctype="Sales Order Item",
        ref_done_field="delivered_qty",
        verb=_("delivered"),
    )
    checker.raise_if_any()


def validate_purchase_receipt(doc, method=None):
    if doc.is_return:
        return
    checker = OverQtyChecker(doc)
    checker.check_non_stock_receipt(
        link_field="purchase_order_item",
        qty_field="received_qty",
        ref_doctype="Purchase Order Item",
        ref_done_field="received_qty",
        verb=_("received"),
    )
    checker.raise_if_any()


def validate_sales_invoice(doc, method=None):
    if doc.is_return:
        return
    checker = OverQtyChecker(doc)
    checker.check_invoice_qty(link_field="dn_detail", ref_doctype="Delivery Note Item")
    checker.check_invoice_qty(link_field="so_detail", ref_doctype="Sales Order Item")
    checker.raise_if_any()


def validate_purchase_invoice(doc, method=None):
    if doc.is_return:
        return
    checker = OverQtyChecker(doc)
    if doc.update_stock:
        checker.check_non_stock_receipt(
            link_field="po_detail",
            qty_field="received_qty",
            ref_doctype="Purchase Order Item",
            ref_done_field="received_qty",
            verb=_("received"),
        )
    checker.check_invoice_qty(link_field="pr_detail", ref_doctype="Purchase Receipt Item")
    checker.check_invoice_qty(link_field="po_detail", ref_doctype="Purchase Order Item")
    checker.raise_if_any()


# ---------------------------------------------------------------------------
# Implementation
# ---------------------------------------------------------------------------


class OverQtyChecker:
    def __init__(self, doc):
        self.doc = doc
        self.errors = []
        role = frappe.get_single_value("Stock Settings", "role_allowed_to_over_deliver_receive")
        self.bypass_role = role if role and role in frappe.get_roles() else None
        self._item_allowance, self._global_qty, self._global_amt = {}, None, None

    def allowance(self, item_code):
        allowance, self._item_allowance, self._global_qty, self._global_amt = get_allowance_for(
            item_code, self._item_allowance, self._global_qty, self._global_amt, "qty"
        )
        return flt(allowance)

    # -- SO -> DN, PO -> PR, PO -> PI (update stock): non-stock items only ----

    def check_non_stock_receipt(self, link_field, qty_field, ref_doctype, ref_done_field, verb):
        """Standard ERPNext already checks stock items; this covers non-stock items.

        `ref_done_field` (delivered_qty / received_qty) only counts submitted
        documents, so the current document is never included in it.
        """
        this_qty, this_rows = {}, {}
        for row in self.doc.items:
            ref = row.get(link_field)
            if not ref or frappe.get_cached_value("Item", row.item_code, "is_stock_item"):
                continue
            this_qty[ref] = this_qty.get(ref, 0) + flt(row.get(qty_field))
            this_rows.setdefault(ref, []).append(row.idx)

        if not this_qty:
            return

        refs = frappe.get_all(
            ref_doctype,
            filters={"name": ["in", list(this_qty)]},
            fields=["name", "parenttype", "parent", "idx", "item_code", "qty", "uom", ref_done_field],
        )
        for ref in refs:
            self._compare(
                ref=ref,
                ref_qty=flt(ref.qty),
                already=flt(ref.get(ref_done_field)),
                this=this_qty[ref.name],
                rows=this_rows[ref.name],
                uom=ref.uom,
                verb=verb,
            )

    # -- DN -> SI, SO -> SI, PR -> PI, PO -> PI: all items, stock UOM -------

    def check_invoice_qty(self, link_field, ref_doctype):
        this_qty, this_rows = {}, {}
        for row in self.doc.items:
            ref = row.get(link_field)
            if not ref:
                continue
            this_qty[ref] = this_qty.get(ref, 0) + flt(row.stock_qty)
            this_rows.setdefault(ref, []).append(row.idx)

        if not this_qty:
            return

        refs = frappe.get_all(
            ref_doctype,
            filters={"name": ["in", list(this_qty)]},
            fields=["name", "parenttype", "parent", "idx", "item_code", "stock_qty", "stock_uom"],
        )
        already = self._already_invoiced(link_field, list(this_qty))

        for ref in refs:
            self._compare(
                ref=ref,
                ref_qty=flt(ref.stock_qty),
                already=flt(already.get(ref.name)),
                this=this_qty[ref.name],
                rows=this_rows[ref.name],
                uom=ref.stock_uom,
                verb=_("invoiced"),
            )

    def _already_invoiced(self, link_field, refs):
        """Net stock qty on submitted invoices (credit/debit notes are negative),
        excluding the current document."""
        item_dt = frappe.qb.DocType(f"{self.doc.doctype} Item")
        parent_dt = frappe.qb.DocType(self.doc.doctype)
        query = (
            frappe.qb.from_(item_dt)
            .join(parent_dt)
            .on(parent_dt.name == item_dt.parent)
            .select(item_dt[link_field], frappe.query_builder.functions.Sum(item_dt.stock_qty))
            .where(item_dt[link_field].isin(refs))
            .where(parent_dt.docstatus == 1)
            .groupby(item_dt[link_field])
        )
        if self.doc.name and not self.doc.is_new():
            query = query.where(parent_dt.name != self.doc.name)
        return frappe._dict(query.run())

    # -- shared --------------------------------------------------------------

    def _compare(self, ref, ref_qty, already, this, rows, uom, verb):
        if ref_qty <= 0:
            return
        max_allowed = flt(ref_qty * (100 + self.allowance(ref.item_code)) / 100, 6)
        excess = flt(already + this - max_allowed, 6)
        if excess <= PRECISION_TOLERANCE:
            return

        self.errors.append(
            _(
                "Row {0}: Item {1}: {2} {3} (row {4}) qty is {5} {6}, already {7} {8}. "
                "This {9} has {10}, which exceeds the maximum allowed {11} by {12}."
            ).format(
                ", ".join(str(i) for i in rows),
                frappe.bold(ref.item_code),
                _(ref.parenttype),
                frappe.bold(ref.parent),
                ref.idx,
                flt(ref_qty, 3),
                uom or "",
                verb,
                flt(already, 3),
                _(self.doc.doctype),
                flt(this, 3),
                flt(max_allowed, 3),
                frappe.bold(flt(excess, 3)),
            )
        )

    def raise_if_any(self):
        if not self.errors:
            return
        msg = "<br><br>".join(self.errors)
        if self.bypass_role:
            frappe.msgprint(
                msg,
                title=_("Over Qty (allowed by role {0})").format(self.bypass_role),
                indicator="orange",
            )
        else:
            frappe.throw(
                msg
                + "<br><br>"
                + _(
                    'To allow this, update "Over Delivery/Receipt Allowance" in Stock Settings '
                    "or on the Item."
                ),
                title=_("Qty Exceeds Source Document"),
            )
