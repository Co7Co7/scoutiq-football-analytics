# Plan, modelo y guía Power BI

## 1. Diagnóstico de las fuentes

| Fuente | Filas | Identifica jugadores por | Identifica clubes por | Granularidad |
|---|---|---|---|---|
| Master_Salarios.csv | 7,958 | `Player` (texto, con acentos) | `Club` | jugador-temporada |
| Master_Salarios_2526.csv | 2,827 | `Player` | `Club` | jugador-temporada (solo 25-26) |
| Master_Rating.csv | 8,608 | `player` (sin acentos) | `team` (versión corta) | jugador-temporada |
| Master_Rendimiento.csv | 10,209 | `player` | `squad` (con acentos) | jugador-temporada |
| logos.xlsx | 5 | — | — | liga |

**El problema** no es solo que los nombres difieran ("Atletico Madrid" vs "Atletico" vs "Atlético Madrid"), sino también:

- **Salarios 25-26** etiqueta como `Liga = 'Desconocida'` a 1,104 jugadores de La Liga + Serie A (no las distingue).
- **Master_Rating** tiene errores de scraping: nombres de equipos compuestos quedaron pegados al nombre del jugador. RB Leipzig → equipo `Desconocido`, jugador `"Christopher NkunkuRBL"`. Lo mismo con PSG, Saint-Étienne, St. Pauli, Parma Calcio 1913.
- **Salarios 25-26** no trae la columna `Adj_Net_Total_PY_2026` que sí tiene el histórico.

## 2. Solución elegida: modelo en estrella

En vez de intentar un solo dataset gigante, construyo el modelo dimensional clásico que Power BI maneja mejor:

```
                    dim_temporada
                         |
                         |
   dim_liga ───┐         ↓        ┌─── dim_club
               └──→ fact_salarios ←──┘
               └──→ fact_rating ←───┘
               └──→ fact_rendimiento ←┘
                         ↑
                         |
                    dim_jugador
```

**Por qué este diseño:**

- **dim_club es el puente.** Tiene `ClubID` único + columnas con los nombres tal como aparecen en cada fuente (`AliasSalarios`, `AliasRating`, `AliasRend`). Así el `ClubID` es la única clave que necesitan las hechos.
- **dim_jugador usa clave compuesta normalizada** (nombre sin acentos + ClubID + Temporada). Esto desambigua jugadores con el mismo nombre en clubes/temporadas distintos, que es justamente donde fallarías si solo unieras por nombre.
- **3 tablas de hechos en lugar de una.** Cada fuente mide cosas distintas (salarios, rating WhoScored, stats FBref). Mantenerlas separadas permite usar `CROSSFILTER` y `USERELATIONSHIP` en DAX, y las relaciones de Power BI se mantienen limpias (cada relación uno-a-muchos desde dim_jugador con cardinalidad correcta).

## 3. Pasos del ETL (lo que hace el script)

1. **Carga las 4 fuentes** y consolida los dos archivos de Salarios.
2. **Limpia errores de scraping** en Rating: parchea los 5 patrones detectados (Saint-Etienne, St Pauli, RB Leipzig, PSG, Parma).
3. **Construye dim_liga** (5 filas) con código, país y URL del logo. La unión de `logos.xlsx` se hace acá por la columna `Liga`.
4. **Construye dim_temporada** (4 filas: 22-23 a 25-26) con AnioInicio/AnioFin para cálculos de tiempo en DAX.
5. **Construye dim_club** (125 filas) con el mapeo manual de aliases. Esto requirió revisar las 5 ligas × 3-4 temporadas. Es la parte tediosa pero crítica.
6. **Resuelve la liga "Desconocida"** en Salarios 25-26 mirando el club (los 40 clubes son exactamente La Liga + Serie A).
7. **Asigna ClubID** a cada fact por join en `(nombre_normalizado, liga)`.
8. **Construye dim_jugador** con clave compuesta y le asigna `PlayerID` único.
9. **Limpia formato** del campo `apps` en Rating (`"31(7)"` → `Starts=31, SubsIn=7, TotalApps=38`).
10. **Exporta** todo como CSVs individuales y como Excel multi-hoja.

## 4. Resultado del matching

| Tabla | Filas | Sin ClubID | Sin PlayerID |
|---|---|---|---|
| fact_salarios | 10,785 | 0 | 0 |
| fact_rating | 8,608 | 0 | 0 |
| fact_rendimiento | 10,209 | 0 | 0 |

**100% de cobertura.** Los 14,631 registros de jugador-club-temporada están todos vinculados.

Cobertura cruzada (cuántos jugadores aparecen en varias fuentes):
- En Salarios ∩ Rating: 6,548
- En Salarios ∩ Rendimiento: 6,910
- En las 3 fuentes: 6,197

