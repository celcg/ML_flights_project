# ML Flights Project

Proyecto de machine learning para predecir el **retraso de llegada 60 minutos
antes de la salida programada**. El objetivo actual es obtener una predicción
útil antes de la operación, sin introducir datos que todavía no serían
conocidos en ese momento.

La población de modelado se limita a vuelos comerciales regulares
(`ICAO Flight Type = S`). La meteorología se ha aplazado: primero se valida el
valor de los datos de vuelo, el histórico operativo reciente y la rotación de
la aeronave.

## Estado actual

- Pipeline temporal sin leakage para la tarea `arrival_pre` a T-60.
- Train hasta septiembre de 2022; validación en diciembre de 2022; test final
  de marzo de 2023 todavía intacto.
- Variables operativas observables en ventanas de 1, 6 y 24 horas; la ablación
  retiene 1 y 24 horas y elimina 6 horas.
- Modelos comparados: Ridge, Random Forest, Gradient-Boosted Trees, XGBoost y
  CatBoost, además de baselines históricos y un ensemble Ridge + CatBoost.
- Ridge es la elección actual por su mejor equilibrio entre vuelos generales y
  vuelos con retrasos elevados, además de su bajo consumo de memoria.

### Resultados principales

Comparación homogénea sobre las mismas 29.315 filas de validación y usando un
10% determinista de train para Ridge y el baseline comparable:

| Métrica (minutos) | Baseline histórico | Ridge T-60 | Mejora |
|---|---:|---:|---:|
| MAE global | 10,45 | 9,94 | 4,8% |
| RMSE global | 15,83 | 14,80 | 6,5% |
| MAE en vuelos con retraso >15 min | 22,68 | 18,21 | 19,7% |
| RMSE en vuelos con retraso >15 min | 29,77 | 25,88 | 13,1% |

El RMSE global de Ridge al 10% es **14,80 minutos**, frente a **15,83 minutos**
del baseline comparable: una reducción de **1,03 minutos (6,5%)**. CatBoost obtiene un resultado
global ligeramente mejor, pero Ridge gana el criterio acordado que pondera al
50% el MAE global y el MAE de los vuelos con retrasos elevados.

## Datos

Los vuelos proceden del **EUROCONTROL Aviation Data Repository for Research**.
Por restricciones de licencia, los datos reales no se distribuyen con el
repositorio.

1. Registrarse en OneSky Online y aceptar las condiciones de EUROCONTROL.
2. Descargar y extraer los ficheros de vuelos.
3. Colocarlos en `data/raw/flights/`.
4. Ejecutar las notebooks en el orden indicado más abajo.

La incorporación de más meses/años tiene prioridad sobre la meteorología porque
mejora la cobertura de estacionalidad, rutas y eventos de retraso poco frecuentes.
METAR queda como enriquecimiento posterior una vez fijada una referencia sólida.

## Flujo de notebooks

Ejecutar desde `notebooks/`:

1. `01_initial_analysis_sample.ipynb`: contrato de datos y exploración inicial.
2. `02_numeric_data_profiling.ipynb`: perfil numérico, calidad y transformaciones
   opcionales log/Yeo-Johnson aprendidas solo con train.
3. `03_non_numeric_data_analysis.ipynb`: integridad de dimensiones, cobertura,
   cardinalidad y decisiones de codificación categórica.
4. `04_cleaning_pyspark.ipynb`: limpieza completa y generación de variables con
   PySpark.
5. `05_arrival_pre_baselines.ipynb`: mediana global, ruta y ruta+aerolínea con
   fallbacks y métricas segmentadas.
6. `06_arrival_pre_model_benchmark.ipynb`: benchmark de Ridge, Random Forest,
   GBT y XGBoost con configuración de memoria reducida.
7. `07_arrival_pre_aligned_validation.ipynb`: CatBoost, curva 1/5/10% y selección
   sobre una validación idéntica.
8. `08_arrival_pre_t60_operational_features.ipynb`: variables observables T-60,
   rotación previa, auditoría de leakage, ablación y ensemble.
9. `09_business_aviation_analysis.ipynb`: informe analítico de negocio en inglés
   sobre demanda, fiabilidad de rutas y operadores, franjas horarias,
   recuperación de retrasos, correlaciones y pruebas estadísticas. Excluye marzo
   de 2023 para conservar el test ciego.

La notebook 03 exploratoria original se conserva en
`archive/03_non_numeric_data_analysis_original.ipynb`.

## Variables principales

