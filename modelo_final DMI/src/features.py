import pandas as pd

FEATURES = [
    "peso_vivo_kg",
    "categoria_terrabovina",
    "condicion_corporal",
    "estado_fisiologico_norm",
]
MISSING_CATEGORY = "DESCONOCIDO"


def normalize_estado(value: object) -> str:
    if value is None or pd.isna(value):
        return MISSING_CATEGORY
    normalized = str(value).strip().upper().replace(" ", "")
    return normalized or MISSING_CATEGORY


def prepare_features(df: pd.DataFrame) -> pd.DataFrame:
    missing = set(FEATURES) - set(df.columns)
    if missing:
        raise ValueError(f"Faltan columnas requeridas: {sorted(missing)}")

    out = df[FEATURES].copy()
    out["peso_vivo_kg"] = pd.to_numeric(out["peso_vivo_kg"], errors="raise")
    out["condicion_corporal"] = pd.to_numeric(out["condicion_corporal"], errors="coerce")
    out["categoria_terrabovina"] = out["categoria_terrabovina"].astype(str).str.strip()
    out["estado_fisiologico_norm"] = out["estado_fisiologico_norm"].map(normalize_estado)

    not_cow = out["categoria_terrabovina"] != "Vaca"
    out.loc[not_cow, "condicion_corporal"] = float("nan")
    out.loc[not_cow, "estado_fisiologico_norm"] = MISSING_CATEGORY
    return out
