"""Sugeno order-zero priority, behavior-compatible with prioridad_sugeno_v1."""
import math

MODEL = 'prioridad_sugeno_v1'
OUTPUTS = ((55, 20, 20), (90, 55, 20), (90, 90, 55))


def finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def rounded(value):
    # Match JavaScript Math.round, not Python's ties-to-even round.
    return math.floor(value * 100 + .5) / 100


def partition(x, a, b, c):
    low = max(0, min(1, (b - x) / (b - a)))
    high = max(0, min(1, (x - b) / (c - b)))
    return low, max(0, 1 - low - high), high


def evaluate_priority(p):
    stock, growth, demand, animals = (p.get(k) for k in ('stock', 'growth', 'demand', 'animals'))
    if (p.get('issues') or not all(finite(x) for x in (stock, growth, demand, animals))
            or growth < 0 or demand <= 0 or animals <= 0 or animals != int(animals)):
        return None
    ratio = demand / growth if growth else None
    days = max(0, stock) / demand
    pressure = partition(ratio if ratio is not None else 2, .8, 1.2, 2)
    reserve = partition(days, 3, 7, 14)
    rules, total, weight = [], 0, 0
    for i, pressure_name in enumerate(('BAJA', 'MEDIA', 'ALTA')):
        for j, reserve_name in enumerate(('CORTA', 'MEDIA', 'LARGA')):
            activation = pressure[i] * reserve[j]
            if not activation:
                continue
            total += activation * OUTPUTS[i][j]
            weight += activation
            rules.append(dict(pressure=pressure_name, reserve=reserve_name,
                              activation=rounded(activation), output=OUTPUTS[i][j]))
    score = rounded(total / weight)
    explanation = ('La reserva estimada cubre hasta 3 días de consumo sin contar crecimiento.' if days <= 3
                   else 'Hay consumo y no hay crecimiento utilizable estimado.' if growth == 0
                   else 'El consumo duplica o supera el crecimiento utilizable estimado.' if ratio >= 2
                   else 'Prioridad según la presión de pastoreo y la reserva estimada.')
    return dict(model=MODEL, score=score, level='ALTA' if score >= 70 else 'MEDIA' if score >= 40 else 'BAJA',
                explanation=explanation, inputs=dict(pressureRatio=rounded(ratio) if ratio is not None else None,
                zeroGrowth=growth == 0, reserveDays=rounded(days)), rules=rules)
