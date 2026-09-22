"""Observed Sentinel-2 variability. Independent of DMP, DMI and stock models."""
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import math
import time
import urllib.request

import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.features import rasterize
from rasterio.transform import from_origin
from rasterio.vrt import WarpedVRT
from pyproj import Transformer
from shapely.geometry import box, mapping, shape
from shapely.ops import transform as transform_shape
from validation import PredictionInputError, validate_dmp

VERSION = 'sentinel2-intrapotrero-v1'
PROCESSING_REVISION = 'earthsearch-cog-offset-v2'
STAC = 'https://earth-search.aws.element84.com/v1/search'
RESOLUTION = 10
# Only confidently classified vegetation and bare soil; no water/shadow/cloud interpolation.
VALID_SCL = (4, 5)


class IntrapaddockSourceError(RuntimeError):
    pass


def make_grid(geojson):
    polygon = shape(geojson)
    lon, lat = polygon.centroid.coords[0]
    if not -60 <= lat <= -20 or not -80 <= lon <= -50:
        raise PredictionInputError('El análisis intrapotrero está disponible para Argentina.')
    crs = f'EPSG:{32700 + min(60, int((lon + 180) / 6) + 1)}'
    forward = Transformer.from_crs('EPSG:4326', crs, always_xy=True).transform
    backward = Transformer.from_crs(crs, 'EPSG:4326', always_xy=True).transform
    projected = transform_shape(forward, polygon)
    left, bottom, right, top = projected.bounds
    left = math.floor(left / RESOLUTION) * RESOLUTION
    top = math.ceil(top / RESOLUTION) * RESOLUTION
    width = math.ceil((right - left) / RESOLUTION)
    height = math.ceil((top - bottom) / RESOLUTION)
    if width * height > 1_000_000 or projected.area > 100_000_000:
        raise PredictionInputError('El potrero excede el límite de 10.000 ha o su extensión espacial es demasiado grande.')
    return projected, crs, from_origin(left, top, RESOLUTION, RESOLUTION), (height, width), backward


def pixel_weights(geometry, grid_shape, affine):
    """Exact fractional area at polygon edges, including interior holes."""
    weights = rasterize([(mapping(geometry), 1)], out_shape=grid_shape, transform=affine).astype('float64') * 100
    edges = rasterize([(mapping(geometry.boundary), 1)], out_shape=grid_shape, transform=affine, all_touched=True)
    for row, col in np.argwhere(edges):
        x, y = affine * (int(col), int(row))
        weights[row, col] = geometry.intersection(box(x, y - RESOLUTION, x + RESOLUTION, y)).area
    return weights


def sectors_for(polygon, grid_shape, affine, backward):
    left, bottom, right, top = polygon.bounds
    midx, midy = (left + right) / 2, (bottom + top) / 2
    quadrants = [box(left, midy, midx, top), box(midx, midy, right, top),
                 box(left, bottom, midx, midy), box(midx, bottom, right, midy)]
    sectors, weights = [], []
    for identifier, quadrant in zip('abcd', quadrants):
        geometry = polygon.intersection(quadrant)
        if geometry.area <= 0.01:
            continue
        sectors.append({'id': identifier, 'name': f'Sector {identifier.upper()}',
                        'areaHa': geometry.area / 10000, 'geometry': mapping(transform_shape(backward, geometry)),
                        'observations': {}, 'validAreaHa': {}, 'validPixels': {}, 'comparisons': {}})
        weights.append(pixel_weights(geometry, grid_shape, affine))
    return sectors, weights


def fetch_scenes(geojson, target):
    payload = {'collections': ['sentinel-2-l2a'], 'intersects': geojson,
               'datetime': f'{target - timedelta(days=90)}T00:00:00Z/{target}T23:59:59Z',
               'sortby': [{'field': 'properties.datetime', 'direction': 'desc'}], 'limit': 24}
    req = urllib.request.Request(STAC, data=json.dumps(payload).encode(), headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=25) as response:
            return sorted(json.load(response).get('features', []), key=lambda item: item.get('properties', {}).get('datetime', ''), reverse=True)
    except Exception as exc:
        raise IntrapaddockSourceError('No se pudo consultar el catálogo Sentinel-2. Reintentá más tarde.') from exc


def reflectance(values, asset, scene):
    """Earth Search legacy COGs can already have the BOA offset subtracted.

    Their raster:bands metadata can still advertise -0.1 (Earth Search #66).
    Respect the explicit applied flag for COG assets only, never original JP2s.
    Do not guess calibration from pixel values or clamp negative reflectance.
    """
    metadata = asset.get('raster:bands', [{}])[0]
    scale = float(metadata.get('scale', 0.0001))
    offset = float(metadata.get('offset', 0))
    is_cog = 'cloud-optimized' in asset.get('type', '')
    if is_cog and scene.get('properties', {}).get('earthsearch:boa_offset_applied') is True:
        offset = 0.0
    return values * scale + offset


def read_scene(scene, crs, affine, grid_shape):
    bands = {}
    with rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN='EMPTY_DIR', GDAL_HTTP_TIMEOUT='20', GDAL_HTTP_MAX_RETRY='1'):
        for name in ('red', 'nir', 'scl'):
            asset = scene['assets'][name]
            # URLs come only from the fixed public STAC collection, never the client.
            with rasterio.open(asset['href']) as source:
                with WarpedVRT(source, crs=crs, transform=affine, width=grid_shape[1], height=grid_shape[0],
                               resampling=Resampling.nearest, nodata=0) as vrt:
                    values = vrt.read(1, masked=True).astype('float32').filled(np.nan)
            if name != 'scl':
                values = reflectance(values, asset, scene)
            bands[name] = values
    return ndvi_from_bands(bands['red'], bands['nir'], bands['scl'])


