"""Small, temporary progress records shared by Gunicorn workers on this host."""
import json
import os
import tempfile
import time
from pathlib import Path
from uuid import UUID, uuid4

DIRECTORY = Path(tempfile.gettempdir()) / 'terrabovina-stock-progress'
TTL = 3600

def record_path(identifier):
    return DIRECTORY / (str(UUID(identifier)) + '.json')

def read_progress(identifier):
    try:
        path = record_path(identifier)
        if time.time() - path.stat().st_mtime > TTL:
            return None
        return json.loads(path.read_text(encoding='utf8'))
    except (ValueError, TypeError, AttributeError, OSError, json.JSONDecodeError):
        return None

def reporter(identifier):
    path = record_path(identifier)
    last = -1
    try:
        DIRECTORY.mkdir(exist_ok=True)
        for old in DIRECTORY.glob('*.json'):
            if time.time() - old.stat().st_mtime > TTL:
                old.unlink(missing_ok=True)
    except OSError:
        pass

    def report(value):
        nonlocal last
        value = max(last, min(100, max(0, int(value))))
        if value == last:
            return
        last = value
        temporary = path.with_suffix('.' + uuid4().hex + '.tmp')
        try:
            temporary.write_text(json.dumps({'porcentaje': value}), encoding='utf8')
            os.replace(temporary, path)
        except OSError:
            # Telemetry must never change the calculation or its error handling.
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
    return report
