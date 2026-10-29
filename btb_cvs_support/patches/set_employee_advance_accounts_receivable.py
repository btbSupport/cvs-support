"""Sets account_type = Receivable on the accounts Employee Advances are booked
against, where the account has no type at all.

HRMS (version-15 after 15.45.3, and v16) refuses any other type: new advances
fail validation, paying or returning an advance throws in set_total_advance_paid,
and hrms.patches.v15_0.call_set_total_advance_paid_on_advance_documents aborts
`bench migrate`. On cvsqatar the company default is 'Petty Cash Logistics - D',
an untyped Asset account, so this touches it, 'Petty Cash Admin/HR - D' and
'Employee Advance - D'.

Only untyped accounts are changed - an account already typed (e.g. 'Petty
Cash - D', type Cash) is a deliberate choice and is left for a person to
decide. Accounts used only by cancelled advances are ignored.

Consequence, agreed before shipping: GL entries on these accounts now need a
party, and their balances show in receivable reports.

Runs pre_model_sync so it lands before the hrms patch. Uses db.set_value, not
a document save, because the Account schema is not yet synced at that point.
Idempotent, and safe on v15: nothing there reads the type until hrms updates.
"""

import frappe


def advance_accounts():
	used = frappe.get_all("Employee Advance",
						  filters={"docstatus": ["<", 2], "advance_account": ["is", "set"]},
						  pluck="advance_account", distinct=True)
	defaults = frappe.get_all("Company",
							  filters={"default_employee_advance_account": ["is", "set"]},
							  pluck="default_employee_advance_account")
	return sorted(set(used) | set(defaults))


def execute():
	if(not frappe.db.has_table("Employee Advance")):
		return

	changed, skipped = [], []
	for name in advance_accounts():
		account = frappe.db.get_value("Account", name,
									  ["account_type", "root_type", "is_group"], as_dict=True)
		if(not account or account.account_type == "Receivable"):
			continue
		if(account.account_type or account.is_group or account.root_type != "Asset"):
			skipped.append((name, account.account_type or account.root_type))
			continue
		frappe.db.set_value("Account", name, "account_type", "Receivable")
		changed.append(name)

	print(f"Employee advance accounts set to Receivable: {changed or 'none'}")
	for name, reason in skipped:
		print(f"  SKIPPED {name!r}: {reason}")
