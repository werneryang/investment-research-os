"""Reverse coverage checks for public reference records and paired navigation routes."""
from collections import defaultdict

REFERENCE_SOURCES = {'activities', 'mappings', 'relations'}
ROUTE_KEYS = ('object', 'subject', 'question', 'topic')


def reference_catalog(content, index):
    """One material, multiple routes. Explicit record membership prevents scope drift."""
    materials = content['classification'].get('references', [])
    assigned = {source: set() for source in REFERENCE_SOURCES}
    records = []
    for material in materials:
        source, ids = material['source'], material['records']
        available = index.get(source, {})
        unknown = set(ids) - set(available)
        if unknown:
            raise ValueError(f'Unknown reference records in {material["id"]}: {sorted(unknown)}')
        duplicates = assigned[source] & set(ids)
        if duplicates or len(set(ids)) != len(ids):
            raise ValueError(f'Duplicate reference ownership: {material["id"]}')
        assigned[source].update(ids)
        entities = set()
        for identifier in ids:
            row = available[identifier]
            if source == 'relations':
                entities.update(row['endpoints'])
            elif source == 'mappings':
                entities.add(row['owner'])
        if source == 'activities':
            # A company's relevance comes from explicit mappings / direct relationships,
            # not from an activity name or from a company merely appearing in a report.
            for row in index['mappings'].values():
                if row['activity'] in ids: entities.add(row['owner'])
            for row in index['relations'].values():
                if row.get('activity') in ids: entities.update(row['endpoints'])
        routes = [{**r, 'href': material['href'], 'available': bool(ids), 'report': False,
                   'entity_ids': sorted(entities)} for r in material['routes']]
        records.append({'id': material['id'], 'title': material['title'], 'kind': 'reference',
                        'source': source, 'record_ids': ids, 'record_count': len(ids), 'routes': routes})
    for source in REFERENCE_SOURCES:
        unassigned = set(index.get(source, {})) - assigned[source]
        if unassigned:
            raise ValueError(f'Public references missing navigation coverage ({source}): {sorted(unassigned)}')
    return records


def coverage_report(model):
    """Sparse inventory of registered pairs; this does not assess unregistered cells."""
    pairs = defaultdict(lambda: {'studies': set(), 'available_studies': set(),
                                 'capabilities': set(), 'references': set()})
    for kind in ('studies', 'capabilities', 'references'):
        for record in model[kind]:
            for route in record['routes']:
                bucket = pairs[tuple(route[k] for k in ROUTE_KEYS)]
                bucket[kind].add(record['id'])
                if kind == 'studies' and route['available']:
                    bucket['available_studies'].add(record['id'])
    return {'scope': 'Registered route coverage only; unregistered combinations remain unassessed.',
            'pairs': [{**dict(zip(ROUTE_KEYS, key)), **{k: sorted(v) for k,v in value.items()}}
                      for key,value in sorted(pairs.items())]}
