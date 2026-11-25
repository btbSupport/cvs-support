// Copyright (c) 2025, BizTBaa and contributors
// For license information, please see license.txt

frappe.ui.form.on("FTOCountryWiseCost", {
	refresh(frm) {
		// Required is enforced by the controller (validate_boq_identifier); this only shows the asterisk.
		frm.toggle_reqd("boq_identifier", true);
	},
});
