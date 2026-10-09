"""Group allocation and hard husbandry constraints; no database or model training."""
import copy
import math
from .fuzzy_priority import finite, rounded
from .paddock_engine import recommend as aggregate_recommend, HORIZON

VERSION = 'rotacion_grupos_v2'
# Saved stock already includes today's resident consumption. A transfer recorded
# for today adds arrival-day consumption before the seven future forecast days.
# Reserve a full arrival day conservatively; do not pretend this pasture is free.
ARRIVAL_RESERVE_DAYS = 1
CATEGORIES = {'TERNERO', 'VAQUILLONA', 'NOVILLO', 'VACA', 'TORO'}


def validate_groups(payload):
    groups = payload.get('groups')
    if not isinstance(groups, list):
        raise ValueError('Se requieren grupos de ganado.')
    paddocks = {p['id']: p for p in payload['paddocks']}
    group_ids, animal_ids, counts = set(), set(), {i: 0 for i in paddocks}
    for p in paddocks.values():
        policy = p.get('management', {})
        if (not isinstance(policy, dict) or not isinstance(policy.get('service', False), bool)
                or not isinstance(policy.get('categories', list(CATEGORIES)), list)
                or any(c not in CATEGORIES for c in policy.get('categories', []))):
            raise ValueError('Reglas de potrero inválidas.')
    for g in groups:
        if (not isinstance(g, dict) or not isinstance(g.get('id'), str) or g['id'] in group_ids
                or g.get('origin') not in paddocks or not isinstance(g.get('name'), str)
                or any(not isinstance(g.get(k), bool) for k in ('allowSplit', 'motherCalf', 'isolated'))
                or not isinstance(g.get('animals'), list) or not g['animals']
                or not isinstance(g.get('issues', []), list)):
            raise ValueError('Grupo inválido.')
        if g['motherCalf'] and g['allowSplit']:
            raise ValueError('No se puede dividir un grupo madre-cría.')
        group_ids.add(g['id'])
        for a in g['animals']:
            if (not isinstance(a, dict) or not finite(a.get('id')) or a['id'] <= 0 or a['id'] != int(a['id'])
                    or a['id'] in animal_ids or a.get('category') not in CATEGORIES
                    or a.get('sex') not in ('M', 'F')
                    or (a.get('condition') is not None and (not finite(a['condition']) or not 1 <= a['condition'] <= 5))
                    or (a.get('demand') is not None and (not finite(a['demand']) or a['demand'] <= 0))):
                raise ValueError('Datos del ganado inválidos.')
            animal_ids.add(a['id'])
            counts[g['origin']] += 1
    if any(counts[i] != p['animals'] for i, p in paddocks.items()):
        raise ValueError('Los grupos no coinciden con el ganado actual.')


def compatible(group, destination, residents, incoming=None):
    animals = incoming if incoming is not None else group['animals']
    policy = destination.get('management', {})
    if any(a['category'] not in policy.get('categories', CATEGORIES) for a in animals):
        return 'El destino no admite las categorías del grupo.'
    others = [g for g in residents if g.get('configId', g['id']) != group.get('configId',group['id']) and g['animals']]
    if others and (group['isolated'] or any(g['isolated'] for g in others)):
        return 'Un grupo aislado no puede convivir con otros grupos.'
    categories = {a['category'] for a in animals}
    categories.update(a['category'] for g in others for a in g['animals'])
    if 'TORO' in categories:
        if 'TERNERO' in categories:
            return 'No se recomienda mezclar toros con terneros.'
        if categories.intersection({'VACA', 'VAQUILLONA'}) and not policy.get('service', False):
            return 'La convivencia con toros requiere servicio reproductivo habilitado.'
    return None


def condition_key(group):
    known = [a['condition'] for a in group['animals'] if a.get('condition') is not None]
    # Lower recorded body condition receives precedence inside the same urgency level.
    # Unknown observations are never filled with an assumed normal score.
    return min(known) if known else 6


