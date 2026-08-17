# Arquitectura del sistema

Documento de arquitectura de **forward_v2**, el valorizador de forwards FX
USD/CLP. Describe los componentes, el modelo de datos, los flujos, el modelo de
seguridad y los puntos de extensión.

Para la metodología cuantitativa ver [`METODOLOGIA.md`](METODOLOGIA.md); para el
informe de auditoría del sistema anterior ver [`AUDITORIA.md`](AUDITORIA.md).

---

## Índice

1. [Vista general](#1-vista-general)
2. [Por qué `core/` es independiente de Django](#2-por-qué-core-es-independiente-de-django)
3. [Modelo de datos](#3-modelo-de-datos)
4. [Flujo de una valorización](#4-flujo-de-una-valorización)
5. [Mapa de URLs y responsabilidades](#5-mapa-de-urls-y-responsabilidades)
6. [Modelo de seguridad](#6-modelo-de-seguridad)
7. [Despliegue](#7-despliegue)
8. [Cómo extender el sistema](#8-cómo-extender-el-sistema)
9. [Estado de implementación](#9-estado-de-implementación)

---

## 1. Vista general

```mermaid
graph TB
    subgraph cliente["Cliente"]
        NAV["Navegador<br/>HTML + Chart.js"]
    end

    subgraph django["Capa web — Django 5"]
        URLS["config/urls.py<br/>valorizador/urls.py<br/>accounts/urls.py"]
        VIEWS["valorizador/views.py<br/>vistas con @login_required"]
        FORMS["valorizador/forms.py<br/>validación declarativa"]
        MODELS["valorizador/models.py<br/>ORM + OwnedQuerySet"]
        TPL["templates/<br/>+ templatetags/format_tags.py"]
        ACC["accounts/views.py<br/>login con límite de intentos"]
    end

    subgraph servicios["Servicios de aplicación"]
        IMP["services/importers.py<br/>CSV / Excel → dicts"]
        COR["services/cordada_excel.py<br/>libro .xlsm → curvas y contratos"]
        EXP["services/excel_export.py<br/>valorización → .xlsx"]
    end

    subgraph core["core/ — motor cuantitativo (sin Django)"]
        VAL["valuation.py<br/>Contract · MarketData · PricingConfig<br/>price_contract · price_portfolio<br/>sensitivity_matrix"]
        CUR["curves.py<br/>Curve · DiscountCurve<br/>interpolación y extrapolación"]
        DC["daycount.py<br/>ACT/360 · ACT/365 · 30/360<br/>30E/360 · ACT/ACT"]
        CAL["calendars.py<br/>feriados CL · US · CL+US<br/>convenciones de ajuste"]
        CRE["credit.py<br/>CreditProfile<br/>exposición esperada · CVA/DVA"]
        XLM["excel_model.py<br/>réplica del motor en<br/>fórmulas nativas de Excel"]
    end

    subgraph cli["Línea de comandos"]
        BLD["scripts/build_excel_model.py<br/>genera el libro plantilla"]
        DEMO["manage.py cargar_demo<br/>caso Cordada 31-05-2026"]
    end

    subgraph datos["Persistencia y externos"]
        DB[("SQLite / PostgreSQL")]
        XLS["Libro Cordada .xlsm"]
        GEM["API Gemini<br/>(asistente, opcional)"]
    end

    NAV -->|HTTPS| URLS
    URLS --> VIEWS
    URLS --> ACC
    VIEWS --> FORMS
    VIEWS --> MODELS
    VIEWS --> TPL
    VIEWS --> IMP
    VIEWS --> COR
    VIEWS --> EXP
    VIEWS -->|"to_core() / as_curves()"| VAL
    IMP --> MODELS
    COR --> MODELS
    XLS --> COR
    VAL --> CUR
    VAL --> DC
    VAL --> CAL
    VAL --> CRE
    CUR --> DC
    CRE --> CUR
    EXP --> XLM
    BLD --> XLM
    XLM --> VAL
    DEMO --> MODELS
    MODELS --> DB
    VIEWS -.->|"sólo si ASSISTANT_ENABLED"| GEM

    style core fill:#eef6ff,stroke:#3b6ea5,stroke-width:2px
    style django fill:#f7f7f7,stroke:#888
    style servicios fill:#fdf6ec,stroke:#c08a3e
    style cli fill:#f0f4ef,stroke:#5a7a52
```

### Capas y responsabilidades

| Capa | Directorio | Responsabilidad | Depende de |
|---|---|---|---|
| **Motor** | `core/` (módulos de cálculo) | Matemática financiera pura. Recibe estructuras planas, devuelve estructuras planas | Sólo la biblioteca estándar de Python |
| **Generador de Excel** | `core/excel_model.py` | Réplica del motor en fórmulas nativas de Excel | `openpyxl`, `core` |
| **Servicios** | `valorizador/services/` | Traducción entre formatos externos (Excel, CSV) y estructuras del dominio | `openpyxl`, `core` |
| **Web** | `valorizador/`, `accounts/` | HTTP, sesiones, autorización, persistencia, presentación | Django, `core`, servicios |
| **Configuración** | `config/` | Ajustes, URLs raíz, WSGI/ASGI | Django |

La dirección de las dependencias es estricta: **los cinco módulos de cálculo de
`core/` no importan nada de Django ni de las capas superiores**. Verificable:

```bash
grep -rn "django" core/valuation.py core/curves.py core/daycount.py \
                  core/calendars.py core/credit.py core/__init__.py
# sin resultados
```

**Única excepción, acotada y con respaldo.** `core/excel_model.py` intenta leer
las constantes del caso de demostración desde el comando de Django, y si no
puede usa una copia local idéntica:

```python
# core/excel_model.py
def _demo_constantes():
    """Intenta leer las constantes del comando de Django; si no, usa la copia local."""
    try:
        os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
        import django
        django.setup()
        from valorizador.management.commands import cargar_demo as cd
        return (list(cd.FWD_NODOS), list(cd.DESC_NODOS), list(cd.CONTRATOS),
                float(cd.SPOT_VALORIZACION), cd.FECHA_VALORIZACION)
    except Exception:
        return (list(_DEMO_FWD), list(_DEMO_DESC), list(_DEMO_CONTRATOS),
                _DEMO_SPOT, _DEMO_FECHA)
```

Afecta sólo a `demo_data()`, una función de conveniencia; ninguna fórmula ni
ningún cálculo depende de Django, y el generador funciona íntegramente sin él.

---

## 2. Por qué `core/` es independiente de Django

En el sistema anterior la lógica de valorización vivía en
`valorizador/services/valuation.py` y recibía **instancias de modelos Django**:

```python
# v1: valorizador/services/valuation.py
def valorizar_contrato(contrato, valuation_date, spot_val, curvas, config=None):
    ...
    fwd_contract = float(contrato.fwd_price)
    notional = float(contrato.notional)
    'cartera_nombre': contrato.cartera.nombre if contrato.cartera else '-',
```

Esa firma acopla la matemática a la base de datos. Para probar una fórmula hay
que levantar Django, migrar una base y crear registros; para usar el motor desde
un cuaderno de análisis o desde un script hay que hacer lo mismo.

En `forward_v2` el motor recibe *dataclasses* planas:

```python
# core/valuation.py
@dataclass
class Contract:
    notional: float
    fwd_price: float
    maturity_date: date
    side: str = "Venta"
    spot_inicio: float = 0.0
    ...
```

y el modelo Django provee un adaptador de una línea:

```python
# valorizador/models.py
def to_core(self):
    """Convierte a `core.Contract` para el motor."""
    from core.valuation import Contract
    return Contract(
        id=self.pk,
        notional=float(self.notional),
        fwd_price=float(self.fwd_price),
        maturity_date=self.maturity_date,
        ...
    )
```

```python
# valorizador/models.py
def as_curves(self) -> dict:
    """Convierte a objetos `core.Curve` listos para el motor."""
    from core.curves import Curve
    ...
```

### Qué se gana

| Beneficio | Detalle |
|---|---|
| **Un solo motor, cuatro consumidores** | La aplicación web, el generador del libro Excel, la exportación de una valorización y los 175 tests de `core/tests/` llaman exactamente al mismo `price_portfolio`. No hay una segunda implementación que se desincronice |
| **Tests sin base de datos** | Un test de convención de días o de extrapolación es una función pura: entra un `Contract` y un `MarketData`, sale un `dict`. No necesita migraciones, ni fixtures, ni transacciones. Los 175 tests de `core/tests/` corren sin Django |
| **Reconciliación reproducible** | El caso Cordada se puede correr desde un script de una página, sin servidor. Es lo que permite afirmar que la diferencia con la planilla es de 0,00 pesos |
| **La hoja Reconciliación del libro Excel** | El generador escribe en el `.xlsx` los valores que produjo el motor Python junto a las fórmulas nativas de Excel, de modo que el propio archivo compara ambos caminos celda por celda |
| **Auditabilidad** | Un revisor financiero puede leer los cinco módulos de cálculo (1.613 líneas en total) sin conocer Django |
| **Portabilidad** | El motor se puede empaquetar como biblioteca, exponer como API, o llamar desde un cuaderno Jupyter sin arrastrar el framework |
| **Sin dependencias pesadas** | Los módulos de cálculo usan sólo `math`, `datetime`, `bisect`, `dataclasses` y `functools`. El sistema anterior arrastraba NumPy para hacer una interpolación lineal de dos puntos |

### La regla que lo mantiene

> Los módulos de cálculo de `core/` no importan Django, no leen de la base de
> datos, no conocen el concepto de usuario y no formatean nada para pantalla. Si
> una función necesita cualquiera de esas cosas, no pertenece a `core/`.

El punto de contacto es unidireccional: los modelos conocen `core`, `core` no
conoce los modelos.

---

## 3. Modelo de datos

```mermaid
erDiagram
    USER ||--o{ CARTERA : "created_by"
    USER ||--o{ CONTRAPARTE : "created_by"
    USER ||--o{ CONTRATO_FORWARD : "created_by"
    USER ||--o{ CONJUNTO_CURVAS : "created_by"
    USER ||--o{ VALORIZACION_GUARDADA : "created_by"

    CARTERA ||--o{ CONTRATO_FORWARD : "agrupa (SET_NULL)"
    CONTRAPARTE ||--o{ CONTRATO_FORWARD : "ficha de crédito (SET_NULL)"

    CONJUNTO_CURVAS ||--o{ PUNTO_CURVA : "nodos (CASCADE)"
    CONJUNTO_CURVAS ||--o{ VALORIZACION_GUARDADA : "insumo (SET_NULL)"

    VALORIZACION_GUARDADA ||--o{ LINEA_VALORIZACION : "detalle (CASCADE)"
    CONTRATO_FORWARD ||--o{ LINEA_VALORIZACION : "origen (SET_NULL)"

    USER {
        int id PK
        string username UK
        string password "pbkdf2"
        bool is_staff
    }

    CARTERA {
        int id PK
        string nombre
        text descripcion
        int created_by FK
    }

    CONTRAPARTE {
        int id PK
        string nombre
        decimal spread_bp "CDS o proxy"
        decimal recovery "0-1"
        bool tiene_isda_neteo
        int created_by FK
    }

    CONJUNTO_CURVAS {
        int id PK
        string label
        date valuation_date
        decimal spot_usdclp
        string source
        bool is_active
        int created_by FK
    }

    PUNTO_CURVA {
        int id PK
        int conjunto FK
        string nombre "FWDUSDCLP CLP423 ..."
        int tenor_days
        decimal value
    }

    CONTRATO_FORWARD {
        int id PK
        int cartera FK "nullable"
        int contraparte_ref FK "nullable"
        string counterparty
        string folio
        string side "Compra Venta"
        string modality
        string base_ccy
        string quote_ccy
        decimal notional "CHECK gt 0"
        decimal fwd_price "CHECK gt 0"
        decimal spot_inicio "S0"
        date start_date "nullable"
        date maturity_date
        string fwd_curve
        string disc_curve
        string status
        int created_by FK
    }

    VALORIZACION_GUARDADA {
        int id PK
        date valuation_date
        string label
        int curve_set FK "nullable"
        decimal spot
        decimal total_mtm
        decimal total_mtm_ajustado
        decimal total_spot
        decimal total_fwdpoints
        decimal total_delta
        decimal total_dv01
        decimal total_cva
        decimal total_dva
        int num_contracts
        json config_json
        int created_by FK
    }

    LINEA_VALORIZACION {
        int id PK
        int valorizacion FK
        int contrato FK "nullable"
        string folio
        string counterparty
        string cartera_nombre
        date maturity_date
        decimal notional
        decimal spot_inicio
        decimal spot_val
        decimal fwd_contract
        decimal fwd_mkt
        int days_to_mat
        decimal year_fraction
        decimal disc_rate
        decimal disc_factor
        decimal mtm
        decimal mtm_ajustado
        decimal spot_component
        decimal fwd_points
        decimal delta
        decimal dv01
        decimal theta_1d
        decimal cva
        decimal dva
        json flags
    }
```

### Decisiones de diseño

**`created_by` es obligatorio y no nulo.** En el sistema anterior era
`null=True, on_delete=SET_NULL`, de modo que un objeto podía quedar sin dueño y
por lo tanto fuera de cualquier filtro por usuario. Aquí es
`on_delete=models.CASCADE` y sin `null=True`: todo objeto tiene dueño y borrar
el usuario borra sus datos.

```python
# valorizador/models.py
created_by = models.ForeignKey(
    settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='contratos'
)
```

**`OwnedQuerySet.for_user` centraliza el aislamiento.** En vez de repetir
`filter(created_by=request.user)` en cada vista (y olvidarlo en algunas, que es
exactamente lo que ocurrió en la v1), hay un único punto:

```python
# valorizador/models.py
class OwnedQuerySet(models.QuerySet):
    def for_user(self, user):
        """Filtra por dueño. El staff ve todo."""
        if user.is_staff:
            return self
        return self.filter(created_by=user)
```

**Unicidad por usuario, no global.** El folio, el nombre de cartera y el nombre
de contraparte son únicos dentro del espacio de cada usuario:

```python
# valorizador/models.py
constraints = [
    models.UniqueConstraint(
        fields=['created_by', 'nombre'], name='cartera_unica_por_usuario'
    )
]
```

Esto evita que la importación de un usuario bloquee la de otro por colisión de
folios, que era el comportamiento anterior.

**Invariantes en la base de datos, no sólo en el formulario.** Nocional y precio
positivos son restricciones `CHECK`:

```python
# valorizador/models.py
models.CheckConstraint(condition=models.Q(notional__gt=0), name='notional_positivo'),
models.CheckConstraint(condition=models.Q(fwd_price__gt=0), name='precio_fwd_positivo'),
```

Y un nodo de curva no puede repetir plazo dentro de la misma curva:

```python
models.UniqueConstraint(
    fields=['conjunto', 'nombre', 'tenor_days'], name='punto_unico_por_curva',
)
```

**Índices sobre los campos por los que efectivamente se filtra:**

```python
# valorizador/models.py
indexes = [models.Index(fields=['created_by', 'status', 'maturity_date'])]   # ContratoForward
indexes = [models.Index(fields=['created_by', '-valuation_date'])]           # ConjuntoCurvas
```

**`LineaValorizacion` es una fotografía inmutable.** Copia todos los valores
—incluidos `counterparty`, `cartera_nombre`, `spot_inicio`— en lugar de
depender de las relaciones. Si mañana se corrige el contrato o se borra la
cartera, la valorización histórica no cambia. La relación a `ContratoForward` es
`SET_NULL` precisamente para eso.

**`config_json` es `JSONField`, no `TextField`.** La configuración con la que se
corrió cada valorización queda consultable, que es el requisito de trazabilidad:
dos corridas del mismo día con distinta política de extrapolación dan números
distintos y hay que poder saber cuál fue cuál.

---

## 4. Flujo de una valorización

Desde que el usuario aprieta el botón hasta que la fila queda guardada.

```mermaid
sequenceDiagram
    autonumber
    actor U as Usuario
    participant V as views.valorizar
    participant F as ValorizarForm
    participant M as ORM
    participant C as core.price_portfolio
    participant S as core.sensitivity_matrix
    participant T as Template
    participant G as views.valorizar_guardar

    U->>V: POST /valorizar/ (+ token CSRF)
    V->>F: ValorizarForm(request.POST, user=request.user)
    Note over F: querysets de conjunto y cartera<br/>acotados a created_by=user
    F-->>V: is_valid() + cleaned_data

    V->>M: ContratoForward.objects.for_user(user)<br/>.filter(status='Vigente', base_ccy=moneda)
    M-->>V: contratos del usuario
    V->>V: filter(pk__in=selected_ids) sobre ese queryset
    Note over V: un id ajeno simplemente no aparece:<br/>el filtro de dueño va primero

    V->>M: conjunto.as_curves()
    M-->>V: dict[str, core.Curve]
    V->>V: MarketData(fecha, spot, curvas, etiqueta)
    V->>V: _build_config(cleaned_data) → PricingConfig

    V->>C: price_portfolio([c.to_core() ...], market, config)
    loop por contrato
        C->>C: ajustar vencimiento (calendario)
        C->>C: días corridos + fracción de año (convención)
        C->>C: F = curva_fwd.value(días)
        C->>C: r = curva_desc.zero_rate(días); DF = factor(días, t)
        C->>C: mtm, componente spot, puntos forward
        C->>C: delta, DV01, theta por bump; gamma = 0
        C->>C: banderas de extrapolación y de rango
    end
    opt calc_cva
        C->>C: agrupar por contraparte → cva_dva_netting_set
        C->>C: asignar CVA/DVA por contribución a la EPE
    end
    C-->>V: {lines, totals, por_contraparte, diagnostics, config}

    V->>S: sensitivity_matrix(contratos, market, config, shock_max)
    S-->>V: matriz de revaluación completa

    V->>T: render valorizar.html (result + result_json + sensibilidad)
    T-->>U: tabla, totales, mapa de escenarios

    U->>G: POST /valorizar/guardar/ (result_data JSON)
    G->>M: transaction.atomic()
    G->>M: ValorizacionGuardada.objects.create(..., created_by=user)
    G->>M: LineaValorizacion.objects.bulk_create([...])
    M-->>G: ok
    G-->>U: redirect a /valorizaciones/<pk>/
```

### Paso a paso

| # | Paso | Dónde | Detalle |
|---|---|---|---|
| 1 | Autenticación | `@login_required` | Sin sesión, redirección a `/accounts/login/` |
| 2 | Validación CSRF | `CsrfViewMiddleware` | Token obligatorio en todo POST |
| 3 | Validación del formulario | `ValorizarForm` | Tipos, rangos (`0 < shock ≤ 50 %`), pertenencia de las claves foráneas |
| 4 | Selección de contratos | `views.valorizar` | El filtro por dueño se aplica **antes** que el filtro por ids |
| 5 | Construcción del mercado | `ConjuntoCurvas.as_curves()` | Nodos → `core.Curve`, ordenados y deduplicados |
| 6 | Construcción de la configuración | `_build_config` | Convenciones + perfil de crédito |
| 7 | Valorización | `core.price_portfolio` | Contrato a contrato, luego CVA por conjunto de neteo |
| 8 | Escenarios | `core.sensitivity_matrix` | Revaluación completa de cada celda |
| 9 | Presentación | `valorizar.html` | El resultado viaja también como JSON en un campo oculto |
| 10 | Persistencia | `valorizar_guardar` | Cabecera + líneas dentro de una transacción |

### Por qué el resultado viaja al cliente y vuelve

El guardado no recalcula: recibe el JSON que ya se mostró. Esto garantiza que
**lo que se guarda es exactamente lo que el usuario vio**, sin riesgo de que un
cambio de curva entre la corrida y el guardado produzca una fila distinta de la
pantalla.

El costo es que el cliente puede alterar el JSON. La mitigación es que los datos
guardados no otorgan ningún privilegio ni afectan a otros usuarios: son un
registro propio. El `conjunto_id` sí se revalida contra el dueño antes de
asociarlo:

```python
# valorizador/views.py
conjunto = ConjuntoCurvas.objects.for_user(request.user).filter(pk=conjunto_id).first()
```

Si se quisiera eliminar por completo esa superficie, la alternativa es guardar
el resultado en la sesión o en una tabla temporal con un token de un solo uso.

### Contraste con el flujo anterior

En la v1 el mismo flujo tenía tres problemas estructurales:

```python
# v1: valorizador/views.py — selección sin filtro de dueño
selected_contracts = ContratoForward.objects.filter(pk__in=selected_ids)
```

```python
# v1: valorizador/views.py — paso de datos al template por introspección del scope
context = {
    ...
    'sensibilidad': getattr(request, '_sensibilidad', None)
}
if 'sensibilidad' in locals():
    context['sensibilidad'] = sensibilidad
```

```python
# v1: valorizador/views.py — lectura de parámetros sin validación
notional=Decimal(request.POST['notional']),
fwd_price=Decimal(request.POST['fwd_price']),
```

Ninguno de los tres sobrevive en `forward_v2`.

---

## 5. Mapa de URLs y responsabilidades

Raíz (`config/urls.py`):

| Prefijo | Incluye |
|---|---|
| `/admin/` | `django.contrib.admin` |
| `/accounts/` | `accounts.urls` |
| `/` | `valorizador.urls` |

### Cuentas (`accounts/urls.py`)

| Ruta | Vista | Método | Responsabilidad |
|---|---|---|---|
| `/accounts/login/` | `LoginRateLimitedView` | GET, POST | Inicio de sesión con límite de 10 intentos fallidos por IP en 15 minutos |
| `/accounts/logout/` | `LogoutView` | POST | Cierre de sesión |
| `/accounts/registro/` | `register` | GET, POST | Alta de usuario con `UserCreationForm` |
| `/accounts/perfil/` | `profile` | GET | Resumen de objetos propios |
| `/accounts/cambiar-clave/` | `PasswordChangeView` | GET, POST | Cambio de contraseña |
| `/accounts/cambiar-clave/listo/` | `PasswordChangeDoneView` | GET | Confirmación |

### Valorizador (`valorizador/urls.py`)

| Ruta | Vista | Método | Responsabilidad | Aislamiento |
|---|---|---|---|---|
| `/` | `dashboard` | GET | Panel: conteos, MtM por contraparte, curvas activas, perfil de vencimientos | `for_user` |
| `/curvas/` | `curvas_list` | GET | Listado de conjuntos de curvas | `for_user` |
| `/curvas/crear/` | `curvas_create` | GET, POST | Alta de conjunto + nodos | asigna `created_by` |
| `/curvas/<pk>/` | `curvas_detail` | GET | Gráfico de la curva, puntos forward implícitos, estadísticas | `for_user` |
| `/curvas/<pk>/editar/` | `curvas_edit` | GET, POST | Edición; reemplaza los nodos en una transacción | `for_user` |
| `/curvas/<pk>/eliminar/` | `curvas_delete` | **POST** | Borrado | `for_user` |
| `/curvas/<pk>/duplicar/` | `curvas_duplicate` | **POST** | Copia el conjunto y sus nodos | `for_user` |
| `/curvas/<pk>/activar/` | `curvas_activate` | **POST** | Marca el conjunto activo del usuario | `for_user` |
| `/curvas/importar-puntos/` | `curvas_import_points` | **POST** | AJAX: archivo → nodos + avisos por fila | validación de archivo |
| `/carteras/` | `carteras_list` | GET | Listado de carteras | `for_user` |
| `/carteras/crear/` | `cartera_create` | GET, POST | Alta de cartera | asigna `created_by` |
| `/carteras/<pk>/eliminar/` | `cartera_delete` | **POST** | Borrado; los contratos quedan sin cartera (`SET_NULL`) | `for_user` |
| `/contrapartes/` | `contrapartes_list` | GET, POST | Listado y alta de fichas de crédito | `for_user` |
| `/contratos/` | `contratos_list` | GET | Listado con filtros por estado, cartera y búsqueda de texto | `for_user` |
| `/contratos/crear/` | `contrato_create` | GET, POST | Alta validada por `ContratoForm` | asigna `created_by` |
| `/contratos/<pk>/editar/` | `contrato_edit` | GET, POST | Edición | `for_user` |
| `/contratos/<pk>/eliminar/` | `contrato_delete` | **POST** | Borrado | `for_user` |
| `/contratos/importar/` | `contratos_import` | GET, POST | Vista previa e importación masiva con informe de filas descartadas | `for_user` |
| `/contratos/exportar/` | `contratos_export_csv` | GET | Exportación CSV con BOM y separador `;` | `for_user` |
| `/valorizar/` | `valorizar` | GET, POST | Corrida de valorización y matriz de escenarios | `for_user` |
| `/valorizar/guardar/` | `valorizar_guardar` | **POST** | Persistencia de cabecera y líneas | asigna `created_by` |
| `/valorizaciones/` | `valorizaciones_list` | GET | Histórico | `for_user` |
| `/valorizaciones/<pk>/` | `valorizacion_detail` | GET | Detalle, totales de griegas, mapa de calor, resumen por contraparte | `for_user` |
| `/valorizaciones/<pk>/csv/` | `valorizacion_export_csv` | GET | Exportación CSV | `for_user` |
| `/valorizaciones/<pk>/xlsx/` | `valorizacion_export_xlsx` | GET | Exportación a Excel | `for_user` |
| `/valorizaciones/<pk>/eliminar/` | `valorizacion_delete` | **POST** | Borrado | `for_user` |
| `/cargar-libro/` | `upload_excel` | GET, POST | Carga del libro Cordada: crea conjunto de curvas y contratos | `for_user` |
| `/api/chat/` | `api_chat` | **POST** | Asistente sobre metodología y cartera propia | sesión + límite de frecuencia |

**Toda operación destructiva exige POST.** Las rutas marcadas con **POST** usan
`@require_POST`, de modo que no se pueden disparar con un `<img src>` ni con un
enlace, y el token CSRF es obligatorio.

---

## 6. Modelo de seguridad

### 6.1 Autenticación

- Backend estándar de Django (`django.contrib.auth`), contraseñas con PBKDF2-SHA256.
- Validadores de contraseña con **longitud mínima de 10** caracteres (el
  proyecto anterior usaba el default de 8):

```python
# config/settings.py
{'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
 'OPTIONS': {'min_length': 10}},
```

- **Límite de intentos de login por IP**, que el sistema anterior no tenía:

```python
# accounts/views.py
MAX_INTENTOS = 10
VENTANA_SEGUNDOS = 900

class LoginRateLimitedView(auth_views.LoginView):
    def post(self, request, *args, **kwargs):
        if cache.get(self._clave(), 0) >= MAX_INTENTOS:
            messages.error(request, 'Demasiados intentos fallidos. Espera unos minutos antes de reintentar.')
            return self.form_invalid(self.get_form())
        return super().post(request, *args, **kwargs)
```

La clave del contador considera `X-Forwarded-For` para funcionar detrás de un
proxy inverso. El backend de caché por defecto es en memoria del proceso: con
varios *workers* de gunicorn el límite es por proceso. Para un despliegue serio
conviene configurar Redis o Memcached como `CACHES['default']`.

### 6.2 Aislamiento por usuario

Es el control más importante del sistema, porque cada usuario ve datos
comercialmente sensibles: contrapartes, nocionales y precios pactados.

Tres capas:

1. **Modelo**: `created_by` obligatorio, `on_delete=CASCADE`.
2. **QuerySet**: `OwnedQuerySet.for_user(user)` como única forma de listar.
3. **Vista**: todo acceso por clave primaria usa
   `get_object_or_404(Modelo.objects.for_user(request.user), pk=pk)`, de modo
   que un identificador ajeno produce **404**, no 403 (no se filtra siquiera la
   existencia del objeto).

```python
# valorizador/views.py
contrato = get_object_or_404(ContratoForward.objects.for_user(request.user), pk=pk)
```

El personal marcado como `is_staff` ve todo, por diseño explícito y
documentado en el propio `OwnedQuerySet`.

**Estado global eliminado.** En el sistema anterior activar un conjunto de
curvas ejecutaba `ConjuntoCurvas.objects.update(is_active=False)` sobre **toda
la tabla**, desactivando el conjunto activo de los demás usuarios. Ahora el
alcance es el propio usuario:

```python
# valorizador/views.py
with transaction.atomic():
    ConjuntoCurvas.objects.filter(created_by=request.user).update(is_active=False)
    ConjuntoCurvas.objects.filter(pk=conjunto.pk).update(is_active=True)
```

### 6.3 CSRF y cabeceras

- `CsrfViewMiddleware` activo; **ningún endpoint usa `@csrf_exempt`**.
- El endpoint del asistente exige sesión, POST y token, al revés que el
  original.

```python
# config/settings.py
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = 'same-origin'
X_FRAME_OPTIONS = 'DENY'
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'
CSRF_COOKIE_SAMESITE = 'Lax'

if not DEBUG:
    SECURE_SSL_REDIRECT = env_bool('SECURE_SSL_REDIRECT', True)
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = int(env('SECURE_HSTS_SECONDS', 31536000))
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
```

`CSRF_TRUSTED_ORIGINS` se lee del entorno, necesario cuando la aplicación corre
detrás de un proxy con dominio propio.

### 6.4 Límites de frecuencia y de tamaño

**Asistente:** 30 consultas por usuario por hora, mensaje truncado a 4.000
caracteres, historial acotado a los últimos 10 turnos:

```python
# valorizador/views.py
clave = f'chat_rate_{request.user.pk}'
usados = cache.get(clave, 0)
if usados >= 30:
    return JsonResponse({'error': 'Alcanzaste el límite de consultas por hora.'}, status=429)
cache.set(clave, usados + 1, 3600)
```

**Cargas de archivo:** límite efectivo validado en el formulario, además de los
límites de Django:

```python
# config/settings.py
FILE_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024      # umbral de volcado a disco
DATA_UPLOAD_MAX_MEMORY_SIZE = 20 * 1024 * 1024     # límite real del cuerpo
MAX_UPLOAD_SIZE = int(env('MAX_UPLOAD_SIZE', 20 * 1024 * 1024))
```

```python
# valorizador/forms.py
limite = getattr(settings, 'MAX_UPLOAD_SIZE', 20 * 1024 * 1024)
if f.size > limite:
    raise forms.ValidationError(
        f'El archivo pesa {f.size / 1e6:.1f} MB y el límite es {limite / 1e6:.0f} MB.'
    )
```

> El sistema anterior definía sólo `FILE_UPLOAD_MAX_MEMORY_SIZE = 10485760` y lo
> trataba como si fuera un límite de tamaño. No lo es: ese ajuste sólo controla
> a partir de qué tamaño Django vuelca el archivo a disco en vez de mantenerlo
> en memoria. No hay tope de subida.

### 6.5 Manejo de secretos

| Regla | Implementación |
|---|---|
| Ninguna credencial en el repositorio | `.env` está en `.gitignore`; sólo se versiona `.env.example` con valores vacíos |
| Sin clave por defecto en producción | `SECRET_KEY` sin valor y `DEBUG=False` ⇒ el proyecto **se niega a arrancar** |
| `DEBUG` seguro por defecto | `DEBUG = env_bool('DEBUG', False)` |
| `ALLOWED_HOSTS` explícito | Se lee del entorno; sin valor y sin `DEBUG`, lista vacía (Django rechaza todo) |
| Funcionalidad opcional se autodesactiva | Sin `GEMINI_API_KEY`, `ASSISTANT_ENABLED = False` y el endpoint devuelve 503 |

```python
# config/settings.py
SECRET_KEY = env('SECRET_KEY')
if not SECRET_KEY:
    if DEBUG:
        SECRET_KEY = 'django-insecure-solo-para-desarrollo-local-no-usar-en-produccion'
    else:
        raise ImproperlyConfigured(
            'SECRET_KEY es obligatoria cuando DEBUG=False. ...'
        )
```

### 6.6 Manejo de errores

Los errores internos se registran con traza completa en el log del servidor y se
devuelve al usuario un mensaje genérico. El sistema anterior devolvía
`str(exception)` al cliente, lo que filtra rutas, nombres de tabla y detalles de
la infraestructura:

```python
# valorizador/views.py
except Exception as exc:
    log.exception('Error en el asistente')
    return JsonResponse(
        {'error': 'El asistente no está disponible en este momento.'}, status=502
    )
```

### 6.7 Contenedor

El proceso corre como usuario sin privilegios:

```dockerfile
# Dockerfile
RUN useradd --create-home --uid 10001 appuser \
 && mkdir -p /app/staticfiles /app/media \
 && chown -R appuser:appuser /app

USER appuser
```

### 6.8 Riesgos residuales conocidos

| Riesgo | Estado |
|---|---|
| Caché en memoria del proceso: los límites de frecuencia son por *worker* | Configurar Redis/Memcached en producción |
| El JSON de resultados viaja al cliente y vuelve en `valorizar_guardar` | Sólo afecta datos propios; el `conjunto_id` sí se revalida |
| No hay `.dockerignore`: un `docker build` local copia el `.env` a la imagen | **Pendiente**: agregar `.dockerignore` con `.env`, `db.sqlite3`, `.git` |
| Sin registro de auditoría de accesos y borrados | No implementado |
| Sin autenticación de segundo factor | No implementado |
| El asistente envía al proveedor externo folios, contrapartes y nocionales del usuario | Documentado; desactivable no configurando la clave |

---

## 7. Despliegue

### 7.1 Variables de entorno

| Variable | Obligatoria | Por defecto | Descripción |
|---|---|---|---|
| `SECRET_KEY` | **Sí** si `DEBUG=False` | — | Clave de firma de Django. Generar con `get_random_secret_key()` |
| `DEBUG` | No | `False` | Nunca `True` en producción |
| `ALLOWED_HOSTS` | **Sí** en producción | `localhost,127.0.0.1` sólo si `DEBUG` | Lista separada por comas |
| `CSRF_TRUSTED_ORIGINS` | Detrás de proxy | vacío | Orígenes con esquema, p. ej. `https://forwards.ejemplo.cl` |
| `DATABASE_URL` | No | SQLite | `postgresql://usuario:clave@host:5432/base` |
| `SQLITE_PATH` | No | `BASE_DIR/db.sqlite3` | Ruta del archivo SQLite |
| `GEMINI_API_KEY` | No | — | Sin ella el asistente queda desactivado |
| `GEMINI_MODEL` | No | `gemini-2.0-flash` | Modelo del asistente |
| `SECURE_SSL_REDIRECT` | No | `True` si `DEBUG=False` | Desactivar sólo si el proxy ya redirige |
| `SECURE_HSTS_SECONDS` | No | `31536000` | HSTS |
| `MAX_UPLOAD_SIZE` | No | `20971520` (20 MB) | Tope de subida |
| `LOG_LEVEL` | No | `INFO` | Nivel del logger raíz |

Plantilla en `.env.example`. **`.env` nunca se versiona.**

### 7.2 Base de datos

SQLite sirve para desarrollo y para una instalación de un solo usuario. Para
producción con concurrencia real, PostgreSQL:

```bash
export DATABASE_URL="postgresql://forward:clave@db:5432/forward"
python manage.py migrate
```

El soporte está implementado sin dependencias adicionales de configuración
(`dj-database-url` no es necesario), parseando la URL directamente:

```python
# config/settings.py
_db_url = env('DATABASE_URL')
if _db_url and _db_url.startswith(('postgres://', 'postgresql://')):
    from urllib.parse import urlparse
    u = urlparse(_db_url)
    DATABASES['default'] = {
        'ENGINE': 'django.db.backends.postgresql',
        ...
        'CONN_MAX_AGE': 600,
    }
```

Requiere instalar `psycopg[binary]` en el entorno.

**Motivos para migrar a PostgreSQL:** SQLite bloquea la base completa en cada
escritura, no soporta bien varios *workers* de gunicorn escribiendo en paralelo,
y con `volumes` de Docker el archivo queda expuesto a corrupción si el
contenedor se detiene durante una escritura.

### 7.3 Archivos estáticos

WhiteNoise sirve los estáticos desde el propio proceso, con compresión y
*hashing* de nombres:

```python
# config/settings.py
STORAGES = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'whitenoise.storage.CompressedManifestStaticFilesStorage'},
}
```

`collectstatic` se ejecuta en tiempo de construcción de la imagen. Con
`CompressedManifestStaticFilesStorage` **todo archivo referenciado desde un
template debe existir en `collectstatic`**, o el render falla en producción.

### 7.4 Docker

```dockerfile
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

RUN useradd --create-home --uid 10001 appuser \
 && mkdir -p /app/staticfiles /app/media \
 && chown -R appuser:appuser /app
USER appuser

RUN SECRET_KEY=build-only DEBUG=False ALLOWED_HOSTS=localhost \
    python manage.py collectstatic --noinput

EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD curl -fsS http://localhost:8080/accounts/login/ || exit 1

CMD ["gunicorn", "config.wsgi:application", \
     "--bind", "0.0.0.0:8080", "--workers", "3", \
     "--timeout", "120", "--access-logfile", "-"]
```

```yaml
# docker-compose.yml
services:
  web:
    build: .
    ports: ["8080:8080"]
    env_file: [.env]
    environment:
      DEBUG: "False"
    volumes:
      - sqlite-data:/app/data
    restart: unless-stopped

volumes:
  sqlite-data:
```

### 7.5 Lista de verificación para producción

- [ ] `DEBUG=False` y `SECRET_KEY` generada, nunca la de desarrollo.
- [ ] `ALLOWED_HOSTS` con el dominio real, no `*`.
- [ ] HTTPS terminado en el proxy inverso, con `SECURE_PROXY_SSL_HEADER` ya
      configurado y `CSRF_TRUSTED_ORIGINS` apuntando al dominio.
- [ ] PostgreSQL en lugar de SQLite.
- [ ] Backend de caché compartido (Redis/Memcached) para que los límites de
      frecuencia funcionen entre *workers*.
- [ ] `python manage.py check --deploy` sin advertencias.
- [ ] Respaldo periódico de la base de datos y prueba de restauración.
- [ ] Rotación y retención de logs; los logs van a `stdout` por diseño.
- [ ] Agregar `.dockerignore` (`.env`, `db.sqlite3`, `.git`, `__pycache__`)
      antes de publicar imágenes.
- [ ] Revisar que el asistente esté desactivado si no se quiere enviar datos de
      cartera a un proveedor externo.

---

## 8. Cómo extender el sistema

### 8.1 Agregar una convención de conteo de días

Todo ocurre en `core/daycount.py` y se propaga solo.

1. **Registrar el nombre** en la tupla de convenciones:

```python
# core/daycount.py
DAY_COUNT_CONVENTIONS = (
    "ACT/360", "ACT/365", "30/360", "30E/360", "ACT/ACT",
    "ACT/365F",     # nueva
)
```

2. **Implementar la fracción de año** en `day_count_fraction`, y el numerador en
   `day_count_days` si la convención no usa días corridos.

3. **Declarar la base anual nominal** en `year_basis`, que se usa para los
   factores de los nodos en la interpolación log-lineal y para los reportes.

4. Listo. `PricingConfig.validate()` acepta el nuevo nombre automáticamente y
   `ValorizarForm` construye sus opciones desde la misma tupla:

```python
# valorizador/forms.py
day_count = forms.ChoiceField(
    choices=[(c, c) for c in DAY_COUNT_CONVENTIONS], initial='ACT/360',
    label='Conteo de días',
)
```

5. Agregar un test con al menos un caso donde la nueva convención **difiera** de
   las existentes. Una convención que nunca difiere no aporta nada.

### 8.2 Agregar una curva

Las curvas se identifican por nombre en `PuntoCurva.nombre` y se resuelven por
nombre desde el contrato (`fwd_curve`, `disc_curve`). Para agregar, por ejemplo,
descuento en USD sobre SOFR:

1. **Registrar la opción** en el modelo:

```python
# valorizador/models.py
CURVE_CHOICES = [
    ('FWDUSDCLP', 'Forward USD/CLP (outright)'),
    ('FWDEURCLP', 'Forward EUR/CLP (outright)'),
    ('CLP423', 'Descuento CLP cámara'),
    ('USD_SOFR', 'Descuento USD SOFR'),
]
```

2. Cargar los nodos: por el formulario, por importación de archivo, o
   agregando el par de columnas `dia_USD_SOFR` / `c_USD_SOFR` a la hoja
   `CURVE MASTER` del libro, que el lector reconoce por patrón:

```python
# valorizador/services/cordada_excel.py
m = re.match(r'^dia[_\s]*(.+)$', h, re.IGNORECASE)
```

3. Apuntar el contrato a la nueva curva con `disc_curve='USD_SOFR'`.

**Nada más.** El motor resuelve la curva por nombre desde `MarketData.curves`:

```python
# core/valuation.py
fwd_raw = market.curve(contract.fwd_curve)
disc_raw = market.curve(contract.disc_curve)
```

Consideración: `sensitivity_matrix` desplaza únicamente las curvas cuyo nombre
empieza con `FWD`. Una curva de outrights con otro prefijo no se moverá en los
escenarios de spot.

### 8.3 Agregar una interpolación o una extrapolación

En `core/curves.py`: agregar el nombre a `INTERP_METHODS` o `EXTRAP_METHODS` y
la rama correspondiente en `Curve.value` o `Curve._extrapolate`. Los formularios
y la validación se actualizan solos, porque leen de esas mismas tuplas.

### 8.4 Agregar un producto

El caso más pesado. La estructura que hay que replicar es la de `core/valuation.py`:

1. **Una dataclass de contrato** con los atributos económicos, sin nada de
   Django.
2. **Una función `price_<producto>(contract, market, config) -> dict`** que
   devuelva la misma forma de diccionario: `mtm`, `flags`, `error`, más los
   campos propios del producto.
3. **Reutilizar** `Curve`, `DiscountCurve`, `day_count_fraction` y `Calendar`.
   Un swap de tasa, por ejemplo, sólo agrega una malla de cupones.
4. **Un modelo Django** con un método `to_core()`.
5. **Un caso de reconciliación** contra una fuente externa confiable.

Recomendación de diseño: si el producto comparte el conjunto de neteo con los
forwards, la función de exposición esperada debe agregarse a
`cva_dva_netting_set` como un `forward_fn`/`discount_fn` más, en lugar de
calcular su CVA por separado. Ese es exactamente el punto de tener un conjunto de
neteo.

### 8.5 Qué no hacer

- **No duplicar la fórmula del MtM** en una vista, en una plantilla o en un
  exportador. Si algo necesita el MtM, que llame a `price_contract`.
- **No poner lógica de presentación en `core/`.** Los formatos con separadores
  chilenos viven en `valorizador/templatetags/format_tags.py`.
- **No consultar la base de datos sin `for_user`.** Si hace falta una consulta
  global, que sea explícita y comentada.

---

## 9. Estado de implementación

Verificado por ejecución al momento de escribir este documento.

| Componente | Líneas | Estado |
|---|---:|---|
| Motor `core/` (5 módulos de cálculo) | 1.613 | Completo. Reconciliado al centavo contra el libro Cordada |
| `core/excel_model.py` (réplica en fórmulas de Excel) | 1.587 | Completo. Genera 9 hojas con fórmulas vivas |
| Modelos, migración inicial, panel de administración | 390 | Completo. `manage.py check` y `makemigrations --check` sin observaciones |
| Vistas, formularios, URLs | 1.339 | Completo |
| Plantillas HTML | 21 archivos | Completo (`valorizador/` y `accounts/`) |
| Estáticos (CSS + 3 módulos JS) | — | Completo |
| `services/importers.py`, `cordada_excel.py`, `excel_export.py` | 938 | Completo |
| `scripts/build_excel_model.py` | 262 | Completo |
| Comando `cargar_demo` | 141 | Completo |
| Configuración, Dockerfile, docker-compose | — | Completo |
| **Suite de tests** | 3.192 | **337 tests, todos pasan** (175 en `core/tests/`, 162 en `valorizador/tests/`) |

### Pendientes conocidos

| ID | Pendiente |
|---|---|
| **P-01** | La política de extrapolación `"Puntos"` devuelve la misma expresión que `"Lineal"`: la opción existe en el formulario y en `EXTRAP_METHODS`, pero todavía no se diferencia numéricamente |
| **P-05** | No hay `.dockerignore`: un `docker build` desde un árbol de trabajo local copiaría `.env` y `db.sqlite3` a la imagen |
| **P-06** | `accounts/tests/` existe vacío: el límite de intentos de login no tiene cobertura propia |
| **P-07** | El libro generado `Valorizador_Forwards.xlsx` queda en la raíz del proyecto y no está en `.gitignore` |

Detalle en [`AUDITORIA.md`](AUDITORIA.md#pendientes-propios-de-forward_v2).
