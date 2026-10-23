/* 交互图表：读取每次运行的 daily.json（已是合格数据），只做呈现，不重新计算。
 * 缺失值保持为断点（spanGaps: false），与计算中不插值的规则一致。
 * Chart.js 未能加载时，展开静态图并提示。 */
(function () {
  "use strict";

  var PALETTE = ["#2b6cb0", "#dd6b20", "#2f855a", "#c53030", "#6b46c1", "#718096", "#b7791f"];
  var RANGES = [["1M", 1], ["3M", 3], ["6M", 6], ["1Y", 12], ["全部", 0]];

  function css(name) {
    return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  }

  function el(tag, attrs, text) {
    var node = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) { node.setAttribute(k, attrs[k]); });
    if (text != null) node.textContent = text;
    return node;
  }

  function toggle(label, pressed, onClick) {
    var b = el("button", { type: "button", class: "toggle", "aria-pressed": String(pressed) }, label);
    b.addEventListener("click", function () {
      b.setAttribute("aria-pressed", String(b.getAttribute("aria-pressed") !== "true"));
      onClick(b);
    });
    return b;
  }

  function baseOptions(yTitle) {
    var grid = css("--line"), text = css("--muted");
    return {
      responsive: true, maintainAspectRatio: false, animation: false,
      interaction: { mode: "index", intersect: false },
      plugins: { legend: { labels: { color: text, boxWidth: 12 } } },
      scales: {
        x: { ticks: { color: text, maxTicksLimit: 6, autoSkip: true, autoSkipPadding: 16, maxRotation: 0 },
             grid: { color: grid } },
        y: { title: { display: true, text: yTitle, color: text }, ticks: { color: text }, grid: { color: grid } }
      }
    };
  }

  function sliceByMonths(rows, months) {
    if (!months || !rows.length) return rows;
    var last = new Date(rows[rows.length - 1].date);
    var from = new Date(last); from.setMonth(from.getMonth() - months);
    return rows.filter(function (r) { return new Date(r.date) >= from; });
  }

  function seriesChart(box, data) {
    var groups = [
      { id: "levels", label: "收益率（%）", unit: "%", series: data.levels.map(function (t) { return { key: t, label: t }; }) },
      { id: "spreads", label: "利差与曲率（bp）", unit: "bp", series: data.spreads.concat(data.curvature) }
    ].filter(function (g) { return g.series.length; });
    if (!groups.length) return;

    var state = { group: groups[0], months: 0, hidden: {} };
    var controls = el("div", { class: "controls" });
    var seriesControls = el("div", { class: "controls" });
    var canvasBox = el("div", { class: "chart-box" });
    var canvas = el("canvas", { role: "img", "aria-label": "收益率与利差走势（可交互）" });
    canvasBox.appendChild(canvas);
    box.appendChild(controls); box.appendChild(seriesControls); box.appendChild(canvasBox);

    var chart = new Chart(canvas, { type: "line", data: { labels: [], datasets: [] }, options: baseOptions("") });

    function render() {
      var rows = sliceByMonths(data.rows, state.months);
      var g = state.group;
      chart.data.labels = rows.map(function (r) { return r.date; });
      chart.data.datasets = g.series.map(function (s, i) {
        return {
          label: s.label, data: rows.map(function (r) { return r[s.key] == null ? null : r[s.key]; }),
          borderColor: PALETTE[i % PALETTE.length], backgroundColor: PALETTE[i % PALETTE.length],
          borderWidth: 1.4, pointRadius: 0, spanGaps: false, hidden: !!state.hidden[g.id + s.key]
        };
      });
      chart.options.scales.y.title.text = g.unit;
      chart.options.plugins.tooltip = { callbacks: { label: function (c) {
        return c.dataset.label + "：" + (c.parsed.y == null ? "—" : c.parsed.y.toFixed(g.unit === "%" ? 2 : 0)) + " " + g.unit;
      } } };
      chart.update();
      seriesControls.innerHTML = "";
      seriesControls.appendChild(el("span", { class: "group-label" }, "序列"));
      g.series.forEach(function (s) {
        seriesControls.appendChild(toggle(s.label, !state.hidden[g.id + s.key], function () {
          state.hidden[g.id + s.key] = !state.hidden[g.id + s.key]; render();
        }));
      });
    }

    controls.appendChild(el("span", { class: "group-label" }, "指标"));
    var groupButtons = groups.map(function (g, i) {
      var b = el("button", { type: "button", class: "toggle", "aria-pressed": String(i === 0) }, g.label);
      b.addEventListener("click", function () {
        state.group = g;
        groupButtons.forEach(function (o) { o.setAttribute("aria-pressed", String(o === b)); });
        render();
      });
      controls.appendChild(b);
      return b;
    });
    controls.appendChild(el("span", { class: "group-label" }, "　区间"));
    var rangeButtons = RANGES.map(function (r) {
      var b = el("button", { type: "button", class: "toggle", "aria-pressed": String(r[1] === 0) }, r[0]);
      b.addEventListener("click", function () {
        state.months = r[1];
        rangeButtons.forEach(function (o) { o.setAttribute("aria-pressed", String(o === b)); });
        render();
      });
      controls.appendChild(b);
      return b;
    });
    render();
  }

  function curveChart(box, data) {
    if (!data.tenors.length || !data.rows.length) return;
    var dates = data.rows.map(function (r) { return r.date; });
    var controls = el("div", { class: "controls" });
    var a = el("select", { "aria-label": "比较日期 A" }), b = el("select", { "aria-label": "比较日期 B" });
    dates.slice().reverse().forEach(function (d) { a.appendChild(el("option", { value: d }, d)); b.appendChild(el("option", { value: d }, d)); });
    a.value = dates[0]; b.value = dates[dates.length - 1];
    controls.appendChild(el("span", { class: "group-label" }, "曲线对比"));
    controls.appendChild(a); controls.appendChild(el("span", { class: "group-label" }, "vs")); controls.appendChild(b);
    var canvasBox = el("div", { class: "chart-box" });
    var canvas = el("canvas", { role: "img", "aria-label": "两个日期的收益率曲线对比（可交互）" });
    canvasBox.appendChild(canvas);
    box.appendChild(controls); box.appendChild(canvasBox);

    var byDate = {};
    data.rows.forEach(function (r) { byDate[r.date] = r; });
    var opts = baseOptions("%");
    opts.interaction = { mode: "nearest", intersect: false };
    opts.scales.x = { type: "linear", title: { display: true, text: "期限（年）", color: css("--muted") },
                      ticks: { color: css("--muted") }, grid: { color: css("--line") } };
    opts.plugins.tooltip = { callbacks: { label: function (c) {
      return c.dataset.label + " " + c.raw.tenor + "：" + c.parsed.y.toFixed(2) + "%";
    } } };
    var chart = new Chart(canvas, { type: "scatter", data: { datasets: [] }, options: opts });

    function points(date) {
      var row = byDate[date];
      return data.tenors.filter(function (t) { return row[t.code] != null; })
        .map(function (t) { return { x: t.months / 12, y: row[t.code], tenor: t.code }; });
    }
    function render() {
      chart.data.datasets = [a.value, b.value].map(function (d, i) {
        return { label: d, data: points(d), showLine: true, borderColor: PALETTE[i], backgroundColor: PALETTE[i],
                 pointRadius: 2.5, borderWidth: 1.6 };
      });
      chart.update();
    }
    a.addEventListener("change", render); b.addEventListener("change", render);
    render();
  }

  function fail(box, message) {
    box.appendChild(el("p", { class: "chart-error" }, message));
    var details = box.parentNode.querySelector("details.static-figs");
    if (details) details.open = true;
  }

  function staleness() {
    var bar = document.querySelector("[data-built-at]");
    var warn = document.querySelector(".stale");
    if (!bar || !warn) return;
    var built = new Date(bar.getAttribute("data-built-at")), now = new Date();
    var weekdays = 0, d = new Date(built);
    while (d < now) { d.setUTCDate(d.getUTCDate() + 1); if (d <= now && d.getUTCDay() % 6 !== 0) weekdays++; }
    var hours = Math.floor((now - built) / 36e5);
    var age = document.querySelector("[data-age]");
    if (age) age.textContent = hours < 48 ? hours + " 小时前" : Math.floor(hours / 24) + " 天前";
    if (weekdays > 2) {
      warn.classList.add("show");
      warn.querySelector("[data-weekdays]").textContent = String(weekdays);
    }
  }

  document.addEventListener("DOMContentLoaded", function () {
    staleness();
    document.querySelectorAll(".interactive[data-src]").forEach(function (box) {
      if (!window.Chart) { fail(box, "交互图表未能加载，已显示静态图。"); return; }
      fetch(box.getAttribute("data-src"))
        .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
        .then(function (data) {
          var grid = el("div", { class: "chart-grid" });
          var left = el("div"), right = el("div");
          grid.appendChild(left); grid.appendChild(right); box.appendChild(grid);
          seriesChart(left, data); curveChart(right, data);
        })
        .catch(function () { fail(box, "图表数据未能加载，已显示静态图。"); });
    });
  });
})();
