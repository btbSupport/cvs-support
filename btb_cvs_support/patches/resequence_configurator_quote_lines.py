"""Renumbers the lines of draft configurator quotes 1..n in cart order.

Lines used to take the cart item's own idx, so quotes show gaps and repeats
(4; 1, 1, 1, 1). From now on events.quote_line_sequence keeps them in step;
this brings the existing drafts in line. Submitted and cancelled quotes are
left as they are.
"""

import frappe

from btb_cvs_support.events.quote_line_sequence import resequence_quote_lines


def execute():
    quotes = frappe.get_all(
        "Quotation",
        filters={"custom_customizable": 1, "docstatus": 0},
        pluck="name",
    )
    for quote in quotes:
        resequence_quote_lines(quote)
