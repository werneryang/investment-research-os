/* 交互图表：读取每次运行的 chart.json（由研究分支的展示组件生成），只做呈现，不重新计算。
 * kind 决定图表类型：curve（收益率走势与曲线对比）、scenarios（假设债券情景）、panels（通用面板：折线、散点、
 * 柱状、瀑布，可切换视图）；未知类型回退到静态图。颜色取自 style.css 的 --c1…--c8，按固定顺序使用。
 * 缺失值保持为断点（spanGaps: false），与计算中不插值的规则一致。
 *
 * 渐进增强：每个 .chart-panel 默认显示静态图；只有 Chart.js 已加载、数据取得、
 * 图表生成都成功后，才显示交互图表并收起静态图。任何一步失败，静态图保持可见，
 * 并按实际情况说明（有没有静态图）。禁用脚本时页面同样只显示静态图。 */
(function () {
  "use strict";

  var PALETTE = [];
  /* 页面语言：英文页面（html lang="en"）的界面文字用英文 */
  var EN = document.documentElement.lang === "en";
  function T(zh, en) { return EN ? en : zh; }
  var RANGES = [["1M", 1], ["3M", 3], ["6M", 6], ["1Y", 12], [T("全部", "All"), 0]];

  function css(name) {
    return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  }
  function palette() {
    if (!PALETTE.length) for (var i = 1; i <= 8; i++) PALETTE.push(css("--c" + i) || "#777");
    return PALETTE;
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
      { id: "levels", label: T("收益率（%）", "Yield (%)"), unit: "%", series: data.levels.map(function (t) { return { key: t, label: t }; }) },
      { id: "spreads", label: T("利差与曲率（bp）", "Spreads and curvature (bp)"), unit: "bp", series: data.spreads.concat(data.curvature) }
    ].filter(function (g) { return g.series.length; });
    if (!groups.length) return;

    var state = { group: groups[0], months: 0, hidden: {} };
    var controls = el("div", { class: "controls" });
    var seriesControls = el("div", { class: "controls" });
    var canvasBox = el("div", { class: "chart-box" });
    var canvas = el("canvas", { role: "img", "aria-label": T("收益率与利差走势（可交互）", "Yield and spread history (interactive)") });
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
      seriesControls.appendChild(el("span", { class: "group-label" }, T("序列", "Series")));
      g.series.forEach(function (s) {
        seriesControls.appendChild(toggle(s.label, !state.hidden[g.id + s.key], function () {
          state.hidden[g.id + s.key] = !state.hidden[g.id + s.key]; render();
        }));
      });
    }

    controls.appendChild(el("span", { class: "group-label" }, T("指标", "Metric")));
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
    controls.appendChild(el("span", { class: "group-label" }, T("　区间", " Range")));
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
    var a = el("select", { "aria-label": T("比较日期 A", "Comparison date A") }), b = el("select", { "aria-label": T("比较日期 B", "Comparison date B") });
    dates.slice().reverse().forEach(function (d) { a.appendChild(el("option", { value: d }, d)); b.appendChild(el("option", { value: d }, d)); });
    a.value = dates[0]; b.value = dates[dates.length - 1];
    controls.appendChild(el("span", { class: "group-label" }, T("曲线对比", "Compare curves")));
    controls.appendChild(a); controls.appendChild(el("span", { class: "group-label" }, "vs")); controls.appendChild(b);
    var canvasBox = el("div", { class: "chart-box" });
    var canvas = el("canvas", { role: "img", "aria-label": T("两个日期的收益率曲线对比（可交互）", "Yield curves on two dates (interactive)") });
    canvasBox.appendChild(canvas);
    box.appendChild(controls); box.appendChild(canvasBox);

    var byDate = {};
    data.rows.forEach(function (r) { byDate[r.date] = r; });
    /* 横轴按期限（年）的平方根排布：线性轴会把 1M–2Y 挤在左侧几个百分点内，
     * 对数轴又过度放大短端。刻度直接标期限代码，避免把位置误读为线性年数。 */
    var TICKS = ["3M", "1Y", "2Y", "5Y", "10Y", "20Y", "30Y"];
    var pos = function (months) { return Math.sqrt(months / 12); };
    var tickAt = {};
    data.tenors.forEach(function (t) { if (TICKS.indexOf(t.code) >= 0) tickAt[pos(t.months).toFixed(4)] = t.code; });
    var maxMonths = Math.max.apply(null, data.tenors.map(function (t) { return t.months; }));
    var opts = baseOptions("%");
    opts.interaction = { mode: "nearest", intersect: false };
    opts.scales.x = { type: "linear", min: 0, max: pos(maxMonths),
                      title: { display: true, text: T("期限（平方根刻度）", "Tenor (square-root scale)"), color: css("--muted") },
                      afterBuildTicks: function (axis) {
                        axis.ticks = Object.keys(tickAt).map(function (v) { return { value: +v }; });
                      },
                      ticks: { color: css("--muted"), autoSkip: false, maxRotation: 0,
                               callback: function (v) { return tickAt[(+v).toFixed(4)] || ""; } },
                      grid: { color: css("--line") } };
    opts.plugins.tooltip = { callbacks: { label: function (c) {
      return c.dataset.label + " " + c.raw.tenor + "：" + c.parsed.y.toFixed(2) + "%";
    } } };
    var chart = new Chart(canvas, { type: "scatter", data: { datasets: [] }, options: opts });

    function points(date) {
      var row = byDate[date];
      return data.tenors.filter(function (t) { return row[t.code] != null; })
        .map(function (t) { return { x: pos(t.months), y: row[t.code], tenor: t.code }; });
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

  /* 情景研究：所选期限的价格变化（完整重新定价与两种近似）及近似误差。x 轴为收益率冲击（bp）。 */
  function scenarioCharts(left, right, data) {
    if (!data.tenors || !data.tenors.length) throw new Error("no scenarios");
    var state = { tenor: data.focus || data.tenors[0] };
    var controls = el("div", { class: "controls" });
    controls.appendChild(el("span", { class: "group-label" }, T("假设债券期限", "Hypothetical bond tenor")));
    var buttons = data.tenors.map(function (t) {
      var b = el("button", { type: "button", class: "toggle", "aria-pressed": String(t === state.tenor) }, t);
      b.addEventListener("click", function () {
        state.tenor = t;
        buttons.forEach(function (o) { o.setAttribute("aria-pressed", String(o === b)); });
        render();
      });
      controls.appendChild(b);
      return b;
    });
    left.appendChild(controls);

    function lineChart(host, label, yTitle) {
      var box = el("div", { class: "chart-box" });
      var canvas = el("canvas", { role: "img", "aria-label": label });
      box.appendChild(canvas); host.appendChild(box);
      var opts = baseOptions(yTitle);
      opts.scales.x = { type: "linear", title: { display: true, text: T("收益率冲击（bp）", "Yield shock (bp)"), color: css("--muted") },
                        ticks: { color: css("--muted") }, grid: { color: css("--line") } };
      return new Chart(canvas, { type: "scatter", data: { datasets: [] }, options: opts });
    }
    var priceChart = lineChart(left, T("价格变化：完整重新定价与近似（可交互）", "Price change: full repricing and approximations (interactive)"), T("价格变化（%）", "Price change (%)"));
    right.appendChild(el("div", { class: "controls" }, T("近似误差 = 近似 − 完整重新定价（百分点）", "Approximation error = approximation − full repricing (pp)")));
    var errorChart = lineChart(right, T("近似误差（可交互）", "Approximation error (interactive)"), T("误差（pp）", "Error (pp)"));

    function series(rows, key, label, i, dash) {
      return { label: label, data: rows.map(function (r) { return { x: r.shock_bp, y: r[key] }; }),
               showLine: true, borderColor: PALETTE[i], backgroundColor: PALETTE[i], pointRadius: 2.5,
               borderWidth: 1.6, borderDash: dash || [] };
    }
    function render() {
      var rows = data.scenarios[state.tenor] || [];
      priceChart.data.datasets = [series(rows, "full_pct", T("完整重新定价", "Full repricing"), 0),
                                  series(rows, "duration_pct", T("久期近似", "Duration approx."), 1, [6, 4]),
                                  series(rows, "duration_convexity_pct", T("久期 + 凸性", "Duration + convexity"), 2, [2, 3])];
      errorChart.data.datasets = [series(rows, "duration_error_pp", T("久期近似误差", "Duration approx. error"), 1),
                                  series(rows, "duration_convexity_error_pp", T("久期 + 凸性误差", "Duration + convexity error"), 2)];
      priceChart.update(); errorChart.update();
    }
    render();
  }

  /* ---- 通用面板 ------------------------------------------------------------------
   * 每个面板一张图；views 是同一面板的不同数据视图（如名义 / 实际、各时间窗口）。点的 ref 是结果中的
   * 路径（如 results.nominal.SP500），关键发现的「在图中定位」据此高亮。数值已在生成网站时换算成显示单位，
   * 这里只格式化，不重新计算（瀑布图只把各部分依次堆叠显示）。 */
  var REGISTRY = [];

  function titled(axis) {
    return axis.label + (axis.unit ? T("（" + axis.unit + "）", " (" + axis.unit + ")") : "");
  }

  function fmt(axis, v) {
    if (v == null || isNaN(v)) return "—";
    var d = axis.digits == null ? 1 : axis.digits;
    return (axis.signed && v > 0 ? "+" : "") + v.toFixed(d) + (axis.unit ? (axis.unit === "%" ? "%" : " " + axis.unit) : "");
  }

  /* 散点的直接标注：只在面板要求时画（点少于十几个），文字用正文墨色，不用系列色 */
  var pointLabels = {
    id: "pointLabels",
    afterDatasetsDraw: function (chart) {
      if (!chart.options.plugins.pointLabels) return;
      var ctx = chart.ctx;
      ctx.save(); ctx.font = "11px " + getComputedStyle(document.body).fontFamily; ctx.fillStyle = css("--fg");
      chart.data.datasets.forEach(function (ds, i) {
        if (!chart.isDatasetVisible(i)) return;
        chart.getDatasetMeta(i).data.forEach(function (el, j) {
          var p = ds.data[j]; if (p && p.label) ctx.fillText(p.label, el.x + 6, el.y - 6);
        });
      });
      ctx.restore();
    }
  };

  function datasetsFor(panel, view) {
    var colors = palette();
    if (panel.type === "waterfall") {
      var pts = view.series[0].points, run = 0;
      var bars = pts.map(function (p) {
        if (p.total) { run = p.y; return { x: p.x, y: [0, p.y], v: p.y, ref: p.ref, total: true }; }
        var from = run; run += p.y;
        return { x: p.x, y: [from, run], v: p.y, ref: p.ref };
      });
      return [{ label: view.series[0].label, data: bars, parsing: { xAxisKey: "x", yAxisKey: "y" },
                backgroundColor: bars.map(function (b) { return b.total ? css("--muted") : b.v >= 0 ? colors[0] : colors[7]; }),
                borderRadius: 4, borderSkipped: false, maxBarThickness: 48 }];
    }
    return view.series.map(function (s, i) {
      var c = colors[(s.slot == null ? i : s.slot) % colors.length];
      var base = { label: s.label, borderColor: c, backgroundColor: c, borderDash: s.dash ? [6, 4] : [] };
      if (panel.type === "bar") {
        return Object.assign(base, { data: s.points.map(function (p) { return { x: panel.horizontal ? p.y : p.x, y: panel.horizontal ? p.x : p.y, ref: p.ref, label: p.label }; }),
                                     borderRadius: 4, borderSkipped: false, maxBarThickness: 28 });
      }
      if (panel.type === "scatter") {
        return Object.assign(base, { data: s.points, pointRadius: 4.5, pointHoverRadius: 7, pointBorderColor: css("--panel"), pointBorderWidth: 1.5 });
      }
      return Object.assign(base, { data: s.points, pointRadius: 0, pointHoverRadius: 4, borderWidth: 2, spanGaps: false });
    });
  }

  function buildPanel(host, panel) {
    var card = el("div", { class: "chart-card" + (panel.wide ? " wide" : "") });
    card.appendChild(el("h4", {}, panel.title));
    var controls = el("div", { class: "controls" });
    var box = el("div", { class: "chart-box" });
    box.style.height = (panel.height || 280) + "px";
    var canvas = el("canvas", { role: "img", "aria-label": panel.title });
    box.appendChild(canvas);
    card.appendChild(controls); card.appendChild(box);
    if (panel.note) card.appendChild(el("p", { class: "chart-note" }, panel.note));
    host.appendChild(card);

    var state = { view: 0, log: !!panel.y.log_default };
    var horizontal = panel.type === "bar" && panel.horizontal;
    var valueAxis = horizontal ? "x" : "y", catAxis = horizontal ? "y" : "x";
    var opts = baseOptions(titled(panel.y));
    opts.plugins.pointLabels = !!panel.labels;
    opts.plugins.legend.display = panel.type !== "waterfall" && (panel.views[0].series.length > 1);
    if (horizontal) {
      opts.indexAxis = "y";
      opts.scales.x.title = { display: true, text: opts.scales.y.title.text, color: css("--muted") };
      opts.scales.y = { ticks: { color: css("--muted"), autoSkip: false, font: { size: 10 } }, grid: { display: false } };
    }
    if (panel.type === "scatter" || (panel.type === "line" && panel.x.type === "linear")) {
      opts.scales.x.type = "linear";
      opts.scales.x.title = { display: true, text: titled(panel.x), color: css("--muted") };
      if (panel.x.type === "linear" && panel.type === "line") {
        opts.scales.x.bounds = "data";  // 横轴只到数据两端，不按整刻度外扩
        opts.scales.x.ticks.callback = function (v) { return String(v); };
      }
    }
    if (panel.type === "scatter") {
      opts.interaction = { mode: "nearest", intersect: true };
      opts.scales.x.grace = "5%"; opts.scales.y.grace = "8%";
    }
    opts.layout = { padding: { top: 6, right: panel.labels ? 56 : 8 } };  // 直接标注不被裁掉
    opts.plugins.tooltip = { callbacks: {
      title: function (items) {
        var p = items[0] && items[0].raw;
        return p && p.label ? p.label : items[0] ? String(items[0].label) : "";
      },
      label: function (c) {
        var p = c.raw || {};
        if (panel.type === "waterfall") return (p.total ? T("合计", "Total") : c.dataset.label) + T("：", ": ") + fmt(Object.assign({ signed: !p.total }, panel.y), p.v);
        if (panel.type === "scatter") return panel.x.label + " " + fmt(panel.x, p.x) + " · " + panel.y.label + " " + fmt(panel.y, p.y);
        return c.dataset.label + T("：", ": ") + fmt(panel.y, horizontal ? c.parsed.x : c.parsed.y);
      } } };
    if (panel.y.zero) opts.scales[valueAxis].beginAtZero = true;
    var chart = new Chart(canvas, { type: panel.type === "waterfall" ? "bar" : panel.type, data: { datasets: [] },
                                    options: opts, plugins: [pointLabels] });
    var entry = { chart: chart, panel: panel, state: state, render: null };
    REGISTRY.push(entry);

    function render() {
      var view = panel.views[state.view];
      chart.data.datasets = datasetsFor(panel, view);
      if (panel.type === "line" && panel.x.type !== "linear") {
        var seen = {}, labels = [];
        view.series.forEach(function (s) { s.points.forEach(function (p) { if (!seen[p.x]) { seen[p.x] = 1; labels.push(p.x); } }); });
        labels.sort();
        chart.data.labels = labels;
        chart.data.datasets.forEach(function (ds, i) {
          var by = {}; view.series[i].points.forEach(function (p) { by[p.x] = p.y; });
          ds.data = labels.map(function (x) { return by[x] == null ? null : by[x]; });
        });
      } else if (panel.type === "bar" || panel.type === "waterfall") {
        chart.data.labels = view.series[0].points.map(function (p) { return p.x; });  // 类别轴按给定顺序
      } else {
        chart.data.labels = undefined;
      }
      var scale = chart.options.scales[valueAxis];
      scale.type = state.log ? "logarithmic" : "linear";
      /* 对数轴只标 1、10、100…，避免 50,000.0 这类刻度 */
      scale.ticks.callback = state.log ? function (v) {
        var p = Math.log10(v);
        return Math.abs(p - Math.round(p)) < 1e-9 ? Number(v).toLocaleString() : "";
      } : undefined;
      if (horizontal) box.style.height = Math.max(panel.height || 280, 16 * view.series[0].points.length + 60) + "px";
      chart.update();
    }
    entry.render = render;
    if (panel.views.length > 1) {
      controls.appendChild(el("span", { class: "group-label" }, panel.views_label || T("视图", "View")));
      var buttons = panel.views.map(function (v, i) {
        var b = el("button", { type: "button", class: "toggle", "aria-pressed": String(i === 0) }, v.label);
        b.addEventListener("click", function () {
          state.view = i;
          buttons.forEach(function (o) { o.setAttribute("aria-pressed", String(o === b)); });
          render();
        });
        controls.appendChild(b);
        return b;
      });
      entry.select = function (i) { buttons[i].click(); };
    }
    if (panel.y.log_toggle) {
      controls.appendChild(toggle(T("对数刻度", "Log scale"), state.log, function (b) {
        state.log = b.getAttribute("aria-pressed") === "true"; render();
      }));
    }
    if (!controls.childNodes.length) controls.hidden = true;
    render();
  }

  function panelCharts(grid, data) {
    if (!data.panels || !data.panels.length) throw new Error("no panels");
    grid.className = "panel-grid";
    data.panels.forEach(function (panel) { buildPanel(grid, panel); });
  }

  /* 引用 ref 的发现：证据键等于 ref，或以 ref + "." 开头 */
  function cites(refs, ref) {
    return !!ref && refs.some(function (k) { return k === ref || k.indexOf(ref + ".") === 0; });
  }

  function matches(entry, refs, viewIndex) {
    var hits = [];
    entry.panel.views[viewIndex].series.forEach(function (s, di) {
      s.points.forEach(function (p, i) { if (cites(refs, p.ref)) hits.push({ datasetIndex: di, index: i }); });
    });
    return hits;
  }

  function highlight(refs) {
    var first = null;
    document.querySelectorAll(".hl").forEach(function (n) { n.classList.remove("hl"); });
    document.querySelectorAll("[data-ref]").forEach(function (n) {
      if (cites(refs, n.getAttribute("data-ref"))) { n.classList.add("hl"); first = first || n; }
    });
    REGISTRY.forEach(function (entry) {
      var view = entry.state.view, hits = matches(entry, refs, view);
      if (!hits.length) {
        for (var v = 0; v < entry.panel.views.length && !hits.length; v++) {
          if (v !== view && matches(entry, refs, v).length && entry.select) { entry.select(v); hits = matches(entry, refs, v); }
        }
      }
      if (entry.panel.type === "waterfall") hits = hits.map(function (h) { return { datasetIndex: 0, index: h.index }; });
      var c = entry.chart;
      c.setActiveElements(hits);
      if (c.tooltip) c.tooltip.setActiveElements(hits.slice(0, 1), { x: 0, y: 0 });
      c.update();
      if (hits.length) first = first || c.canvas;
    });
    if (first) first.scrollIntoView({ behavior: "smooth", block: "center" });
  }

  function hasTarget(refs) {
    var dom = Array.prototype.some.call(document.querySelectorAll("[data-ref]"), function (n) { return cites(refs, n.getAttribute("data-ref")); });
    return dom || REGISTRY.some(function (entry) {
      return entry.panel.views.some(function (_, v) { return matches(entry, refs, v).length > 0; });
    });
  }

  /* 关键发现旁的「在图中定位」：只在本页确有对应图形时显示 */
  function enableLocate() {
    document.querySelectorAll("button.locate[data-refs]").forEach(function (b) {
      var refs = JSON.parse(b.getAttribute("data-refs"));
      b.hidden = !hasTarget(refs);
      if (!b.dataset.bound) {
        b.dataset.bound = "1";
        b.addEventListener("click", function () { highlight(refs); });
      }
    });
  }

  var BUILDERS = {
    curve: function (grid, data) {
      var left = el("div"), right = el("div");
      grid.appendChild(left); grid.appendChild(right);
      seriesChart(left, data); curveChart(right, data);
    },
    scenarios: function (grid, data) {
      var left = el("div"), right = el("div");
      grid.appendChild(left); grid.appendChild(right);
      scenarioCharts(left, right, data);
    },
    panels: panelCharts
  };

  function enhance(panel) {
    var box = panel.querySelector(".interactive");
    var still = panel.querySelector(".chart-static");
    var status = panel.querySelector(".chart-status");
    var hasStatic = !!(still && still.querySelector("img"));

    function fallback(reason) {
      box.hidden = true;
      box.innerHTML = "";
      if (still) still.hidden = false;
      status.textContent = reason + (hasStatic ? T("，以下为静态图（与完整报告相同）。", "; showing the static figures instead (same as the full report).")
                                          : T("；本页没有可用的静态图。", "; no static figures are available on this page."));
      status.classList.add("warn");
    }

    if (!window.Chart) { fallback(T("交互图表脚本未能加载", "The interactive chart script did not load")); return; }
    fetch(panel.getAttribute("data-src"))
      .then(function (r) { if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); })
      .then(function (data) {
        var grid = el("div", { class: "chart-grid" });
        box.appendChild(grid);
        try {
          var build = BUILDERS[data.kind || "curve"];
          if (!build) throw new Error("unknown chart kind " + data.kind);
          palette();
          build(grid, data);
        } catch (err) {
          fallback(T("交互图表生成失败", "The interactive chart could not be drawn"));
          return;
        }
        box.hidden = false;
        REGISTRY.forEach(function (entry) { entry.chart.resize(); });
        enableLocate();
        if (!hasStatic) return;
        still.hidden = true;
        panel.appendChild(still);  // 展开的静态图放在按钮下方，展开时读者不会丢失位置
        var toggleStatic = el("button", { type: "button", class: "toggle", "aria-expanded": "false" }, T("显示静态图", "Show static figures"));
        toggleStatic.addEventListener("click", function () {
          still.hidden = !still.hidden;
          toggleStatic.setAttribute("aria-expanded", String(!still.hidden));
          toggleStatic.textContent = still.hidden ? T("显示静态图", "Show static figures") : T("隐藏静态图", "Hide static figures");
        });
        status.appendChild(toggleStatic);
      })
      .catch(function () { fallback(T("图表数据未能加载", "The chart data did not load")); });
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
    if (age) age.textContent = hours < 48 ? hours + T(" 小时前", " hours ago") : Math.floor(hours / 24) + T(" 天前", " days ago");
    if (weekdays > 2) {
      warn.classList.add("show");
      warn.querySelector("[data-weekdays]").textContent = String(weekdays);
    }
  }

  /* 语言切换：记住读者的选择（中文页面的页头脚本据此转到英文页面）；存储不可用时只切换本次 */
  function rememberLanguage() {
    document.querySelectorAll(".lang-switch").forEach(function (a) {
      a.addEventListener("click", function () {
        try { localStorage.setItem("lang", a.getAttribute("data-lang")); } catch (e) { /* 忽略 */ }
      });
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    rememberLanguage();
    staleness();
    document.querySelectorAll(".chart-panel[data-src]").forEach(enhance);
    enableLocate();
  });
})();
