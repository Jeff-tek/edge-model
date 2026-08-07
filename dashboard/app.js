"use strict";

/* Edge Model dashboard renderer. Pure DOM + hand-rolled SVG, no dependencies. */

const $ = (sel) => document.querySelector(sel);

function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined && text !== null) node.textContent = String(text);
  return node;
}

const fmtMoney = (v) =>
  (v < 0 ? "-$" : "$") + Math.abs(v).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const fmtPct = (v) => (v * 100).toFixed(1) + "%";
const fmtOdds = (v) => (v ? Number(v).toFixed(2) : "—");

function pctClass(v) {
  if (v > 0) return "pos";
  if (v < 0) return "neg";
  return "";
}

function kpi(label, value, sub, valueClass) {
  const card = el("div", "kpi");
  card.appendChild(el("div", "label", label));
  const val = el("div", "value " + (valueClass || ""));
  val.textContent = value;
  card.appendChild(val);
  if (sub) card.appendChild(el("div", "sub", sub));
  return card;
}

/* ---------------- SVG helpers ---------------- */

function svgEl(tag, attrs) {
  const node = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
  return node;
}

function makeSvg(width, height, viewH) {
  const svg = svgEl("svg", { viewBox: `0 0 ${width} ${viewH}`, role: "img" });
  svg.setAttribute("preserveAspectRatio", "xMidYMid meet");
  return { svg, width, height, viewH };
}

function lineChart(points, opts) {
  /* points: array of {label, value} */
  if (!points || points.length < 2) return null;
  const W = 640, H = 180, padL = 46, padR = 12, padT = 12, padB = 26;
  const xs = points.map((_, i) => padL + (i * (W - padL - padR)) / (points.length - 1));
  const vals = points.map((p) => p.value);
  const min = Math.min(...vals), max = Math.max(...vals);
  const span = max - min || 1;
  const y = (v) => padT + (1 - (v - min) / span) * (H - padT - padB);
  const ys = vals.map(y);
  const { svg } = makeSvg(W, H, H);

  for (let i = 0; i <= 3; i++) {
    const gy = padT + (i * (H - padT - padB)) / 3;
    svg.appendChild(svgEl("line", { x1: padL, y1: gy, x2: W - padR, y2: gy, class: "grid-line" }));
    const tick = max - (i * span) / 3;
    const t = svgEl("text", { x: padL - 6, y: gy + 4, "text-anchor": "end", fill: "currentColor", "font-size": 10 });
    t.textContent = tick.toFixed(0);
    svg.appendChild(t);
  }

  const path = ys.map((v, i) => (i === 0 ? `M ${xs[i]} ${v}` : `L ${xs[i]} ${v}`)).join(" ");
  const area = path + ` L ${xs[xs.length - 1]} ${H - padB} L ${xs[0]} ${H - padB} Z`;
  svg.appendChild(svgEl("path", { d: area, fill: "rgba(79,156,249,0.12)" }));
  svg.appendChild(svgEl("path", { d: path, fill: "none", stroke: "#4f9cf9", "stroke-width": 2, "stroke-linejoin": "round", "stroke-linecap": "round" }));

  const step = Math.ceil(points.length / 6);
  points.forEach((p, i) => {
    if (i % step !== 0 && i !== points.length - 1) return;
    const t = svgEl("text", { x: xs[i], y: H - 8, "text-anchor": "middle", fill: "currentColor", "font-size": 10 });
    t.textContent = p.label;
    svg.appendChild(t);
  });
  return svg;
}

