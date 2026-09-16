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

	const RANGES = [7, 30, 90];
	let active_days = 30;
	let charts = {};
	// The currency the figures are denominated in, which is whatever Triple
	// Whale aggregated in rather than the site default. Set from each response.
	let currency = frappe.boot.sysdefaults.currency;

	$(page.body).html(`
		<div class="tw-page">
			<div id="tw-state" class="tw-state-bar"></div>

			<div class="tw-toolbar">
				<div class="tw-range">
					${RANGES.map(
						(d) =>
							`<button type="button" class="tw-range-btn ${
								d === active_days ? "tw-range-active" : ""
							}" data-days="${d}">${d}D</button>`
					).join("")}
				</div>
				<div id="tw-period" class="tw-period"></div>
			</div>

			<div id="tw-kpis" class="tw-kpi-grid"></div>

			<div class="tw-grid-2">
				<div class="tw-card">
					<div class="tw-card-head">
						<h5>Revenue vs Ad Spend</h5>
						<span class="tw-legend">
							<i class="tw-dot tw-dot-rev"></i>Revenue
							<i class="tw-dot tw-dot-spend"></i>Spend
						</span>
					</div>
					<div id="tw-chart-revenue" class="tw-chart"></div>
				</div>
				<div class="tw-card">
					<div class="tw-card-head">
						<h5>Efficiency</h5>
						<span class="tw-legend"><i class="tw-dot tw-dot-mer"></i>MER</span>
					</div>
					<div id="tw-chart-mer" class="tw-chart"></div>
				</div>
			</div>

			<div class="tw-grid-2">
				<div class="tw-card">
					<div class="tw-card-head"><h5>Spend by Channel</h5></div>
					<div id="tw-chart-channel" class="tw-chart"></div>
				</div>
				<div class="tw-card">
					<div class="tw-card-head"><h5>New vs Returning Revenue</h5></div>
					<div id="tw-chart-customers" class="tw-chart"></div>
				</div>
			</div>

			<div class="tw-card">
				<div class="tw-card-head"><h5>Channel Performance</h5></div>
				<div id="tw-channels"></div>
			</div>

			<div class="tw-card">
				<div class="tw-card-head">
					<h5>Products</h5>
					<span class="tw-legend tw-muted">Top 25 by revenue</span>
				</div>
				<div id="tw-products"></div>
			</div>
		</div>
	`);

	$(page.body).on("click", ".tw-range-btn", function () {
		active_days = parseInt($(this).data("days"), 10);
		$(".tw-range-btn").removeClass("tw-range-active");
		$(this).addClass("tw-range-active");
		load();
	});

	// ---- formatting -------------------------------------------------------

	const nf = (v, d = 0) =>
		v === null || v === undefined
			? "—"
			: Number(v).toLocaleString(undefined, {
					minimumFractionDigits: d,
					maximumFractionDigits: d,
			  });

	function money(v) {
		if (v === null || v === undefined) return "—";
		const sym = frappe.model.get_currency_symbol
			? frappe.model.get_currency_symbol(currency) || ""
			: "";
		const n = Number(v);
		const abs = Math.abs(n);
		const sign = n < 0 ? "-" : "";
		// Indian numbering groups by lakh and crore; everywhere else by
		// thousand and million, so the abbreviation has to follow the
		// currency rather than being fixed.
		if (currency === "INR") {
			if (abs >= 1e7) return `${sign}${sym}${(abs / 1e7).toFixed(2)}Cr`;
			if (abs >= 1e5) return `${sign}${sym}${(abs / 1e5).toFixed(2)}L`;
		} else {
			if (abs >= 1e9) return `${sign}${sym}${(abs / 1e9).toFixed(2)}B`;
			if (abs >= 1e6) return `${sign}${sym}${(abs / 1e6).toFixed(2)}M`;
		}
		if (abs >= 1e3) return `${sign}${sym}${(abs / 1e3).toFixed(1)}k`;
		return `${sign}${sym}${nf(abs, 0)}`;
	}

	const pct = (v) => (v === null || v === undefined ? "—" : `${Number(v).toFixed(1)}%`);
	const mult = (v) => (v === null || v === undefined ? "—" : `${Number(v).toFixed(2)}x`);
	const esc = (v) => frappe.utils.escape_html(String(v == null ? "" : v));

	function delta(cur, prev) {
		if (cur == null || prev == null || !prev) return "";
		const change = ((cur - prev) / Math.abs(prev)) * 100;
		if (!isFinite(change)) return "";
		const dir = change >= 0 ? "up" : "down";
		const arrow = change >= 0 ? "↑" : "↓";
		return `<span class="tw-delta tw-delta-${dir}">${arrow} ${Math.abs(change).toFixed(
			0
		)}%</span>`;
	}

	// ---- KPI cards --------------------------------------------------------

	function spark(values, color) {
		if (!values || values.length < 2) return "";
		const w = 120;
		const h = 28;
		const nums = values.map((v) => Number(v) || 0);
		const min = Math.min(...nums);
		const max = Math.max(...nums);
		const span = max - min || 1;
		const step = w / (nums.length - 1);
		const pts = nums
			.map((v, i) => `${(i * step).toFixed(1)},${(h - ((v - min) / span) * h).toFixed(1)}`)
			.join(" ");
		return `<svg class="tw-spark" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none">
			<polyline points="${pts}" fill="none" stroke="${color}" stroke-width="1.5"
				stroke-linejoin="round" stroke-linecap="round"/>
		</svg>`;
	}

	function kpi(o) {
		return `
			<div class="tw-kpi ${o.accent ? "tw-kpi-accent" : ""}">
				<div class="tw-kpi-top">
					<span class="tw-kpi-label">${esc(o.label)}</span>
					${o.delta || ""}
				</div>
				<div class="tw-kpi-value">${o.value}</div>
				<div class="tw-kpi-foot">
					<span class="tw-kpi-hint">${esc(o.hint || "")}</span>
					${o.spark || ""}
				</div>
			</div>`;
	}

	function render_overview(d) {
		if (d.currency) currency = d.currency;
		const t = d.totals || {};
		const p = d.previous || {};
		const s = d.series || [];

		$("#tw-period").html(
			s.length
				? `${frappe.datetime.str_to_user(d.period.start)} – ${frappe.datetime.str_to_user(
						d.period.end
				  )} · ${s.length} days · ${esc(currency)}`
				: ""
		);

		if (!s.length) {
			$("#tw-kpis").html(
				`<div class="tw-empty tw-empty-wide">
					<div class="tw-empty-title">No metrics yet</div>
					<div>Run a sync to pull this period in.</div>
				</div>`
			);
			destroy_charts();
			return;
		}

		const col = (k) => s.map((r) => r[k] || 0);

		$("#tw-kpis").html(
			[
				kpi({
					label: "Total Sales",
					value: money(t.total_sales),
					delta: delta(t.total_sales, p.total_sales),
					spark: spark(col("total_sales"), "#2490ef"),
					accent: true,
				}),
				kpi({
					label: "Ad Spend",
					value: money(t.spend),
					delta: delta(t.spend, p.spend),
					spark: spark(col("spend"), "#f59e0b"),
				}),
				kpi({
					label: "MER",
					value: mult(t.mer),
					hint: "revenue per ad spend",
					delta: delta(t.mer, p.mer),
					spark: spark(col("mer"), "#8b5cf6"),
				}),
				kpi({
					label: "Net Profit",
					value: money(t.net_profit),
					delta: delta(t.net_profit, p.net_profit),
					spark: spark(col("net_profit"), "#10b981"),
				}),
				kpi({
					label: "Orders",
					value: nf(t.orders),
					delta: delta(t.orders, p.orders),
					spark: spark(col("orders"), "#2490ef"),
				}),
				kpi({
					label: "AOV",
					value: money(t.aov),
					delta: delta(t.aov, p.aov),
				}),
				kpi({
					label: "CAC",
					value: money(t.ncpa),
					hint: t.ncpa == null ? "no new customers recorded" : "per new customer",
				}),
				kpi({
					label: "New Customer Share",
					value: pct(t.new_customer_share),
					hint: "of revenue",
				}),
				kpi({
					label: "LTV : CAC",
					value: mult(t.ltv_cac_ratio),
					hint: "above 3x is healthy",
				}),
				kpi({ label: "Site CVR", value: pct(t.site_conversion_rate) }),
				kpi({ label: "Visitors", value: nf(t.visitors) }),
				kpi({ label: "Refunded", value: money(t.total_refunded_price) }),
				kpi({ label: "Return Rate", value: pct(t.returns_percent) }),
			].join("")
		);

		draw_revenue(s);
		draw_mer(s);
		draw_customers(t);
	}

	// ---- charts -----------------------------------------------------------

	function destroy_charts() {
		Object.keys(charts).forEach((k) => {
			try {
				charts[k] && charts[k].destroy && charts[k].destroy();
			} catch (e) {
				// a chart that never rendered has nothing to tear down
			}
		});
		charts = {};
	}

	const short_date = (d) =>
		frappe.datetime
			.str_to_obj(d)
			.toLocaleDateString(undefined, { day: "numeric", month: "short" });

	function draw_revenue(s) {
		charts.revenue = new frappe.Chart("#tw-chart-revenue", {
			type: "axis-mixed",
			height: 240,
			animate: false,
			colors: ["#2490ef", "#f59e0b"],
			axisOptions: { xIsSeries: true, xAxisMode: "tick" },
			lineOptions: { hideDots: 1, regionFill: 1 },
			data: {
				labels: s.map((r) => short_date(r.metric_date)),
				datasets: [
					{
						name: "Revenue",
						chartType: "line",
						values: s.map((r) => r.total_sales || 0),
					},
					{ name: "Ad Spend", chartType: "bar", values: s.map((r) => r.spend || 0) },
				],
			},
		});
	}

	function draw_mer(s) {
		charts.mer = new frappe.Chart("#tw-chart-mer", {
			type: "line",
			height: 240,
			animate: false,
			colors: ["#8b5cf6"],
			axisOptions: { xIsSeries: true, xAxisMode: "tick" },
			lineOptions: { hideDots: 1, regionFill: 1 },
			data: {
				labels: s.map((r) => short_date(r.metric_date)),
				datasets: [{ name: "MER", values: s.map((r) => r.mer || 0) }],
			},
		});
	}

	function draw_customers(t) {
		const nc = t.new_customer_revenue || 0;
		const rc = t.returning_customer_revenue || 0;
		if (!nc && !rc) {
			$("#tw-chart-customers").html(`<div class="tw-empty">No customer split yet.</div>`);
			return;
		}
		charts.customers = new frappe.Chart("#tw-chart-customers", {
			type: "donut",
			height: 240,
			animate: false,
			colors: ["#2490ef", "#10b981"],
			data: { labels: ["New", "Returning"], datasets: [{ values: [nc, rc] }] },
		});
	}

	function draw_channel_chart(rows) {
		const withSpend = (rows || []).filter((r) => (r.spend || 0) > 0);
		if (!withSpend.length) {
			$("#tw-chart-channel").html(`<div class="tw-empty">No ad spend yet.</div>`);
			return;
		}
		charts.channel = new frappe.Chart("#tw-chart-channel", {
			type: "donut",
			height: 240,
			animate: false,
			colors: ["#1877f2", "#ea4335", "#111111", "#e60023", "#ff9900", "#8b5cf6"],
			data: {
				labels: withSpend.map((r) => channel_label(r.channel)),
				datasets: [{ values: withSpend.map((r) => r.spend || 0) }],
			},
		});
	}

	// ---- tables -----------------------------------------------------------

	function channel_label(id) {
		return String(id || "")
			.replace(/-ads$/, "")
			.replace(/-/g, " ")
			.replace(/\b\w/g, (ch) => ch.toUpperCase());
	}

	function bar_cell(value, max, color) {
		const w = max ? Math.max(2, (Math.abs(value || 0) / max) * 100) : 0;
		return `<div class="tw-barcell">
			<span class="tw-barcell-v">${money(value)}</span>
			<span class="tw-barcell-track"><span class="tw-barcell-fill"
				style="width:${w.toFixed(1)}%;background:${color}"></span></span>
		</div>`;
	}

	function roas_pill(v) {
		if (v === null || v === undefined) return "—";
		const n = Number(v);
		const cls = n >= 3 ? "good" : n >= 1 ? "ok" : "bad";
		return `<span class="tw-roas tw-roas-${cls}">${n.toFixed(2)}x</span>`;
	}

	function render_channels(d) {
		if (d.currency) currency = d.currency;
		const rows = d.channels || [];
		if (!rows.length) {
			$("#tw-channels").html(`<div class="tw-empty">No ad data for this period yet.</div>`);
			draw_channel_chart([]);
			return;
		}
		draw_channel_chart(rows);

		const maxSpend = Math.max(...rows.map((r) => r.spend || 0));
		const body = rows
			.map(
				(r) => `
			<tr>
				<td><span class="tw-chan">${esc(channel_label(r.channel))}</span></td>
				<td class="tw-bar">${bar_cell(r.spend, maxSpend, "#f59e0b")}</td>
				<td class="tw-right">${nf(r.impressions)}</td>
				<td class="tw-right">${nf(r.clicks)}</td>
				<td class="tw-right">${pct(r.ctr)}</td>
				<td class="tw-right">${money(r.cpc)}</td>
				<td class="tw-right">${money(r.conversion_value)}</td>
				<td class="tw-right">${roas_pill(r.roas)}</td>
			</tr>`
			)
			.join("");

		$("#tw-channels").html(`
			<div class="tw-table-wrap">
				<table class="tw-table">
					<thead><tr>
						<th>Channel</th><th>Spend</th>
						<th class="tw-right">Impressions</th><th class="tw-right">Clicks</th>
						<th class="tw-right">CTR</th><th class="tw-right">CPC</th>
						<th class="tw-right">Conv. Value</th><th class="tw-right">ROAS</th>
					</tr></thead>
					<tbody>${body}</tbody>
				</table>
			</div>`);
	}

	function render_products(d) {
		if (d.currency) currency = d.currency;
		const rows = d.products || [];
		if (!rows.length) {
			$("#tw-products").html(
				`<div class="tw-empty">No product metrics for this period yet.</div>`
			);
			return;
		}
		const maxRev = Math.max(...rows.map((r) => r.product_revenue || 0));
		const body = rows
			.map((r) => {
				const title = r.product_title || r.sku || r.product_id;
				const link = r.item
					? `<a href="/app/item/${encodeURIComponent(r.item)}">${esc(title)}</a>`
					: esc(title);
				const sub = [
					r.sku ? esc(r.sku) : "",
					r.vendor ? esc(r.vendor) : "",
					r.item ? "" : `<span class="tw-unlinked">unlinked</span>`,
				]
					.filter(Boolean)
					.join(" · ");
				return `
				<tr>
					<td>
						<div class="tw-prod">${link}</div>
						<div class="tw-sub">${sub}</div>
					</td>
					<td class="tw-right">${nf(r.units_sold)}</td>
					<td class="tw-bar">${bar_cell(r.product_revenue, maxRev, "#2490ef")}</td>
					<td class="tw-right">${money(r.attributed_spend)}</td>
					<td class="tw-right">${roas_pill(r.attributed_roas)}</td>
					<td class="tw-right">${pct(r.conversion_rate)}</td>
					<td class="tw-right">${pct(r.return_rate)}</td>
				</tr>`;
			})
			.join("");

		$("#tw-products").html(`
			<div class="tw-table-wrap">
				<table class="tw-table">
					<thead><tr>
						<th>Product</th><th class="tw-right">Units</th><th>Revenue</th>
						<th class="tw-right">Ad Spend</th><th class="tw-right">ROAS</th>
						<th class="tw-right">CVR</th><th class="tw-right">Returns</th>
					</tr></thead>
					<tbody>${body}</tbody>
				</table>
			</div>`);
	}

	// ---- state bar --------------------------------------------------------

	function render_state(s) {
		if (!s.is_enabled || !s.has_key) {
			$("#tw-state").html(`
				<div class="tw-state-warn">
					<i class="fa fa-exclamation-triangle"></i>
					<span><strong>Not configured.</strong>
					Add an API key and shop domain in Settings, then enable the connector.</span>
				</div>`);
			return;
		}
		const pills = ["metrics", "attribution", "ads"]
			.map((k) => {
				const l = s.last_sync[k];
				if (!l) return `<span class="tw-pill tw-pill-grey">${k} · never</span>`;
				const cls =
					l.status === "success" ? "green" : l.status === "failed" ? "red" : "blue";
				const when =
					l.status === "success"
						? frappe.datetime.comment_when(l.started_at)
						: l.status;
				return `<span class="tw-pill tw-pill-${cls}">${k} · ${when}</span>`;
			})
			.join("");
		$("#tw-state").html(`
			<div class="tw-state-left">
				<strong>${esc(s.shop_domain)}</strong>
				<span class="tw-muted">${nf(s.daily_rows)} days · ${nf(
			s.product_rows
		)} products · ${nf(s.ad_rows)} channel rows</span>
			</div>
			<div class="tw-state-pills">${pills}</div>`);
	}

	// ---- io ---------------------------------------------------------------

	function run_sync() {
		const methods = [
			"alaiy_os_connector_triple_whale.api.sync.trigger_metrics_sync",
			"alaiy_os_connector_triple_whale.api.sync.trigger_attribution_sync",
			"alaiy_os_connector_triple_whale.api.sync.trigger_ads_sync",
		];
		Promise.all(methods.map((method) => frappe.call({ method }))).then(() => {
			frappe.show_alert({
				message: __("Syncs queued — refresh in a moment"),
				indicator: "blue",
			});
		});
	}

	function load() {
		destroy_charts();
		const args = { days: active_days };
		frappe.call({
			method: "alaiy_os_connector_triple_whale.api.dashboard.get_state",
			callback: (r) => r.message && render_state(r.message),
		});
		frappe.call({
			method: "alaiy_os_connector_triple_whale.api.dashboard.get_overview",
			args,
			callback: (r) => r.message && render_overview(r.message),
		});
		frappe.call({
			method: "alaiy_os_connector_triple_whale.api.dashboard.get_channels",
			args,
			callback: (r) => r.message && render_channels(r.message),
		});
		frappe.call({
			method: "alaiy_os_connector_triple_whale.api.dashboard.get_top_products",
			args: { days: active_days, limit: 25 },
			callback: (r) => r.message && render_products(r.message),
		});
	}

	load();
};
