'use strict';
(() => {
  const BATCH = { first: '第一批 · 先做', second: '第二批', later: '后续' };
  const AVAILABLE = { public: '通常公开可得', partial: '部分 / 条件可得', unavailable: '关键数据未公开', unknown: '尚未评估' };
  const AVAILABLE_SHORT = { public: '数据公开', partial: '数据部分可得', unavailable: '关键数据未公开', unknown: '数据未评估' };
  const SCOPE = { facts: '事实整理', historical: '历史计算', conditional: '条件推演', qualitative: '定性线索', unassessed: '待评估' };
  const KIND = { decomposition: '拆解', checklist: '检查清单', routing: '方法选择', measurement: '测量', scenario: '情景推演', argument: '论证对照', tracking: '跟踪' };
  const STATUS = { draft: '草稿', consolidated: '已归纳', retired: '已停用' };
  const DEPTH = { runnable: '该来源讲解可执行', partial: '该来源讲解不完整', mention: '仅提及', unknown: '深度未填写' };
  const CHECK = { source_checked: '已对照原件', derived_checked: '仅对照派生版本', draft: '未回原文核对', unknown: '核对状态未填写' };
  const TIER = { professional: '专业研究机构', academic: '学术', student: '学生', creator: '个人创作者', ai_template: 'AI 工具模版', official: '官方申报', own: '个人输入' };
  const REVIEW = { pending: '待用户复核', passed: '用户复核通过', partial: '用户复核部分通过', failed: '用户复核不通过' };
  const TECH = { pass: '技术复核通过', pass_with_corrections: '技术复核通过（有更正）', pass_with_notes: '技术复核通过（有待定事项）', fail: '技术复核不通过' };
  const MIX = { student_only: '仅学生来源', no_record: '无提取记录', mixed: '学生加其他来源', non_student: '无学生来源' };
  const VIEWS = ['logic', 'library', 'relations', 'labels'];
  const TABS = ['content', 'conditions', 'sources', 'boundaries'];
  const rank = { first: 0, second: 1, later: 2 };
  const DEFAULT = { view: 'logic', mech: 'expectations_gap', stage: 'all', batch: 'all', availability: 'all', scope: 'all', q: '', id: 'dupont-return-decomposition', tab: 'content', panel: 'list' };
  const esc = value => String(value ?? '').replace(/[&<>"']/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[char]));

  function filterCards(data, state) {
    const stage = data.stages.find(s => s.id === state.stage);
    const terms = state.q.trim().toLocaleLowerCase().split(/\s+/).filter(Boolean);
    return data.cards.filter(c =>
      (!stage || stage.methods.includes(c.id)) &&
      (state.batch === 'all' || c.ui.batch === state.batch) &&
      (state.availability === 'all' || c.ui.availability.status === state.availability) &&
      (state.scope === 'all' || c.ui.scope.types.includes(state.scope)) &&
      terms.every(term => [c.id, c.name_zh, c.name_en, ...Object.values(c.sections), c.ui.scope.note].join(' ').toLocaleLowerCase().includes(term))
    ).sort((a, b) => rank[a.ui.batch] - rank[b.ui.batch] || a.name_zh.localeCompare(b.name_zh, 'zh-Hans'));
  }

  function relatedIds(data, id) {
    const card = data.cards.find(c => c.id === id);
    if (!card) return [];
    return [...new Set([...(card.related || []), ...data.cards.filter(c => c.related.includes(id)).map(c => c.id)])].filter(other => other !== id);
  }

  // Methods listed for one return mechanism, in the order the routing table gives them.
  function mechanismCards(data, type) {
    const mechanism = (data.mechanisms || []).find(m => m.type === type);
    if (!mechanism) return [];
    return mechanism.methods.map(id => data.cards.find(c => c.id === id)).filter(Boolean);
  }

  function normalizeState(raw, data) {
    const s = { ...DEFAULT, ...raw };
    if (s.view === 'questions') s.view = 'logic';  // Example routes now live on the logic page.
    if (!VIEWS.includes(s.view)) s.view = 'logic';
    const mechanisms = (data.mechanisms || []).map(m => m.type);
    if (!mechanisms.includes(s.mech)) s.mech = mechanisms[0] || DEFAULT.mech;
    if (!['all', ...data.stages.map(x => x.id)].includes(s.stage)) s.stage = 'all';
    if (!['all', ...Object.keys(BATCH)].includes(s.batch)) s.batch = 'all';
    if (!['all', ...Object.keys(AVAILABLE)].includes(s.availability)) s.availability = 'all';
    if (!['all', ...Object.keys(SCOPE)].includes(s.scope)) s.scope = 'all';
    if (!data.cards.some(c => c.id === s.id)) s.id = data.cards[0]?.id || '';
    if (!TABS.includes(s.tab)) s.tab = 'content';
    if (!['list', 'detail'].includes(s.panel)) s.panel = 'list';
    s.q = String(s.q || '').slice(0, 300);
    return s;
  }
  if (typeof module !== 'undefined') module.exports = { filterCards, relatedIds, mechanismCards, normalizeState };
  if (typeof document === 'undefined') return;

  const STORAGE_KEY = 'method-atlas-v2';
  let data, byId, state;
  const $ = selector => document.querySelector(selector);
  const narrow = () => matchMedia('(max-width: 1000px)').matches;

  function readHash() {
    const p = new URLSearchParams(location.hash.slice(1));
    const raw = {};
    for (const key of Object.keys(DEFAULT)) if (p.has(key)) raw[key] = p.get(key);
    if (p.has('method')) { raw.id = p.get('method'); raw.panel ??= 'detail'; }
    return raw;
  }
  // Without an explicit method, open on the first method of the selected mechanism rather than an unrelated card.
  function loadState(raw) {
    const s = normalizeState(raw, data);
    if (!raw.id && s.view === 'logic') s.id = mechanismCards(data, s.mech)[0]?.id || s.id;
    return s;
  }
  function save(push = false) {
    const p = new URLSearchParams();
    for (const [key, value] of Object.entries(state)) if (value !== DEFAULT[key]) p.set(key, value);
    p.set('method', state.id);
    p.delete('id');
    const url = location.pathname + location.search + '#' + p.toString();
    history[push ? 'pushState' : 'replaceState']({}, '', url);
    try { localStorage.setItem(STORAGE_KEY, JSON.stringify(state)); } catch { /* Read-only/private browsing works without persistence. */ }
  }

  // ---------- shared pieces ----------
  const stageIndex = id => data.stages.findIndex(s => s.id === id);
  const stageLabel = id => { const i = stageIndex(id); return i < 0 ? '' : `${String(i + 1).padStart(2, '0')} ${data.stages[i].name}`; };
  const badge = c => `<span class="batch-badge ${c.ui.batch}">${BATCH[c.ui.batch]}</span>`;
  // Who wrote the materials behind a card; only the two weak cases get a visible flag.
  const mixFlag = c => ['student_only', 'no_record'].includes(c.source_mix.label) ? MIX[c.source_mix.label] : '';
  const mixText = c => Object.entries(c.source_mix.tiers).map(([t, n]) => `${TIER[t] || t} ${n}`).join(' · ') || '没有可计入的提取记录';
  const avail = (c, labels = AVAILABLE_SHORT) => `<span class="avail ${c.ui.availability.status}">${labels[c.ui.availability.status]}</span>`;
  const pressed = c => `aria-pressed="${state.id === c.id}"`;

  function rowHTML(c, index) {
    return `<button class="method-row ${c.ui.batch}" data-method="${esc(c.id)}" ${pressed(c)}>
      ${index === undefined ? '' : `<span class="row-index">${String(index + 1).padStart(2, '0')}</span>`}
      <span class="row-main"><span class="row-name">${esc(c.name_zh)}</span><span class="row-question">${esc(c.question_summary)}</span></span>
      <span class="row-meta">${badge(c)}${avail(c)}</span>
    </button>`;
  }
  function cardHTML(c) {
    return `<button class="method-card ${c.ui.batch}" data-method="${esc(c.id)}" ${pressed(c)}>
      <span class="card-top"><span class="card-stage">${esc(stageLabel(c.stage))}</span>${badge(c)}</span>
      <span class="card-name">${esc(c.name_zh)}</span>
      <span class="card-question">${esc(c.question_summary)}</span>
      <span class="card-meta">${avail(c)}<span>${c.ui.scope.types.map(t => SCOPE[t]).join(' · ')}</span></span>
      <span class="card-foot"><span>${esc(KIND[c.kind] || c.kind)}</span><span>${esc(STATUS[c.status] || c.status)}</span>${mixFlag(c) ? `<span class="mix-flag">${mixFlag(c)}</span>` : ''}</span>
    </button>`;
  }
  const chipHTML = c => `<button class="chip" data-method="${esc(c.id)}" ${pressed(c)}>${esc(c.name_zh)}</button>`;

  // ---------- navigation ----------
  function renderNavigation() {
    $('#library-stats').textContent = `${data.cards.length} 张方法卡 · ${data.records.length} 份记录`;
    $('#build-info').textContent = '快照生成于 ' + new Date(data.built_at).toLocaleString('zh-CN');
    document.querySelectorAll('[data-view]').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.view === state.view)));
    $('#stage-nav').innerHTML = `<button data-stage="all" aria-pressed="${state.stage === 'all'}"><span class="stage-number">全部</span><span class="stage-name">所有环节</span><span class="stage-count">${data.cards.length}</span></button>` + data.stages.map((s, i) => `<button data-stage="${s.id}" aria-pressed="${state.stage === s.id}"><span class="stage-number">${String(i + 1).padStart(2, '0')}</span><span class="stage-name">${esc(s.name)}</span><span class="stage-count">${s.methods.length}</span></button>`).join('');
    $('#batch-filters').innerHTML = `<span class="filter-label">实施批次</span><button class="batch-button" data-batch="all" aria-pressed="${state.batch === 'all'}">全部<b>${data.cards.length}</b></button>` + Object.keys(BATCH).map(b => `<button class="batch-button ${b}" data-batch="${b}" aria-pressed="${state.batch === b}">${BATCH[b]}<b>${data.batch_counts[b]}</b></button>`).join('');
    $('.filters').hidden = state.view !== 'library';
    $('#search').value = state.q;
    $('#availability').value = state.availability;
    $('#scope').value = state.scope;
    document.body.dataset.view = state.view;
    document.body.classList.toggle('detail-open', state.panel === 'detail');
  }

  // ---------- views ----------
  function renderLogic() {
    const mechanism = data.mechanisms.find(m => m.type === state.mech);
    const methods = mechanismCards(data, state.mech);
    return `<div class="page-head">
        <p class="eyebrow">投资逻辑</p>
        <h1>先想清楚赌的是什么，再找方法。</h1>
        <p class="lede">从“为什么认为价格会变”出发：这个判断要证明什么，用哪些方法证明，库里还缺什么。</p>
        <p class="provenance">机制的划分、要证明什么、对应哪些卡，都是整理时补充，尚无材料来源。</p>
      </div>
      <section class="step">
        <h2><span class="step-no">1</span>你认为价格为什么会变？</h2>
        <div class="mech-grid">${data.mechanisms.map(m => `<button class="mech" data-mech="${esc(m.type)}" aria-pressed="${m.type === state.mech}"><span class="mech-name">${esc(m.name)}</span><span class="mech-def">${esc(m.definition)}</span><span class="mech-count">先看 ${m.methods.length} 个 · 共 ${m.methods.length + m.more.length} 个</span></button>`).join('')}</div>
        <p class="hint">机制不互斥，一个判断可以同时属于两种。不按用了什么方法倒推：用了 DCF 不等于赌估值修复。</p>
      </section>
      <section class="step">
        <h2><span class="step-no">2</span>赌“${esc(mechanism.name)}”，要证明什么</h2>
        <ol class="prove">${mechanism.prove.map(p => `<li>${esc(p)}</li>`).join('')}</ol>
      </section>
      <section class="step">
        <h2><span class="step-no">3</span>先看这些方法<span class="count">${methods.length} 个</span></h2>
        <div class="row-list">${methods.map((c, i) => rowHTML(c, i)).join('')}</div>
        ${mechanism.more.length ? `<h3 class="sub">按需再看<span class="count">${mechanism.more.length} 个</span></h3><div class="chips">${mechanism.more.map(id => chipHTML(byId[id])).join('')}</div>` : ''}
        <p class="hint">“先看”的卡直接回答上面要证明的事，“按需再看”是做到某一项时可能用到的。两档都不代表这种机制只需要这些方法，也不判断方法是否有效。</p>
      </section>
      <section class="step">
        <h2><span class="step-no">4</span>库里还缺什么</h2>
        <div class="callout prose">${mechanism.missing_html}</div>
        <p class="hint">找不到卡、或卡里讲到一半的地方，就是下一步该去找材料提取的方法。</p>
      </section>
      <section class="block">
        <h2>各机制通用<span class="count">${data.common.reduce((n, g) => n + g.methods.length, 0)} 个</span></h2>
        <p class="hint lead">不专属于某一种机制，按用途分组，顺序大致跟着一次研究的先后。</p>
        <div class="common-grid">${data.common.map(g => `<div class="common"><h3>${esc(g.label)}</h3><div class="chips">${g.methods.map(id => chipHTML(byId[id])).join('')}</div></div>`).join('')}</div>
      </section>
      <section class="block">
        <h2>从一个具体问题开始<span class="count">${data.routes.length} 条示例</span></h2>
        <p class="hint">路径是导航建议，可按研究对象调整；不表示已经运行或具备全部输入。</p>
        <div class="route-grid">${data.routes.map(r => `<article class="route-card"><h3>${esc(r.question)}</h3><ol class="route-steps">${r.methods.map(id => `<li><button data-method="${esc(id)}" ${pressed(byId[id])}>${esc(byId[id].name_zh)}</button></li>`).join('')}</ol><p class="boundary">${esc(r.boundary)}</p></article>`).join('')}</div>
      </section>`;
  }
  function renderLibrary(filtered) {
    const stage = data.stages.find(s => s.id === state.stage);
    const intro = stage ? esc(stage.question) : '全部环节，按实施批次排序。';
    const list = filtered.length ? `<div class="card-grid">${filtered.map(cardHTML).join('')}</div>` : '<div class="empty"><h3>没有符合条件的方法</h3><p>尝试减少筛选条件，或换一个问题关键词。</p><button data-action="reset">清除筛选</button></div>';
    return `<div class="list-header"><div><h2>${esc(stage ? stageLabel(stage.id) : '全部研究方法')}</h2><p class="view-intro">${intro}</p></div><span class="count" role="status">${filtered.length} / ${data.cards.length} 项</span></div>${list}`;
  }
  function renderRelations(selected) {
    const neighbors = relatedIds(data, state.id).map(id => byId[id]);
    return `<div class="page-head"><p class="eyebrow">关联方法</p><h1>${esc(selected.name_zh)}</h1><p class="lede">按卡片已有 related 字段展开一层。连线表示相关，不表示因果、依赖或执行先后。选择一个方法可继续展开。</p></div>
      <div class="list-header"><div><h2>相关方法</h2></div><span class="count">${neighbors.length} 个</span></div>
      ${neighbors.length ? `<div class="row-list">${neighbors.map(c => rowHTML(c)).join('')}</div>` : '<p class="boundary">暂无相关方法。</p>'}
      <p class="hint">全库共有 ${data.relationship_count} 对不重复关联。</p>`;
  }
  function renderLabels() {
    return `<div class="page-head"><p class="eyebrow">标签说明</p><h1>三个独立标签</h1><p class="lede">资料拿得到、能做完某一步、前提已具备，是三件不同的事。</p></div>
      <div class="explainer-grid">
      <article class="explainer"><h3>公开数据可得性 · 看输入</h3><p>需要的资料能否从公开渠道取得？</p><ul><li><span class="avail public">通常公开可得</span>：有常见公开披露渠道，具体公司仍需检查。</li><li><span class="avail partial">部分 / 条件可得</span>：关键明细、历史版本或付费输入可能缺失。</li><li><span class="avail unavailable">关键数据未公开</span>：有证据表明所需关键输入未披露。</li><li><span class="avail unknown">尚未评估</span>：仅留给尚未完成初评的新方法；当前方法库已逐项初评。</li></ul><p>公开可得不等于有稳定接口，也不等于已下载或完成核对。</p></article>
      <article class="explainer"><h3>可执行范围 · 看输出</h3><p>可以整理事实、计算历史指标、在假设下推演，或只给定性线索。这些是输出类型，不是质量等级。</p><p>同一卡片可以有多个范围。例如现金周期可计算历史值，未来预测仍需收入、成本和天数假设。</p></article>
      <article class="explainer"><h3>前置依赖 · 看准备</h3><p>执行前需要的数据、口径、比较对象、模型与参数。关联方法不自动等于前置依赖。</p><p>方法层面列出所需条件；具体公司实例另记数据覆盖、依赖就绪和实测结果。“尚未实测”仅用于具体公司实例，本版尚未建立实例。</p></article>
      <article class="explainer"><h3>颜色表示实施顺序</h3><p><span class="batch-badge first">第一批 · 先做</span> 四项优先方法的指定范围。</p><p><span class="batch-badge second">第二批</span> 十项需附注、口径判断或额外资料的方法。</p><p><span class="batch-badge later">后续</span> 其余方法均已完成初评；实施顺序不代表质量等级。</p></article>
      </div>
      <p class="boundary">${esc(data.assessment_basis)}</p>`;
  }

  // ---------- detail ----------
  function section(c, title, open = false, label = title) {
    const content = c.section_html[title];
    if (!content) return `<details><summary>${esc(label)}</summary><p class="prose">本卡尚未填写；不表示没有限制。</p></details>`;
    return `<details${open ? ' open' : ''}><summary>${esc(label)}</summary><div class="prose">${content}</div></details>`;
  }
  function renderConditions(c) {
    const m = c.ui, deps = m.dependencies, runs = m.executions || [];
    const executions = runs.length ? `<section class="label-row"><h3>执行实测<span>在真实公司上照卡走过；不改变归纳状态，也不判断方法对错</span></h3><ul>${runs.map(r => `<li><strong>${esc(r.company)}</strong> · 第 ${r.steps.map(Number).join('、')} 步 · ${esc(REVIEW[r.review] || r.review)}${r.technical_review ? ` · ${esc(TECH[r.technical_review.result] || r.technical_review.result)}（${esc(r.technical_review.by)}，${esc(r.technical_review.date)}，未经人工）` : ''}<br>${esc(r.reached)}<br><span class="quiet">第一处要猜：${esc(r.first_guess)}</span> <a href="results/${esc(r.test)}.html" target="_blank" rel="noopener">测试记录 ↗</a></li>`).join('')}</ul></section>` : '';
    return `<p class="detail-context">方法层面：${m.assessment === 'unassessed' ? '尚未初评' : '初评完成 · 依据卡片整理'}。公司实例：${runs.length ? `已有 ${runs.length} 条实测记录，见下方“执行实测”。` : '尚未建立；选定公司、期间与数据版本后另记实测结果。'}</p>${executions}
      <section class="label-row"><h3>公开数据可得性</h3><div class="label-value">${avail(c, AVAILABLE)}</div><p>${esc(m.availability.note)}</p>${m.availability.channels.length ? `<ul class="channels">${m.availability.channels.map(s => `<li>${esc(s)}</li>`).join('')}</ul>` : ''}</section>
      <section class="label-row"><h3>可执行范围</h3><div class="label-value">${m.scope.types.map(t => `<span class="tag">${SCOPE[t]}</span>`).join('')}</div><p>${esc(m.scope.note)}</p></section>
      <section class="label-row"><h3>前置依赖<span>方法层面的准备条件</span></h3>${deps.methods.length ? `<div class="chips">${deps.methods.map(id => `<button class="chip" data-dependency="${esc(id)}">${esc(byId[id].name_zh)}</button>`).join('')}</div>` : ''}<ul>${deps.requirements.map(s => `<li>${esc(s)}</li>`).join('')}</ul>${deps.unresolved.map(s => `<p class="missing">待补：${esc(s)}</p>`).join('')}</section>
      <p class="label-note">${esc(m.rationale)}</p>`;
  }
  function renderSources(c) {
    return `<p class="detail-context">核对状态只表示与指定版本一致；讲解深度来自单份记录，不代表整张方法卡完整或方法有效。</p><h3 class="section-title">依据构成 · ${esc(MIX[c.source_mix.label])}</h3><p class="source-mix">${esc(mixText(c))}</p><p class="quiet">按提取记录的作者层级统计，一份记录算一条，只被提及的不算。层级说明材料是谁写的，不判断方法对错。${c.source_mix.unrecorded ? `另有 ${c.source_mix.unrecorded} 条引用没有提取记录。` : ''}</p><h3 class="section-title">卡片来源引用 · ${c.sources.length} 条</h3><p class="quiet">引用条数不等于独立来源数。</p>${c.sources.map(s => `<div class="source-ref">${esc(s.ref)} <span class="quiet">[${esc(s.type)}]</span>${s.recorded ? '' : ' <span class="tag mix-flag">无提取记录</span>'}</div>`).join('')}<h3 class="section-title">可定位的提取记录 · ${c.evidence.length} 条映射</h3>${c.evidence.length ? c.evidence.map(e => `<article class="evidence-card"><h3>${esc(e.title)} · ${esc(e.ref)}</h3><div class="evidence-tags"><span class="tag">${esc(DEPTH[e.depth] || e.depth)}</span><span class="tag">${esc(CHECK[e.status] || e.status)}</span><span class="tag">${esc(TIER[e.tier] || e.tier)}</span></div><p>${esc(e.review)}</p><a href="${esc(e.source_path)}" target="_blank" rel="noopener">查看研究成果 ↗</a></article>`).join('') : '<p class="boundary">暂无可自动定位的记录映射，请以上方来源引用及原卡为准。</p>'}`;
  }
  function renderDetail(c) {
    if (!c) { $('#detail').innerHTML = ''; return; }
    let body;
    if (state.tab === 'conditions') body = renderConditions(c);
    else if (state.tab === 'sources') body = renderSources(c);
    else if (state.tab === 'boundaries') body = ['推翻条件', '方法失效条件', '变体与冲突', '别名与易混方法', '待补充'].map((t, i) => section(c, t, i === 0)).join('');
    else {
      const fullQuestion = (c.sections['回答什么问题'] || '').includes('\n\n') ? section(c, '回答什么问题', false, '问题的完整表述') : '';
      body = fullQuestion + section(c, '适用 / 不适用', true) + section(c, '所需数据') + section(c, '步骤', true) + section(c, '输出格式') + section(c, '判断规则与常见误读') + section(c, '来源案例');
    }
    if (state.tab === 'content') {
      const displayed = ['回答什么问题', '适用 / 不适用', '所需数据', '步骤', '输出格式', '判断规则与常见误读', '来源案例', '推翻条件', '方法失效条件', '变体与冲突', '别名与易混方法', '待补充'];
      body += Object.keys(c.section_html).filter(key => !displayed.includes(key)).map(key => section(c, key)).join('');
      if (c.reports.length) body += '<h3>相关公开报告</h3><ul>' + c.reports.map(r => `<li><a href="${esc(r.url)}">${esc(r.id)}</a></li>`).join('') + '</ul>';
    }
    const mechanisms = data.mechanisms.filter(m => c.mechanisms.includes(m.type));
    const where = mechanisms.map(m => `<button class="chip" data-mech="${esc(m.type)}">${esc(m.name)}</button>`).join('') + c.common.map(label => `<span class="tag">通用 · ${esc(label)}</span>`).join('');
    const tab = (id, label) => `<button data-tab="${id}" aria-pressed="${state.tab === id}">${label}</button>`;
    $('#detail').innerHTML = `<button class="detail-back" data-action="back-list">← 返回</button><article class="detail-panel ${c.ui.batch}">
      <header class="detail-header">
        <div class="detail-tags">${badge(c)}<span class="tag">${esc(STATUS[c.status] || c.status)}</span><span class="tag">${esc(KIND[c.kind] || c.kind)}</span>${mixFlag(c) ? `<span class="tag mix-flag">${mixFlag(c)}</span>` : ''}</div>
        <h2>${esc(c.name_zh)}</h2><p class="english">${esc(c.name_en)}</p>
        <p class="question">${esc(c.question_summary)}</p>
        <dl class="where">
          <div><dt>研究环节</dt><dd><button class="chip" data-stage="${esc(c.stage)}">${esc(stageLabel(c.stage))}</button></dd></div>
          <div><dt>收益机制</dt><dd>${where || '<span class="quiet">未列入对照表</span>'}</dd></div>
          <div><dt>执行条件</dt><dd>${avail(c)}<span class="quiet">${c.ui.scope.types.map(t => SCOPE[t]).join(' · ')}</span></dd></div>
        </dl>
        <div class="detail-actions"><button data-action="relations">关联方法 · ${relatedIds(data, c.id).length}</button></div>
      </header>
      <nav class="detail-tabs" aria-label="详情栏目">${tab('content', '怎么做')}${tab('conditions', '执行条件')}${tab('sources', '来源证据')}${tab('boundaries', '推翻与边界')}</nav>
      <div class="detail-body">${body}</div></article>`;
  }

  function renderResults() {
    let selected = byId[state.id];
    if (state.view === 'library') {
      const filtered = filterCards(data, state);
      if (filtered.length && !filtered.some(c => c.id === state.id)) state.id = filtered[0].id;
      selected = filtered.length ? byId[state.id] : null;
      $('#results').innerHTML = renderLibrary(filtered);
    } else if (state.view === 'relations') $('#results').innerHTML = renderRelations(selected);
    else if (state.view === 'labels') $('#results').innerHTML = renderLabels();
    else $('#results').innerHTML = renderLogic();
    renderDetail(selected);
  }
  function render() { renderNavigation(); renderResults(); }
  function moveToMethod(id, reset = false) {
    if (!byId[id]) return;
    if (reset) state = { ...state, view: 'library', stage: 'all', batch: 'all', availability: 'all', scope: 'all', q: '' };
    state.id = id;
    state.tab = 'content';
    state.panel = 'detail';
    render(); save(true);
    $('#detail').scrollTop = 0;
    if (narrow()) scrollTo({ top: 0, behavior: 'auto' });
  }
  const clearFilters = () => ({ ...state, stage: 'all', batch: 'all', availability: 'all', scope: 'all', q: '' });

  document.addEventListener('click', e => {
    const b = e.target.closest('button');
    if (!b || !data) return;
    if (b.dataset.method) return moveToMethod(b.dataset.method);
    if (b.dataset.dependency) return moveToMethod(b.dataset.dependency, true);
    if (b.dataset.tab) { state.tab = b.dataset.tab; renderDetail(byId[state.id]); save(); return; }
    if (b.dataset.view) { state.view = b.dataset.view; state.panel = 'list'; }
    else if (b.dataset.mech) {
      state.mech = b.dataset.mech; state.view = 'logic'; state.panel = 'list';
      const first = mechanismCards(data, state.mech)[0];
      if (first && !byId[state.id].mechanisms.includes(state.mech)) { state.id = first.id; state.tab = 'content'; }
    }
    else if (b.dataset.stage) {
      // From a method's detail the stage chip opens that whole stage; in the library it composes with other filters.
      if (b.closest('#detail')) state = clearFilters();
      state = { ...state, stage: b.dataset.stage, view: 'library', panel: 'list' };
    }
    else if (b.dataset.batch) state.batch = b.dataset.batch;
    else if (b.dataset.action === 'reset') state = clearFilters();
    else if (b.dataset.action === 'relations') { state.view = 'relations'; state.panel = 'list'; }
    else if (b.dataset.action === 'back-list') state.panel = 'list';
    else if (b.dataset.action === 'retry') { location.reload(); return; }
    else return;
    render(); save(true);
    if (narrow() || b.closest('#detail')) scrollTo({ top: 0, behavior: 'auto' });
  });
  $('#search').addEventListener('input', e => { if (data) { state.q = e.target.value; renderResults(); save(); } });
  for (const field of ['availability', 'scope']) $('#' + field).addEventListener('change', e => { if (data) { state[field] = e.target.value; renderResults(); save(); } });
  window.addEventListener('hashchange', () => { if (data) { state = loadState(readHash()); render(); save(); } });
  window.addEventListener('popstate', () => { if (data) { state = loadState(readHash()); render(); } });

  async function init() {
    try {
      if (window.__CATALOG__) data = window.__CATALOG__;  // Single-file build embeds the catalog.
      else {
        const response = await fetch('catalog.json', { cache: 'no-store' });
        if (!response.ok) throw new Error('HTTP ' + response.status);
        data = await response.json();
      }
      byId = Object.fromEntries(data.cards.map(c => [c.id, c]));
      let stored = {};
      try { stored = JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}'); } catch { /* Optional saved state. */ }
      state = loadState(location.hash ? readHash() : stored);
      $('#load-state').textContent = '';
      render(); save();
    } catch (error) {
      data = null;
      $('#load-state').innerHTML = `<div class="error" role="alert">方法库暂时无法加载。<p>${esc(error.message)}</p><button data-action="retry">重新加载</button></div>`;
      $('#load-state button').addEventListener('click', () => location.reload());
    }
  }
  init();
})();
