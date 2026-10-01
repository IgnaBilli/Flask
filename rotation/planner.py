"""Daily CP-SAT model. Inputs are harvestable kg DM, never raw biomass.

Reserve is an additional operational buffer in the SAME harvestable units.
No silent clipping of a deficit; snapshots and projections are immutable.
"""
from datetime import date, timedelta
import math
from ortools.sat.python import cp_model

VERSION = 'rotation_cp_sat_v1'
SCALE = 100  # centi-kg, conservative rounding of supply and demand

def validate(data):
    if not isinstance(data, dict):
        raise ValueError('Objeto JSON requerido.')
    date.fromisoformat(data['start'])
    h = data['horizon']
    if type(h) is not int or not 1 <= h <= 28:
        raise ValueError('Horizonte permitido: 1 a 28 días.')
    ps, us = data['paddocks'], data['units']
    if not 1 <= len(ps) <= 30 or not 1 <= len(us) <= 80:
        raise ValueError('Se admiten 1–30 potreros y 1–80 unidades de movimiento.')
    if len({p['id'] for p in ps}) != len(ps) or len({u['id'] for u in us}) != len(us):
        raise ValueError('Identificadores duplicados.')
    animal_ids = [a for u in us for a in u['animals']]
    if len(set(animal_ids)) != len(animal_ids):
        raise ValueError('Un animal aparece en más de una unidad.')
    for p in ps:
        for k in ['stock', 'growth', 'reserve']:
            if isinstance(p[k], bool) or not isinstance(p[k], (float, int)) or not math.isfinite(p[k]) or not 0 <= p[k] <= 1e8:
                raise ValueError(f'{k}: valor no válido.')
        for k in ['rest', 'max_stay', 'occupied_days', 'rested_days']:
            if type(p[k]) is not int or not 0 <= p[k] <= 10000:
                raise ValueError(f'{k}: entero no negativo requerido.')
        if p['max_stay'] < 1 or len(p['available']) != h:
            raise ValueError('Permanencia o disponibilidad inválida.')
    ids = {p['id'] for p in ps}
    for u in us:
        if not u['animals'] or not math.isfinite(u['demand']) or not 0 < u['demand'] <= 1e7 or u['origin'] not in ids:
            raise ValueError('Unidad sin animales, consumo válido u origen.')
        if len(u['allowed']) != len(ps) or any(len(row) != h for row in u['allowed']):
            raise ValueError('Matriz de destinos inválida.')

def simulate(data, assignments):
    stocks = {p['id']: p['stock'] for p in data['paddocks']}
    rows = []
    for d in range(data['horizon']):
        day = (date.fromisoformat(data['start']) + timedelta(days=d)).isoformat()
        for p in data['paddocks']:
            units = [u for u in data['units'] if assignments[u['id']][d] == p['id']]
            demand = sum(u['demand'] for u in units)
            stocks[p['id']] += p['growth'] - demand
            rows.append(dict(date=day, paddock=p['id'], stock=round(stocks[p['id']], 2),
                demand=round(demand, 2), reserve=p['reserve'], growth=p['growth'],
                animals=sum(len(u['animals']) for u in units),
                deficit=round(max(0, p['reserve'] - stocks[p['id']]), 2)))
    return rows

