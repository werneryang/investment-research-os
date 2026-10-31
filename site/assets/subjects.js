/* Stable entity IDs are selected explicitly; aliases only help find them. */
(() => {
  const normalize = value => value.toLowerCase().trim().replace(/[\s._-]+/g, '');
  const distance = (a, b) => {
    let previous = Array.from({length:b.length+1}, (_,i)=>i);
    for(let i=1;i<=a.length;i++) {
      const next=[i];
      for(let j=1;j<=b.length;j++) next[j]=Math.min(next[j-1]+1,previous[j]+1,previous[j-1]+(a[i-1]===b[j-1]?0:1));
      previous=next;
    }
    return previous[b.length];
  };
  const candidates = (entities, query) => {
    const q=normalize(query); if(!q) return [];
    return Object.entries(entities).map(([id,e])=>{
      const names=[e.name,...(e.aliases||[])].map(normalize);
      const score=names.some(n=>n===q)?0:names.some(n=>n.includes(q))?1:q.length>=4&&names.some(n=>distance(n,q)<=2)?2:9;
      return {id,name:e.name,score};
    }).filter(x=>x.score<9).sort((a,b)=>a.score-b.score||a.name.localeCompare(b.name)).slice(0,6);
  };
  function suggest(container, entities, query, select, en) {
    container.replaceChildren();
    for(const item of candidates(entities,query)) {
      const button=document.createElement('button');button.type='button';
      button.textContent=(item.score===2?(en?'Did you mean: ':'是否要找：'):(en?'Select subject: ':'选择主体：'))+item.name;
      button.addEventListener('click',()=>select(item.id));container.append(button);
    }
  }
  // Unknown URL IDs stay visible and produce no matches, rather than silently broadening the query.
  function setField(field, value, en) {
    if(field.tagName==='SELECT'&&value&&![...field.options].some(o=>o.value===value)) {
      field.add(new Option((en?'Unknown: ':'未登记：')+value,value));
    }
    field.value=value;
  }
  function save(fields, mode='push', hash=null) {
    const url=new URL(location), q=new URLSearchParams();
    if(url.searchParams.get('lang')==='zh')q.set('lang','zh');
    for(const field of fields)if(field.value)q.set(field.name,field.value);
    url.search=q.toString();if(hash!==null)url.hash=hash;
    if(url.href!==location.href)history[mode==='replace'?'replaceState':'pushState'](null,'',url);
  }
  const problem = r => ['failed','stale'].includes(r.technical)||['rejected','retracted'].includes(r.human)||r.evidence_problem;
  function recordMatch(row, state, mapping=false) {
    const ids=[state.entity,state.compare].filter(Boolean);
    const ends=mapping?[row.owner,row.entity]:row.endpoints;
    if(ids.length&&!ids.some(id=>ends.includes(id)))return false;
    if(state.activity&&(state.activity==='unknown'?!!row.activity:row.activity!==state.activity))return false;
    if(!mapping&&state.relation_type&&row.type!==state.relation_type)return false;
    if(state.review==='passed'&&(row.technical!=='passed'||problem(row)))return false;
    if(state.review==='none'&&(row.technical!=='none'||problem(row)))return false;
    if(state.review==='problem'&&!problem(row))return false;
    if(state.review&&!['passed','none','problem'].includes(state.review))return false;
    if(state.evidence_before&&(!row.evidence_date||row.evidence_date>state.evidence_before))return false;
    return true;
  }
  const role = (row, id) => row.provider ? row.provider===id?'downstream':'upstream':row.type;
  const api={candidates,suggest,setField,save,problem,recordMatch,role};
  if(typeof module!=='undefined')module.exports=api;
  if(typeof window!=='undefined')window.IROSSubjects=api;
  if(typeof document!=='undefined')document.querySelectorAll('.lang-switch').forEach(a=>a.addEventListener('click',()=>{
    const url=new URL(a.href),q=new URLSearchParams(location.search);
    if(a.dataset.lang==='zh')q.set('lang','zh');else q.delete('lang');
    url.search=q.toString();url.hash=location.hash;a.href=url.href;
  }));
})();
