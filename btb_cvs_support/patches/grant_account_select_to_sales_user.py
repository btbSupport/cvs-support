"""Gives Sales User Select on Account.

ERPNext v16 checks Account access on every Quotation save (payment schedule ->
party account), so sales users without it cannot save a quotation at all.
Select is the smallest grant that passes the check: it allows picking an
account, not opening Account records.

Only sites whose Account permissions are customised are affected; the
standard permissions already give Sales User Read.
"""

import frappe
from frappe.permissions import add_permission, update_permission_property


def execute():
    if not frappe.db.exists("Custom DocPerm", {"parent": "Account"}):
        return  # standard permissions apply, Sales User already has Read

    existing = frappe.db.get_value(
        "Custom DocPerm",
        {"parent": "Account", "role": "Sales User", "permlevel": 0, "if_owner": 0},
        ["select", "read"],
        as_dict=True,
    )
    if existing:
        if not (existing.select or existing.read):
            update_permission_property("Account", "Sales User", 0, "select", 1)
        return

    add_permission("Account", "Sales User", 0, "select")
    # Custom DocPerm defaults read to 1; keep the grant to Select only
    update_permission_property("Account", "Sales User", 0, "read", 0)