def plan(data):
    validate(data)
    ps, us, h = data['paddocks'], data['units'], data['horizon']
    model = cp_model.CpModel()
    x = {(i,j,d): model.new_bool_var(f'x{i}_{j}_{d}') for i in range(len(us)) for j in range(len(ps)) for d in range(h)}
    occupied = {(j,d): model.new_bool_var(f'o{j}_{d}') for j in range(len(ps)) for d in range(h)}
    changes = []
    for i,u in enumerate(us):
        for d in range(h):
            model.add_exactly_one(x[i,j,d] for j in range(len(ps)))
            for j,p in enumerate(ps):
                if not u['allowed'][j][d] or not p['available'][d] or (u.get('fixed') and p['id'] != u['origin']):
                    model.add(x[i,j,d] == 0)
            change = model.new_bool_var(f'move{i}_{d}')
            if d == 0:
                origin = next(j for j,p in enumerate(ps) if p['id'] == u['origin'])
                model.add(change == 1 - x[i,origin,d])
            else:
                for j in range(len(ps)):
                    model.add(change >= x[i,j,d] - x[i,j,d-1])
                    model.add(change <= 2 - x[i,j,d] - x[i,j,d-1])
            changes.append(change)
    max_pressure = model.new_int_var(0, 1000, 'maximum_utilization')
    for j,p in enumerate(ps):
        start_stock = math.floor(p['stock'] * SCALE)
        growth = math.floor(p['growth'] * SCALE)
        reserve = math.ceil(p['reserve'] * SCALE)
        demand = [math.ceil(u['demand'] * SCALE) for u in us]
        initial_occupied = any(u['origin'] == p['id'] for u in us)
        total_consumed = sum(demand[i]*x[i,j,d] for i in range(len(us)) for d in range(h))
        budget = start_stock + growth*h - reserve
        if budget > 0:
            model.add(total_consumed * 1000 <= max_pressure * budget)
        for d in range(h):
            model.add_max_equality(occupied[j,d], [x[i,j,d] for i in range(len(us))])
            # Excluded/resting paddocks can recover below buffer, but cannot be grazed below it.
            remaining = start_stock + growth*(d+1) - sum(demand[i]*x[i,j,t] for i in range(len(us)) for t in range(d+1))
            model.add(remaining >= reserve).only_enforce_if(occupied[j,d])
            model.add(remaining >= 0)
            # An entry after an empty day requires the full preceding rest interval.
            previous = occupied[j,d-1] if d else int(initial_occupied)
            entry = model.new_bool_var(f'entry{j}_{d}')
            model.add(entry >= occupied[j,d] - previous)
            model.add(entry <= occupied[j,d])
            model.add(entry <= 1-previous)
            for t in range(max(0,d-p['rest']), d):
                model.add(occupied[j,t] == 0).only_enforce_if(entry)
            if d < p['rest']:
                if initial_occupied or p['rested_days'] + d < p['rest']:
                    model.add(entry == 0)
            # A nonempty paddock changing groups has not rested.
            if initial_occupied and d + p['occupied_days'] >= p['max_stay']:
                model.add(sum(occupied[j,t] for t in range(d+1)) <= d)
            if d >= p['max_stay']:
                model.add(sum(occupied[j,t] for t in range(d-p['max_stay'], d+1)) <= p['max_stay'])
        for a in range(len(us)):
            for b in range(a+1,len(us)):
                if us[b]['group'] in us[a].get('incompatible',[]) or us[a]['group'] in us[b].get('incompatible',[]):
                    for d in range(h): model.add(x[a,j,d]+x[b,j,d] <= 1)
    # Lexicographic objective: worst forage utilization, then total movements.
    model.minimize(max_pressure * (len(us)*h+1) + sum(changes))
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = min(15, max(1,float(data.get('time_limit',8))))
    solver.parameters.num_search_workers = 4
    solver.parameters.random_seed = 19
    status = solver.solve(model)
    baseline = simulate(data,{u['id']:[u['origin']]*h for u in us})
    result = dict(version=VERSION, solver=solver.status_name(status), baseline=baseline,
        projection=[], steps=[], assignment={}, elapsed=round(solver.wall_time,3),
        assumptions=['Crecimiento constante durante el horizonte; no es un pronóstico climático.',
                     'Reserva adicional expresada en materia seca utilizable; no equivale a altura residual.',
                     'La planificación no registra movimientos reales.'])
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        result['status'] = 'INVIABLE' if status == cp_model.INFEASIBLE else 'INCONCLUSO'
        result['message'] = ('No existe un plan que cumpla todas las restricciones del escenario. Revisá oferta, descanso, exclusiones y grupos; la rotación no crea forraje.'
            if status == cp_model.INFEASIBLE else 'Se alcanzó el límite de cálculo sin demostrar una solución ni inviabilidad.')
        return result
    schedule = {u['id']:[next(p['id'] for j,p in enumerate(ps) if solver.value(x[i,j,d])) for d in range(h)] for i,u in enumerate(us)}
    result.update(status='OPTIMO' if status == cp_model.OPTIMAL else 'FACTIBLE', assignment=schedule,
        projection=simulate(data,schedule), max_utilization=solver.value(max_pressure)/10)
    for u in us:
        previous = u['origin']
        for d,dest in enumerate(schedule[u['id']]):
            if dest != previous:
                day = (date.fromisoformat(data['start'])+timedelta(days=d)).isoformat()
                until = next((n for n in range(d+1,h) if schedule[u['id']][n] != dest),h)
                result['steps'].append(dict(id=f'{u["id"]}:{d}',group=u['group'],name=u['name'],animals=u['animals'],
                    origin=previous,destination=dest,date=day,days=until-d,
                    reason='Destino permitido por reglas de acceso, convivencia, descanso y reserva. Elegido al minimizar la presión máxima de consumo y luego los movimientos.'))
            previous = dest
    result['steps'].sort(key=lambda s:(s['date'],str(s['group'])))
    return result
