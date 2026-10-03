# Respaldo regional por proximidad

El servicio `POST /predict/stock` conserva primero las reglas regionales
directas de `gis_utils.py`. Cuando no hay regla directa, un potrero completamente
dentro de Buenos Aires, Corrientes, Chaco, Formosa, Misiones, Santa Fe,
Entre Ríos o La Pampa puede obtener una
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

## Respaldo del cálculo sin observaciones (v3)

Para polígonos válidos completamente dentro de las ocho provincias, Stock
también puede calcularse si falta una escena, clima o historia DMP suficiente.
Cada bloque conserva el ajuste DMP cuando hay observación e historia válidas.
En los demás se usa la curva mensual regional sin anomalía (multiplicador 1).
No se inventan NDVI, clima, DMP ni una mediana histórica: permanecen nulos o
con sus observaciones reales. `factor_dmp_original` es null en el respaldo.

Se priorizan los bloques recientes dentro de un presupuesto remoto de 120 s
por consulta; una llamada ya iniciada puede terminar después. Al agotarse,
los bloques restantes utilizan la curva local. Las lecturas GDAL tienen timeout
de 20 s. El balance se devuelve en orden cronológico y descuenta consumo
normalmente, con piso cero. No se agregan biomasa inicial ni números arbitrarios.

Cuando MapBiomas indica cobertura incompatible, se conserva esa clasificación
y se estima el potencial regional bajo el uso ganadero asumido por el producto;
no se aplica DMP de bosque/agua/urbano como si midiera pasto. Esto NO demuestra
que haya forraje real allí. Fuera de estas ocho provincias se conserva el rechazo anterior.

`respaldo_estimacion` registra cantidad de bloques regionales/ajustados y ámbito;
cada período incluye `metodo_crecimiento` y `motivo_respaldo`. La aplicabilidad
es BAJA cuando hay respaldo. El backend preserva estas trazas y no informa una
variación climática observada de 0% cuando solo se aplicó una referencia.
El supuesto ganadero sigue siendo explícito en la API, sin nuevos formularios
ni banners. Los campos inválidos, polígonos demasiado pequeños (<=0,01 ha),
ubicaciones fuera del ámbito y fallas de infraestructura/configuración siguen
pudiendo fallar. No existe garantía absoluta ante cualquier falla del servicio.

El análisis intrapotrero usa el mismo selector regional, manteniendo separado
el módulo experimental climático sin modelo validado. Sus otras APIs no se
sustituyen por este respaldo de Stock.

## Verificación

`python -B -m unittest discover -s tests -v` incluye regresiones de selección,
límites provinciales, prioridades, distancias, curvas incompletas, reglas previas,
huecos de cartografía y balance completo con fuentes externas simuladas.
Las pruebas reales y el respaldo anterior al despliegue se guardan fuera del
repositorio en `deploy-terrabovina/respaldo-regional-20261002`.

## Ampliación territorial (v4)

Se agregan los polígonos completos de Santa Fe, Entre Ríos y La Pampa a
`provincias_respaldo_stock.geojson`, extraídos de la descarga GeoRef oficial
del 29/09/2026. La cobertura del módulo climático experimental queda separada
en su archivo anterior: esta ampliación no le atribuye nuevas fuentes.
El respaldo de Stock requiere que todo el polígono esté dentro de la unión
provincial y admite potreros que crucen límites internos del ámbito.
No se relajan las fronteras internacionales ni se agrega un número constante.
En el oeste pampeano puede transferirse Caldenal a Monte sin coincidencia
ambiental; es una aproximación de baja confianza, no una validación del Monte.
El caso Espinal/U20 de Santa Fe obtiene una referencia próxima compatible
por ecorregión; no una curva específica medida en ese potrero.
