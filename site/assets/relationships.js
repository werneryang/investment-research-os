/* One direct-record set drives the table, coverage comparison and one-hop diagram. */
(() => {
  const S=window.IROSSubjects,en=document.documentElement.lang.startsWith('en');
  const L=(zh,english)=>en?english:zh;
  for(const host of document.querySelectorAll('.relationship-view')) {
    const config=JSON.parse(host.dataset.relationshipIndex), form=host.querySelector('form');
    const mappings=[...host.querySelectorAll('[data-mapping]')].map(el=>({el,row:JSON.parse(el.dataset.mapping)}));
    const relations=[...host.querySelectorAll('[data-relation]')].map(el=>({el,row:JSON.parse(el.dataset.relation)}));
    const studies=[...host.querySelectorAll('[data-related]')].map(el=>({el,row:JSON.parse(el.dataset.related)}));
    const fields=form?[...form.elements].filter(f=>f.name):[];
    const state=()=>form?Object.fromEntries(fields.map(f=>[f.name,f.value])):{entity:config.initial};
    const name=id=>config.entities[id]?.name||id;
    const roleName=r=>({upstream:L('上游提供方','Upstream provider'),downstream:L('下游接收方','Downstream recipient')}[r]||config.types[r]||r);
    const textNode=(tag,text)=>{const node=document.createElement(tag);node.textContent=text;return node;};
    const link=id=>{const a=textNode('a',name(id));a.href=config.prefix+'sources.html?entity='+encodeURIComponent(id)+'#relationships';return a;};
    function renderDiagram(visible) {
      const diagram=host.querySelector('.diagram-content');if(!diagram)return;
      diagram.replaceChildren();
      if(!visible.length){diagram.append(textNode('p',L('当前筛选没有登记关系。','No registered relationships match.')));return;}
      for(const {row} of visible) {
        const card=document.createElement('div');card.className='relationship-edge';card.dataset.edge=row.id;
        card.append(link(row.endpoints[0]),textNode('span',row.provider?' → ':' ↔ '),link(row.endpoints[1]));
        card.append(textNode('p',config.types[row.type]+' · '+(row.activity?config.activities[row.activity]:L('环节尚未确定','Activity undetermined'))));
        const status=S.problem(row)?L('记录存在复核问题','Review problem'):row.technical==='passed'?L('技术复核通过','Technical review passed'):L('暂无技术复核记录','No technical review record');
        card.append(textNode('small',status+' · '+({candidate:L('未人工确认','Not human-confirmed'),confirmed:L('人工确认','Human-confirmed'),rejected:L('人工否定','Human-rejected'),retracted:L('已撤回','Retracted')}[row.human])));
        const evidence=textNode('a',L('查看本条范围与证据','Scope and evidence'));evidence.href='#ref-'+row.id;card.append(evidence);diagram.append(card);
      }
    }
    function compare(ids, visibleMaps, visible) {
      const box=host.querySelector('.relationship-comparison');box.hidden=ids.length!==2;box.replaceChildren();if(box.hidden)return;
      box.append(textNode('p',L('对照当前筛选下的登记记录覆盖，不比较经济依赖或业务规模。共享关系在下表只列一次。','Coverage of registered records under current filters, not economic dependence or business size. Shared relationships appear once below.')));
      const table=document.createElement('table'),head=document.createElement('tr');
      for(const h of [L('记录覆盖','Record coverage'),...ids.map(name)])head.append(textNode('th',h));table.append(head);
      const metrics=[
        [L('业务映射','Business mappings'), id=>visibleMaps.filter(x=>[x.row.owner,x.row.entity].includes(id)).length],
        [L('上游提供方关系','Upstream provider relationships'),id=>visible.filter(x=>x.row.recipient===id).length],
        [L('下游接收方关系','Downstream recipient relationships'),id=>visible.filter(x=>x.row.provider===id).length],
        [L('无向关系','Undirected relationships'),id=>visible.filter(x=>!x.row.provider&&x.row.endpoints.includes(id)).length],
        [L('尚未人工确认','Not human-confirmed'),id=>visible.filter(x=>x.row.endpoints.includes(id)&&x.row.human==='candidate').length],
        [L('环节尚未确定','Activity undetermined'),id=>visible.filter(x=>x.row.endpoints.includes(id)&&!x.row.activity).length]
      ];
      for(const [label,count] of metrics){const tr=document.createElement('tr');tr.append(textNode('th',label));for(const id of ids)tr.append(textNode('td',String(count(id))));table.append(tr);}
      box.append(table);
    }
    function update(save=false,mode='push') {
      const s=state(),ids=[...new Set([s.entity,s.compare].filter(Boolean))];
      const visibleMaps=mappings.filter(x=>{x.el.hidden=!S.recordMatch(x.row,s,true);return !x.el.hidden;});
      const visible=relations.filter(x=>{x.el.hidden=!S.recordMatch(x.row,s);return !x.el.hidden;});
      let studyCount=0;
      studies.forEach(x=>{x.el.hidden=ids.length>0&&!ids.some(id=>x.row.entities.includes(id));if(!x.el.hidden)studyCount++;});
      for(const {el,row} of visible)el.querySelector('.relative-role').textContent=ids.filter(id=>row.endpoints.includes(id)).map(id=>(en?'Relative to '+name(id)+': ':name(id)+'的')+roleName(S.role(row,id))).join(' · ');
      host.querySelector('.mapping-empty').hidden=visibleMaps.length>0;
      host.querySelector('.relation-empty').hidden=visible.length>0;
      host.querySelector('.related-empty').hidden=studyCount>0;
      host.querySelector('#business-mappings > summary').textContent=L('分部与业务映射','Segment-to-business mappings')+' · '+visibleMaps.length;
      host.querySelector('#business-relations > summary').textContent=L('直接公司关系（含候选）','Direct company relationships (including candidates)')+' · '+visible.length;
      const unknown=ids.filter(id=>!config.entities[id]);
      let status=unknown.length?L('未登记的主体：','Unregistered subject: ')+unknown.join(', ')+'. ':'';
      status+=ids.length?ids.map(name).join(' / '):L('全部已登记主体','All registered subjects');
      status+=L(` · ${visibleMaps.length} 条业务映射 · ${visible.length} 条直接关系 · ${studyCount} 项相关研究登记`, ` · ${visibleMaps.length} business mappings · ${visible.length} direct relationships · ${studyCount} registered studies`);
      if(s.evidence_before)status+=L('；日期不明的证据已排除。','; records with unknown evidence dates are excluded.');
      if(s.relation_type)status+=L('；关系类型仅筛选关系表。','; relationship type applies only to relationships.');
      if(s.entity_search)status+=L('；搜索文字只提供候选，请点击选择主体。','; search suggests subjects—select a suggestion to filter.');
      host.querySelector('.relationship-status').textContent=status;
      if(ids.length||Object.values(s).some(Boolean))for(const sel of ['#business-mappings','#business-relations','.related-studies'])host.querySelector(sel).open=true;
      compare(ids,visibleMaps,visible);renderDiagram(visible);
      if(form)S.suggest(form.querySelector('.entity-suggestions'),config.entities,s.entity_search,id=>{form.elements.entity.value=id;form.elements.entity_search.value='';update(true);},en);
      if(save)S.save(fields,mode);
    }
    if(form) {
      const restore=()=>{const q=new URLSearchParams(location.search);fields.forEach(f=>S.setField(f,q.get(f.name)||'',en));update();};
      restore();form.hidden=false;
      form.addEventListener('submit',e=>e.preventDefault());
      form.addEventListener('input',e=>{if(e.target.type==='search')update(true,'replace');});
      form.addEventListener('change',()=>update(true));
      form.addEventListener('reset',e=>{e.preventDefault();fields.forEach(f=>f.value='');update(true);});
      window.addEventListener('popstate',restore);
    } else update();
  }
})();
