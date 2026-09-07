"""Validate prediction requests before loading sources or running models."""
import math
from datetime import date, datetime
from shapely.geometry import shape


class PredictionInputError(ValueError):
    pass


def number(value, field, minimum=None, maximum=None):
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise PredictionInputError(f'{field} debe ser un número finito.') from exc
    if isinstance(value, bool) or not math.isfinite(result):
        raise PredictionInputError(f'{field} debe ser un número finito.')
    if (minimum is not None and result < minimum) or (maximum is not None and result > maximum):
        raise PredictionInputError(f'{field} está fuera del rango permitido.')
    return result


def validate_dmi(data, categories):
    if not isinstance(data, dict):
        raise PredictionInputError('Body JSON debe ser un objeto.')
    animals = data.get('animales')
    if not isinstance(animals, list) or not 1 <= len(animals) <= 1000:
        raise PredictionInputError('animales debe contener entre 1 y 1000 elementos.')
    ids = set()
    for animal in animals:
        if not isinstance(animal, dict):
            raise PredictionInputError('Cada animal debe ser un objeto.')
        identifier = animal.get('animal_id')
        if not isinstance(identifier, (str, int)) or isinstance(identifier, bool) or not str(identifier).strip():
            raise PredictionInputError('Cada animal requiere animal_id.')
        if str(identifier) in ids:
            raise PredictionInputError('animal_id no puede repetirse en el lote.')
        ids.add(str(identifier))
        if not isinstance(animal.get('categoria_terrabovina'), str) or animal['categoria_terrabovina'] not in categories:
            raise PredictionInputError('categoria_terrabovina no es una categoría admitida.')
        if number(animal.get('peso_vivo_kg'), 'peso_vivo_kg') <= 0:
            raise PredictionInputError('peso_vivo_kg debe ser mayor que cero.')
        if animal.get('condicion_corporal') is not None:
            number(animal['condicion_corporal'], 'condicion_corporal', 1, 5)
    return animals


def validate_dmp(data):
    if not isinstance(data, dict) or not data:
        raise PredictionInputError('Body JSON debe ser un objeto no vacío.')
    days = number(data.get('dmp_dias_periodo', 10), 'dmp_dias_periodo', 1, 365)
    if not days.is_integer():
        raise PredictionInputError('dmp_dias_periodo debe ser un entero.')
    data = {**data, 'dmp_dias_periodo': int(days)}
    if 'fecha' in data:
        try:
            target = datetime.strptime(str(data['fecha']), '%Y-%m-%d').date()
        except ValueError as exc:
            raise PredictionInputError('fecha debe tener formato YYYY-MM-DD.') from exc
        if target.isoformat() != data['fecha'] or target > date.today():
            raise PredictionInputError('fecha debe ser válida y no futura.')
    if 'geojson' in data:
        geo = data['geojson']
        try:
            ring = geo['coordinates'][0]
            if geo.get('type') != 'Polygon' or len(ring) < 4 or ring[0] != ring[-1]:
                raise ValueError('El anillo debe estar cerrado.')
            for rings in geo['coordinates']:
                for point in rings:
                    if len(point) != 2:
                        raise ValueError('Coordenadas 2D requeridas.')
                    number(point[0], 'longitud', -180, 180)
                    number(point[1], 'latitud', -90, 90)
            polygon = shape(geo)
            if polygon.is_empty or not polygon.is_valid or polygon.area <= 0:
                raise ValueError('Polígono inválido.')
        except (TypeError, KeyError, IndexError, ValueError) as exc:
            raise PredictionInputError('geojson debe ser un Polygon válido y cerrado.') from exc
    else:
        number(data.get('latitud'), 'latitud', -90, 90)
        number(data.get('longitud'), 'longitud', -180, 180)
    if 'ndvi_promedio' in data:
        number(data['ndvi_promedio'], 'ndvi_promedio', -1, 1)
    return data
