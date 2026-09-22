# Corrección radiométrica del análisis intrapotrero

Revisión `earthsearch-cog-offset-v2`, dentro del contrato `sentinel2-intrapotrero-v1`.

En los COG de la colección Earth Search `sentinel-2-l2a`, el indicador
`earthsearch:boa_offset_applied=true` informa que el desplazamiento BOA ya fue
aplicado a los valores almacenados. Algunos assets conservan `offset=-0.1` en
`raster:bands`. Restarlo otra vez produce reflectancia negativa en rojo y descarta
vegetación válida; también sesga el NDVI de los píxeles que sobreviven.

Para assets explícitamente COG con ese indicador se aplica solo la escala. Para
JP2, indicador falso o ausente se mantiene escala más offset de la banda. No se
elige calibración según el valor del píxel ni se fuerzan negativos a cero.

La máscara SCL sigue aceptando únicamente clases 4 y 5; no se rellenan nubes, agua
o sombras. Los resultados persistidos anteriores deben regenerarse. El frontend
los identifica por ausencia de `processingRevision` y muestra un aviso.

La fecha inicial de la interfaz es la más reciente con cobertura >=80%; si no
existe, la de mayor cobertura (desempate por fecha reciente). Es una preferencia
de visualización, no un umbral de validación agronómica. Las demás capturas siguen
disponibles y muestran su cobertura. No se mezclan fechas para rellenar huecos.

Regresión: raster GeoTIFF con rojo=500, NIR=2500, offset ya aplicado y SCL=4
debe producir NDVI=2/3; SCL=9 permanece sin observación. Para JP2, rojo=1500 y
NIR=3500 requieren restar el offset y representan la misma reflectancia.

Referencias del proveedor:
- https://github.com/Element84/earth-search#gainoffset-in-items-after-jan-25-2022
- https://github.com/Element84/earth-search/issues/66

La documentación general remite a raster:bands; la incidencia #66 registra la
inconsistencia de la colección anterior. La corrección se apoya además en el
indicador explícito de las escenas actuales y la comprobación de sus COG.
