/* 交互图表：读取每次运行的 chart.json（由研究分支的展示组件生成），只做呈现，不重新计算。
 * kind 决定图表类型：curve（收益率走势与曲线对比）、scenarios（假设债券情景）；未知类型回退到静态图。
 * 缺失值保持为断点（spanGaps: false），与计算中不插值的规则一致。
 *
 * 渐进增强：每个 .chart-panel 默认显示静态图；只有 Chart.js 已加载、数据取得、
 * 图表生成都成功后，才显示交互图表并收起静态图。任何一步失败，静态图保持可见，
 * 并按实际情况说明（有没有静态图）。禁用脚本时页面同样只显示静态图。 */
(function () {
  "use strict";

  var PALETTE = ["#2b6cb0", "#dd6b20", "#2f855a", "#c53030", "#6b46c1", "#718096", "#b7791f"];
  /* 页面语言：英文页面（html lang="en"）的界面文字用英文 */
  var EN = document.documentElement.lang === "en";
  function T(zh, en) { return EN ? en : zh; }
  var RANGES = [["1M", 1], ["3M", 3], ["6M", 6], ["1Y", 12], [T("全部", "All"), 0]];

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

  var BUILDERS = {
    curve: function (left, right, data) { seriesChart(left, data); curveChart(right, data); },
    scenarios: scenarioCharts
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
        var left = el("div"), right = el("div");
        grid.appendChild(left); grid.appendChild(right); box.appendChild(grid);
        try {
          var build = BUILDERS[data.kind || "curve"];
          if (!build) throw new Error("unknown chart kind " + data.kind);
          build(left, right, data);
        } catch (err) {
          fallback(T("交互图表生成失败", "The interactive chart could not be drawn"));
          return;
        }
        box.hidden = false;
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
  });
})();
