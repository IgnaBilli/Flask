"""Ventanas de feat/json-rules-begin; no modifica utilización ni referencias."""
import re
import unicodedata

WINDOWS = {
    'PASTIZAL_NATURAL': {'primavera': 38, 'verano': 48, 'otonio': 60, 'invierno': 90},
    'PASTURA_IMPLANTADA': {'primavera': 35, 'verano': 45, 'otonio': 60, 'invierno': 90},
}

def seasonal_window(target, coverage):
    key = target.month * 100 + target.day
    season = ('primavera' if 921 <= key <= 1220 else
              'verano' if key >= 1221 or key <= 320 else
              'otonio' if 321 <= key <= 620 else 'invierno')
    normalized = ''.join(c for c in unicodedata.normalize('NFD', coverage or '') if not unicodedata.combining(c)).lower()
    normalized = ' '.join(re.sub(r'[_-]', ' ', normalized).split())
    normalized = ' '.join(w[:-1] if w.endswith('s') else w for w in normalized.split())
    implanted = {'pastura', 'pastura implantada', 'pastura perenne', 'pradera', 'cultivo temporario', 'cultivo perenne', 'agricultura'}
    natural = {'pastizal', 'pastizal natural', 'campo natural', 'formacion herbacea', 'formacion natural no forestal', 'vegetacion herbacea'}
    profile = 'PASTURA_IMPLANTADA' if normalized in implanted else 'PASTIZAL_NATURAL'
    return {'dias': WINDOWS[profile][season], 'estacion': season, 'perfil': profile,
            'cobertura_reconocida': normalized in natural | implanted,
            'criterio': 'estacion_fecha_objetivo', 'fuente': 'feat/json-rules-begin'}
