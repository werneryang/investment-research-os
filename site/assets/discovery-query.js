/* Pure paired-route matching, shared by the page and exhaustive navigation tests. */
(() => {
  const axes=['object','subject','question','topic'];
  const studyFilters=['result_type','market','frequency','start','end','cutoff'];
  const synonyms={'pe':['valuation','multiples'],'p/e':['valuation','multiples'],'市盈率':['valuation','multiples'],'估值':['valuation'],'valuation':['valuation'],'相关性':['returns','correlation'],'correlation':['returns','correlation'],'事件':['events'],'event':['events'],'events':['events'],'辞职':['events'],'离任':['events']};
  const routeMatch=(route,q)=>axes.every(k=>!q[k]||route[k]===q[k])&&(!q.entity||(route.entity_ids||[]).includes(q.entity));
  const endDate=x=>x.length===4?x+'-12-31':x.length===7?x+'-31':x;
  // Split on whitespace, list punctuation and CJK/non-CJK boundaries. There is no dictionary: a CJK run is
  // only split around the class words in `synonyms`, so "辞职事件" yields two class words and "估值倍数" keeps "倍数".
  const cjkRun=/^[\u3400-\u9fff\uf900-\ufaff]+$/;
  const classWords=new RegExp('('+Object.keys(synonyms).filter(k=>cjkRun.test(k)).sort((a,b)=>b.length-a.length).join('|')+')');
  const terms=search=>[...new Set((search||'').toLowerCase().split(/[\s,，、;；]+/).flatMap(p=>p.match(/[\u3400-\u9fff\uf900-\ufaff]+|[^\u3400-\u9fff\uf900-\ufaff]+/g)||[]).flatMap(t=>cjkRun.test(t)?t.split(classWords).filter(Boolean):[t]))];
  function textOf(record,routes,vocab,en) {
    const subjects=routes.flatMap(r=>r.entity_ids||[]).flatMap(id=>[vocab.entities[id]?.name,...(vocab.entities[id]?.aliases||[])]).join(' ');
    const title=typeof record.title==='object'?record.title[en?'en':'zh']:record.title||'';
    return (subjects+' '+title+' '+routes.map(r=>[vocab.objects[r.object].name,vocab.objects[r.object].children[r.subject],vocab.questions[r.question].name,vocab.questions[r.question].children[r.topic],r.scope[en?'en':'zh']].join(' ')).join(' ')).toLowerCase();
  }
  // Words found in no record are reported, not silently dropped: the caller passes them back as q.ignore.
  function searchTerms(search,records,vocab,en=false) {
    const query=(search||'').trim().toLowerCase();
    if(!query||synonyms[query])return {known:query?[query]:[],unknown:[],classes:synonyms[query]?[query]:[]};
    const texts=records.map(r=>textOf(r,r.routes,vocab,en)),known=[],unknown=[];
    for(const t of terms(query))(synonyms[t]||texts.some(x=>x.includes(t))?known:unknown).push(t);
    // `classes` are the known words that select a question class rather than match text.
    return {known,unknown,classes:known.filter(t=>synonyms[t])};
  }
  function match(record,q,vocab,en=false) {
    const query=(q.search||'').trim().toLowerCase(),ignore=q.ignore||[];
    const words=synonyms[query]?[query]:terms(query).filter(t=>!ignore.includes(t));
    const aliases=words.map(t=>synonyms[t]).filter(Boolean),plain=words.filter(t=>!synonyms[t]);
    const base=record.routes.filter(r=>routeMatch(r,q));
    const routes=base.filter(r=>aliases.every(a=>r.question===a[0]&&(!a[1]||r.topic===a[1])));
    const baseMatch=record.routes.length?base.length>0:!axes.some(k=>q[k])&&!q.entity;
    let show=baseMatch&&(!record.routes.length||routes.length>0);
    const text=textOf(record,routes,vocab,en);
    show &&= !query||((!aliases.length||routes.length>0)&&(plain.every(t=>text.includes(t))||text.includes(query)));
    if(record.kind==='study') {
      show &&= !(q.start&&q.end&&q.start>q.end);
      show &&= (!q.result_type||record.result_type===q.result_type)&&(!q.market||record.scope.market===q.market)&&(!q.frequency||record.scope.frequency===q.frequency);
      show &&= (!q.start||endDate(String(record.scope.end||''))>=q.start)&&(!q.end||String(record.scope.start||'9999')<=q.end)&&(!q.cutoff||endDate(String(record.cutoff))>=q.cutoff);
    }
    return {show,baseMatch,routes};
  }
  function state(counts,query,entities) {
    if(counts.published)return 'results';
    if(query.entity&&!entities[query.entity])return 'unknown_subject';
    if(counts.missing)return 'unavailable';
    if(counts.references)return 'references';
    if(counts.capabilities)return 'capabilities';
    if(counts.base)return 'filtered';
    return 'unassessed';
  }
  function emptyText(key,en=false) {
    const words={
      results:['',''],
      unknown_subject:['该主体尚未登记，无法据此判断研究覆盖。','This subject is not registered; its research coverage cannot be assessed here.'],
      unavailable:['已有匹配研究登记，但当前未发布或未提供所选内容；请查看下方的发布与可用状态。','Matching studies are registered, but are unpublished or do not currently provide the selected content. See their publication and availability statuses below.'],
      references:['当前尚无已发布的匹配研究；已有部分参照资料，见下方。参照资料不等于完整研究或已确认结论。','No published studies match; partial reference materials are available below. References are not complete studies or confirmed conclusions.'],
      capabilities:['当前尚无已发布的匹配研究；已有数据能力或规划登记，具体取得状态见下方。','No published studies match; data capabilities or plans are registered. See their acquisition status below.'],
      filtered:['这个分类路径已有登记内容，但被当前关键词或研究筛选条件排除。可减少筛选条件后查看。','This classification path has registered content, but the current search or study filters exclude it. Try fewer filters.'],
      unassessed:['这个对象与问题组合尚无登记的研究、参照或数据规划，其研究覆盖尚未评估。','No studies, references or data plans are registered for this object–question combination; its research coverage remains unassessed.']
    };
    return words[key][en?1:0];
  }
  const className=(word,vocab)=>vocab.questions[synonyms[word]?.[0]]?.name||word;
  const api={routeMatch,match,terms,searchTerms,className,state,emptyText,studyFilters};
  if(typeof module!=='undefined')module.exports=api;
  if(typeof window!=='undefined')window.IROSDiscovery=api;
})();
