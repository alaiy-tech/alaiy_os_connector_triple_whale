const TW_SYNC_TYPE_COLORS = {
	metrics: "blue",
	ads: "green",
	cohorts: "purple",
	attribution: "orange",
	webhook: "cyan",
};

const TW_TRIGGER_COLORS = {
	scheduled: "purple",
	manual: "pink",
	webhook: "cyan",
};

const TW_STATUS_COLORS = {
	queued: "grey",
	running: "blue",
	success: "green",
	failed: "red",
	skipped: "yellow",
};

function alaiy_pill(value, colors) {
	if (!value) return "";
	const color = colors[value] || "darkgrey";
	return `<span class="indicator-pill ${color} filterable" data-filter="=,${value}">
		<span>${frappe.utils.escape_html(value)}</span>
	</span>`;
}

frappe.listview_settings["Triple Whale Sync Log"] = {
	get_indicator(doc) {
		return [
			__(doc.status),
			TW_STATUS_COLORS[doc.status] || "darkgrey",
			`status,=,${doc.status}`,
		];
	},
	formatters: {
		sync_type: (value) => alaiy_pill(value, TW_SYNC_TYPE_COLORS),
		trigger: (value) => alaiy_pill(value, TW_TRIGGER_COLORS),
		status: (value) => alaiy_pill(value, TW_STATUS_COLORS),
	},
};
