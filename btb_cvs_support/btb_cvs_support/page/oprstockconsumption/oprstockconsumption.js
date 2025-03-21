frappe.pages['oprstockconsumption'].on_page_load = function (wrapper) {
	new consumptionPage(wrapper);
}

consumptionPage = Class.extend({
	init: function (wrapper) {
		this.page = frappe.ui.make_app_page({
			parent: wrapper,
			title: 'First',
			single_column: true
		});
		this.make();
	},
	make: function () {
		$(frappe.render_template(`oprstockconsumption`, this)).appendTo(this.page);
	}
})