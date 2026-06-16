const $ = (id) => document.getElementById(id);

const state = {
  scenarios: [],
  dates: [],
  result: null,
  rerunTimer: null,
};

async function api(path) {
  const res = await fetch(path);
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.error || `Request failed: ${res.status}`);
  }
  return res.json();
}

function params() {
  const query = new URLSearchParams({
    scenario_id: $("scenarioSelect").value,
    start: $("dateSelect").value,
    days: $("daysSelect").value,
    comfort_weight: $("comfortWeight").value,
    cost_weight: $("costWeight").value,
    emissions_weight: $("emissionsWeight").value,
    peak_weight: $("peakWeight").value,
    comfort_min_c: $("comfortMin").value,
    comfort_max_c: $("comfortMax").value,
  });
  return query.toString();
}

async function init() {
  try {
    await api("/api/health");
    $("serviceStatus").textContent = "Backend connected";
    state.scenarios = await api("/api/scenarios");
    $("scenarioSelect").innerHTML = state.scenarios
      .map((s) => `<option value="${s.scenario_id}">${s.scenario_id} - ${s.name}</option>`)
      .join("");
    await refreshDates();
    bind();
    await run();
  } catch (err) {
    $("serviceStatus").textContent = err.message;
  }
}

function bind() {
  $("scenarioSelect").addEventListener("change", async () => {
    await refreshDates();
    await run();
  });
  $("runButton").addEventListener("click", run);
  ["dateSelect", "daysSelect"].forEach((id) => $(id).addEventListener("change", run));
  ["comfortWeight", "costWeight", "emissionsWeight", "peakWeight", "comfortMin", "comfortMax"].forEach((id) => {
    $(id).addEventListener("input", scheduleRun);
    $(id).addEventListener("change", scheduleRun);
  });
}

function scheduleRun() {
  window.clearTimeout(state.rerunTimer);
  $("runButton").textContent = "Updating...";
  state.rerunTimer = window.setTimeout(run, 450);
}

async function refreshDates() {
  const id = $("scenarioSelect").value || "PUB-A";
  state.dates = await api(`/api/dates?scenario_id=${encodeURIComponent(id)}`);
  $("dateSelect").innerHTML = state.dates.map((d) => `<option value="${d}">${d}</option>`).join("");
}

async function run() {
  $("runButton").disabled = true;
  $("runButton").textContent = "Running...";
  try {
    const result = await api(`/api/run?${params()}`);
    state.result = result;
    render(result);
  } catch (err) {
    alert(err.message);
  } finally {
    $("runButton").disabled = false;
    $("runButton").textContent = "Run optimization";
  }
}

function render(result) {
  const scenario = result.scenario;
  const overall = result.overall;
  $("scenarioType").textContent = `${scenario.scenario_id} / ${scenario.building_type} / ${scenario.timezone}`;
  $("scenarioName").textContent = scenario.name;
  $("scenarioFocus").textContent = scenario.evaluation_focus || "Constraint-aware cooling schedule.";
  $("rowCount").textContent = `${result.schedule.length} rows`;
  $("elapsed").textContent = `${result.elapsed_ms} ms`;
  $("comfortMin").placeholder = scenario.comfort_min_c;
  $("comfortMax").placeholder = scenario.comfort_max_c;

  $("kpiGrid").innerHTML = [
    kpi("Cost saving", money(overall.cost_saving_pkr), `${overall.cost_saving_pct}%`),
    kpi("Energy saving", `${num(overall.energy_saving_kwh)} kWh`, `${overall.energy_saving_pct}%`),
    kpi("Emissions avoided", `${num(overall.emissions_avoided_kgco2e)} kg`, "grid CO2e"),
    kpi("Comfort compliance", `${num(overall.comfort_compliance_pct)}%`, `${overall.unsafe_interval_count} unsafe intervals`),
    kpi("Peak demand", `${num(overall.peak_grid_demand_kw)} kW`, "optimized"),
    kpi("Solar utilization", `${num(overall.solar_utilization_pct)}%`, `${num(overall.solar_used_kwh)} kWh used`),
    kpi("Violations", `${overall.constraint_violation_count}`, "reported, not hidden"),
    kpi("Run id", result.run_id, "deterministic"),
  ].join("");

  renderChecks(result.checks);
  renderReasons(result.schedule);
  renderTable(result.schedule);
  renderBars(overall);
  renderLines(result.schedule);
  $("scheduleExport").href = `/api/export/schedule.csv?${params()}`;
  $("summaryExport").href = `/api/export/summary.csv?${params()}`;
}

function kpi(label, value, sub) {
  return `<div class="kpi"><span>${label}</span><strong>${value}</strong><small>${sub}</small></div>`;
}

function renderChecks(checks) {
  $("checks").innerHTML = checks
    .map(
      (c) =>
        `<div class="check"><b>${c.id}</b><span>${c.description}</span><strong class="${c.result === "PASS" ? "pass" : "fail"}">${c.result}</strong></div>`,
    )
    .join("");
}

function renderReasons(rows) {
  const counts = {};
  rows.forEach((r) => (counts[r.reason_code] = (counts[r.reason_code] || 0) + 1));
  const max = Math.max(...Object.values(counts), 1);
  $("reasons").innerHTML = Object.entries(counts)
    .sort((a, b) => b[1] - a[1])
    .map(([reason, count]) => `<div class="reason-row"><b>${reason}</b><div class="bar"><i style="width:${(count / max) * 100}%"></i></div><span>${count}</span></div>`)
    .join("");
}