function barChart(items, opts) {
  /* items: array of {label, value} — positive green, negative red */
  if (!items || items.length === 0) return null;
  const W = 640, H = 160, padL = 46, padR = 12, padT = 12, padB = 26;
  const vals = items.map((i) => i.value);
  const maxAbs = Math.max(1, ...vals.map((v) => Math.abs(v)));
  const y0 = padT + (H - padT - padB) / 2;
  const scale = (H - padT - padB) / 2 / maxAbs;
  const slot = (W - padL - padR) / items.length;
  const bw = Math.min(46, slot * 0.6);
  const { svg } = makeSvg(W, H, H);

  svg.appendChild(svgEl("line", { x1: padL, y1: y0, x2: W - padR, y2: y0, class: "grid-line" }));
  items.forEach((item, i) => {
    const cx = padL + slot * i + slot / 2;
    const h = item.value * scale;
    const y = item.value >= 0 ? y0 - h : y0;
    const color = item.value >= 0 ? "#3fb96f" : "#e5534b";
    svg.appendChild(svgEl("rect", { x: cx - bw / 2, y, width: bw, height: Math.max(1, Math.abs(h)), rx: 3, fill: color }));
    const t = svgEl("text", { x: cx, y: H - 8, "text-anchor": "middle", fill: "currentColor", "font-size": 10 });
    t.textContent = item.label;
    svg.appendChild(t);
  });
  const maxT = svgEl("text", { x: padL - 6, y: y0 + 4, "text-anchor": "end", fill: "currentColor", "font-size": 10 });
  maxT.textContent = maxAbs.toFixed(0);
  svg.appendChild(maxT);
  return svg;
}

function calibrationChart(bins) {
  /* bins: array of {bin_low, actual, n} */
  if (!bins || bins.length === 0) return null;
  const W = 640, H = 170, padL = 40, padR = 12, padT = 12, padB = 26;
  const slot = (W - padL - padR) / bins.length;
  const bw = Math.min(52, slot * 0.62);
  const { svg } = makeSvg(W, H, H);
  [0, 0.5, 1].forEach((g) => {
    const gy = padT + (1 - g) * (H - padT - padB);
    svg.appendChild(svgEl("line", { x1: padL, y1: gy, x2: W - padR, y2: gy, class: "grid-line" }));
    const t = svgEl("text", { x: padL - 6, y: gy + 4, "text-anchor": "end", fill: "currentColor", "font-size": 10 });
    t.textContent = g.toFixed(1);
    svg.appendChild(t);
  });
  bins.forEach((bin, i) => {
    const cx = padL + slot * i + slot / 2;
    const h = bin.actual * (H - padT - padB);
    const y = padT + (H - padT - padB) - h;
    svg.appendChild(svgEl("rect", { x: cx - bw / 2, y, width: bw, height: h, rx: 3, fill: "#4f9cf9" }));
    const label = svgEl("text", { x: cx, y: y - 4, "text-anchor": "middle", fill: "currentColor", "font-size": 10 });
    label.textContent = fmtPct(bin.actual);
    svg.appendChild(label);
    const t = svgEl("text", { x: cx, y: H - 8, "text-anchor": "middle", fill: "currentColor", "font-size": 10 });
    t.textContent = "≥" + (bin.bin_low * 100).toFixed(0) + "%";
    svg.appendChild(t);
  });
  return svg;
}

/* ---------------- data loading ---------------- */

async function loadData() {
  try {
    const resp = await fetch("data.json", { cache: "no-store" });
    if (resp.ok) return { data: await resp.json(), source: "live" };
  } catch (_) { /* fall through to sample */ }
  const resp = await fetch("data.sample.json");
  return { data: await resp.json(), source: "sample" };
}

/* ---------------- renderers ---------------- */

function renderKpis(data) {
  const wrap = $("#kpis");
  wrap.innerHTML = "";
  const paper = data.paper, bt = data.backtest;

  wrap.appendChild(kpi("Bankroll", fmtMoney(paper.bankroll),
    "started " + fmtMoney(paper.starting_bankroll), paper.net_pl >= 0 ? "pos" : "neg"));
  wrap.appendChild(kpi("Net P/L", fmtMoney(paper.net_pl),
    paper.settled_bets + " settled bets", pctClass(paper.net_pl)));
  wrap.appendChild(kpi("Paper hit rate", fmtPct(paper.hit_rate),
    paper.win_streak.count + " " + (paper.win_streak.kind || "bets") + (paper.paused ? " · PAUSED" : "")));
  wrap.appendChild(kpi("Parlay hit rate", fmtPct(bt.parlay_hit_rate),
    bt.parlays + " parlays"));
  wrap.appendChild(kpi("Backtest ROI", (bt.roi * 100).toFixed(1) + "%",
    "net " + fmtMoney(bt.net_profit), pctClass(bt.roi)));
  wrap.appendChild(kpi("Leg hit rate", fmtPct(bt.leg_hit_rate),
    bt.legs + " legs"));
}

