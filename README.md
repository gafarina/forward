# Valorizador de Forwards FX USD/CLP

Sistema de valorización a valor razonable de contratos forward de tipo de cambio
contra pesos chilenos, con descomposición contable, sensibilidades, ajuste por
riesgo de crédito y escenarios de estrés.

Reproduce **al centavo** la planilla operativa
`CalculadoraForward Cordada_v2.xlsm` y corrige los defectos metodológicos y de
seguridad del sistema anterior, documentados uno a uno en
[`docs/AUDITORIA.md`](docs/AUDITORIA.md).

---

> ## ⚠️ Advertencia de seguridad sobre el repositorio original
>
> **El repositorio [`github.com/gafarina/forward`](https://github.com/gafarina/forward)
> es público y contiene una clave de API de Google Gemini válida, versionada en
> el archivo `.env`.** También contiene la base de datos `db.sqlite3` con
> contrapartes, nocionales y el hash de la contraseña del superusuario, y el
> libro Excel de 3 MB con la cartera real de forwards vigentes.
>
> La credencial debe considerarse **comprometida**. Los repositorios públicos de
> GitHub son rastreados por robots que extraen claves de API en minutos.
>
> ### Pasos de remediación, en este orden
>
> **1. Revocar la clave de Gemini.** En
> [Google AI Studio](https://aistudio.google.com/apikey) o en la consola de
> Google Cloud, eliminar la clave `AIzaSy…` (no basta con restringirla), generar
> una nueva y revisar la facturación desde el 2026-08-06 en busca de consumo no
> autorizado.
>
> **2. Rotar el resto de las credenciales.** Cambiar la contraseña del usuario
> `admin` y generar una `SECRET_KEY` nueva: la del repositorio
> (`django-insecure-default-secret-key-for-dev`) es pública y permite falsificar
> sesiones y tokens de recuperación de contraseña.
>
> ```bash
> python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
> ```
>
> **3. Purgar el historial de git.**
>
> ```bash
> pip install git-filter-repo
> git clone --mirror https://github.com/gafarina/forward.git forward-limpio.git
> cd forward-limpio.git
> cp -r . ../forward-respaldo.git                    # respaldo antes de tocar nada
>
> git filter-repo --force --invert-paths \
>   --path .env \
>   --path db.sqlite3 \
>   --path "06052026 CalculadoraForward Cordada_v2.xlsm" \
>   --path contratos.xlsx --path contrato_test.xlsx \
>   --path curvas_descuento.xlsx --path curvas_descuento_v2.xlsx \
>   --path curva_test_forward_2.xlsx --path test_curvas_fwd.xlsx \
>   --path-glob '*.pyc' --path-glob '__pycache__/*'
>
> git remote add origin https://github.com/gafarina/forward.git
> git push --force --mirror origin
> ```
>
> Después: solicitar a GitHub la purga de la caché de objetos huérfanos, y pedir
> a cualquier colaborador que **reclone** (un `git pull` sobre un clon antiguo
> reintroduce el historial purgado).
>
> **4. Impedir la reincidencia.** Crear `.gitignore` y `.dockerignore`, y activar
> *Secret scanning* con *Push protection* en **Settings → Code security**.
>
> **5. Si hay un despliegue en línea con más de un usuario**, suspender el
> registro abierto: cualquier usuario autenticado puede leer y borrar la cartera
> de los demás (hallazgos **S-03** y **S-04** de la auditoría).
>
> Detalle completo con comandos verificados en
> [`docs/AUDITORIA.md` §5](docs/AUDITORIA.md#5-acciones-inmediatas-para-el-dueño-del-repositorio).

---

## Índice

1. [Qué resuelve](#1-qué-resuelve)
2. [Funcionalidades](#2-funcionalidades)
3. [Instalación local](#3-instalación-local)
4. [Despliegue con Docker](#4-despliegue-con-docker)
5. [Estructura del proyecto](#5-estructura-del-proyecto)
6. [Tests](#6-tests)
7. [El libro Excel](#7-el-libro-excel)
8. [Qué cambió respecto de v1](#8-qué-cambió-respecto-de-v1)
9. [Estado de implementación](#9-estado-de-implementación)
10. [Documentación](#10-documentación)

---

## 1. Qué resuelve

Una empresa que cubre exposición cambiaria con forwards USD/CLP necesita, cada
cierre:

- **Valorizar** la cartera a valor razonable contra las curvas de mercado del
  día.
- **Descomponer** el resultado en componente spot (reserva de cobertura en ORI)
  y puntos forward (costo de la cobertura), que es lo que exige la contabilidad
  de coberturas.
- **Medir sensibilidades**: cuánto cambia el valor si el dólar sube un peso, si
  las tasas suben un punto base, o si pasa un día.
- **Cuantificar el riesgo de crédito** de las contrapartes bancarias.
- **Correr escenarios** de estrés sobre el tipo de cambio y el diferencial de
  tasas.
- **Conciliar** contra la planilla operativa, al centavo, para poder distinguir
  un error de datos de un error de método.

Este sistema hace las seis cosas con un motor auditable de ~1.300 líneas que no
depende del framework web, y guarda cada corrida con la configuración
metodológica exacta con la que se produjo.

### El caso de referencia

Cartera de tres contratos por USD 5 millones, valorizada al 31-05-2026 con las
curvas del libro Cordada:

| Folio | Contraparte | Vcto | Días | Nocional | MtM del sistema | MtM de la planilla | Diferencia |
|---|---|---|---:|---:|---:|---:|---:|
| 756929 | BTG Pactual | 2026-07-07 | 37 | USD 1.000.000 | −5.096.628,95 | −5.096.628,95 | **0,00** |
| 118039 | Bice | 2026-07-13 | 43 | USD 2.000.000 | 2.592.812,56 | 2.592.812,56 | **0,00** |
| 116845 | Bice | 2026-06-12 | 12 | USD 2.000.000 | −4.346.625,78 | −4.346.625,78 | **0,00** |
| | | | | **USD 5.000.000** | **−6.850.442,17** | **−6.850.442,17** | **0,00** |

El sistema anterior producía −6.850.095,21, con una diferencia de 346,96 pesos
que provenía de extrapolar plano donde la planilla extrapola linealmente
(hallazgo **M-01**).

---

## 2. Funcionalidades

### Motor de valorización

| Área | Opciones |
|---|---|
| **Conteo de días** | ACT/360 · ACT/365 · 30/360 US (NASD) · 30E/360 (Eurobond) · ACT/ACT ISDA |
| **Interpolación** | Lineal · Log-lineal sobre factores de descuento · Escalonada |
| **Extrapolación** | Lineal (replica la planilla) · Plana · Puntos forward constantes |
| **Capitalización** | Compuesta · Simple · Continua |
| **Calendarios** | Chile (con reglas de traslado de las leyes 20.215 y 20.299, feriado bancario del 31-12) · EE.UU. · conjunto CL+US · sólo fines de semana |
| **Ajuste de fechas** | Exacto · Following · ModifiedFollowing · Preceding · ModifiedPreceding |

### Resultados por operación

MtM · componente spot · puntos forward · forward de mercado · tasa de descuento ·
factor de descuento · fracción de año · delta · delta 1 % · gamma (cero, por
linealidad) · DV01 · theta a un día · CVA · DVA · MtM ajustado por crédito ·
banderas de diagnóstico.

### Riesgo de crédito

Modelo de intensidad de default (`h = s/(1−R)`, supervivencia exponencial) con
exposición esperada en forma cerrada bajo Bachelier sobre el precio forward,
calculada sobre el conjunto de neteo por contraparte y asignada a cada operación
por su contribución. Spread y tasa de recuperación configurables **por
contraparte**.

### Escenarios

Matriz de revaluación completa cruzando desplazamientos del spot (que arrastran
la curva de outrights) contra desplazamientos de la curva forward.

### Diagnóstico

El motor marca cada línea con banderas explícitas en vez de calcular en
silencio: extrapolación fuera de rango (indicando el rango real), falta del
tipo de cambio al inicio, tasas fuera de rango razonable, posible confusión de
unidades entre porcentaje y fracción, contratos vencidos, vencimiento ajustado
por calendario.

### Datos

Carga del libro Cordada `.xlsm` con detección de hojas y columnas por patrón ·
importación de curvas y contratos desde CSV/Excel con informe de filas
descartadas · exportación a CSV y a Excel · asistente conversacional opcional
sobre metodología y cartera propia.

### Libro Excel con fórmulas vivas

`core/excel_model.py` replica el motor en **fórmulas nativas de Excel**: sin VBA,
sin macros y sin funciones definidas por el usuario. El archivo abre en Excel,
LibreOffice, Google Sheets o Numbers, y recalcula al cambiar cualquier celda de
entrada. Nueve hojas: Portada, Parámetros, Curvas, Contratos, Valorización,
Sensibilidad, Griegas, **Reconciliación** (compara las fórmulas de Excel contra
los valores que produjo el motor Python) y Metodología.

---

## 3. Instalación local

Requiere **Python 3.11 o superior**.

### Paso 1 — Obtener el código y crear el entorno

```bash
git clone <url-del-repositorio> forward_v2
cd forward_v2

python3 -m venv .venv
source .venv/bin/activate        # en Windows: .venv\Scripts\activate
```

### Paso 2 — Instalar dependencias

```bash
pip install --upgrade pip
pip install -r requirements.txt          # producción
pip install -r requirements-dev.txt      # + pytest, coverage, ruff
```

Dependencias de producción: Django 5.0-5.1, openpyxl, whitenoise, gunicorn,
python-dotenv y (opcional) google-generativeai. **El motor `core/` no tiene
dependencias externas**: sólo biblioteca estándar.

### Paso 3 — Configurar el entorno

```bash
cp .env.example .env
```

Editar `.env` y generar una `SECRET_KEY`:

```bash
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

`.env` mínimo para desarrollo:

```ini
SECRET_KEY=<la-clave-generada>
DEBUG=True
ALLOWED_HOSTS=localhost,127.0.0.1
```

Variables completas en [`.env.example`](.env.example) y en
[`docs/ARQUITECTURA.md` §7.1](docs/ARQUITECTURA.md#71-variables-de-entorno).

> `.env` está en `.gitignore` y **nunca debe versionarse**. Sin `SECRET_KEY` y
> con `DEBUG=False`, el proyecto se niega a arrancar en lugar de usar una clave
> por defecto conocida.

### Paso 4 — Migraciones

```bash
python manage.py migrate
```

### Paso 5 — Cargar el caso de demostración

```bash
python manage.py cargar_demo --usuario demo
```

Salida:

```
Usuario "demo" creado con clave: <clave-aleatoria-de-16-caracteres>
Demo cargada para "demo": 14 nodos de curva y 3 contratos nuevos (3 en total).
Valores de referencia de la planilla (extrapolación lineal, ACT/360, compuesta):
  756929  MTM -5.096.628,95   Componente spot -5.162.209,39
  118039  MTM  2.592.812,56   Componente spot  2.709.119,64
  116845  MTM -4.346.625,78   Componente spot -5.114.348,92
```

Opciones:

| Opción | Efecto |
|---|---|
| `--usuario NOMBRE` | Usuario propietario de los datos (por defecto `demo`) |
| `--clave CLAVE` | Contraseña. Si se omite, se genera aleatoria y se imprime |
| `--reset` | Borra los datos previos del usuario antes de cargar |

El comando crea: una cartera "Cordada", dos contrapartes con sus spreads de
crédito, el conjunto de curvas del 31-05-2026 (7 nodos forward + 7 de descuento)
y los tres contratos con su tipo de cambio al inicio correcto.

### Paso 6 — Usuario administrador (opcional)

```bash
python manage.py createsuperuser
```

### Paso 7 — Levantar el servidor

```bash
python manage.py runserver
```

Abrir <http://127.0.0.1:8000/> e ingresar con las credenciales del paso 5.

### Verificación rápida sin servidor

Para comprobar que el motor reproduce la planilla, sin levantar Django:

```bash
python3 - <<'EOF'
from datetime import date
from core.curves import Curve
from core.valuation import Contract, MarketData, PricingConfig, price_contract

FWD  = [(1,892.21),(2,892.205),(8,892.19),(15,892.13),(22,892.105),(31,892.06),(62,892.03)]
DESC = [(92,3.48231),(183,3.61177),(271,3.70649),(365,3.78017),(731,3.98414),
        (1096,4.24534),(1461,4.42915)]

market = MarketData(
    valuation_date=date(2026, 5, 31), spot=892.89,
    curves={'FWDUSDCLP': Curve('FWDUSDCLP', [x for x,_ in FWD],  [y for _,y in FWD]),
            'CLP423':    Curve('CLP423',    [x for x,_ in DESC], [y for _,y in DESC])},
)
config = PricingConfig(day_count='ACT/360', interp_method='Lineal',
                       extrap_method='Lineal', compounding='Compuesta')

c = Contract(notional=1_000_000, fwd_price=886.94, maturity_date=date(2026, 7, 7),
             side='Venta', spot_inicio=887.71, folio='756929')
r = price_contract(c, market, config)

print(f"tasa      {r['disc_rate']:.6f} %   (planilla 3.404065 %)")
print(f"factor    {r['disc_factor']:.10f} (planilla 0.9965655190)")
print(f"MtM       {r['mtm']:>16,.2f}  (planilla -5,096,628.95)")
print(f"comp spot {r['spot_component']:>16,.2f}  (planilla -5,162,209.39)")
print(f"puntos    {r['fwd_points']:>16,.2f}  (planilla     65,580.44)")
EOF
```

---

## 4. Despliegue con Docker

### Construcción y ejecución

```bash
cp .env.example .env
# editar .env: SECRET_KEY, DEBUG=False, ALLOWED_HOSTS con el dominio real

docker compose up --build -d
docker compose exec web python manage.py migrate
docker compose exec web python manage.py createsuperuser
```

La aplicación queda en <http://localhost:8080/>.

### Qué hace la imagen

- Base `python:3.12-slim`.
- Ejecuta como usuario **sin privilegios** `appuser` (uid 10001). El sistema
  anterior corría como `root`.
- `collectstatic` en tiempo de construcción, con WhiteNoise y compresión.
- `gunicorn` con 3 *workers*, tiempo límite de 120 s y logs de acceso a
  `stdout`.
- Comprobación de salud contra `/accounts/login/` cada 30 s.

### Antes de exponerlo a internet

- [ ] `DEBUG=False` y `SECRET_KEY` propia.
- [ ] `ALLOWED_HOSTS` con el dominio real, nunca `*`.
- [ ] HTTPS terminado en un proxy inverso. `SECURE_PROXY_SSL_HEADER` ya está
      configurado; agregar el dominio a `CSRF_TRUSTED_ORIGINS`.
- [ ] PostgreSQL en lugar de SQLite: `DATABASE_URL=postgresql://…` (requiere
      `pip install "psycopg[binary]"`).
- [ ] Backend de caché compartido (Redis/Memcached), para que los límites de
      intentos de login y de consultas al asistente funcionen entre *workers*.
- [ ] `python manage.py check --deploy` sin advertencias.
- [ ] **Crear `.dockerignore`** con `.env`, `db.sqlite3`, `.git` y
      `__pycache__`. El proyecto todavía no lo trae (pendiente **P-05**).
- [ ] Respaldo periódico de la base de datos, con prueba de restauración.

Detalle en
[`docs/ARQUITECTURA.md` §7](docs/ARQUITECTURA.md#7-despliegue).

---

## 5. Estructura del proyecto

```
forward_v2/
│
├── core/                          # ── MOTOR CUANTITATIVO ──
│   │                              #    Sin Django. Sólo biblioteca estándar.
│   │                              #    El mismo código alimenta la web, el
│   │                              #    Excel y los tests.
│   ├── valuation.py               # Contract, MarketData, PricingConfig
│   │                              # price_contract, price_portfolio
│   │                              # sensitivity_matrix, griegas por bump
│   ├── curves.py                  # Curve, DiscountCurve
│   │                              # interpolación (lineal, log-lineal, escalonada)
│   │                              # extrapolación (lineal, plana, puntos)
│   │                              # factores de descuento (compuesta/simple/continua)
│   ├── daycount.py                # ACT/360, ACT/365, 30/360 US, 30E/360, ACT/ACT
│   ├── calendars.py               # feriados CL (leyes 20.215 / 20.299 / 21.357),
│   │                              # feriados US, calendario conjunto, ajustes
│   ├── credit.py                  # CreditProfile, exposición esperada Bachelier,
│   │                              # CVA/DVA con neteo por contraparte
│   ├── excel_model.py             # réplica del motor en fórmulas nativas de Excel
│   │                              # (9 hojas, sin VBA ni macros)
│   └── tests/                     # 175 tests · no necesitan base de datos
│
├── config/                        # ── CONFIGURACIÓN DEL PROYECTO ──
│   ├── settings.py                # entorno, seguridad, base de datos, logging
│   ├── urls.py                    # URLs raíz
│   ├── wsgi.py  /  asgi.py
│
├── valorizador/                   # ── APLICACIÓN PRINCIPAL ──
│   ├── models.py                  # ConjuntoCurvas, PuntoCurva, Contraparte,
│   │                              # Cartera, ContratoForward,
│   │                              # ValorizacionGuardada, LineaValorizacion
│   │                              # + OwnedQuerySet.for_user (aislamiento)
│   ├── views.py                   # todas con @login_required y for_user
│   ├── forms.py                   # validación declarativa (ModelForm)
│   ├── urls.py                    # mapa de rutas
│   ├── admin.py                   # panel de administración
│   ├── context_processors.py      # flags a los templates
│   ├── services/
│   │   ├── importers.py           # CSV/Excel → dicts, con informe de errores
│   │   ├── cordada_excel.py       # libro .xlsm → curvas, spot, contratos
│   │   └── excel_export.py        # valorización guardada → .xlsx con fórmulas
│   ├── management/commands/
│   │   └── cargar_demo.py         # caso de referencia Cordada 31-05-2026
│   ├── templatetags/
│   │   └── format_tags.py         # formatos chilenos (miles con punto)
│   ├── templates/valorizador/     # 15 plantillas HTML
│   ├── static/valorizador/        # CSS + 3 módulos JS
│   ├── migrations/
│   └── tests/                     # 162 tests
│
├── accounts/                      # ── CUENTAS ──
│   ├── views.py                   # login con límite de intentos por IP
│   ├── urls.py
│   ├── templates/accounts/        # login, registro, perfil, cambio de clave
│   └── tests/                     # (pendiente P-06)
│
├── docs/
│   ├── METODOLOGIA.md             # producto, fórmulas, convenciones, límites
│   ├── ARQUITECTURA.md            # componentes, datos, flujos, seguridad
│   └── AUDITORIA.md               # informe sobre el repositorio original
│
├── scripts/
│   └── build_excel_model.py       # genera el libro plantilla desde la línea de comandos
│
├── data/                          # punto de montaje del volumen de Docker
│                                  # (docker-compose: sqlite-data:/app/data)
│
├── manage.py
├── requirements.txt
├── requirements-dev.txt
├── pytest.ini
├── Dockerfile
├── docker-compose.yml
├── .env.example                   # plantilla; .env NUNCA se versiona
├── .gitignore
└── README.md
```

### La regla de dependencias

```
core/  ←  services/  ←  views/  ←  templates/
  ↑          ↑
  │          └─  scripts/build_excel_model.py
  └─────────────  models.py (adaptadores to_core() y as_curves())
```

**Los cinco módulos de cálculo de `core/` no importan Django, no consultan la
base de datos y no conocen el concepto de usuario.** Verificable:

```bash
grep -rn "django" core/valuation.py core/curves.py core/daycount.py \
                  core/calendars.py core/credit.py core/__init__.py
# sin resultados
```

Es lo que permite que el mismo código produzca los números de la web, del libro
Excel, de la exportación y de los 175 tests del motor, sin ninguna
reimplementación paralela. La única excepción es `core/excel_model.py`, que
intenta leer las constantes de la demo desde Django y cae en una copia local si
no puede; está documentada en
[`docs/ARQUITECTURA.md` §2](docs/ARQUITECTURA.md#2-por-qué-core-es-independiente-de-django).

---

## 6. Tests

**337 tests, todos en verde.** El repositorio original no tenía ninguno
(hallazgo [R-02](docs/AUDITORIA.md#r-02--cero-tests)).

### Ejecución

```bash
pip install -r requirements-dev.txt

# Necesario una vez: el proyecto usa CompressedManifestStaticFilesStorage y
# los tests de vistas fallan sin el manifiesto de estáticos.
python manage.py collectstatic --noinput

pytest                                  # toda la suite
pytest core/tests -v                    # sólo el motor (sin base de datos)
pytest valorizador/tests/test_views.py  # sólo las vistas
pytest -k reconcilia                    # sólo la reconciliación
```

Salida esperada:

```
337 passed, 338 subtests passed in 22.16s
```

### Qué cubre

| Archivo | Tests | Área |
|---|---:|---|
| `core/tests/test_valuation.py` | 54 | MtM, descomposición, banderas, griegas, cartera, escenarios, **reconciliación Cordada** |
| `core/tests/test_curves.py` | 39 | Interpolación, extrapolación, factores de descuento, curvas degeneradas |
| `core/tests/test_calendars.py` | 33 | Feriados chilenos y de EE.UU., reglas de traslado, convenciones de ajuste |
| `core/tests/test_credit.py` | 25 | Exposición esperada, supervivencia, neteo, asignación por operación |
| `core/tests/test_daycount.py` | 24 | Las cinco convenciones y los casos donde difieren |
| `valorizador/tests/test_importers.py` | 48 | Parseo de números y fechas, informe de errores por fila |
| `valorizador/tests/test_views.py` | 45 | **Aislamiento por usuario**, flujo completo, filtros, validación |
| `valorizador/tests/test_models.py` | 26 | Restricciones, `for_user`, adaptadores `to_core` / `as_curves` |
| `valorizador/tests/test_commands.py` | 17 | `cargar_demo` y sus valores de referencia |
| `valorizador/tests/test_cordada_excel.py` | 13 | Lectura del libro por patrón y por encabezado |
| `valorizador/tests/test_format_tags.py` | 13 | Formatos chilenos |
| | **337** | 175 en el motor, 162 en la aplicación |

Los 175 tests de `core/tests/` **no necesitan base de datos** ni el marcador
`@pytest.mark.django_db`: el motor recibe *dataclasses* y devuelve diccionarios.
Es el beneficio directo de haberlo separado de Django.

`accounts/tests/` sigue vacío: el límite de intentos de login no tiene cobertura
propia (pendiente **P-06**).

### Cobertura y análisis estático

```bash
coverage run -m pytest
coverage report -m
coverage html && open htmlcov/index.html

ruff check .
ruff format --check .
```

---

## 7. El libro Excel

### Cargar el libro Cordada

Desde la interfaz: **Cargar libro** → seleccionar el `.xlsm` → confirmar.

El lector (`valorizador/services/cordada_excel.py`) extrae:

| Dato | Origen | Método de localización |
|---|---|---|
| Fecha de valorización | Hoja *Forwards Cordada …* | Búsqueda de la etiqueta "Fecha" en las primeras filas |
| Tipo de cambio de valorización | Columna *Tipo de Cambio Fecha valoración* | Por encabezado |
| Curvas | Hoja *CURVE MASTER* | Pares de columnas `dia_X` / `c_X`, todos los que existan |
| Contratos vigentes | Hoja *FWD Vigentes …* | Columnas por encabezado, no por posición |
| **Tipo de cambio al inicio** | Columna *Tipo de Cambio al Inicio del Contrato*, mapeado **por folio** | Por encabezado |

A diferencia del cargador anterior, las hojas se localizan por patrón (no por el
nombre exacto que incluye el día del mes) y las columnas por encabezado (no por
índice posicional). Cada cosa que no se encuentra genera un aviso visible en
lugar de fallar en silencio.

Verificado sobre el libro real: extrae la fecha 2026-05-31, el spot 892,89, dos
curvas con 28 y 18 nodos, y los tres contratos con su spot al inicio correcto
(887,71 / 894,25 / 890,33).

> **Por qué importa el spot al inicio.** El cargador anterior asignaba a todos
> los contratos el spot de la fecha de valorización, con lo que el componente
> spot quedaba idénticamente en cero y el 100 % del resultado se clasificaba
> como puntos forward. Hallazgo **M-06**.

### Generar el libro Excel

`core/excel_model.py` construye un `.xlsx` **con fórmulas vivas**: salvo los
datos de entrada y las columnas de referencia de la hoja *Reconciliación*, todo
lo demás son fórmulas nativas que se recalculan al cambiar cualquier celda.

```bash
# Libro con el caso de referencia Cordada 31-05-2026
python scripts/build_excel_model.py --desde-demo --salida ./Valorizador_Forwards.xlsx

# Libro en blanco: 60 nodos por curva y 100 filas de contratos,
# todas con las fórmulas ya escritas
python scripts/build_excel_model.py --salida ./plantilla.xlsx

# Con datos propios desde CSV
python scripts/build_excel_model.py \
    --curva-fwd fwd.csv --curva-desc desc.csv --contratos ops.csv \
    --fecha 2026-05-31 --spot 892.89 --extrapolacion Lineal

# Sólo algunas hojas
python scripts/build_excel_model.py --desde-demo \
    --hojas Parámetros,Curvas,Contratos,Valorización
```

Salida de la primera variante:

```
Libro generado: ./Valorizador_Forwards.xlsx
  versión del modelo   : 2.0
  fecha de valorización: 2026-05-31
  spot                 : 892.89
  nodos forward        : 7
  nodos descuento      : 7
  contratos            : 3 (filas preparadas: 100)
  extrapolación        : Lineal | base anual: 360
  referencia del motor Python (para la hoja Reconciliación):
      756929  d=  37  F=892.054194  tasa=3.404065  MtM=-5,096,628.95  spot=-5,162,209.39
      118039  d=  43  F=892.048387  tasa=3.412601  MtM=2,592,812.56  spot=2,709,119.64
      116845  d=  12  F=892.155714  tasa=3.368499  MtM=-4,346,625.78  spot=-5,114,348.92
```

**Hojas del libro:**

| Hoja | Contenido |
|---|---|
| **Portada** | Índice, parámetros de la corrida y advertencias |
| **Parámetros** | Fecha, spot, base anual, extrapolación, capitalización (celdas de entrada) |
| **Curvas** | Nodos de outrights y de descuento, con 60 filas reservadas por curva |
| **Contratos** | Cartera, con 100 filas preparadas |
| **Valorización** | MtM, componente spot, puntos forward, tasa, factor — todo en fórmula |
| **Sensibilidad** | Matriz de escenarios spot × curva |
| **Griegas** | Delta, DV01, theta |
| **Reconciliación** | Fórmulas de Excel contra los valores del motor Python, celda por celda |
| **Metodología** | Resumen de las convenciones aplicadas |

La interpolación y la extrapolación se resuelven con una sola expresión nativa,
localizando el nodo inferior con `COUNTIF` en vez de `MATCH` (que sobre un rango
con celdas vacías al final devuelve resultados dependientes de la
implementación):

```
k = MAX(1; MIN(n−1; COUNTIF(dias; "<=" & x)))
y = INDEX(val;k) + (x − INDEX(dias;k)) · (INDEX(val;k+1) − INDEX(val;k))
                                        / (INDEX(dias;k+1) − INDEX(dias;k))
```

La extrapolación plana no necesita una segunda fórmula: basta acotar el plazo
consultado al rango de nodos con `MIN(MAX(x; x₁); xₙ)`.

### Exportar una valorización

Desde el detalle de una valorización guardada:

| Formato | Ruta |
|---|---|
| **CSV** | `/valorizaciones/<pk>/csv/` — UTF-8 con BOM y separador `;`, listo para Excel en español |
| **Excel** | `/valorizaciones/<pk>/xlsx/` — el mismo libro con fórmulas vivas, poblado con los datos de esa valorización |

`services/excel_export.py` y `scripts/build_excel_model.py` delegan ambos en
`core.excel_model`: la plantilla que se distribuye y el archivo que descarga un
usuario son el mismo modelo, con las mismas fórmulas. Cuando la configuración de
la valorización no se puede reproducir con fórmulas (por ejemplo capitalización
simple o continua), se informa como advertencia en la portada en lugar de
exportarse en silencio.

El CSV incluye por línea: folio, contraparte, cartera, operación, vencimiento,
monto, moneda, tipo de cambio al inicio, forward del contrato, días, fracción de
año, forward de mercado, tipo de cambio de valorización, tasa de descuento,
factor, MtM, MtM ajustado, componente spot, puntos forward, delta, DV01, theta y
CVA/DVA; más una fila de totales.

### Importar curvas o contratos desde CSV/Excel

**Contratos** → **Importar**, o desde el formulario de curvas, botón de
importación de nodos.

El importador reconoce encabezados en español e inglés, con y sin tildes, formato
numérico chileno (`1.234,56`) y anglosajón (`1,234.56`), fechas ISO, `dd/mm/aaaa`
y seriales de Excel. **Cada fila descartada se informa con su número de línea y
el motivo**, además de avisos de calidad de datos (por ejemplo, tasas que
parecen venir en fracción en lugar de porcentaje).

---

## 8. Qué cambió respecto de v1

Referencia completa con evidencia, citas de código e impacto cuantificado en
[`docs/AUDITORIA.md`](docs/AUDITORIA.md).

### Seguridad

| Antes (v1) | Ahora (v2) | Hallazgo |
|---|---|---|
| Clave de Gemini real versionada en `.env` | `.env` en `.gitignore`; sólo `.env.example` sin valores | [S-01](docs/AUDITORIA.md#s-01--clave-de-api-de-gemini-válida-publicada-en-env-versionado) |
| `api_chat` con `@csrf_exempt` y `@login_required` comentado | Sesión + CSRF + POST + 30 consultas/hora por usuario | [S-02](docs/AUDITORIA.md#s-02--endpoint-api_chat-abierto-a-internet) |
| Listados y exportaciones sin filtro por dueño | `OwnedQuerySet.for_user` en todas las consultas | [S-03](docs/AUDITORIA.md#s-03--fuga-de-datos-entre-usuarios) |
| Borrado y lectura de objetos ajenos por identificador | Filtro de dueño dentro de `get_object_or_404` (404, no 403) | [S-04](docs/AUDITORIA.md#s-04--acceso-y-borrado-de-objetos-ajenos-por-identificador) |
| `db.sqlite3` versionada con contrapartes y hash del superusuario | Excluida; el estado inicial se reproduce con `cargar_demo` | [S-05](docs/AUDITORIA.md#s-05--base-de-datos-versionada-con-datos-reales) |
| `DEBUG=True`, `ALLOWED_HOSTS=['*']`, `SECRET_KEY` conocida | `DEBUG=False` por defecto; sin `SECRET_KEY` no arranca; hosts del entorno | [S-06](docs/AUDITORIA.md#s-06--configuración-insegura-por-defecto) |
| Libro con cartera real de 3 MB versionado | No hay datos reales en el repositorio | [S-07](docs/AUDITORIA.md#s-07--libro-operativo-con-cartera-real-versionado) |
| Contenedor como `root` | Usuario `appuser` sin privilegios | [S-08](docs/AUDITORIA.md#s-08--contenedor-como-root-y-sin-dockerignore) |
| Activar curvas desactivaba las de todos los usuarios | Alcance limitado al propio usuario | [S-09](docs/AUDITORIA.md#s-09--estado-global-compartido-entre-usuarios) |
| Folios únicos globalmente: la carga de uno bloqueaba la de otro | Unicidad por usuario | [S-10](docs/AUDITORIA.md#s-10--deduplicación-global-de-folios) |
| `str(exception)` al cliente | Traza al log, mensaje genérico al usuario | [S-11](docs/AUDITORIA.md#s-11--detalle-de-excepciones-devuelto-al-cliente) |
| Sin límite de intentos de login | 10 intentos por IP en 15 minutos | [S-12](docs/AUDITORIA.md#s-12--sin-límite-de-intentos-de-inicio-de-sesión) |
| Sin límite efectivo de tamaño de archivo | `DATA_UPLOAD_MAX_MEMORY_SIZE` + validación de tamaño y extensión en el formulario | [S-13](docs/AUDITORIA.md#s-13--límite-de-tamaño-de-archivo-inexistente) |
| Sin `.gitignore`, 26 `.pyc` versionados | `.gitignore` completo desde el primer commit | [S-14](docs/AUDITORIA.md#s-14--archivos-compilados-versionados-y-sin-gitignore) |

### Metodología

| Antes (v1) | Ahora (v2) | Impacto medido | Hallazgo |
|---|---|---|---|
| Extrapolación plana en ambas curvas, sin aviso en el extremo corto | Tres políticas; lineal por defecto (replica la planilla); aviso en ambos extremos de ambas curvas | **+346,96 CLP** en 3 contratos por USD 5 M; reconciliación exacta con v2 | [M-01](docs/AUDITORIA.md#m-01--extrapolación-plana-donde-la-planilla-extrapola-linealmente) |
| "30/360" idéntica a ACT/360 | 30/360 US (NASD) y 30E/360 reales, más ACT/ACT ISDA | 950 CLP por millón a 92 días | [M-02](docs/AUDITORIA.md#m-02--convención-30360-declarada-pero-no-implementada) |
| Log-lineal nunca aplicada al descuento; devuelve basura con tasas negativas | Log-lineal sobre factores de descuento; tolera tasas cero o negativas | 6,31e-09 vs −0,040147 % en el caso negativo; hasta 2 pb en la curva real | [M-03](docs/AUDITORIA.md#m-03--interpolación-log-lineal-nunca-aplicada-al-descuento) |
| Días hábiles: sólo sábados y domingos | Feriados legales chilenos con reglas de traslado, feriado bancario, calendario CL+US | 6 de 6 feriados de 2026 tratados como hábiles por v1 | [M-04](docs/AUDITORIA.md#m-04--ajuste-de-días-hábiles-ignora-los-feriados-chilenos) |
| CVA = `50 pb × t × MtM_hoy`, sin neteo, contaminando el MtM | Intensidad de default + exposición esperada Bachelier + neteo por contraparte; `mtm` y `mtm_ajustado` separados | ATM: 0,00 vs 286.672,82; neteo evita +14,6 % de sobrestimación | [M-05](docs/AUDITORIA.md#m-05--cvadva-sin-exposición-esperada-sin-severidad-sin-neteo) |
| `spot_inicio` poblado con el spot de la fecha de valorización | Mapeado por folio desde la columna del libro; obligatorio en el formulario | 100 % del resultado mal clasificado en la descomposición contable | [M-06](docs/AUDITORIA.md#m-06--spot_inicio-poblado-con-el-spot-de-la-fecha-de-valorización) |
| Extrapolación plana de outrights (diferencial que colapsa a cero) | Documentado; política de puntos constantes disponible | 78 pb a 1.000 días entre políticas | [M-07](docs/AUDITORIA.md#m-07--extrapolación-plana-de-outrights-implica-diferencial-de-tasas-nulo) |
| Delta cerrado sin supuesto documentado; sin theta; "rho" mal nombrado | Todo por bump y revaluación; theta agregada; gamma declarada cero; DV01 con nombre correcto | Theta de −20.654,90 al día en la cartera, antes invisible | [M-08](docs/AUDITORIA.md#m-08--delta-sin-supuesto-documentado-sin-theta-rho-mal-nombrado) |
| Curvas sin ordenar ni deduplicar | Normalización en el constructor + restricción de unicidad | — | [M-09](docs/AUDITORIA.md#m-09--curvas-sin-ordenar-ni-deduplicar) |
| Convención desconocida caía en base 360 en silencio | Error explícito con la lista de convenciones válidas | — | [M-10](docs/AUDITORIA.md#m-10--convención-de-días-desconocida-cae-silenciosamente-en-base-360) |

### Robustez y calidad

| Antes (v1) | Ahora (v2) | Hallazgo |
|---|---|---|
| La carga del libro estaba **rota**: importaba tres modelos inexistentes | Lector autocontenido, verificado sobre el libro real | [R-01](docs/AUDITORIA.md#r-01--la-carga-del-libro-cordada-está-rota) |
| Cero tests | **337 tests en verde** (175 del motor, 162 de la aplicación) | [R-02](docs/AUDITORIA.md#r-02--cero-tests) |
| `if 'sensibilidad' in locals()` y variables sin asignar | Flujo explícito con formulario validado | [R-03](docs/AUDITORIA.md#r-03--if-sensibilidad-in-locals-y-variables-potencialmente-sin-asignar) |
| Importador descarta filas en silencio | Motivo y número de línea por fila descartada | [R-04](docs/AUDITORIA.md#r-04--el-importador-descarta-filas-en-silencio) |
| Nombres de hoja y celdas fijos (`B5`, `C1`, filas 2-29) | Localización por patrón y por encabezado | [R-05](docs/AUDITORIA.md#r-05--nombres-de-hoja-y-coordenadas-de-celda-fijos-en-el-código) |
| `request.POST['campo']` dentro de `except Exception` | `ModelForm` con validación declarativa + `CHECK` en la base de datos | [R-06](docs/AUDITORIA.md#r-06--lectura-de-requestpostcampo-sin-validación) |
| `requirements.txt` declaraba `google-genai`, el código usaba `google.generativeai` | Dependencia correcta, import local y opcional | [R-07](docs/AUDITORIA.md#r-07--la-dependencia-declarada-no-es-la-que-el-código-importa) |
| Sin índices de base de datos | Índices compuestos por `created_by` | [R-08](docs/AUDITORIA.md#r-08--sin-índices-de-base-de-datos) |
| Llamada a servicio externo dentro de la petición, sin caché | Eliminada; el spot se ingresa o viene del conjunto de curvas | [R-09](docs/AUDITORIA.md#r-09--llamada-a-servicio-externo-dentro-de-la-petición) |
| Archivo temporal no se borraba si fallaba | Bloque `finally` | [R-10](docs/AUDITORIA.md#r-10--archivo-temporal-no-se-elimina-si-ocurre-una-excepción) |
| `except:` desnudo | `JSONField` nativo, sin deserialización manual | [R-11](docs/AUDITORIA.md#r-11--except-desnudo) |
| NumPy para interpolar entre dos puntos | Sólo biblioteca estándar en `core/` | [R-12](docs/AUDITORIA.md#r-12--numpy-para-interpolar-linealmente-entre-dos-puntos) |

---

## 9. Estado de implementación

Verificado por ejecución.

| Componente | Estado |
|---|---|
| Motor `core/` (5 módulos de cálculo, 1.613 líneas) | **Completo.** Reconciliado al centavo contra el libro Cordada |
| `core/excel_model.py` (réplica en fórmulas de Excel, 9 hojas) | **Completo.** Verificado generando el libro |
| Modelos, migración inicial, panel de administración | **Completo.** `manage.py check` y `makemigrations --check` sin observaciones |
| Vistas, formularios, URLs | **Completo** |
| Plantillas HTML (21) y estáticos (CSS + 3 módulos JS) | **Completo** |
| Servicios de importación, lectura del libro y exportación | **Completo.** Verificados sobre el libro real |
| `scripts/build_excel_model.py` | **Completo** |
| Comando `cargar_demo` | **Completo.** Verificado en ejecución |
| Configuración, Dockerfile, docker-compose | **Completo** |
| Suite de tests | **Completo.** 337 tests, todos pasan |

### Pendientes conocidos

| ID | Pendiente |
|---|---|
| **P-01** | La extrapolación `"Puntos"` devuelve la misma expresión que `"Lineal"`: la opción existe pero todavía no se diferencia numéricamente |
| **P-05** | Falta `.dockerignore`: un `docker build` local copiaría `.env` y `db.sqlite3` a la imagen |
| **P-06** | `accounts/tests/` vacío: el límite de intentos de login no tiene cobertura propia |
| **P-07** | El libro generado `Valorizador_Forwards.xlsx` queda en la raíz y no está en `.gitignore` |

Detalle en
[`docs/AUDITORIA.md`](docs/AUDITORIA.md#pendientes-propios-de-forward_v2).

---

## 10. Documentación

| Documento | Contenido |
|---|---|
| [`docs/METODOLOGIA.md`](docs/METODOLOGIA.md) | Definición del producto y convención de signos · fórmula del MtM y su descomposición contable · construcción de curvas y paridad cubierta · interpolación y extrapolación con el análisis del caso Cordada · convenciones de conteo de días con las reglas exactas de 30/360 · descuento y capitalización · calendario chileno con base legal · sensibilidades · CVA/DVA · escenarios · supuestos y limitaciones declarados |
| [`docs/ARQUITECTURA.md`](docs/ARQUITECTURA.md) | Diagrama de componentes · por qué `core/` es independiente de Django · modelo entidad-relación · flujo de una valorización paso a paso · mapa de URLs · modelo de seguridad · despliegue · puntos de extensión |
| [`docs/AUDITORIA.md`](docs/AUDITORIA.md) | 37 hallazgos sobre el repositorio original, con evidencia, impacto cuantificado y resolución · pendientes propios de v2 · acciones inmediatas con comandos concretos |

---

## Licencia y uso

Sistema interno de valorización. Las cifras que produce son una herramienta de
cálculo y control: **no sustituyen la conciliación contra las confirmaciones de
las contrapartes ni el juicio contable**. Los supuestos y limitaciones del
modelo están declarados explícitamente en
[`docs/METODOLOGIA.md` §12](docs/METODOLOGIA.md#12-supuestos-y-limitaciones).
