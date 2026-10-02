# Respaldo regional por proximidad

El servicio `POST /predict/stock` conserva primero las reglas regionales
directas de `gis_utils.py`. Cuando no hay regla directa, un potrero completamente
dentro de Buenos Aires, Corrientes, Chaco, Formosa o Misiones puede obtener una
referencia transferida mediante `nearby_reference.py`. La cobertura se verifica
con los polígonos provinciales GeoRef/IGN ya incluidos en el repositorio.
Fuera de ese ámbito se conserva el comportamiento regional anterior.

## Selección

Se ordenan las referencias disponibles por:

1. Coincidencia de unidad de vegetación Oyarzabal y ecorregión IGN.
2. Misma unidad de vegetación.
3. Misma ecorregión.
4. Si no existe coincidencia, cualquier referencia con curva mensual completa.

Dentro de cada nivel gana la menor distancia WGS84 al punto del límite operativo
obtenido al limitar las coordenadas del potrero al bbox regional. Es una distancia
aproximada a la región, no a una estación o parcela medida. Si empatan, se usa la
distancia al centro del bbox y finalmente el identificador para reproducibilidad.
Cuando una unidad identifica un perfil concreto, no se agregan otros perfiles de
esa región. Se excluyen curvas incompletas, N/D, no finitas o negativas. Los
valores mensuales publicados no se alteran ni interpolan.

La producción sigue calculándose mediante las curvas seleccionadas y la anomalía
DMP del propio potrero, con los datos satelitales y meteorológicos del lugar.
No se copia el stock de otro potrero ni se comparan directamente series climáticas
entre regiones. Se conservan la mediana y el rango de los perfiles seleccionados,
el 50% utilizable y el balance existente. Ese rango no es un intervalo estadístico
de confianza ni representa todo el error de transferencia.

## Trazabilidad y límites

`seleccion_referencia.estado = RESPALDO_PROXIMIDAD` identifica el respaldo.
`seleccion_referencia.respaldo` registra versión, provincias, candidatos ordenados,
distancias y coincidencias ambientales. Confianza y aplicabilidad son BAJA;
`validacion_local` y `comparacion_climatica_directa` son false. Las reglas de
priorización constituyen una heurística del sistema, no una técnica validada por
los autores de las curvas. Una clasificación ambiental semejante tampoco prueba
que ambos campos tengan igual productividad.

El cambio elimina el bloqueo por ausencia de referencia regional en el ámbito
indicado, siempre que la matriz y la cartografía estén disponibles. No garantiza
un valor ante coberturas no admitidas (bosque cerrado, agua, urbano, etc.), errores
de entrada, falta de escenas válidas o fallas externas. Se conserva el supuesto
ganadero existente para coberturas agrícolas. No se agregan avisos visuales ni
inputs a la interfaz. El análisis intrapotrero usa el mismo selector, manteniendo
separado el módulo experimental climático sin modelo validado.

## Verificación

`python -B -m unittest discover -s tests -v` incluye regresiones de selección,
límites provinciales, prioridades, distancias, curvas incompletas, reglas previas,
huecos de cartografía y balance completo con fuentes externas simuladas.
Las pruebas reales y el respaldo anterior al despliegue se guardan fuera del
repositorio en `deploy-terrabovina/respaldo-regional-20261002`.
