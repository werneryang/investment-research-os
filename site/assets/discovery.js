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
  const S=window.IROSSubjects, Q=window.IROSDiscovery;
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
  function update(save=true, mode='push') {
    const query=Object.fromEntries(fields.map(f=>[f.name,f.value]));
    const counts={published:0,missing:0,capabilities:0,references:0,base:0};
    for (const {el,data} of records) {
      const {show,baseMatch,routes:matched}=Q.match(data,query,vocab,en);
      if(baseMatch)counts.base++;
      if(show) {
        if(data.kind==='study') {if(matched.some(r=>r.available))counts.published++;else counts.missing++;}
        else if(data.kind==='reference')counts.references++;
        else counts.capabilities++;
      }
      el.querySelectorAll('[data-route]').forEach(link=>{
        const r=JSON.parse(link.dataset.route);
        link.hidden=!matched.some(m=>['object','subject','question','topic','target'].every(k=>m[k]===r[k]));
        if(data.kind==='reference') {
          const a=link.querySelector('a'),url=new URL(r.href,location.href);
          if(query.entity)url.searchParams.set('entity',query.entity);a.href=url.href;
        }
      });
      el.hidden=!show;
      const status=el.querySelector('.result-status');
      if(status)status.textContent=!data.published?(en?'Not published':'尚未发布'):matched.some(r=>r.available)?(en?'Matching results':'有匹配结果'):(en?'Matching content unavailable in this run':'本次未提供匹配内容');
      const finding=el.querySelector('.general-finding');if(finding)finding.hidden=fields.some(x=>x.value);
    }
    const {published,missing,capabilities,references}=counts;
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
    const empty=host.querySelector('.empty-state'),state=Q.state(counts,query,vocab.entities);
    empty.hidden=state==='results';empty.textContent=Q.emptyText(state,en);empty.dataset.state=state;
    host.querySelector('.reference-filter-note').hidden=!Q.studyFilters.some(k=>query[k]);
    host.querySelector('.query-status').textContent=en?`${published} studies with matching results · ${missing} unavailable or unpublished · ${capabilities} data/planning entries · ${references} reference entries`:`${published} 项研究有匹配结果 · ${missing} 项内容缺失或未发布 · ${capabilities} 项数据或规划 · ${references} 项参照`;
    const subject=val('entity'), entry=host.querySelector('.subject-reference');
    entry.hidden=!subject;entry.replaceChildren();
    if(subject){
      const a=document.createElement('a');a.href='sources.html?entity='+encodeURIComponent(subject)+'#relationships';
      a.textContent=(vocab.entities[subject]?.name||subject)+(en?' · View registered business activities and direct relationships':' · 查看已登记业务与直接关系');entry.append(a);
      entry.append(document.createTextNode(en?' (reference view; does not imply a matching study or valuation)':'（参照资料入口，不代表存在匹配研究或估值结果）'));
    }
    S.suggest(form.querySelector('.entity-suggestions'),vocab.entities,query.search,id=>{
      form.elements.entity.value=id;form.elements.search.value='';update();
    },en);
    if(save)S.save(fields,mode);

  }
  function restore() {
    const params=new URLSearchParams(location.search);
    for(const key of ['object','question'])S.setField(form.elements.namedItem(key),params.get(key)||'',en);
    children();fields.forEach(f=>S.setField(f,params.get(f.name)||'',en));update(false);
    if(['result_type','market','frequency','start','end','cutoff'].some(val))form.querySelector('.advanced-filters').open=true;
  }
  form.hidden=false;restore();window.addEventListener('popstate',restore);
  form.addEventListener('submit',event=>event.preventDefault());
  form.addEventListener('input',event=>{if(event.target.type==='search')update(true,'replace');});
  form.addEventListener('change',event=>{if(['object','question'].includes(event.target.name))children();update();});
  form.addEventListener('reset',event=>{event.preventDefault();fields.forEach(f=>f.value='');children();update();});
  host.querySelectorAll('[data-filter]').forEach(a=>a.addEventListener('click',event=>{
    event.preventDefault();form.elements.namedItem(a.dataset.filter).value=a.dataset.value;children();update();form.scrollIntoView({block:'start',behavior:'smooth'});
  }));
})();
