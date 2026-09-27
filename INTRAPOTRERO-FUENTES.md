# Curvas utilizadas por el análisis intrapotrero

Fuente numérica efectiva: `stock/data/parametros_regionales.json`, versión 1.1.0. Valores en kg MS/ha/día; orden enero a diciembre. Se reutilizan las curvas existentes, sin nuevos coeficientes inventados.

[Método completo, fuentes conceptuales y relación con el PFI](https://github.com/JuanManuelSosa2004/BackendTerrabovina/blob/StockCalc/INTRAPOTRERO.md).

Las atribuciones siguientes se transcriben del archivo de parámetros; no implican que todas las series originales se hayan recuperado y auditado independientemente. La matriz PFI 3.8 es una compilación interna, distinta de main.pdf. La etiqueta declarada loma/bajo no cambia la curva seleccionada. Los perfiles del Caldenal no se habilitan en esta primera versión Centro/NEA.

## Catálogo por región

| Región | Perfiles disponibles |
|---|---|
| Corrientes | pastos_cortos, malezal, pajonal, flechillar |
| Norte de Entre Rios | pastizal_natural_entre_rios_norte |
| Nordeste de Buenos Aires | pastizal_natural_buenos_aires_ne |
| Centro de Buenos Aires | pastizal_regular_bueno_buenos_aires_centro, pastizal_degradado_buenos_aires_centro |
| Pampa Deprimida | pampa_deprimida_loma_media_loma, pampa_deprimida_bajo_dulce, pampa_deprimida_bajo_alcalino |
| Caldenal Norte (Victorica-Loventuel) | caldenal_norte_sabana, caldenal_norte_eragrostis |
| Caldenal Centro (Toay-Anguil) | caldenal_centro_sabana, caldenal_centro_eragrostis |
| Caldenal Sur (General Acha-Peru) | caldenal_sur_sabana, caldenal_sur_eragrostis |
| Chaco Humedo oriental | chaco_humedo_paja_amarilla, chaco_humedo_paja_boba |
| Norte de Santa Fe | santa_fe_panicum_prionitis, santa_fe_spartina_argentinensis |

## Valores y referencias heredadas

### Pastos cortos

ID: `pastos_cortos`

Valores: 27.5, 30.9, 24.1, 16.1, 7.2, 3.9, 5.0, 7.0, 11.0, 20.0, 26.0, 29.3.

Procedencia declarada: Pizzio et al. (2021), INTA, Produccion y utilizacion de los pastizales de Corrientes, Tabla 3, p. 63.

### Malezal

ID: `malezal`

Valores: 18.1, 24.6, 24.5, 18.3, 13.2, 5.2, 3.8, 5.7, 7.9, 13.0, 17.2, 22.0.

Procedencia declarada: Pizzio et al. (2021), INTA, Produccion y utilizacion de los pastizales de Corrientes, Tabla 3, p. 63.

### Pajonal

ID: `pajonal`

Valores: 19.8, 21.3, 16.3, 11.8, 6.3, 4.2, 4.3, 6.5, 10.7, 17.1, 20.2, 19.4.

Procedencia declarada: Pizzio et al. (2021), INTA, Produccion y utilizacion de los pastizales de Corrientes, Tabla 3, p. 63.

### Flechillar

ID: `flechillar`

Valores: 15.1, 17.8, 14.1, 9.8, 4.3, 2.6, 3.5, 5.4, 8.3, 11.7, 13.3, 16.2.

Procedencia declarada: Pizzio et al. (2021), INTA, Produccion y utilizacion de los pastizales de Corrientes, Tabla 3, p. 63.

### Pastizal natural del norte de Entre Rios

ID: `pastizal_natural_entre_rios_norte`

Valores: 13.5, 13.8, 11.8, 10.2, 7.3, 5.9, 5.2, 5.7, 8.2, 11.3, 14.7, 14.5.

Procedencia declarada: Serie regional LART compilada en TerraBovina_fuentes_referencia_regional.xlsx.

### Pastizal natural del nordeste de Buenos Aires

ID: `pastizal_natural_buenos_aires_ne`

Valores: 16.8, 19.8, 17.0, 13.3, 10.1, 8.7, 8.5, 9.7, 12.4, 15.7, 17.5, 15.7.

Procedencia declarada: Serie INTA/LART compilada en TerraBovina_fuentes_referencia_regional.xlsx.

### Pastizal regular-bueno del centro de Buenos Aires

ID: `pastizal_regular_bueno_buenos_aires_centro`

Valores: 13.0, 12.3, 13.8, 11.1, 7.4, 6.6, 6.7, 7.6, 10.0, 15.4, 18.1, 13.8.

Procedencia declarada: Recavarren, INTA Balcarce, Tablas practicas para presupuestacion forrajera, Tabla 1.

### Pastizal degradado del centro de Buenos Aires

ID: `pastizal_degradado_buenos_aires_centro`

Valores: 8.7, 9.2, 10.3, 8.3, 5.0, 4.4, 4.5, 5.7, 7.5, 12.8, 15.1, 11.0.

Procedencia declarada: Recavarren, INTA Balcarce, Tablas practicas para presupuestacion forrajera, Tabla 1.

### Pampa Deprimida - loma y media loma

ID: `pampa_deprimida_loma_media_loma`

Valores: 17.3, 16.4, 18.4, 14.8, 9.9, 8.8, 8.9, 10.1, 13.3, 20.5, 24.1, 18.4.

Procedencia declarada: Matriz de referencias regionales para TerraBovina, PFI 3.8, pagina 8, fila BA-04.

### Pampa Deprimida - bajo dulce

ID: `pampa_deprimida_bajo_dulce`

Valores: 20.5, 19.4, 21.7, 17.5, 11.7, 10.4, 10.6, 12.0, 15.7, 24.3, 28.5, 21.7.

Procedencia declarada: Matriz de referencias regionales para TerraBovina, PFI 3.8, pagina 8, fila BA-05.

### Pampa Deprimida - bajo alcalino

ID: `pampa_deprimida_bajo_alcalino`

Valores: 7.0, 7.4, 8.3, 6.7, 4.0, 3.5, 3.6, 4.6, 6.0, 10.3, 12.1, 8.8.

Procedencia declarada: Matriz de referencias regionales para TerraBovina, PFI 3.8, pagina 8, fila BA-06.

### Caldenal Norte - vegetacion herbacea de sabana

ID: `caldenal_norte_sabana`

Valores: 18.1, 10.3, 8.4, 4.6, 1.8, 0.7, 0.4, 0.5, 1.3, 3.4, 7.7, 10.6.

Procedencia declarada: Matriz de referencias regionales para TerraBovina, PFI 3.8, pagina 8, fila LP-01.

### Caldenal Centro - vegetacion herbacea de sabana

ID: `caldenal_centro_sabana`

Valores: 11.1, 7.2, 5.8, 4.6, 2.5, 1.3, 1.2, 1.7, 3.7, 6.2, 8.6, 6.6.

Procedencia declarada: Matriz de referencias regionales para TerraBovina, PFI 3.8, pagina 8, fila LP-02.

### Caldenal Sur - vegetacion herbacea de sabana

ID: `caldenal_sur_sabana`

Valores: 12.0, 7.3, 6.8, 4.8, 2.3, 1.4, 1.2, 1.5, 2.6, 4.5, 6.8, 6.8.

Procedencia declarada: Matriz de referencias regionales para TerraBovina, PFI 3.8, pagina 8, fila LP-03.

### Caldenal Norte - pastura de Eragrostis curvula

ID: `caldenal_norte_eragrostis`

Valores: 30.0, 17.2, 14.8, 8.1, 3.0, 1.5, 1.2, 1.5, 3.6, 7.5, 13.2, 17.3.

Procedencia declarada: Matriz de referencias regionales para TerraBovina, PFI 3.8, pagina 8, fila LP-04.

### Caldenal Centro - pastura de Eragrostis curvula

ID: `caldenal_centro_eragrostis`

Valores: 19.9, 13.8, 12.3, 6.9, 2.6, 1.3, 1.0, 1.4, 4.8, 10.0, 13.2, 10.0.

Procedencia declarada: Matriz de referencias regionales para TerraBovina, PFI 3.8, pagina 8, fila LP-05.

### Caldenal Sur - pastura de Eragrostis curvula

ID: `caldenal_sur_eragrostis`

Valores: 13.0, 8.7, 8.0, 5.4, 2.7, 1.7, 1.8, 2.8, 6.1, 12.4, 14.6, 8.3.

Procedencia declarada: Matriz de referencias regionales para TerraBovina, PFI 3.8, pagina 8, fila LP-06.

### Chaco Humedo oriental - pajonal de paja amarilla

ID: `chaco_humedo_paja_amarilla`

Valores: 28.9, 28.9, 28.9, 12.3, 12.3, 12.3, 12.3, 12.3, 12.3, 28.9, 28.9, 28.9.

Procedencia declarada: Matriz de referencias regionales para TerraBovina, PFI 3.8, pagina 8, fila CH-01.

### Chaco Humedo oriental - pajonal de paja boba

ID: `chaco_humedo_paja_boba`

Valores: 29.5, 29.5, 29.5, 12.6, 12.6, 12.6, 12.6, 12.6, 12.6, 29.5, 29.5, 29.5.

Procedencia declarada: Matriz de referencias regionales para TerraBovina, PFI 3.8, pagina 8, fila CH-02.

### Norte de Santa Fe - pajonal de Panicum prionitis

ID: `santa_fe_panicum_prionitis`

Valores: 17.8, 17.8, 17.8, 7.6, 7.6, 7.6, 7.6, 7.6, 7.6, 17.8, 17.8, 17.8.

Procedencia declarada: Matriz de referencias regionales para TerraBovina, PFI 3.8, pagina 8, fila SF-02.

### Norte de Santa Fe - espartillar de Spartina argentinensis

ID: `santa_fe_spartina_argentinensis`

Valores: 11.0, 11.0, 11.0, 4.7, 4.7, 4.7, 4.7, 4.7, 4.7, 11.0, 11.0, 11.0.

Procedencia declarada: Matriz de referencias regionales para TerraBovina, PFI 3.8, pagina 8, fila SF-01.

## Servicio y verificación

`POST /intrapotrero/analizar` recibe Polygon WGS84, fecha ISO y configuración. Usa Shapely/pyproj ya presentes; no agrega dependencias ni llamadas remotas. Endpoint 422 para datos inválidos; 500 controlado para fallos inesperados. Los datos no se guardan en Flask: Node valida pertenencia y registra cada revisión.

Pruebas: `python -m unittest test_intrapaddock -v` y `python -m unittest discover -s tests -v`. El primer conjunto usa selección regional controlada para aislar la geometría; se verifica también el endpoint con el GIS real.

Rama desplegada: `StockCalc`. Respaldo previo: tag `respaldo/pre-intrapotrero-20260927`, commit `593d72afc64b966001be535ba6b6d727eb4ac85c`. Ver las instrucciones de recuperación en el repositorio BackendTerrabovina.
