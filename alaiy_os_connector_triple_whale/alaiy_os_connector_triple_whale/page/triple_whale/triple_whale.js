frappe.pages["triple-whale"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: "Triple Whale",
		single_column: true,
	});

	page.set_secondary_action(
		"Settings",
		() => frappe.set_route("Form", "Triple Whale Connector Settings"),
		"settings"
	);

	page.set_primary_action("Sync Now", () => run_sync(), "refresh");

	const ranges = [7, 30, 90];
	let active_days = 30;

	$(page.body).html(`
		<div class="tw-page">
			<div class="tw-card">
				<div class="tw-card-body">
					<div id="tw-state" class="tw-state"></div>
				</div>
			</div>

			<div class="tw-range">
				${ranges
					.map(
						(d) =>
							`<button type="button" class="tw-range-btn ${
								d === active_days ? "tw-range-active" : ""
							}" data-days="${d}">Last ${d} days</button>`
					)
					.join("")}
			</div>

			<div class="tw-card">
				<div class="tw-card-header">
					<span class="tw-icon-badge"><i class="fa fa-line-chart"></i></span>
					<div class="tw-card-header-text">
						<h5>Overview</h5>
						<p>Blended performance across every channel.</p>
					</div>
				</div>
				<div class="tw-card-body">
					<div id="tw-kpis" class="tw-kpi-grid"></div>
				</div>
			</div>

			<div class="tw-card">
				<div class="tw-card-header">
					<span class="tw-icon-badge"><i class="fa fa-cube"></i></span>
					<div class="tw-card-header-text">
						<h5>Products</h5>
						<p>Per-product revenue, funnel and returns.</p>
					</div>
				</div>
				<div class="tw-card-body">
					<div id="tw-products"></div>
				</div>
			</div>
		</div>
	`);

	$(page.body).on("click", ".tw-range-btn", function () {
		active_days = parseInt($(this).data("days"), 10);
		$(".tw-range-btn").removeClass("tw-range-active");
		$(this).addClass("tw-range-active");
		load();
	});

	function fmt_money(v) {
		if (v === null || v === undefined) return "—";
		return format_currency(v);
	}

	function fmt_num(v, digits) {
		if (v === null || v === undefined) return "—";
		return Number(v).toLocaleString(undefined, {
			minimumFractionDigits: digits || 0,
			maximumFractionDigits: digits || 0,
		});
	}

	function fmt_pct(v) {
		if (v === null || v === undefined) return "—";
		return `${Number(v).toFixed(1)}%`;
	}

	function fmt_x(v) {
		if (v === null || v === undefined) return "—";
		return `${Number(v).toFixed(2)}x`;
	}

	function kpi(label, value, hint) {
		return `
			<div class="tw-kpi">
				<div class="tw-kpi-label">${frappe.utils.escape_html(label)}</div>
				<div class="tw-kpi-value">${value}</div>
				${hint ? `<div class="tw-kpi-hint">${frappe.utils.escape_html(hint)}</div>` : ""}
			</div>`;
	}

	function render_state(s) {
		if (!s.is_enabled || !s.has_key) {
			$("#tw-state").html(`
				<div class="tw-state-row tw-state-warn">
					<i class="fa fa-exclamation-triangle"></i>
					<div>
						<strong>Not configured.</strong>
						Add an API key and shop domain in Settings, then enable the connector.
					</div>
				</div>`);
			return;
		}

		const parts = ["metrics", "attribution"].map((k) => {
			const l = s.last_sync[k];
			if (!l) return `<span class="tw-pill tw-pill-grey">${k}: never run</span>`;
			const cls =
				l.status === "success"
					? "tw-pill-green"
					: l.status === "failed"
					? "tw-pill-red"
					: "tw-pill-blue";
			const when = l.started_at ? frappe.datetime.comment_when(l.started_at) : "";
			return `<span class="tw-pill ${cls}">${k}: ${l.status} ${when}</span>`;
		});

		$("#tw-state").html(`
			<div class="tw-state-row">
				<div class="tw-state-shop">
					<strong>${frappe.utils.escape_html(s.shop_domain || "")}</strong>
					<span class="tw-text-muted">${fmt_num(s.daily_rows)} days · ${fmt_num(
			s.product_rows
		)} product rows cached</span>
				</div>
				<div class="tw-state-pills">${parts.join("")}</div>
			</div>`);
	}

	function render_overview(d) {
		const t = d.totals || {};
		if (!d.period.days) {
			$("#tw-kpis").html(
				`<div class="tw-empty">No metrics for this period yet. Run a sync to pull them in.</div>`
			);
			return;
		}
		$("#tw-kpis").html(
			[
				kpi("Total Sales", fmt_money(t.total_sales)),
				kpi("Ad Spend", fmt_money(t.spend)),
				kpi("MER", fmt_x(t.mer), "Revenue per ad dollar"),
				kpi("Net Profit", fmt_money(t.net_profit)),
				kpi("Net Margin", fmt_pct(t.net_margin)),
				kpi("POAS", fmt_x(t.poas), "Profit per ad dollar"),
				kpi("Orders", fmt_num(t.orders)),
				kpi("AOV", fmt_money(t.aov)),
				kpi("New Customer Revenue", fmt_money(t.new_customer_revenue)),
				kpi("Returning Revenue", fmt_money(t.returning_customer_revenue)),
				kpi("Refunded", fmt_money(t.total_refunded_price)),
				kpi("Return Rate", fmt_pct(t.returns_percent)),
			].join("")
		);
	}

	function render_products(d) {
		const rows = d.products || [];
		if (!rows.length) {
			$("#tw-products").html(
				`<div class="tw-empty">No product metrics for this period yet.</div>`
			);
			return;
		}

		const body = rows
			.map((r) => {
				const title = r.product_title || r.sku || r.product_id;
				const link = r.item
					? `<a href="/app/item/${encodeURIComponent(r.item)}">${frappe.utils.escape_html(
							title
					  )}</a>`
					: frappe.utils.escape_html(title);
				return `
				<tr>
					<td>
						${link}
						${r.sku ? `<div class="tw-text-muted">${frappe.utils.escape_html(r.sku)}</div>` : ""}
					</td>
					<td class="tw-right">${fmt_num(r.units_sold)}</td>
					<td class="tw-right">${fmt_money(r.product_revenue)}</td>
					<td class="tw-right">${fmt_money(r.attributed_spend)}</td>
					<td class="tw-right">${fmt_x(r.attributed_roas)}</td>
					<td class="tw-right">${fmt_pct(r.conversion_rate)}</td>
					<td class="tw-right">${fmt_pct(r.return_rate)}</td>
				</tr>`;
			})
			.join("");

		$("#tw-products").html(`
			<div class="tw-table-wrap">
				<table class="tw-table">
					<thead>
						<tr>
							<th>Product</th>
							<th class="tw-right">Units</th>
							<th class="tw-right">Revenue</th>
							<th class="tw-right">Ad Spend</th>
							<th class="tw-right">ROAS</th>
							<th class="tw-right">CVR</th>
							<th class="tw-right">Returns</th>
						</tr>
					</thead>
					<tbody>${body}</tbody>
				</table>
			</div>`);
	}

	function run_sync() {
		frappe.call({
			method: "alaiy_os_connector_triple_whale.api.sync.trigger_metrics_sync",
			callback: () => {
				frappe.show_alert({ message: __("Sync queued"), indicator: "blue" });
				frappe.call({
					method:
						"alaiy_os_connector_triple_whale.api.sync.trigger_attribution_sync",
				});
			},
		});
	}

	function load() {
		frappe.call({
			method: "alaiy_os_connector_triple_whale.api.dashboard.get_state",
			callback: (r) => r.message && render_state(r.message),
		});
		frappe.call({
			method: "alaiy_os_connector_triple_whale.api.dashboard.get_overview",
			args: { days: active_days },
			callback: (r) => r.message && render_overview(r.message),
		});
		frappe.call({
			method: "alaiy_os_connector_triple_whale.api.dashboard.get_top_products",
			args: { days: active_days, limit: 25 },
			callback: (r) => r.message && render_products(r.message),
		});
	}

	load();
};
