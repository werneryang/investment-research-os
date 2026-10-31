/* Paired route filtering: never form the Cartesian product of objects and questions. */
(() => {
  const revealTarget = () => {
    let id; try { id = decodeURIComponent(location.hash.slice(1)); } catch (_) { return; }
    const target = document.getElementById(id);
    if (!target) return;
    if (target.tagName === 'DETAILS') target.open = true;
    for (let p = target.parentElement; p; p = p.parentElement) if (p.tagName === 'DETAILS') p.open = true;
    if(target.nextElementSibling?.tagName==='DETAILS') target.nextElementSibling.open=true;
    target.scrollIntoView({block: 'start'});
  };
  window.addEventListener('hashchange', revealTarget);
  if (location.hash) revealTarget();
  const host = document.querySelector('.discovery'); if (!host) return;
  const form = host.querySelector('form'), en = document.documentElement.lang.startsWith('en');
  const vocab = JSON.parse(host.dataset.vocabulary);
  const records = [...host.querySelectorAll('[data-record]')].map(el => ({el, data:JSON.parse(el.dataset.record)}));
  const fields = [...form.elements].filter(el => el.name);
  const val = k => form.elements.namedItem(k).value;
  const options = (name, values) => {
    const field = form.elements.namedItem(name), old=field.value;
    field.replaceChildren(new Option(en?'All':'全部',''), ...Object.entries(values).map(([k,v])=>new Option(v,k)));
    field.value = Object.hasOwn(values,old)?old:'';
  };
  function children() {
    options('subject', vocab.objects[val('object')]?.children || {});
    options('topic', vocab.questions[val('question')]?.children || {});
  }
  const routeMatch = r => ['object','subject','question','topic'].every(k=>!val(k)||r[k]===val(k));
  const endDate = x => x.length===4?x+'-12-31':x.length===7?x+'-31':x;
  function update(save=true) {
    let published=0, missing=0, capabilities=0, references=0;
    const query = val('search').trim().toLowerCase();
    const synonyms = {'pe':'valuation','p/e':'valuation','市盈率':'valuation','估值':'valuation','valuation':'valuation','相关性':'returns','correlation':'returns'};
    const alias = synonyms[query];
    for (const {el,data} of records) {
      const matched=data.routes.filter(routeMatch);
      let show = (!data.routes.length ? !val('object')&&!val('question')&&!val('subject')&&!val('topic') : matched.length>0);
      const text = (data.title||'')+' '+matched.map(r=>[vocab.objects[r.object].name,vocab.objects[r.object].children[r.subject],vocab.questions[r.question].name,vocab.questions[r.question].children[r.topic],r.scope[en?'en':'zh']].join(' ')).join(' ');
      show &&= !(val('start') && val('end') && val('start')>val('end'));
      show &&= !query || text.toLowerCase().includes(query) || matched.some(r=>r.question===alias);
      if(data.kind==='study') {
        show &&= (!val('result_type')||data.result_type===val('result_type')) && (!val('market')||data.scope.market===val('market')) && (!val('frequency')||data.scope.frequency===val('frequency'));
        show &&= (!val('start')||endDate(String(data.scope.end||''))>=val('start')) && (!val('end')||String(data.scope.start||'9999')<=val('end')) && (!val('cutoff')||endDate(String(data.cutoff))>=val('cutoff'));
        if (show) { if(matched.some(r=>r.available)) published++; else missing++; }
        el.querySelectorAll('[data-route]').forEach(link=>{link.hidden=!routeMatch(JSON.parse(link.dataset.route));});
      } else {
        // A plan has no observation period or result type. Do not invent those attributes.
        show &&= !['result_type','market','frequency','start','end','cutoff'].some(val);
        if(show) {if(data.kind==='reference')references++;else capabilities++;}
      }
      el.hidden=!show;
      const status=el.querySelector('.result-status');
      if(status) status.textContent=!data.published?(en?'Not published':'尚未发布'):matched.some(r=>r.available)?(en?'Matching results':'有匹配结果'):(en?'Matching content unavailable in this run':'本次未提供匹配内容');
      const finding=el.querySelector('.general-finding');if(finding) finding.hidden=fields.some(x=>x.value); 
    }
    const active=fields.some(x=>x.value);
    host.querySelector('.data-plans').open=active&&capabilities>0;
    host.querySelectorAll('.result-group').forEach(group=>{
      group.hidden=![...group.querySelectorAll('.research-record')].some(el=>!el.hidden);
      group.querySelectorAll('.research-collection').forEach(c=>c.hidden=![...c.querySelectorAll('.research-record')].some(el=>!el.hidden));
      const visible=[...group.querySelectorAll('.research-record')].filter(el=>!el.hidden);
      group.querySelector('.summary-count').textContent=visible.length;
      const failed=visible.filter(el=>el.dataset.severity==='fail').length, limited=visible.filter(el=>el.dataset.severity==='warn').length;
      group.querySelector('.summary-alerts').textContent=(failed?(en?` · ${failed} with failed checks`:` · ${failed} 项检查失败`):'')+(limited?(en?` · ${limited} with data or coverage limits`:` · ${limited} 项有数据或覆盖限制`):'');
      group.querySelector('.summary-alerts').className='summary-alerts '+(failed?'bad':'warn');
      group.open=active;
    });
    host.querySelector('.empty-state').hidden=published>0;
    host.querySelector('.query-status').textContent=en?`${published} studies with matching results · ${missing} unavailable or unpublished · ${capabilities} data/planning entries · ${references} reference entries`:`${published} 项研究有匹配结果 · ${missing} 项内容缺失或未发布 · ${capabilities} 项数据或规划 · ${references} 项参照`;
    if(save){const q=new URLSearchParams();if(new URLSearchParams(location.search).get('lang')==='zh')q.set('lang','zh');fields.forEach(x=>{if(x.value)q.set(x.name,x.value)});const url=new URL(location);url.search=q.toString();history.replaceState(null,'',url);}
  }
  const params=new URLSearchParams(location.search);
  for(const key of ['object','question'])form.elements.namedItem(key).value=params.get(key)||'';
  children();fields.forEach(f=>{if(params.has(f.name))f.value=params.get(f.name)});
  form.hidden=false;
  if(['result_type','market','frequency','start','end','cutoff'].some(val))form.querySelector('.advanced-filters').open=true;
  update(false);
  form.addEventListener('submit',event=>event.preventDefault());
  form.addEventListener('input',event=>{if(['object','question'].includes(event.target.name))children();update();});
  form.addEventListener('reset',()=>setTimeout(()=>{children();update();},0));
  host.querySelectorAll('[data-filter]').forEach(a=>a.addEventListener('click',event=>{
    event.preventDefault();form.elements.namedItem(a.dataset.filter).value=a.dataset.value;children();update();form.scrollIntoView({block:'start',behavior:'smooth'});
  }));
  // Language switches retain the query; object and question IDs are language independent.
  document.querySelectorAll('.lang-switch').forEach(a=>a.addEventListener('click',()=>{
    const url=new URL(a.href);const q=new URLSearchParams(location.search);if(a.dataset.lang==='zh')q.set('lang','zh');url.search=q.toString();a.href=url;
  }));
})();
