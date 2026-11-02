// Core's show_page calls add_custom_cards_in_content on every navigation, and the parsed content
// stays on the workspace, so "Custom Documents" and "Custom Reports" were added again on each
// revisit. Skip the call when the cards are already there.
(() => {
	const CUSTOM_CARDS = ["Custom Documents", "Custom Reports"];
	const proto = frappe.views.Workspace.prototype;
	const add_custom_cards_in_content = proto.add_custom_cards_in_content;

	proto.add_custom_cards_in_content = function () {
		const has_custom_cards = this.content.some(
			(block) => block.type == "card" && CUSTOM_CARDS.includes(block.data?.card_name)
		);
		if (has_custom_cards) return;
		return add_custom_cards_in_content.apply(this, arguments);
	};
})();
