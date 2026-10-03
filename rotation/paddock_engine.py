"""Aggregate recommendations only: no database writes or animal-level decisions."""
import math
from .fuzzy_priority import evaluate_priority, finite, rounded, MODEL

HORIZON = 7
VERSION = 'rotacion_por_potrero_v3'


def validate(payload):
    if not isinstance(payload, dict) or not isinstance(payload.get('paddocks'), list):
        raise ValueError('Se requiere una lista de potreros en paddocks.')
    ids = set()
    for p in payload['paddocks']:
        if not isinstance(p, dict) or not finite(p.get('id')) or p['id'] <= 0 or p['id'] != int(p['id']) or p['id'] in ids:
            raise ValueError('Identificadores de potrero inválidos o duplicados.')
        ids.add(p['id'])
        if not isinstance(p.get('name'), str) or not isinstance(p.get('included'), bool) or not isinstance(p.get('enabled', True), bool):
            raise ValueError('Nombre o disponibilidad de potrero inválidos.')
        n = p.get('animals')
        if not finite(n) or n < 0 or n != int(n):
            raise ValueError('Cantidad de animales inválida.')
        for field in ('stock', 'growth', 'demand'):
            if p.get(field) is not None and not finite(p[field]):
                raise ValueError('Las estimaciones deben ser números finitos o null.')
        if not isinstance(p.get('issues', []), list) or any(not isinstance(x, str) for x in p.get('issues', [])):
            raise ValueError('Lista de datos pendientes inválida.')


def recommend(inputs):
    paddocks = []
    for original in inputs:
        p = dict(original)
        enabled = p.get('enabled') is not False
        issues = list(p.get('issues') or [])
        stock, growth, demand, animals = (p.get(k) for k in ('stock', 'growth', 'demand', 'animals'))
        if ((enabled and (not all(finite(x) for x in (stock, growth)) or growth < 0))
                or not finite(demand) or demand < 0 or not finite(animals) or animals < 0
                or animals != int(animals) or (animals > 0 and demand <= 0)):
            issues.append('Faltan estimaciones válidas de pasto o consumo.')
        valid = (p.get('included') or not enabled) and not issues
        capacity = 0 if not enabled else max(0, stock) / HORIZON + growth if valid else None
        excess = max(0, demand - capacity) if valid else None
        average = demand / animals if valid and animals else None
        remove = animals if not enabled else min(animals, math.ceil(max(0, excess - 1e-9) / average)) if average else 0
        priority = evaluate_priority(dict(p, issues=issues)) if enabled and valid and remove > 0 else None
        status = ('FUERA_USO' if not enabled else 'EXCLUIDO' if not p.get('included') else 'SIN_DATOS' if not valid
                  else 'EXCESO' if remove else 'DISPONIBLE' if capacity > demand + 1e-9 else 'EQUILIBRADO')
        p.update(enabled=enabled, issues=list(dict.fromkeys(issues)), capacity=capacity, average=average,
                 remove=remove, priority=priority, excess=rounded(excess) if excess is not None else None,
                 pressure=rounded(100 * demand / capacity) if valid and capacity > 0 else None, status=status,
                 projectedAnimals=animals, projectedDemand=demand, outgoing=0, incoming=0)
        paddocks.append(p)
    destinations = [p for p in paddocks if p['status'] == 'DISPONIBLE']
    sources = [p for p in paddocks if p['status'] == 'EXCESO' or (not p['enabled'] and p['animals'] > 0)]
    sources.sort(key=lambda p: (p['enabled'], -(p['priority'] or {}).get('score', 0),
                              -(p['pressure'] if p['pressure'] is not None else math.inf), -p['remove'], p['id']))
    recommendations = []
    by_id = {p['id']: p for p in paddocks}
    for source in sources:
        allocations, remaining = {}, source['remove']
        average = source['average']
        while remaining > 0 and average and average > 0:
            options = [p for p in destinations if p['capacity'] - p['projectedDemand'] + 1e-9 >= average]
            options.sort(key=lambda p: ((p['projectedDemand'] + average) / p['capacity'], p['id']))
            if not options:
                break
            dest = options[0]
            room = math.floor((dest['capacity'] - dest['projectedDemand'] + 1e-9) / average)
            next_dest = options[1] if len(options) > 1 else None
            until_next = max(1, math.ceil(((next_dest['projectedDemand'] + average) / next_dest['capacity'] * dest['capacity']
                                          - dest['projectedDemand']) / average - 1e-9)) if next_dest else room
            quantity = min(remaining, room, until_next)
            dest['projectedDemand'] += quantity * average
            dest['projectedAnimals'] += quantity
            dest['incoming'] += quantity
            source['projectedDemand'] -= quantity * average
            source['projectedAnimals'] -= quantity
            source['outgoing'] += quantity
            allocations[dest['id']] = allocations.get(dest['id'], 0) + quantity
            remaining -= quantity
        recommendations.append(dict(origin=source['id'], name=source['name'], remove=source['remove'],
            reason='EXCESO' if source['enabled'] else 'FUERA_USO', needsDemand=not bool(average),
            allocated=source['outgoing'], unallocated=remaining, excess=source['excess'], priority=source['priority'],
            excessPercent=rounded(100 * (source['demand'] - source['capacity']) / source['capacity']) if source['capacity'] and source['capacity'] > 0 else None,
            destinations=[dict(id=id_, name=by_id[id_]['name'], quantity=n) for id_, n in allocations.items()]))
    for p in paddocks:
        p['projectedDemand'] = rounded(p['projectedDemand']) if finite(p['projectedDemand']) else None
        p['projectedBalance'] = (None if p['capacity'] is None or not p['enabled'] else
                                 rounded(max(0, p['stock']) + HORIZON * (p['growth'] - p['projectedDemand'])))
        p['projectedPressure'] = rounded(100 * p['projectedDemand'] / p['capacity']) if p['capacity'] and p['capacity'] > 0 else None
        p['remainingExcess'] = rounded(max(0, (p['projectedDemand'] or 0) - p['capacity'])) if p['capacity'] is not None else None
    return dict(version=VERSION, priorityModel=MODEL, engineRuntime='python', horizon=HORIZON, paddocks=paddocks,
                recommendations=recommendations,
                partial=any((p.get('included') and p['status'] == 'SIN_DATOS') or
                            (not p['enabled'] and p['animals'] > 0 and not p['average']) for p in paddocks),
                totals=dict(excessPaddocks=sum(p['enabled'] for p in sources), closedPaddocks=sum(not p['enabled'] for p in sources),
                            toMove=sum(p['remove'] for p in sources), allocated=sum(p['outgoing'] for p in sources),
                            pending=sum(p['remove'] - p['outgoing'] for p in sources)))
