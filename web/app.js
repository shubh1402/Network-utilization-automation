/* Network Utilization dashboard. No build step: plain JS + Chart.js.
 * Talks to the FastAPI backend, or renders an embedded snapshot
 * (window.NUA_SNAPSHOT) when published as a static demo page. */
(() => {
  "use strict";

  const $ = (sel) => document.querySelector(sel);
  const SNAPSHOT = window.NUA_SNAPSHOT || null;
  const LEVELS = [90, 80, 70];
  const LINKS = ["Primary", "Secondary"];
  const SOURCE_NAMES = { demo: "Demo data", zabbix: "Zabbix API", txt: "Zabbix TXT exports" };

  const state = { config: null, runs: [], run: null, active: null, site: null, chart: null };

  // ---------- helpers ----------
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  const pad = (n) => String(n).padStart(2, "0");
  const parseLocal = (iso) => {
    const [d, t = "00:00:00"] = iso.split("T");
    const [y, m, day] = d.split("-").map(Number);
    const [hh, mm, ss = 0] = t.split(":").map(Number);
    return new Date(y, m - 1, day, hh, mm, ss);
  };
  const hhmm = (date) => `${pad(date.getHours())}:${pad(date.getMinutes())}`;
  const timeOf = (iso) => (iso ? hhmm(parseLocal(iso)) : "–");
  const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  const dayShort = (date) => `${date.getDate()} ${MONTHS[date.getMonth()]}`;
  const dayLong = (iso) => parseLocal(iso).toLocaleDateString("en-GB", { weekday: "long", day: "numeric", month: "long", year: "numeric" });
  const minutes = (n) => (n < 60 ? `${n} min` : `${Math.floor(n / 60)} h ${n % 60 ? (n % 60) + " min" : ""}`.trim());
  const isoDate = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
  const levelOf = (v) => LEVELS.find((t) => v > t) || 0;

  async function api(path, options = {}) {
    const response = await fetch(path, { headers: { "Content-Type": "application/json" }, ...options });
    const body = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(body.detail || `${response.status} ${response.statusText}`);
    return body;
  }

  function notice(text, kind = "") {
    const el = $("#notice");
    el.hidden = !text;
    el.className = `notice ${kind}`;
    el.textContent = text || "";
  }

  // ---------- run form ----------
  function setupForm() {
    const today = state.config?.today ? parseLocal(state.config.today) : new Date();
    const yesterday = new Date(today); yesterday.setDate(today.getDate() - 1);
    for (const id of ["#date-from", "#date-to"]) {
      $(id).max = isoDate(today);
      $(id).value = isoDate(yesterday);
    }
    const sync = () => {
      const mode = $("#period-mode").value;
      $("#field-from").hidden = !(mode === "date" || mode === "range");
      $("#field-to").hidden = mode !== "range";
      $("#label-from").textContent = mode === "range" ? "From" : "Day";
    };
    $("#period-mode").addEventListener("change", sync);
    sync();

    $("#run-form").addEventListener("submit", async (event) => {
      event.preventDefault();
      if (SNAPSHOT) return;
      const mode = $("#period-mode").value;
      const body = { mode };
      if (mode === "date") body.date = $("#date-from").value;
      if (mode === "range") { body.from_date = $("#date-from").value; body.to_date = $("#date-to").value; }
      try {
        notice("");
        const created = await api("/api/runs", { method: "POST", body: JSON.stringify(body) });
        document.getElementById("first-run")?.remove();
        poll(created.id);
        state.runs = await api("/api/runs");
        renderHistory();
      } catch (error) {
        notice(`The report did not start: ${error.message}`, "error");
      }
    });
  }

  function setRunning(running) {
    document.body.classList.toggle("running", running);
    if (running && !state.run) {
      $("#headline").textContent = "Running the first report…";
      $("#facts").textContent = "Each stage below lights up as it finishes.";
    }
    const button = $("#run-button");
    button.disabled = running || !!SNAPSHOT;
    button.textContent = running ? "Running report…" : "Run report";
  }

  async function poll(id) {
    setRunning(true);
    try {
      const run = await api(`/api/runs/${id}`);
      state.active = run;
      renderPipeline(run);
      if (run.status === "queued" || run.status === "running") {
        setTimeout(() => poll(id), 350);
        return;
      }
      if (run.status === "succeeded") {
        state.run = run;
        renderRun();
      } else {
        notice(`The report failed: ${run.error}. The run log below shows where it stopped.`, "error");
      }
      state.runs = await api("/api/runs");
      renderHistory();
      setRunning(false);
    } catch (error) {
      notice(`Lost contact with the server: ${error.message}. Is uvicorn still running?`, "error");
      setRunning(false);
    }
  }

  // ---------- header ----------
  function renderSource() {
    const c = state.config;
    const source = state.run?.data_source || c.data_source;
    $("#source-info").innerHTML = [
      `<span class="pill ${source === "demo" ? "demo" : ""}"><i class="dot"></i>${esc(SOURCE_NAMES[source] || source)}</span>`,
      `<span class="pill">${c.sites.length} sites</span>`,
      `<span class="pill">Times in ${esc(c.timezone)}</span>`,
    ].join("");
  }

  // ---------- verdict ----------
  function periodText(run) {
    const p = run.period;
    if (p.from_date === p.to_date) {
      const text = dayLong(p.from_date);
      return p.is_partial ? `${text}, up to ${timeOf(run.window.end)}` : text;
    }
    const to = parseLocal(p.to_date);
    return `${dayShort(parseLocal(p.from_date))} to ${dayShort(to)} ${to.getFullYear()}${p.is_partial ? `, up to ${timeOf(run.window.end)}` : ""}`;
  }

  function renderVerdict() {
    const run = state.run;
    if (!run) {
      $("#period-text").textContent = "";
      $("#headline").textContent = "No report has been run yet.";
      $("#facts").innerHTML = "Run yesterday's report to see which links crossed 70%, 80% and 90%, and for how long.";
      return;
    }
    const r = run.result, c = r.counts;
    $("#period-text").textContent = periodText(run);
    $("#headline").textContent = r.headline;

    const facts = [`<b>${c.sites_over_70} of ${c.sites}</b> sites crossed 70%.`];
    const captured = r.fortigate.filter((f) => f.status === "SUCCESS").length;
    if (r.eligible_sites.length) {
      facts.push(captured
        ? `FortiGate top talkers captured for <b>${captured}</b> of them.`
        : `FortiGate captures were skipped: ${esc((r.fortigate[0]?.error || "").toLowerCase())}.`);
    }
    const failed = r.checks.filter((k) => !k.passed);
    facts.push(`<b>${c.checks_passed} of ${c.checks_total}</b> accuracy checks passed${failed.length ? `; ${esc(failed.map((k) => k.name.toLowerCase()).join(", "))} needs a look.` : "."}`);
    $("#facts").innerHTML = facts.join(" ");
  }

  // ---------- day strip ----------
  function stripGeometry(run) {
    const start = parseLocal(run.window.start);
    const days = Math.round((parseLocal(run.period.to_date) - parseLocal(run.period.from_date)) / 86400000) + 1;
    const step = run.window.step_minutes;
    const total = Math.round((days * 1440) / step);
    const cells = days === 1 ? 96 : days <= 7 ? days * 24 : days * 6;
    return { start, days, step, total, cells, per: total / cells, cellMinutes: (days * 1440) / cells };
  }

  function cellClass(values, from, per) {
    let max = null, any = false;
    for (let i = from; i < from + per; i++) {
      if (i >= values.length) break;
      any = true;
      const v = values[i];
      if (v !== null && (max === null || v > max)) max = v;
    }
    return { max, future: !any };
  }

  function renderStrip() {
    const run = state.run;
    const rows = $("#strip-rows");
    if (!run) { rows.innerHTML = ""; $("#strip-axis").innerHTML = ""; return; }
    const g = stripGeometry(run);
    const r = run.result;

    // Axis
    const ticks = [];
    if (g.days === 1) {
      for (let h = 0; h < 24; h += 3) ticks.push([(h / 24) * 100, `${pad(h)}:00`, h % 6 ? "minor" : ""]);
    } else {
      const every = g.days <= 7 ? 1 : 5;
      for (let d = 0; d < g.days; d += every) {
        const day = new Date(g.start); day.setDate(day.getDate() + d);
        ticks.push([(d / g.days) * 100, dayShort(day), d % (every * 2) ? "minor" : ""]);
      }
    }
    $("#strip-axis").innerHTML =
      `<span></span><div class="axis-ticks">${ticks.map(([x, t, cls]) => `<span class="${cls}" style="left:${x}%">${t}</span>`).join("")}</div>` +
      `<div class="axis-stats"><span>Peak</span><span>Above 70%</span></div>`;

    const primary = css("--link-primary"), secondary = css("--link-secondary"), empty = css("--cell-empty");
    let html = "";
    for (const [site, links] of Object.entries(r.site_data)) {
      const status = r.site_status[site];
      let bands = "", stats = "";
      for (const link of LINKS) {
        const values = r.series[site]?.[link] || [];
        const color = link === "Primary" ? primary : secondary;
        let cells = "";
        for (let i = 0; i < g.cells; i++) {
          const { max, future } = cellClass(values, Math.round(i * g.per), Math.round(g.per));
          if (future) cells += `<i class="future" data-i="${i}"></i>`;
          else if (max === null) cells += `<i class="gap" data-i="${i}"></i>`;
          else {
            const level = levelOf(max);
            cells += level
              ? `<i class="l${level}" data-i="${i}" data-v="${max}"></i>`
              : `<i data-i="${i}" data-v="${max}" style="background:color-mix(in srgb, ${color} ${Math.round(12 + (max / 70) * 58)}%, ${empty})"></i>`;
          }
        }
        bands += `<div class="band ${link.toLowerCase()}" data-link="${link}" style="--cells:${g.cells}">${cells}</div>`;
        const s = links[link];
        const lvl = levelOf(s.peak);
        const over = s.above_70_events;
        stats += `<span class="${lvl ? "hot" + lvl : "muted"}">${s.total_base_events ? s.peak.toFixed(1) + "%" : "–"}</span>` +
                 `<span class="${over ? "" : "muted"}">${over ? minutes(over) : "–"}</span>`;
      }
      html += `<div class="site-row${site === state.site ? " selected" : ""}" data-site="${esc(site)}">
        <button type="button" class="site-name" aria-pressed="${site === state.site}"><i class="status-dot ${status}" title="${status}"></i>${esc(site)}</button>
        <div class="bands">${bands}</div>
        <div class="row-stats">${stats}</div>
      </div>`;
    }
    rows.innerHTML = html;
  }

  function setupStripEvents() {
    const rows = $("#strip-rows"), tip = $("#tooltip");
    rows.addEventListener("click", (event) => {
      const row = event.target.closest(".site-row");
      if (row) selectSite(row.dataset.site);
    });
    rows.addEventListener("mousemove", (event) => {
      const cell = event.target.closest(".band i");
      if (!cell || !state.run) { tip.hidden = true; return; }
      const site = cell.closest(".site-row").dataset.site;
      const link = cell.parentElement.dataset.link;
      const g = stripGeometry(state.run);
      const from = new Date(g.start.getTime() + Number(cell.dataset.i) * g.cellMinutes * 60000);
      const to = new Date(from.getTime() + g.cellMinutes * 60000);
      const range = g.days === 1 ? `${hhmm(from)} to ${hhmm(to)}` : `${dayShort(from)} ${hhmm(from)} to ${hhmm(to)}`;
      const value = cell.classList.contains("future") ? "Not reached yet"
        : cell.classList.contains("gap") ? "No samples collected" : `Peak ${Number(cell.dataset.v).toFixed(1)}%`;
      tip.innerHTML = `<b>${esc(site)}, ${link.toLowerCase()} link</b><br>${range}<br>${value}`;
      tip.hidden = false;
      const x = Math.min(event.clientX + 14, window.innerWidth - tip.offsetWidth - 8);
      tip.style.left = `${x}px`;
      tip.style.top = `${event.clientY + 16}px`;
    });
    rows.addEventListener("mouseleave", () => { tip.hidden = true; });
  }

  function selectSite(site) {
    state.site = site;
    document.querySelectorAll(".site-row").forEach((row) => {
      const on = row.dataset.site === site;
      row.classList.toggle("selected", on);
      row.querySelector(".site-name").setAttribute("aria-pressed", on);
    });
    renderDetail();
  }

  function defaultSite(run) {
    const rank = { critical: 3, high: 2, elevated: 1, normal: 0, "no-data": -1 };
    const entries = Object.entries(run.result.site_status);
    return entries.reduce((best, cur) => (rank[cur[1]] > rank[best[1]] ? cur : best), entries[0])[0];
  }

  // ---------- site detail ----------
  function renderDetail() {
    const run = state.run;
    const tbody = $("#episodes tbody");
    if (!run || !state.site) {
      $("#detail-title").textContent = "Site detail";
      $("#detail-stats").innerHTML = "";
      tbody.innerHTML = "";
      if (state.chart) { state.chart.destroy(); state.chart = null; }
      return;
    }
    const site = state.site;
    const links = run.result.site_data[site];
    const p = links.Primary, s = links.Secondary;
    $("#detail-title").textContent = site;
    const stat = (label, value) => `<div class="stat"><span>${label}</span><strong>${value}</strong></div>`;
    $("#detail-stats").innerHTML = [
      stat("Primary peak", p.total_base_events ? `${p.peak.toFixed(1)}% at ${timeOf(p.peak_time)}` : "No data"),
      stat("Above 90%", minutes(p.above_90_events)),
      stat("Above 80%", minutes(p.above_80_events)),
      stat("Above 70%", minutes(p.above_70_events)),
      stat("Secondary peak", s.total_base_events ? `${s.peak.toFixed(1)}% at ${timeOf(s.peak_time)}` : "No data"),
    ].join("");

    const episodes = LINKS.flatMap((link) => links[link].episodes.map((e) => ({ ...e, link })))
      .sort((a, b) => a.start.localeCompare(b.start));
    const multiDay = run.period.from_date !== run.period.to_date;
    const when = (iso) => (multiDay ? `${dayShort(parseLocal(iso))} ${timeOf(iso)}` : timeOf(iso));
    tbody.innerHTML = episodes.length
      ? episodes.map((e) => `<tr><td>${e.link}</td><td>${when(e.start)}</td><td>${timeOf(e.end)}</td>
          <td class="num">${e.minutes} of ${e.duration}</td>
          <td class="num"><span class="level l${e.level}">${e.peak.toFixed(1)}%</span></td></tr>`).join("")
      : `<tr><td colspan="5" class="empty">No breach periods: both links stayed at or below 70%.</td></tr>`;

    drawChart();
  }

  const thresholdLabels = {
    id: "thresholdLabels",
    afterDatasetsDraw(chart) {
      const { ctx, chartArea, scales } = chart;
      ctx.save();
      ctx.font = `600 11px ${css("--cond")}`;
      ctx.textAlign = "right";
      for (const t of LEVELS) {
        ctx.fillStyle = css(`--t${t}`);
        ctx.fillText(`${t}%`, chartArea.right - 2, scales.y.getPixelForValue(t) - 4);
      }
      ctx.restore();
    },
  };

  function drawChart() {
    const run = state.run, site = state.site;
    if (state.chart) state.chart.destroy();
    const g = stripGeometry(run);
    const series = run.result.series[site];
    const length = Math.max(series.Primary.length, series.Secondary.length);
    const labels = Array.from({ length }, (_, i) => {
      const t = new Date(g.start.getTime() + i * g.step * 60000);
      return g.days === 1 ? hhmm(t) : `${dayShort(t)} ${hhmm(t)}`;
    });
    const text = css("--muted"), grid = css("--line");
    const tickEvery = g.days === 1 ? 180 / g.step : (1440 / g.step) * Math.ceil(g.days / 8);
    const line = (label, data, color) => ({
      label, data, borderColor: color, backgroundColor: color, borderWidth: 1.6,
      pointRadius: 0, pointHoverRadius: 3, tension: 0.15, spanGaps: false,
    });
    const threshold = (t) => ({
      label: `${t}%`, data: Array(length).fill(t), borderColor: css(`--t${t}`), borderWidth: 1,
      borderDash: [5, 4], pointRadius: 0, pointHoverRadius: 0, isThreshold: true,
    });
    state.chart = new Chart($("#trace"), {
      type: "line",
      data: { labels, datasets: [line("Primary", series.Primary, css("--link-primary")), line("Secondary", series.Secondary, css("--link-secondary")), ...LEVELS.map(threshold)] },
      plugins: [thresholdLabels],
      options: {
        responsive: true, maintainAspectRatio: false, animation: false,
        interaction: { mode: "index", intersect: false },
        plugins: {
          legend: { display: false },
          tooltip: {
            filter: (item) => !item.dataset.isThreshold,
            callbacks: { label: (item) => ` ${item.dataset.label}: ${item.parsed.y == null ? "no data" : item.parsed.y.toFixed(1) + "%"}` },
          },
        },
        scales: {
          x: {
            ticks: {
              color: text, autoSkip: false, maxRotation: 0, font: { family: css("--cond"), size: 12 },
              callback: (_, i) => (i % tickEvery === 0 ? (g.days === 1 ? labels[i] : labels[i].split(" ").slice(0, 2).join(" ")) : null),
            },
            grid: { display: false }, border: { color: grid },
          },
          y: { min: 0, max: 100, ticks: { color: text, stepSize: 20, callback: (v) => `${v}%`, font: { family: css("--cond"), size: 12 } }, grid: { color: grid }, border: { display: false } },
        },
      },
    });
  }

  // ---------- pipeline ----------
  function renderPipeline(run) {
    if (!run) { $("#stages").innerHTML = ""; $("#checks").innerHTML = ""; return; }
    $("#stages").innerHTML = run.stages.map((s) => `
      <li class="${s.status}">
        <span>${esc(s.name)}</span>
        <span class="took">${s.duration_s != null ? s.duration_s.toFixed(2) + " s" : s.status === "running" ? "running" : ""}</span>
        <span class="stage-detail">${esc(s.detail || (s.status === "pending" ? "Waiting" : ""))}</span>
      </li>`).join("");
    const finished = run.finished_at ? `Finished ${timeOf(run.finished_at)} in ${run.duration_s.toFixed(1)} s` : "Running";
    $("#run-meta").textContent = finished;
    $("#log").textContent = run.logs.map((l) => `${l.t}  ${l.level.toUpperCase().padEnd(5)} ${l.msg}`).join("\n");

    const checks = run.result?.checks || [];
    $("#checks").innerHTML = checks.length ? checks.map((k) => {
      const cls = k.passed ? "pass" : k.severity === "warning" ? "warn" : "fail";
      const mark = k.passed ? "✓" : k.severity === "warning" ? "!" : "✕";
      return `<li class="${cls}"><span class="mark" aria-hidden="true">${mark}</span><span>${esc(k.name)}</span><small>${esc(k.detail)}</small></li>`;
    }).join("") : `<li><span></span><small>Checks appear when the run finishes.</small></li>`;
  }

  // ---------- outputs ----------
  function renderOutputs() {
    const run = state.run;
    const downloads = $("#downloads");
    if (!run) { downloads.innerHTML = ""; $("#message").textContent = "The team message appears after the first run."; return; }
    if (SNAPSHOT) {
      downloads.innerHTML = `<span class="run-meta">Excel and text files are created when the project runs locally.</span>`;
    } else {
      const file = (kind, label, ext) => `<a class="btn btn-file" href="/api/runs/${run.id}/files/${kind}" download>${label} <small>${ext}</small></a>`;
      downloads.innerHTML = file("excel", "Download Excel report", ".xlsx") + file("report", "Download text report", ".txt") + file("message", "Download message", ".txt");
    }
    $("#message").textContent = run.result.message_text;
  }

  function setupCopy() {
    $("#copy-message").addEventListener("click", async () => {
      const button = $("#copy-message");
      try {
        await navigator.clipboard.writeText($("#message").textContent);
        button.textContent = "Copied";
      } catch {
        const range = document.createRange();
        range.selectNodeContents($("#message"));
        getSelection().removeAllRanges(); getSelection().addRange(range);
        button.textContent = "Selected, press Ctrl+C";
      }
      setTimeout(() => { button.textContent = "Copy message"; }, 1800);
    });
  }

  // ---------- history ----------
  function renderHistory() {
    const tbody = $("#history tbody");
    if (!state.runs.length) { tbody.innerHTML = `<tr><td colspan="7" class="empty">No runs yet.</td></tr>`; return; }
    tbody.innerHTML = state.runs.map((r) => {
      const label = r.period.from_date === r.period.to_date ? dayShort(parseLocal(r.period.from_date)) + (r.period.is_partial ? " (so far)" : "")
        : `${dayShort(parseLocal(r.period.from_date))} to ${dayShort(parseLocal(r.period.to_date))}`;
      const started = parseLocal(r.created_at);
      return `<tr data-id="${esc(r.id)}" class="${state.run?.id === r.id ? "current" : ""}" tabindex="0">
        <td>${dayShort(started)} ${hhmm(started)}</td><td>${label}</td><td>${esc(SOURCE_NAMES[r.data_source] || r.data_source)}</td>
        <td><span class="result ${r.status}">${r.status === "succeeded" ? "Report ready" : r.status === "failed" ? "Failed" : "Running"}</span></td>
        <td class="num">${r.counts ? `${r.counts.sites_over_70} of ${r.counts.sites}` : "–"}</td>
        <td class="num">${r.counts ? `${r.counts.checks_passed} of ${r.counts.checks_total}` : "–"}</td>
        <td class="num">${r.duration_s != null ? r.duration_s.toFixed(1) + " s" : "–"}</td></tr>`;
    }).join("");
  }

  function setupHistory() {
    const open = async (row) => {
      if (!row || SNAPSHOT) return;
      const run = await api(`/api/runs/${row.dataset.id}`);
      if (run.status !== "succeeded") { renderPipeline(run); return; }
      state.run = run;
      state.site = null;
      renderRun();
      renderHistory();
      window.scrollTo({ top: 0, behavior: "smooth" });
    };
    $("#history tbody").addEventListener("click", (e) => open(e.target.closest("tr[data-id]")));
    $("#history tbody").addEventListener("keydown", (e) => { if (e.key === "Enter") open(e.target.closest("tr[data-id]")); });
  }

  // ---------- orchestration ----------
  function renderRun() {
    document.body.classList.toggle("no-run", !state.run);
    if (state.run) document.getElementById("first-run")?.remove();
    if (state.run && (!state.site || !(state.site in state.run.result.site_data))) state.site = defaultSite(state.run);
    renderSource();
    renderVerdict();
    renderStrip();
    renderDetail();
    renderPipeline(state.active && state.active.status !== "succeeded" ? state.active : state.run);
    renderOutputs();
  }

  async function init() {
    setupStripEvents();
    setupCopy();
    setupHistory();
    try {
      if (SNAPSHOT) {
        state.config = SNAPSHOT.config;
        state.runs = SNAPSHOT.runs;
        state.run = SNAPSHOT.run;
        notice("This is a static snapshot of one pipeline run. Clone the repo and run it locally to generate new reports.");
      } else {
        state.config = await api("/api/config");
        state.runs = await api("/api/runs");
        const latest = state.runs.find((r) => r.status === "succeeded");
        if (latest) state.run = await api(`/api/runs/${latest.id}`);
        const active = state.runs.find((r) => r.status === "running" || r.status === "queued");
        if (active) poll(active.id);
      }
    } catch (error) {
      notice(`Could not reach the API: ${error.message}. Start it with: uvicorn src.api.app:app`, "error");
      return;
    }
    setupForm();
    setRunning(false);
    renderRun();
    renderHistory();
    if (!state.run) {
      renderSource();
      document.body.classList.add("no-run");
      $("#facts").insertAdjacentHTML("afterend", SNAPSHOT ? "" : `<button class="btn btn-run" id="first-run" type="button">Run yesterday's report</button>`);
      $("#first-run")?.addEventListener("click", () => { $("#period-mode").value = "yesterday"; $("#run-form").requestSubmit(); $("#first-run").remove(); });
    }
    window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => { renderStrip(); if (state.site) drawChart(); });
  }

  init();
})();