function renderBacktest(data) {
  const bt = data.backtest;
  $("#bt-subtitle").textContent =
    bt.matches.toLocaleString() + " matches · " + bt.leagues.join(", ") + " · " + bt.seasons.join("/");

  const kpis = $("#bt-kpis");
  kpis.innerHTML = "";
  const items = [
    ["Parlays", String(bt.parlays)],
    ["Wins", String(bt.parlay_wins)],
    ["Hit rate", fmtPct(bt.parlay_hit_rate)],
    ["ROI", (bt.roi * 100).toFixed(1) + "%", pctClass(bt.roi)],
    ["Net profit", fmtMoney(bt.net_profit), pctClass(bt.net_profit)],
    ["Stake/bet", fmtMoney(bt.stake_per_bet)],
    ["Feasible days", String(bt.feasible_matchdays)],
    ["Qualifier days", String(bt.matchdays_with_qualifier)],
  ];
  items.forEach(([label, value, cls]) => {
    const box = el("div", "bt-kpi");
    box.appendChild(el("div", "label", label));
    const v = el("div", "value " + (cls || ""));
    v.textContent = value;
    box.appendChild(v);
    kpis.appendChild(box);
  });

  const sides = $("#bt-calibration");
  sides.innerHTML = "";
  const sideRow = el("div", "side-row");
  Object.entries(bt.side_hit_rates).forEach(([side, info]) => {
    const pill = el("span", "side-pill");
    pill.appendChild(el("b", null, side.toUpperCase()));
    pill.appendChild(document.createTextNode("  " + info.count + " legs · " + fmtPct(info.hit_rate)));
    sideRow.appendChild(pill);
  });
  sides.appendChild(sideRow);

  const calTitle = el("div", "chart-title", "Calibration — actual win rate by model probability");
  sides.appendChild(calTitle);
  const chart = calibrationChart(bt.calibration);
  if (chart) sides.appendChild(chart);
  else sides.appendChild(el("div", "empty-note", "No calibration data yet."));
}

function renderPaper(data) {
  const paper = data.paper;
  const charts = $("#paper-charts");
  charts.innerHTML = "";

  const bankTitle = el("div", "chart-title", "Bankroll over time");
  const bankWrap = el("div", "chart-wrap");
  bankWrap.appendChild(bankTitle);
  const bankChart = lineChart(paper.bankroll_series.map((p) => ({ label: p.date.slice(5), value: p.bankroll })));
  if (bankChart) bankWrap.appendChild(bankChart);
  else bankWrap.appendChild(el("div", "empty-note", "No bankroll history yet."));
  charts.appendChild(bankWrap);

  const weekTitle = el("div", "chart-title", "Weekly P/L");
  const weekWrap = el("div", "chart-wrap");
  weekWrap.appendChild(weekTitle);
  const weekChart = barChart(paper.weekly_pl.map((w) => ({ label: w.week_start.slice(5), value: w.pl })));
  if (weekChart) weekWrap.appendChild(weekChart);
  else weekWrap.appendChild(el("div", "empty-note", "No weekly P/L yet."));
  charts.appendChild(weekWrap);

  const table = el("table");
  const thead = el("thead");
  const hrow = el("tr");
  ["Date", "Match", "Market", "Odds", "Stake", "Result", "Payout"].forEach((h) => {
    const th = el("th", h === "Odds" || h === "Stake" || h === "Payout" ? "num" : "", h);
    hrow.appendChild(th);
  });
  thead.appendChild(hrow);
  table.appendChild(thead);

  const tbody = el("tbody");
  if (paper.recent_trades.length === 0) {
    const tr = el("tr");
    const td = el("td", null, "No settled trades yet.");
    td.colSpan = 7;
    tr.appendChild(td);
    tbody.appendChild(tr);
  }
  paper.recent_trades.forEach((t) => {
    const tr = el("tr");
    tr.appendChild(el("td", null, t.date));
    tr.appendChild(el("td", null, t.home + " vs " + t.away));
    tr.appendChild(el("td", null, t.side.toUpperCase() + " " + Number(t.line).toFixed(1)));
    tr.appendChild(el("td", "num", fmtOdds(t.odds)));
    tr.appendChild(el("td", "num", fmtMoney(t.stake)));
    const resultTd = el("td", null);
    const badge = el("span", "badge " + (t.result === "win" ? "badge-win" : t.result === "loss" ? "badge-loss" : "badge-pending"), t.result);
    resultTd.appendChild(badge);
    tr.appendChild(resultTd);
    tr.appendChild(el("td", "num", t.payout > 0 ? fmtMoney(t.payout) : "0.00"));
    tbody.appendChild(tr);
  });
  table.appendChild(tbody);
  $("#recent-trades").innerHTML = "";
  $("#recent-trades").appendChild(table);
}