- Duración programada, mes, hora y día codificados de forma cíclica y nivel de
  vuelo solicitado.
- Conteo, media, desviación y proporción de retrasos ya observados por origen,
  destino, ruta y operador en ventanas anteriores al horizonte T-60.
- Retraso de llegada/salida de la rotación anterior, minutos desde la llegada
  previa y disponibilidad de la aeronave.
- One-hot para categorías de cardinalidad baja.
- Agrupación de tipos de aeronave raros como `OTHER` y hashing para AC Type,
  aeropuertos y operador.
- Imputación y cualquier transformación ajustadas exclusivamente con train.

La auditoría temporal verifica que ninguna observación posterior a T-60 entra en
las variables; también elimina la contribución del propio vuelo cuando coincide
con el grupo agregado.

## Experimento de escalado al 25%

`scripts/run_t60_25pct.py` mantiene congelados el conjunto de variables, el hash
de 32.768 posiciones y `Ridge(alpha=10)`. Ajusta únicamente Ridge y el baseline
comparable para medir si añadir filas compensa, sin retocar la validación ni leer
test. Los resultados se escriben por separado bajo:

- `data/processed/model/arrival_pre_t60_ops_25pct/`
- `reports/09_t60_25pct_*`
- `models/09_*_25pct.*`

Desde la raíz del proyecto:

```powershell
python scripts\run_t60_25pct.py
```

En este equipo, el ejecutable de `.venv313` puede ser rechazado por el punto de
reanálisis de OneDrive. El comando validado es:

```powershell
& 'C:\Users\celti\AppData\Local\Programs\Python\Python313\python.exe' scripts\run_t60_25pct.py
```

El experimento ya ejecutado contiene **613.884 vuelos de train**. Ridge obtiene
MAE **9,892** y RMSE **14,749**; frente al 10%, mejora solo **0,049 min** en MAE
y **0,049 min** en RMSE. El criterio combinado mejora **0,027 min** (unos 1,6
segundos), muy por debajo del umbral de 0,20. La decisión es **no escalar todavía
a 50%/100% con las mismas variables**: conviene priorizar nuevos periodos y
señales antes de gastar más recursos.

Se recomienda cerrar navegador, VS Code, Word, Joplin y otras aplicaciones hasta
disponer de **4-5 GB de RAM libre**. El preflight detiene el proceso si hay menos
de 1,5 GB para evitar bloquear Windows. Esta regla se conserva para futuras
reproducciones del experimento.

## Entorno técnico

- Python 3.13
- PySpark 4.2
- pandas, NumPy, PyArrow y scikit-learn
- XGBoost y CatBoost
- JupyterLab / nbformat

El procesamiento local usa PySpark, pero **no usa un clúster Hadoop ni HDFS**.
En Windows, `create_spark` compila un adaptador pequeño para el sistema de
archivos local que permite escribir Parquet sin instalar `winutils.exe`.
Parquet se utiliza porque conserva tipos, comprime mejor y permite leer solo las
columnas necesarias durante el entrenamiento.

## Estructura relevante

```text
ML_flights_project/
|-- data/                 # datos locales; no versionados
|-- doc/                  # informes Word
|-- models/               # modelos entrenados
|-- notebooks/            # flujo 01-08 y README operativo
|-- reports/              # métricas, auditorías y predicciones
|-- scripts/              # runners y utilidades reproducibles
|-- src/
|   |-- flight_config.py
|   `-- spark_flight_pipeline.py
|-- tests/
|-- README.md
`-- requirements.txt
```

## Instalación

La configuración validada localmente usa Python 3.13:

```powershell
python -m venv .venv313
.\.venv313\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Para los detalles de ejecución y decisiones compartidas, consultar
`notebooks/README.md`.

## Dataset mensual ampliado

El catálogo descubre nueve cortes entre junio de 2021 y junio de 2023 y elige
un único archivo canónico por mes. La auditoría completa cubre 6.099.999 vuelos:
todos conservan el mismo esquema de 18 columnas y ninguna diferencia de nulos
entre datos nuevos y de referencia supera dos puntos porcentuales. La mayor es
AC Registration, con solo +0,046 puntos.

Las notebooks 10 y 11 implementan el nuevo flujo. Diciembre de 2022 se mantiene
como validación, marzo de 2023 como primer test bloqueado y junio de 2023 como
segundo test futuro. La notebook 09 puede usar los nueve meses con fines
descriptivos, pero sus resultados no entran en el ajuste de modelos.