def ndvi_from_bands(red, nir, scl):
    valid = np.isfinite(red) & np.isfinite(nir) & (red >= 0) & (nir >= 0) & ((red + nir) > 0) & np.isin(scl, VALID_SCL)
    ndvi = np.full(red.shape, np.nan, dtype='float32')
    np.divide(nir - red, nir + red, out=ndvi, where=valid)
    ndvi[(ndvi < -1) | (ndvi > 1)] = np.nan
    return ndvi


def summarize_sector(ndvi, weights):
    valid = np.isfinite(ndvi) & (weights > 0)
    observed = float(weights[valid].sum())
    count = int(valid.sum())
    # Require at least four equivalent full pixels to report a sector mean.
    if observed < 400 - 1e-6:
        return None, 0.0, count
    return float(np.sum(ndvi[valid] * weights[valid]) / observed), observed / 10000, count


def display_cells(ndvi, weights, polygon, affine, backward):
    height, width = ndvi.shape
    stride = max(1, math.ceil(math.sqrt(height * width / 1200)))
    features = []
    for row in range(0, height, stride):
        for col in range(0, width, stride):
            cell_weights = weights[row:row + stride, col:col + stride]
            total = float(cell_weights.sum())
            if total <= 0:
                continue
            values = ndvi[row:row + stride, col:col + stride]
            valid = np.isfinite(values) & (cell_weights > 0)
            valid_area = float(cell_weights[valid].sum())
            # Mixed display cells with <50% usable area are shown as missing.
            mean = float(np.sum(values[valid] * cell_weights[valid]) / valid_area) if valid_area / total >= 0.5 else None
            x, y = affine * (col, row)
            cell = polygon.intersection(box(x, y - stride * RESOLUTION, x + stride * RESOLUTION, y))
            if cell.is_empty or cell.area == 0:
                continue
            features.append({'type': 'Feature', 'geometry': mapping(transform_shape(backward, cell)),
                             'properties': {'ndvi': round(mean, 4) if mean is not None else None,
                                            'coverage': round(valid_area / total * 100, 1)}})
    return {'type': 'FeatureCollection', 'features': features}, stride * RESOLUTION


def calculate_intrapaddock(data):
    data = validate_dmp(data)
    geojson = data.get('geojson')
    if not geojson or sum(len(ring) for ring in geojson['coordinates']) > 5000:
        raise PredictionInputError('Se requiere la geometría del potrero con hasta 5000 vértices.')
    target = date.fromisoformat(data.get('fecha', date.today().isoformat()))
    polygon, crs, affine, grid_shape, backward = make_grid(geojson)
    sectors, weights = sectors_for(polygon, grid_shape, affine, backward)
    total_weights = np.sum(weights, axis=0)
    observations, warnings, rasters = {}, [], {}
    started = time.monotonic()
    candidates = fetch_scenes(geojson, target)
    for scene in candidates[:12]:
        captured = str(scene.get('properties', {}).get('datetime', ''))[:10]
        if not captured or captured in observations:
            continue
        if len(observations) >= 4 or time.monotonic() - started > 240:
            break
        try:
            ndvi = read_scene(scene, crs, affine, grid_shape)
            # Keep the newest capture even if obscured; use the remaining history
            # slots for informative captures instead of four consecutive cloud maps.
            sector_summaries = [summarize_sector(ndvi, w) for w in weights]
            if observations and not any(item[0] is not None for item in sector_summaries):
                continue
            rasters[captured] = ndvi
            cells, display_resolution = display_cells(ndvi, total_weights, polygon, affine, backward)
            for sector, (mean, valid_area, count) in zip(sectors, sector_summaries):
                sector['observations'][captured] = mean
                sector['validAreaHa'][captured] = valid_area
                sector['validPixels'][captured] = count
            observations[captured] = {'sceneId': scene['id'], 'capturedAt': scene['properties']['datetime'],
                                      'cloudPercent': scene['properties'].get('eo:cloud_cover'),
                                      'nativeResolutionM': RESOLUTION, 'displayResolutionM': display_resolution,
                                      'cells': cells}
        except Exception:
            warnings.append(f"No se pudo leer la escena {scene.get('id', '')}.")
    if not observations:
        raise IntrapaddockSourceError('No se pudieron obtener observaciones Sentinel-2 en los últimos 90 días. Reintentá más tarde.')
    dates = sorted(observations)
    for index in range(1, len(dates)):
        current, previous = dates[index], dates[index - 1]
        for sector, sector_weights in zip(sectors, weights):
            common = np.isfinite(rasters[current]) & np.isfinite(rasters[previous]) & (sector_weights > 0)
            area = float(sector_weights[common].sum())
            if area >= 400 - 1e-6 and sector['observations'][current] is not None and sector['observations'][previous] is not None:
                delta = float(np.sum((rasters[current][common] - rasters[previous][common]) * sector_weights[common]) / area)
                sector['comparisons'][current] = {'previousDate': previous, 'delta': delta, 'commonAreaHa': area / 10000}
    signature = hashlib.sha256(json.dumps(geojson, sort_keys=True).encode()).hexdigest()[:16]
    return {'id': f'{signature}-{VERSION}-{PROCESSING_REVISION}', 'illustrative': False, 'version': VERSION,
            'processingRevision': PROCESSING_REVISION,
            'source': 'Sentinel-2 L2A · Earth Search / Copernicus', 'generatedAt': datetime.now(timezone.utc).isoformat(),
            'requestedDate': target.isoformat(), 'geometry': geojson, 'dates': sorted(observations), 'scenes': observations,
            'sectors': sectors, 'warnings': warnings, 'sectorMethod': 'Cuadrantes geométricos fijos; no son ambientes agronómicos.'}
