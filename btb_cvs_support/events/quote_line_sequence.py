"""Keeps configurator quote lines numbered 1..n in cart order.

Quote lines are written from several places (cart item link sync in
onecpq_connect, before_save_quote, ...), each of which may set `idx` to the
cart item's own position, leaving gaps or repeats. Since `idx` is both the
row order and the No. shown, the lines are renumbered by cart position
(cart item idx, then creation) after every change.

A sync of many cart items fires these hooks once per item, so affected quotes
are only collected here and renumbered once each, just before the request's
transaction commits.
"""

from typing import List

import frappe

PENDING_FLAG = "quote_lines_to_resequence"


def on_cart_item_link_change(doc, method=None):
    """BtbCartItemLink on_update / after_delete."""
    if doc.entity_type == "Quotation" and doc.entity:
        queue_resequence(doc.entity)


def on_cart_item_update(doc, method=None):
    """BtbCartItem on_update: every save re-syncs the linked quote lines, which
    puts the cart item's own idx back on them, so renumber on any change, not
    only a reorder."""
    quotes = frappe.db.sql(
        """select distinct entity from `tabBtbCartItemLink`
        where parent = %s and entity_type = 'Quotation'""",
        doc.name,
        pluck=True,
    )
    for quote in quotes:
        queue_resequence(quote)


def on_quote_update(doc, method=None):
    """Quotation on_update."""
    if doc.custom_customizable == 1:
        queue_resequence(doc.name)


def queue_resequence(quote_name: str):
    pending = frappe.flags.get(PENDING_FLAG)
    if pending is None:
        pending = frappe.flags[PENDING_FLAG] = set()
        frappe.db.before_commit.add(_run_pending)
        # a rollback drops the queued callback, so drop the pending set with it
        frappe.db.after_rollback.add(lambda: frappe.flags.pop(PENDING_FLAG, None))
    pending.add(quote_name)


def _run_pending():
    pending = frappe.flags.pop(PENDING_FLAG, None) or set()
    for quote_name in sorted(pending):
        resequence_quote_lines(quote_name)


def resequence_quote_lines(quote_name: str) -> int:
    """Renumber a draft configurator quote's lines 1..n by cart position.
    Lines without a cart item keep their relative order after the cart lines.
    Returns the number of lines whose idx changed."""
    # lock the quote so concurrent syncs of the same quote renumber one at a time
    quote = frappe.db.sql(
        """select custom_customizable, docstatus from `tabQuotation`
        where name = %s for update""",
        quote_name,
        as_dict=True,
    )
    if not quote or quote[0].custom_customizable != 1 or quote[0].docstatus != 0:
        return 0

    lines = frappe.db.sql(
        """select tqi.name, tqi.idx
        from `tabQuotation Item` tqi
        left join `tabBtbCartItem` ci on ci.name = tqi.custom_cart_item
        where tqi.parent = %s and tqi.parenttype = 'Quotation' and tqi.parentfield = 'items'
        order by ci.name is null, ci.idx, ci.creation, tqi.idx, tqi.creation""",
        quote_name,
        as_dict=True,
    )
    changed = [(line.name, seq) for seq, line in enumerate(lines, start=1) if line.idx != seq]
    if changed:
        _update_idx(changed)
    return len(changed)


def _update_idx(changed: List[tuple]):
    # one statement per chunk; only rows whose number moved
    for start in range(0, len(changed), 500):
        chunk = changed[start : start + 500]
        cases = " ".join(["when %s then %s"] * len(chunk))
        names = ", ".join(["%s"] * len(chunk))
        values = [v for pair in chunk for v in pair] + [name for name, _ in chunk]
        frappe.db.sql(
            f"""update `tabQuotation Item` set idx = case name {cases} end
            where name in ({names})""",
            values,
        )