def recommend(inputs, groups):
    result = aggregate_recommend(inputs)
    result['version'] = VERSION
    ps = result['paddocks']
    by_id = {p['id']: p for p in ps}
    residents = {p['id']: [] for p in ps}
    for g in copy.deepcopy(groups):
        residents[g['origin']].append(g)
    for p in ps:
        p.update(projectedDemand=p['demand'], projectedAnimals=p['animals'], incoming=0, outgoing=0,
                 arrivalReserve=0)
    sources = {r['origin']: r for r in result['recommendations']}
    candidates = [g for g in groups if g['origin'] in sources]
    levels = {'ALTA': 0, 'MEDIA': 1, 'BAJA': 2}
    candidates.sort(key=lambda g: (by_id[g['origin']]['enabled'],
        levels.get((by_id[g['origin']]['priority'] or {}).get('level'), 0), condition_key(g),
        -(by_id[g['origin']]['priority'] or {}).get('score', 0), g['origin'], g['id']))
    recommendations = []
    for g in candidates:
        source = by_id[g['origin']]
        excess = max(0, source['projectedDemand'] - source['capacity']) if finite(source['projectedDemand']) and source['capacity'] is not None else math.inf
        if source['enabled'] and excess <= 1e-7:
            continue
        issues = list(g.get('issues', []))
        if any(not finite(a.get('demand')) or a['demand'] <= 0 for a in g['animals']):
            issues.append('Actualizá los datos para obtener el consumo del grupo.')
        if not issues and finite(source['demand']):
            origin_groups = [x for x in groups if x['origin'] == g['origin']]
            values = [a.get('demand') for x in origin_groups for a in x['animals']]
            if all(finite(v) for v in values) and abs(sum(values) - source['demand']) > .01 + len(values)*.000051:
                issues.append('El consumo del grupo no coincide con el balance. Actualizá los datos.')
        selected = sorted(g['animals'], key=lambda a: (a.get('condition') if a.get('condition') is not None else 6, a['id']))
        allocations, blocked = {}, set(issues)
        units = [[a] for a in selected] if g['allowSplit'] else [selected]
        for unit in units:
            if issues:
                break
            if g['allowSplit'] and source['enabled'] and source['projectedDemand'] <= source['capacity'] + 1e-7:
                break
            demand = sum(a['demand'] for a in unit)
            options = []
            for d in ps:
                if d['id'] == source['id'] or d['status'] != 'DISPONIBLE' or d['enabled'] is False:
                    continue
                reason = compatible(g, d, residents[d['id']], unit)
                if reason:
                    blocked.add(reason)
                elif d['capacity'] - d['projectedDemand'] - d['arrivalReserve']/HORIZON + 1e-7 < demand*(1+ARRIVAL_RESERVE_DAYS/HORIZON):
                    blocked.add('No hay capacidad suficiente para recibir el grupo sin dividirlo.' if not g['allowSplit'] else 'No queda capacidad suficiente en los destinos.')
                else:
                    options.append(d)
            if not options:
                continue
            dest = min(options, key=lambda d: ((d['projectedDemand'] + demand) / d['capacity'], d['id']))
            dest['projectedDemand'] += demand
            dest['arrivalReserve'] += demand*ARRIVAL_RESERVE_DAYS
            dest['projectedAnimals'] += len(unit)
            dest['incoming'] += len(unit)
            source['projectedDemand'] -= demand
            source['projectedAnimals'] -= len(unit)
            source['outgoing'] += len(unit)
            allocations.setdefault(dest['id'], []).extend(a['id'] for a in unit)
            resident = next((x for x in residents[dest['id']] if x['id'] == g['id']), None)
            if resident:
                resident['animals'].extend(unit)
            else:
                residents[dest['id']].append(dict(g, animals=list(unit)))
        moved = sum(len(ids) for ids in allocations.values())
        if g['allowSplit'] and not issues:
            moved_ids={i for ids in allocations.values() for i in ids}
            chosen=[a for a in selected if a['id'] in moved_ids]
            residual=source['projectedDemand']-source['capacity'] if source['enabled'] else math.inf
            for a in selected:
                if residual <= 1e-7:
                    break
                if a['id'] not in moved_ids:
                    chosen.append(a)
                    residual -= a['demand']
            selected=chosen
        # Groups that could not be placed are still shown. Other groups can resolve
        # the excess later; consolidate the remaining source need below.
        recommendations.append(dict(id=g['id'], origin=source['id'], name=source['name'], group=g['name'],
            groupId=g.get('configId',g['id']), remove=len(selected), allocated=moved, unallocated=len(selected)-moved,
            reason='EXCESO' if source['enabled'] else 'FUERA_USO', priority=source['priority'],
            excess=source['excess'], needsDemand=bool(issues), excessPercent=None,
            condition=None if condition_key(g) == 6 else condition_key(g),
            missingCondition=sum(a.get('condition') is None for a in selected),
            allowSplit=g['allowSplit'], motherCalf=g['motherCalf'], isolated=g['isolated'],
            blocked=sorted(blocked) if len(selected)>moved else [],
            destinations=[dict(id=i, name=by_id[i]['name'], quantity=len(ids), animalIds=ids) for i, ids in allocations.items()]))
    # Do not claim a blocked group still needs to move if another group resolved its origin.
    recommendations = [r for r in recommendations if r['allocated'] or not by_id[r['origin']]['enabled']
        or not finite(by_id[r['origin']]['projectedDemand']) or by_id[r['origin']]['projectedDemand'] > (by_id[r['origin']]['capacity'] or 0)+1e-7]
    for r in recommendations:
        source=by_id[r['origin']]
        if source['enabled'] and finite(source['projectedDemand']) and source['projectedDemand'] <= (source['capacity'] or 0)+1e-7:
            r.update(remove=r['allocated'], unallocated=0, blocked=[])
    # A failed allocation is not an instruction to evacuate every group of an
    # overloaded paddock. Keep only enough pending groups to cover its residual.
    residual={p['id']:max(0,p['projectedDemand']-(p['capacity'] or 0)) if finite(p['projectedDemand']) else math.inf for p in ps}
    indexed={g['id']:g for g in groups}
    for r in recommendations:
        if not by_id[r['origin']]['enabled'] or not r['unallocated']:
            continue
        if residual[r['origin']] <= 1e-7:
            r.update(remove=r['allocated'],unallocated=0,blocked=[])
        else:
            moved_ids={i for d in r['destinations'] for i in d['animalIds']}
            remaining=[a for a in indexed[r['id']]['animals'] if a['id'] not in moved_ids]
            if all(finite(a.get('demand')) for a in remaining):
                residual[r['origin']] -= sum(a['demand'] for a in remaining)
    recommendations=[r for r in recommendations if r['remove']]
    for p in ps:
        p['projectedDemand'] = rounded(p['projectedDemand']) if finite(p['projectedDemand']) else None
        p['projectedBalance'] = rounded(max(0,p['stock'])+HORIZON*(p['growth']-p['projectedDemand'])) if p['enabled'] and p['capacity'] is not None else None
        p['remainingExcess'] = rounded(max(0,(p['projectedDemand'] or 0)-p['capacity'])) if p['capacity'] is not None else None
        p['projectedPressure'] = rounded(100*p['projectedDemand']/p['capacity']) if p['capacity'] else None
    result.update(recommendations=recommendations, groups=groups, arrivalReserveDays=ARRIVAL_RESERVE_DAYS,
        partial=result['partial'] or any(g.get('issues') for g in groups))
    result['totals'].update(toMove=sum(r['remove'] for r in recommendations), allocated=sum(r['allocated'] for r in recommendations), pending=sum(r['unallocated'] for r in recommendations))
    return result