function renderTable(rows) {
  const first = rows.slice(0, 96);
  $("tableNote").textContent = `First ${first.length} of ${rows.length} rows shown`;
  $("scheduleBody").innerHTML = first
    .map(
      (r) => `<tr>
        <td>${r.timestamp_local.replace("T", " ")}</td>
        <td>${r.recommended_ac_units_on}</td>
        <td>${r.recommended_ac_setpoint_c || ""}</td>
        <td>${r.recommended_fan_units_on}</td>
        <td>${num(r.grid_energy_kwh)}</td>
        <td>${num(r.solar_energy_used_kwh)}</td>
        <td>${num(r.battery_soc_kwh)}</td>
        <td>${num(r.estimated_indoor_temp_c)}</td>
        <td>${r.comfort_status}</td>
        <td title="${r.explanation}">${r.reason_code}</td>
      </tr>`,
    )
    .join("");
}

function renderBars(overall) {
  const canvas = $("barChart");
  const ctx = canvas.getContext("2d");
  const data = [
    ["Energy kWh", overall.baseline_energy_kwh, overall.optimized_energy_kwh],
    ["Cost PKR", overall.baseline_cost_pkr, overall.optimized_cost_pkr],
    ["Emissions kg", overall.baseline_emissions_kgco2e, overall.optimized_emissions_kgco2e],
  ];
  clear(ctx, canvas);
  const w = canvas.width;
  const h = canvas.height;
  const max = Math.max(...data.flatMap((d) => [d[1], d[2]]), 1);
  data.forEach((d, i) => {
    const y = 52 + i * 75;
    drawText(ctx, d[0], 24, y - 14, "#63746b", 15, "700");
    drawBar(ctx, 150, y - 26, (d[1] / max) * (w - 210), 22, "#d9a017");
    drawBar(ctx, 150, y + 4, (d[2] / max) * (w - 210), 22, "#157f5b");
    drawText(ctx, `Baseline ${num(d[1])}`, 160, y - 10, "#17211c", 13, "700");
    drawText(ctx, `Optimized ${num(d[2])}`, 160, y + 20, "#17211c", 13, "700");
  });
  drawLegend(ctx, 24, h - 28, [["Baseline", "#d9a017"], ["Optimized", "#157f5b"]]);
}

function renderLines(rows) {
  const canvas = $("lineChart");
  const ctx = canvas.getContext("2d");
  clear(ctx, canvas);
  const sample = rows.filter((_, i) => i % Math.max(1, Math.floor(rows.length / 96)) === 0).slice(0, 120);
  const grid = sample.map((r) => Number(r.grid_energy_kwh));
  const soc = sample.map((r) => Number(r.battery_soc_kwh));
  const indoor = sample.map((r) => Number(r.estimated_indoor_temp_c));
  drawSeries(ctx, canvas, grid, "#3467b7", "Grid kWh", 0);
  drawSeries(ctx, canvas, soc, "#157f5b", "Battery SOC", 1);
  drawSeries(ctx, canvas, indoor, "#be3a34", "Indoor C", 2);
  drawLegend(ctx, 24, canvas.height - 28, [["Grid kWh", "#3467b7"], ["Battery SOC", "#157f5b"], ["Indoor C", "#be3a34"]]);
}

function clear(ctx, canvas) {
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  ctx.fillStyle = "#ffffff";
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  ctx.strokeStyle = "#d7e2db";
  ctx.lineWidth = 1;
  for (let i = 0; i < 5; i++) {
    const y = 28 + i * 48;
    ctx.beginPath();
    ctx.moveTo(24, y);
    ctx.lineTo(canvas.width - 20, y);
    ctx.stroke();
  }
}

function drawSeries(ctx, canvas, values, color, label, lane) {
  const max = Math.max(...values, 1);
  const min = Math.min(...values, 0);
  const left = 28;
  const top = 26;
  const width = canvas.width - 58;
  const height = canvas.height - 72;
  ctx.strokeStyle = color;
  ctx.lineWidth = 3;
  ctx.beginPath();
  values.forEach((v, i) => {
    const x = left + (i / Math.max(1, values.length - 1)) * width;
    const y = top + height - ((v - min) / Math.max(0.001, max - min)) * height;
    if (i === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  ctx.stroke();
  drawText(ctx, label, canvas.width - 150, 28 + lane * 20, color, 13, "800");
}

function drawBar(ctx, x, y, w, h, color) {
  ctx.fillStyle = color;
  ctx.beginPath();
  ctx.roundRect(x, y, Math.max(2, w), h, 6);
  ctx.fill();
}

function drawLegend(ctx, x, y, items) {
  items.forEach(([label, color], i) => {
    ctx.fillStyle = color;
    ctx.fillRect(x + i * 120, y - 10, 14, 14);
    drawText(ctx, label, x + 20 + i * 120, y + 2, "#63746b", 12, "700");
  });
}

function drawText(ctx, text, x, y, color, size, weight) {
  ctx.fillStyle = color;
  ctx.font = `${weight} ${size}px Segoe UI, Arial`;
  ctx.fillText(text, x, y);
}

function num(value) {
  return Number(value || 0).toLocaleString(undefined, { maximumFractionDigits: 2 });
}

function money(value) {
  return `PKR ${num(value)}`;
}

init();