La diferencia es esperada: Rating solo trae jugadores con suficientes minutos, Rendimiento es muy granular (incluye todos los rosters), Salarios filtra por contratos disponibles públicamente.

## 5. Cargar a Power BI

**Opción A (recomendada):** importa los 7 CSVs uno por uno. Power BI los detectará bien porque los IDs son enteros.

**Opción B:** importa el archivo `modelo_powerbi.xlsx` y selecciona las 7 hojas.

### Relaciones a crear en Power BI (vista Modelo):

| Desde (lado N) | Columna | Hacia (lado 1) | Columna | Cardinalidad |
|---|---|---|---|---|
| fact_salarios | PlayerID | dim_jugador | PlayerID | N:1 |
| fact_salarios | ClubID | dim_club | ClubID | N:1 |
| fact_salarios | LigaID | dim_liga | LigaID | N:1 |
| fact_salarios | TemporadaID | dim_temporada | TemporadaID | N:1 |
| fact_rating | PlayerID | dim_jugador | PlayerID | N:1 |
| fact_rating | ClubID | dim_club | ClubID | N:1 |
| fact_rating | LigaID | dim_liga | LigaID | N:1 |
| fact_rating | TemporadaID | dim_temporada | TemporadaID | N:1 |
| fact_rendimiento | PlayerID | dim_jugador | PlayerID | N:1 |
| fact_rendimiento | ClubID | dim_club | ClubID | N:1 |
| fact_rendimiento | LigaID | dim_liga | LigaID | N:1 |
| fact_rendimiento | TemporadaID | dim_temporada | TemporadaID | N:1 |
| dim_club | LigaID | dim_liga | LigaID | N:1 |

**Importante:** todas las relaciones son uni-direccional (single). No actives bi-direccional salvo que tengas un caso muy específico, suele introducir loops.

### Para mostrar logos en visuales:
En `dim_liga`, marca la columna `LogoURL` como **Categoría de datos: URL de imagen** (Modelado → Categoría de datos).

## 6. Ideas de medidas DAX

```dax
// Salario total por temporada-club
Salario Total := SUM(fact_salarios[Net_Total_PY_USD])

// Costo por gol (cruza salarios con rendimiento)
Costo Por Gol := 
DIVIDE(
    [Salario Total],
    SUM(fact_rendimiento[Goals])
)

// Rating ponderado por minutos
Rating Ponderado := 
DIVIDE(
    SUMX(fact_rating, fact_rating[Rating] * fact_rating[Mins]),
    SUM(fact_rating[Mins])
)

// Promedio salarial liga (para benchmarks)
Salario Promedio Liga := 
CALCULATE(
    AVERAGE(fact_salarios[Net_Total_PY_USD]),
    ALLEXCEPT(fact_salarios, fact_salarios[LigaID], fact_salarios[TemporadaID])
)
```

## 7. Sugerencias de análisis para el dashboard

Con estos datos saldrían dashboards interesantes:

1. **Eficiencia salarial por liga** (scatter plot: salario total vs goles, una burbuja por jugador, color por liga). En la prueba que corrí, Jørgen Strand Larsen del Celta cuesta $21k por gol, mientras Vinícius cuesta $1.3M por gol — gran narrativa.
2. **Inflación salarial 22-26**: usa `Adj_Net_Total_PY_2026` para comparar a precios constantes.
3. **Top 10 fichajes con peor ROI** (alto salario, bajo rating).
4. **Distribución salarial por posición y liga** (boxplot).
5. **Edad vs salario**: ¿quién paga más por veteranos vs jóvenes?

## 8. Limitaciones honestas del modelo

- **Jugadores en mid-season transfers**: si un jugador cambió de club en la misma temporada (ej. enero), tendrás dos `PlayerID` distintos. Es lo correcto técnicamente, pero al analizar "carrera del jugador" tendrás que agrupar. Si necesitas una identidad estable de jugador, podemos crear un `PersonID` adicional usando solo el nombre normalizado.
- **Nombres muy similares**: Sergio García (hay 2-3) podrían colisionar si juegan en el mismo club-temporada. No vi casos en este dataset, pero está la posibilidad.
- **`Adj_Net_Total_PY_2026` para 25-26** lo igualé al `Net_Total_PY_USD` (ya está en términos 2026). Si el factor de ajuste en años pasados sale de un cálculo específico, puedes recalcular.
- **Rating y Rendimiento solo van hasta 24-25** (no hay 25-26 todavía). El dashboard mostrará 25-26 solo con datos de salario.

## 9. Archivos entregados

- `etl_pipeline.py` — script reproducible. Si actualizas las fuentes, lo corres y se regenera todo.
- `dim_liga.csv`, `dim_temporada.csv`, `dim_club.csv`, `dim_jugador.csv`
- `fact_salarios.csv`, `fact_rating.csv`, `fact_rendimiento.csv`
- `modelo_powerbi.xlsx` — todo lo anterior en un solo Excel