def validate_transfer(payload):
    ps = {p['id']: p for p in aggregate_recommend(payload['paddocks'])['paddocks']}
    groups = payload['groups']
    transfer = payload.get('transfer', {})
    ids = transfer.get('animalIds')
    if not isinstance(ids, list) or not ids or any(not finite(i) or i != int(i) for i in ids) or len(set(ids)) != len(ids):
        raise ValueError('Selección de ganado inválida.')
    origin, dest = ps.get(transfer.get('origin')), ps.get(transfer.get('destination'))
    if not origin or not dest or origin['id'] == dest['id'] or dest['enabled'] is False:
        raise ValueError('Destino inválido o fuera de uso.')
    selected_groups = [g for g in groups if any(a['id'] in ids for a in g['animals'])]
    selected = [a for g in selected_groups for a in g['animals'] if a['id'] in ids]
    if len(selected) != len(ids) or any(g['origin'] != origin['id'] for g in selected_groups):
        raise ValueError('El ganado cambió de origen. Volvé a revisar el traslado.')
    residents = [g for g in groups if g['origin'] == dest['id']]
    for g in selected_groups:
        part = [a for a in g['animals'] if a['id'] in ids]
        if not g['allowSplit'] and len(part) != len(g['animals']):
            raise ValueError('El grupo debe trasladarse completo. Habilitá su división si corresponde.')
        reason = compatible(g, dest, residents, part)
        if reason:
            raise ValueError(reason)
        residents.append(dict(g, animals=part))
    if transfer.get('recommendation'):
        if not dest['included'] or dest['issues'] or origin['issues'] or any(g.get('issues') for g in selected_groups):
            raise ValueError('Los datos cambiaron o están pendientes. Actualizá Rotación antes de confirmar.')
        if any(not finite(a.get('demand')) for a in selected):
            raise ValueError('Actualizá el consumo antes de confirmar.')
        if dest['capacity'] is None or dest['demand']+sum(a['demand'] for a in selected)*(1+ARRIVAL_RESERVE_DAYS/HORIZON) > dest['capacity']+1e-7:
            raise ValueError('El destino ya no tiene capacidad para este traslado. Actualizá Rotación.')
    return dict(valid=True)
