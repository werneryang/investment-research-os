/* Pure paired-route matching, shared by the page and exhaustive navigation tests. */
(() => {
  const axes=['object','subject','question','topic'];
  const studyFilters=['result_type','market','frequency','start','end','cutoff'];
  const synonyms={'pe':['valuation','multiples'],'p/e':['valuation','multiples'],'市盈率':['valuation','multiples'],'估值':['valuation'],'valuation':['valuation'],'相关性':['returns','correlation'],'correlation':['returns','correlation']};
  const routeMatch=(route,q)=>axes.every(k=>!q[k]||route[k]===q[k])&&(!q.entity||(route.entity_ids||[]).includes(q.entity));
  const endDate=x=>x.length===4?x+'-12-31':x.length===7?x+'-31':x;
  function match(record,q,vocab,en=false) {
    const query=(q.search||'').trim().toLowerCase(),alias=synonyms[query];
    const base=record.routes.filter(r=>routeMatch(r,q));
    const routes=base.filter(r=>!alias||(r.question===alias[0]&&(!alias[1]||r.topic===alias[1])));
    const baseMatch=record.routes.length?base.length>0:!axes.some(k=>q[k])&&!q.entity;
    let show=baseMatch&&(!record.routes.length||routes.length>0);
    const subjects=routes.flatMap(r=>r.entity_ids||[]).flatMap(id=>[vocab.entities[id]?.name,...(vocab.entities[id]?.aliases||[])]).join(' ');
    const title=typeof record.title==='object'?record.title[en?'en':'zh']:record.title||'';
    const text=subjects+' '+title+' '+routes.map(r=>[vocab.objects[r.object].name,vocab.objects[r.object].children[r.subject],vocab.questions[r.question].name,vocab.questions[r.question].children[r.topic],r.scope[en?'en':'zh']].join(' ')).join(' ');
    show &&= !query||(alias?routes.length>0:text.toLowerCase().includes(query));
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
  const api={routeMatch,match,state,emptyText,studyFilters};
  if(typeof module!=='undefined')module.exports=api;
  if(typeof window!=='undefined')window.IROSDiscovery=api;
})();
