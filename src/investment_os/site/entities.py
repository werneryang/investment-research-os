"""Public subject index, derived from registered identities and evidence, never name inference."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from ..supply_chain.catalog import fingerprint, load_catalog


def _json(value):
    return json.loads(json.dumps(value, ensure_ascii=False, default=str))


def build_index(root: Path, content: dict, definitions: dict) -> dict[str, Any]:
    cat = load_catalog(root) if (root / 'config/supply_chain/activities.yaml').exists() else None
    entities = _json(cat.entities) if cat else {}
    activities = _json(cat.activities) if cat else {}
    by_cik = {}
    for eid, entity in entities.items():
        if entity.get('cik'):
            key = str(int(entity['cik']))
            if key in by_cik:
                raise ValueError(f'Duplicate subject CIK: {key}')
            by_cik[key] = eid
    company_file = root / 'config/company-research.yaml'
    companies = (yaml.safe_load(company_file.read_text()) or {}).get('companies', []) if company_file.exists() else []
    for company in companies:
        cik = str(int(company['cik']))
        eid = by_cik.setdefault(cik, f'cik_{cik}')
        entity = entities.setdefault(eid, {'id': eid, 'type': 'company', 'name': company['label'], 'cik': int(cik)})
        entity.setdefault('aliases', []).append(company['label'])
    for eid, aliases in content.get('entity_aliases', {}).items():
        if eid not in entities:
            raise ValueError(f'Unknown alias subject: {eid}')
        entities[eid].setdefault('aliases', []).extend(aliases)
    for eid, entity in entities.items():
        entity['aliases'] = list(dict.fromkeys([entity['name'], *entity.get('aliases', [])]))
        if entity.get('parent') and entity['parent'] not in entities:
            raise ValueError(f'Unknown parent: {eid}')

    def owner(eid):
        """Only an explicitly registered parent is inherited; anonymous entities stay distinct."""
        seen = set()
        while entities[eid]['type'] == 'segment' and entities[eid].get('parent'):
            if eid in seen:
                raise ValueError(f'Cyclic subject parent: {eid}')
            seen.add(eid)
            eid = entities[eid]['parent']
        return eid

    for eid in entities:
        owner(eid)

    def review(identifier, item):
        record = (cat.technical.get(identifier) or {}) if cat else {}
        technical = ('stale' if fingerprint(cat, identifier) != record['fingerprint'] else record['result']) if record else 'none'
        return {'technical': technical, 'technical_date': record.get('reviewed_at'),
                'technical_limits': record.get('limits', ''), 'human': item.get('review_status', 'candidate')}

    evidence = {}
    if cat:
        for cid, claim in cat.claims.items():
            doc = cat.documents.get(claim.get('document')) or next((d for d in cat.documents.values() if d['accession'] == claim.get('accession')), {})
            evidence[cid] = {**_json(claim), **review(cid, claim),
                             'document': {k: _json(doc.get(k)) for k in ('id', 'entity', 'form', 'url', 'accession', 'accepted_at', 'document_period_end')},
                             'machine_check': 'not_rerun_in_site_build'}

    def record(identifier, item):
        row = {**_json(item), **review(identifier, item)}
        claims = row.get('claims', [])
        if any(cid not in evidence for cid in claims):
            raise ValueError(f'Missing relation evidence: {identifier}')
        dates = [str(evidence[c]['document'].get('accepted_at') or '')[:10] for c in claims]
        row['evidence_date'] = max(dates) if dates and all(dates) else None
        row['evidence_dates'] = sorted(set(d for d in dates if d))
        row['evidence_problem'] = any(evidence[c]['technical'] in ('failed', 'stale') or evidence[c]['human'] in ('rejected', 'retracted') for c in claims)
        return row

    mappings, relations = {}, {}
    if cat:
        for identifier, item in cat.links.items():
            if item['entity'] not in entities or item['activity'] not in activities:
                raise ValueError(f'Invalid mapping endpoint: {identifier}')
            mappings[identifier] = {**record(identifier, item), 'owner': owner(item['entity'])}
        for identifier, item in cat.relations.items():
            ends = [item['provider'], item['recipient']] if 'provider' in item else item['parties']
            if any(eid not in entities for eid in ends) or (item.get('activity') and item['activity'] not in activities):
                raise ValueError(f'Invalid relation endpoint: {identifier}')
            relations[identifier] = {**record(identifier, item), 'endpoints': ends}

    # A company study's explicit CIK is authoritative. Other study associations are curated per route.
    study_entities = {}
    for sid, meta in content.get('studies', {}).items():
        cik = definitions.get(sid, {}).get('method', {}).get('cik')
        declared = meta.get('entity_ids', [])
        if cik is not None:
            key = str(int(cik))
            if key not in by_cik:
                raise ValueError(f'Unknown study CIK: {sid} / {key}')
            if declared and declared != [by_cik[key]]:
                raise ValueError(f'Conflicting study subjects: {sid}')
            declared = [by_cik[key]]
        for r in meta.get('routes', []):
            if cik is not None and r.get('entity_ids', declared) != declared:
                raise ValueError(f'Conflicting company route subjects: {sid}')
            if any(eid not in entities for eid in r.get('entity_ids', declared)):
                raise ValueError(f'Unknown study subject: {sid}')
        if any(eid not in entities for eid in declared):
            raise ValueError(f'Unknown study subject: {sid}')
        study_entities[sid] = list(declared)
    return {'entities': entities, 'activities': activities, 'mappings': mappings, 'relations': relations,
            'evidence': evidence, 'by_cik': by_cik, 'study_entities': study_entities}


def subject_records(index: dict, eid: str) -> dict:
    """Direct records only. No implicit transitive or inherited company relationships."""
    if eid not in index['entities']:
        return {'known': False, 'mappings': [], 'relations': []}
    mappings = [r for r in index['mappings'].values() if eid in (r['owner'], r['entity'])]
    relations = [r for r in index['relations'].values() if eid in r['endpoints']]
    return {'known': True, 'mappings': mappings, 'relations': relations}
