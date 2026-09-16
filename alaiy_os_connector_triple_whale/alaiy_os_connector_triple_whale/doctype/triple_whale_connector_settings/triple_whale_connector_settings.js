frappe.ui.form.on("Triple Whale Connector Settings", {
	refresh(frm) {
		frm.page.set_title(__("Triple Whale Settings"));

		// Mount the shared Alaiy OS connector status card + password reveal.
		alaiy_os.connector_card.mount(frm, "triple_whale");
		alaiy_os.connector_card.setup_password_reveal(
			frm,
			"triple_whale_api_key",
			"triple_whale"
		);

		// Auto-fill Company with the site default if empty.
		if (!frm.doc.triple_whale_company) {
			frappe.db
				.get_single_value("Global Defaults", "default_company")
				.then((company) => {
					if (company) frm.set_value("triple_whale_company", company);
				});
		}

		render_overview(frm);

		frm.add_custom_button(__("Open Dashboard"), () =>
			frappe.set_route("triple-whale")
		);

		frm.add_custom_button(
			__("Test Connection"),
			() => {
				frappe.call({
					// Go through the registry wrapper (not test_connection directly)
					// so a successful test also flips the "Connector Status" card at
					// the top of this form from "Not configured" to "Connected".
					method: "alaiy_os.api.connectors.test_connector",
					args: { connector_id: "triple_whale" },
					callback(r) {
						const res = r.message || {};
						frappe.show_alert(
							{
								message:
									res.message ||
									(res.success ? __("Connected") : __("Connection failed")),
								indicator: res.success ? "green" : "red",
							},
							res.success ? 7 : 9
						);
						frm.reload_doc();
					},
				});
			},
			__("Actions")
		);

		[
			["Sync Store Metrics", "trigger_metrics_sync"],
			["Sync Product Attribution", "trigger_attribution_sync"],
			["Sync Ad Channels", "trigger_ads_sync"],
		].forEach(([label, method]) => {
			frm.add_custom_button(
				__(label),
				() => {
					frappe.call({
						method: `alaiy_os_connector_triple_whale.api.sync.${method}`,
						callback: () => {
							frappe.show_alert(
								{ message: __("{0} queued", [label]), indicator: "blue" },
								5
							);
							setTimeout(() => render_overview(frm), 2000);
						},
					});
				},
				__("Actions")
			);
		});

		frm.add_custom_button(
			__("Sync Everything"),
			() => {
				const methods = [
					"trigger_metrics_sync",
					"trigger_attribution_sync",
					"trigger_ads_sync",
				];
				Promise.all(
					methods.map((m) =>
						frappe.call({
							method: `alaiy_os_connector_triple_whale.api.sync.${m}`,
						})
					)
				).then(() => {
					frappe.show_alert(
						{ message: __("All syncs queued"), indicator: "blue" },
						5
					);
					setTimeout(() => render_overview(frm), 2000);
				});
			},
			__("Actions")
		);
	},
});

function render_overview(frm) {
	frappe.call({
		method:
			"alaiy_os_connector_triple_whale.api.dashboard.get_connection_overview",
		callback(r) {
			if (!r.message) return;
			paint(frm, r.message);
		},
	});
}