function renderTips(data) {
  const tips = data.tips;
  const wrap = $("#tips");
  wrap.innerHTML = "";

  const bannerText = tips.status === "bet" ? "BET — " + tips.parlay.legs.length + "-leg accumulator @ " + fmtOdds(tips.parlay.combined_odds)
    : tips.status === "paused" ? "STOP — MODEL PAUSED"
    : "NO BET TODAY";
  const banner = el("div", "tip-banner " + (tips.status === "bet" ? "tip-bet" : tips.status === "paused" ? "tip-paused" : "tip-no-bet"), bannerText);
  wrap.appendChild(banner);

  if (tips.no_bet_reason) wrap.appendChild(el("div", "reason", tips.no_bet_reason));

  if (tips.parlay) {
    const stats = el("div", "parlay-stats");
    [
      ["Combined odds", fmtOdds(tips.parlay.combined_odds)],
      ["Model win prob", fmtPct(tips.parlay.model_prob)],
      ["Stake", fmtMoney(tips.parlay.stake)],
    ].forEach(([label, value]) => {
      const s = el("div", "parlay-stat");
      s.appendChild(el("div", "label", label));
      s.appendChild(el("div", "value", value));
      stats.appendChild(s);
    });
    wrap.appendChild(stats);

    const table = el("table");
    const hrow = el("tr");
    ["#", "Match", "League", "Market", "Odds"].forEach((h) => hrow.appendChild(el("th", h === "#" ? "" : h === "Odds" ? "num" : "", h)));
    table.appendChild(hrow);
    const tbody = el("tbody");
    tips.parlay.legs.forEach((leg, i) => {
      const tr = el("tr");
      tr.appendChild(el("td", null, String(i + 1)));
      tr.appendChild(el("td", null, leg.home + " vs " + leg.away));
      tr.appendChild(el("td", null, leg.league || "—"));
      tr.appendChild(el("td", null, leg.side.toUpperCase() + " " + Number(leg.line).toFixed(1)));
      tr.appendChild(el("td", "num", fmtOdds(leg.odds)));
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    wrap.appendChild(table);
  }

  if (tips.candidate_legs.length > 0) {
    wrap.appendChild(el("h3", null, "Candidate legs (edge-ranked)"));
    const table = el("table");
    const hrow = el("tr");
    ["Match", "Market", "Odds", "Model", "Edge", ""].forEach((h) => hrow.appendChild(el("th", h === "Odds" || h === "Model" || h === "Edge" ? "num" : "", h)));
    table.appendChild(hrow);
    const tbody = el("tbody");
    tips.candidate_legs.forEach((leg) => {
      const tr = el("tr");
      tr.appendChild(el("td", null, leg.home + " vs " + leg.away));
      tr.appendChild(el("td", null, leg.side.toUpperCase() + " " + Number(leg.line).toFixed(1)));
      tr.appendChild(el("td", "num", fmtOdds(leg.odds)));
      tr.appendChild(el("td", "num", fmtPct(leg.model_prob)));
      const edgeTd = el("td", "num " + pctClass(leg.edge));
      edgeTd.textContent = (leg.edge * 100).toFixed(1) + "%";
      tr.appendChild(edgeTd);
      const q = el("td", null);
      q.appendChild(el("span", "badge " + (leg.qualifies ? "badge-qualifies" : "badge-skip"), leg.qualifies ? "qualifies" : "skip"));
      tr.appendChild(q);
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    wrap.appendChild(table);
  }

  if (tips.past_tips.length > 0) {
    wrap.appendChild(el("h3", null, "Past tips"));
    tips.past_tips.forEach((tip) => {
      const row = el("div", "past-tip");
      row.appendChild(el("span", "date", tip.date));
      row.appendChild(el("span", null, tip.legs + " legs @ " + fmtOdds(tip.combined_odds)));
      const badge = el("span", "badge " + (tip.won ? "badge-win" : "badge-loss"), tip.won ? "won" : "lost");
      row.appendChild(badge);
      row.appendChild(el("span", "num", tip.won ? fmtMoney(tip.payout) : fmtMoney(0)));
      wrap.appendChild(row);
    });
  }
}

function renderFixtures(data) {
  const wrap = $("#fixtures");
  wrap.innerHTML = "";
  const fixtures = data.fixtures;
  if (!fixtures || fixtures.length === 0) {
    wrap.appendChild(el("div", "empty-note", "No upcoming fixtures — set ODDS_API_KEY or run with --odds to populate."));
    return;
  }
  fixtures.forEach((fx) => {
    const row = el("div", "fixture");
    const teams = el("div", "teams");
    teams.appendChild(el("span", "league-code", fx.league || "?"));
    teams.appendChild(document.createTextNode(fx.home + " vs " + fx.away));
    row.appendChild(teams);

    const probs = el("div", "probs");
    const m = fx.model || {};
    probs.appendChild(document.createTextNode("O1.5 " + fmtPct(m["over1.5"] || 0) + "  U4.5 " + fmtPct(m["under4.5"] || 0)));
    row.appendChild(probs);

    const qual = el("div", "qual");
    const quals = fx.qualifies || [];
    if (quals.length === 0) qual.appendChild(el("span", "badge badge-skip", "no edge"));
    quals.forEach((q) => qual.appendChild(el("span", "badge badge-qualifies", q)));
    row.appendChild(qual);
    wrap.appendChild(row);
  });
}

function renderStrategy(data) {
  const s = data.strategy;
  const wrap = $("#strategy");
  wrap.innerHTML = "";
  const grid = el("div", "strategy-grid");
  const items = [
    ["Markets", s.markets.map((m) => m[0].toUpperCase() + " " + Number(m[1]).toFixed(1)).join(" / ")],
    ["Leg odds window", Number(s.leg_odds_window[0]).toFixed(2) + " – " + Number(s.leg_odds_window[1]).toFixed(2)],
    ["Target parlay odds", Number(s.target_parlay_odds).toFixed(1) + "+"],
    ["Min / max legs", s.min_legs + " / " + s.max_legs],
    ["Min edge", fmtPct(s.min_edge)],
    ["Pause after losses", String(s.pause_after_losses)],
  ];
  items.forEach(([label, value]) => {
    const box = el("div", "strategy-item");
    box.appendChild(el("div", "label", label));
    box.appendChild(el("div", "value", value));
    grid.appendChild(box);
  });
  wrap.appendChild(grid);
}

/* ---------------- boot ---------------- */

async function main() {
  const { data, source } = await loadData();
  $("#asOf").textContent = "As of " + data.as_of_date;
  $("#generatedAt").textContent = "Generated " + (data.generated_at ? data.generated_at.slice(0, 16).replace("T", " ") + " UTC" : "");
  const badge = $("#dataSource");
  badge.textContent = source === "live" ? "live data" : "sample data";
  badge.className = "meta-item badge " + (source === "live" ? "badge-win" : "badge-neutral");
  $("#footer-note").textContent =
    "Backtest: " + data.backtest.matches.toLocaleString() + " matches, " + data.backtest.parlays + " parlays, " +
    (data.backtest.roi * 100).toFixed(1) + "% ROI. Model refit daily; paper book appended per settled parlay.";

  renderKpis(data);
  renderBacktest(data);
  renderPaper(data);
  renderTips(data);
  renderFixtures(data);
  renderStrategy(data);
}

document.addEventListener("DOMContentLoaded", () => { main().catch(console.error); });
