// Large output documents (Quotation Format, BOQ, OPR BOQ) that OneDoc could not
// render in time are made in a background job (generator.run_fallback). When the
// job finishes it sends this event to the user who clicked, wherever they are in
// the desk; the bell (Notification Log) keeps the same message for later.
$(document).on("app_ready", function () {
	frappe.realtime.on("btb_document_ready", function (data) {
		if (!data) return;
		const title = frappe.utils.escape_html(data.title || "");
		if (data.file_url) {
			frappe.show_alert({
				message: title + ' <a href="' + encodeURI(data.file_url) + '" target="_blank">' + __("Open") + "</a>",
				indicator: "green",
			}, 15);
		} else {
			frappe.show_alert({ message: title, indicator: "red" }, 15);
		}
		// Refresh the attachments if the user is on that document.
		if (cur_frm && cur_frm.doctype === data.doctype && cur_frm.docname === data.name && !cur_frm.is_dirty()) {
			cur_frm.reload_doc();
		}
	});
});