function paint(frm, d) {
	const esc = (v) => frappe.utils.escape_html(String(v == null ? "" : v));
	const nf = (v) => Number(v || 0).toLocaleString();

	const sync_rows = (d.syncs || [])
		.map((s) => {
			const l = s.last;
			let status = `<span class="twc-pill twc-grey">never run</span>`;
			let detail = "—";
			if (l) {
				const cls =
					l.status === "success"
						? "twc-green"
						: l.status === "failed"
						? "twc-red"
						: "twc-blue";
				status = `<span class="twc-pill ${cls}">${esc(l.status)}</span>`;
				if (l.status === "failed") {
					// The first line of a traceback is the only part that fits, and
					// is usually the message that identifies the failure.
					const first = String(l.error_message || "")
						.split("\n")
						.filter(Boolean)
						.pop();
					detail = `<span class="twc-err">${esc(
						(first || "").slice(0, 120)
					)}</span>`;
				} else {
					detail = `${nf(l.items_created)} new · ${nf(l.items_updated)} updated${
						l.items_failed ? ` · ${nf(l.items_failed)} failed` : ""
					}`;
				}
			}
			const when = l && l.started_at ? frappe.datetime.comment_when(l.started_at) : "—";
			const sched =
				s.interval === "Disabled"
					? `<span class="twc-muted">manual only</span>`
					: esc(s.interval);
			return `
			<tr>
				<td><strong>${esc(s.label)}</strong></td>
				<td>${status}</td>
				<td>${when}</td>
				<td>${detail}</td>
				<td>${sched}</td>
				<td class="twc-right">
					<a href="/app/${frappe.router.slug(s.doctype)}">${nf(s.rows)} rows</a>
				</td>
			</tr>`;
		})
		.join("");

	const integ = d.integrations || {};
	const platforms = integ.platforms || [];
	const counts = integ.metric_counts || {};
	const channels = integ.ad_channels || [];
	const spending = new Set(
		channels.map((c) =>
			String(c.channel || "")
				.replace(/-ads$/, "")
				.toLowerCase()
		)
	);

	const chips = platforms.length
		? platforms
				.map((p) => {
					const live = spending.has(p.split(" ")[0].toLowerCase());
					return `<span class="twc-chip ${live ? "twc-chip-live" : ""}"
						title="${nf(counts[p])} metrics reported">
						${live ? '<i class="twc-live"></i>' : ""}${esc(p)}</span>`;
				})
				.join("")
		: `<span class="twc-muted">Nothing detected yet — run a sync first.</span>`;

	const spend_note = channels.length
		? `<div class="twc-note">Ad spend in the last 30 days from ${channels
				.map((c) => esc(c.channel.replace(/-ads$/, "")))
				.join(", ")}.</div>`
		: "";

	const html = `
	<div class="twc-wrap">
		<div class="twc-block">
			<div class="twc-head">
				<h5>${esc(d.shop_domain || "No shop domain set")}</h5>
				<span class="twc-pill ${d.is_enabled ? "twc-green" : "twc-grey"}">
					${d.is_enabled ? "Enabled" : "Disabled"}</span>
				<span class="twc-pill ${d.has_key ? "twc-green" : "twc-red"}">
					${d.has_key ? "API key set" : "No API key"}</span>
			</div>
			<div class="twc-note">
				Each sync re-fetches the last ${esc(d.lookback_days || 7)} days, because
				Triple Whale restates attribution for several days after an order.
			</div>
		</div>

		<div class="twc-block">
			<div class="twc-label">Syncs</div>
			<table class="twc-table">
				<thead><tr>
					<th>What</th><th>Status</th><th>Last run</th>
					<th>Result</th><th>Schedule</th><th class="twc-right">Stored</th>
				</tr></thead>
				<tbody>${sync_rows}</tbody>
			</table>
		</div>

		<div class="twc-block">
			<div class="twc-label">Connected in Triple Whale</div>
			<div class="twc-chips">${chips}</div>
			${spend_note}
			<div class="twc-note twc-muted">
				Detected from the metrics this account actually reports, not a fixed
				list — a platform connected in Triple Whale appears here after the
				next sync. A dot marks one currently spending.
			</div>
		</div>
	</div>`;

	frm.get_field("is_enabled").$wrapper.after(
		`<div class="twc-mount">${html}</div>`
	);
	frm.$wrapper.find(".twc-mount").not(":last").remove();
	inject_styles();
}

function inject_styles() {
	if (document.getElementById("twc-styles")) return;
	const css = `
	.twc-mount { margin: 12px 0 4px; }
	.twc-wrap { display: flex; flex-direction: column; gap: 14px; }
	.twc-block {
		border: 1px solid var(--border-color); border-radius: 8px;
		padding: 12px 14px; background: var(--card-bg);
	}
	.twc-head { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
	.twc-head h5 { margin: 0; font-size: 13px; font-weight: 600; }
	.twc-label {
		font-size: 10px; font-weight: 600; letter-spacing: .05em;
		text-transform: uppercase; color: var(--text-muted); margin-bottom: 8px;
	}
	.twc-note { font-size: 11px; color: var(--text-muted); margin-top: 8px; }
	.twc-muted { color: var(--text-muted); }
	.twc-right { text-align: right; }
	.twc-pill {
		padding: 2px 8px; border-radius: 999px; font-size: 10px;
		font-weight: 600; text-transform: capitalize; white-space: nowrap;
	}
	.twc-green { background: #dcfce7; color: #166534; }
	.twc-red   { background: #fee2e2; color: #991b1b; }
	.twc-blue  { background: #dbeafe; color: #1e40af; }
	.twc-grey  { background: #f3f4f6; color: #4b5563; }
	.twc-err { color: #991b1b; font-size: 11px; }
	.twc-table { width: 100%; border-collapse: collapse; font-size: 12px; }
	.twc-table th {
		text-align: left; font-size: 10px; text-transform: uppercase;
		letter-spacing: .04em; color: var(--text-muted); font-weight: 600;
		padding: 6px 8px; border-bottom: 1px solid var(--border-color);
	}
	.twc-table td {
		padding: 8px; border-bottom: 1px solid var(--border-color);
		vertical-align: middle;
	}
	.twc-table tbody tr:last-child td { border-bottom: 0; }
	.twc-chips { display: flex; flex-wrap: wrap; gap: 6px; }
	.twc-chip {
		display: inline-flex; align-items: center; gap: 5px;
		padding: 4px 10px; border-radius: 999px; font-size: 11px;
		border: 1px solid var(--border-color); background: var(--bg-light-gray);
	}
	.twc-chip-live { border-color: #16a34a; }
	.twc-live {
		width: 6px; height: 6px; border-radius: 50%;
		background: #16a34a; display: inline-block;
	}
	[data-theme="dark"] .twc-green { background: #14532d; color: #bbf7d0; }
	[data-theme="dark"] .twc-red { background: #7f1d1d; color: #fecaca; }
	[data-theme="dark"] .twc-blue { background: #1e3a8a; color: #bfdbfe; }
	[data-theme="dark"] .twc-grey { background: #374151; color: #d1d5db; }
	[data-theme="dark"] .twc-err { color: #fecaca; }`;
	$("<style id='twc-styles'></style>").text(css).appendTo(document.head);
}
