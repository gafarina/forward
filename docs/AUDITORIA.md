# Informe de auditoría — repositorio `gafarina/forward`

**Objeto auditado:** repositorio público
[`github.com/gafarina/forward`](https://github.com/gafarina/forward), commit
`c7b90b5267616d64e707c8971042e45131b425c5` ("Include all files without ignore",
2026-08-06). Aplicación Django de valorización de forwards FX USD/CLP.

**Alcance:** código fuente completo, configuración, contenido versionado,
metodología de cálculo y calidad de implementación.

**Método:** lectura del código, ejecución del motor original sobre el libro
operativo `06052026 CalculadoraForward Cordada_v2.xlsm` y comparación de sus
resultados contra las celdas de la planilla, contrastando además con el motor de
`forward_v2`.

---

## 1. Resumen ejecutivo

Se identificaron **37 hallazgos**: 4 críticos, 12 altos, 15 medios y 6 bajos.

Los hallazgos críticos son de seguridad y tienen consecuencias inmediatas: una
clave de API válida está publicada en un repositorio público, y cualquier
usuario autenticado de la aplicación puede leer y borrar la cartera de forwards
de los demás usuarios.

El hallazgo metodológico de mayor impacto es que el motor de valorización **no
reproduce la planilla operativa**: extrapola plano donde la planilla extrapola
linealmente, y como el primer nodo de la curva de descuento CLP423 está en 92
días, **todo contrato con plazo residual menor a 92 días se descuenta con la
tasa equivocada**, sin ninguna advertencia al usuario. En la cartera de ejemplo
de tres contratos por USD 5 millones la diferencia acumulada es de 346,96 pesos;
el motor de `forward_v2` reproduce la planilla al centavo.

El hallazgo de robustez más llamativo es que la funcionalidad estrella del
sistema —la carga del libro Cordada— **nunca pudo haber funcionado**: importa
tres modelos que no existen en `models.py`, produciendo un `ImportError` que
queda enmascarado por un `except Exception` genérico.

### Tabla de hallazgos

Ordenados por severidad.

| ID | Título | Categoría | Severidad | Estado en v2 |
|---|---|---|---|---|
| **S-01** | Clave de API de Gemini válida publicada en `.env` versionado | Seguridad | **Crítica** | Corregido |
| **S-02** | Endpoint `api_chat` abierto a internet: `@csrf_exempt` y `@login_required` comentado | Seguridad | **Crítica** | Corregido |
| **S-03** | Fuga de datos entre usuarios: listados y exportaciones sin filtro por dueño | Seguridad | **Crítica** | Corregido |
| **S-04** | Acceso y borrado de objetos ajenos por identificador (IDOR) | Seguridad | **Crítica** | Corregido |
| **S-05** | Base de datos `db.sqlite3` versionada con datos reales de cartera y hash de credenciales | Seguridad | Alta | Corregido |
| **S-06** | Configuración insegura por defecto: `DEBUG=True`, `ALLOWED_HOSTS=['*']`, `SECRET_KEY` conocida, sin cabeceras de seguridad | Seguridad | Alta | Corregido |
| **S-07** | Libro operativo con cartera real versionado en repositorio público | Seguridad | Alta | Corregido |
| **M-01** | Extrapolación plana donde la planilla extrapola linealmente, sin aviso | Metodología | Alta | Corregido |
| **M-02** | Convención 30/360 declarada pero no implementada | Metodología | Alta | Corregido |
| **M-03** | Interpolación log-lineal nunca aplicada al descuento; falla con tasas negativas | Metodología | Alta | Corregido |
| **M-04** | Ajuste de días hábiles ignora los feriados chilenos | Metodología | Alta | Corregido |
| **M-05** | CVA/DVA sin exposición esperada, sin severidad, sin neteo, y contamina el MtM | Metodología | Alta | Corregido |
| **M-06** | `spot_inicio` poblado con el spot de la fecha de valorización | Metodología | Alta | Corregido |
| **R-01** | La carga del libro Cordada está rota: importa modelos inexistentes | Robustez | Alta | Corregido |
| **R-02** | Cero tests en el repositorio | Robustez | Alta | Corregido |
| **R-03** | `if 'sensibilidad' in locals()` y variables potencialmente sin asignar | Robustez | Alta | Corregido |
| **S-08** | Contenedor corre como root y sin `.dockerignore` | Seguridad | Media | Mitigado |
| **S-09** | Estado global compartido: activar curvas desactiva las de todos los usuarios | Seguridad | Media | Corregido |
| **S-10** | Deduplicación global de folios: la carga de un usuario bloquea la de otro | Seguridad | Media | Corregido |
| **S-11** | Detalle de excepciones de Python devuelto al cliente | Seguridad | Media | Corregido |
| **S-12** | Sin límite de intentos de inicio de sesión | Seguridad | Media | Corregido |
| **S-13** | Límite de tamaño de archivo inexistente (`FILE_UPLOAD_MAX_MEMORY_SIZE` mal interpretado) | Seguridad | Media | Corregido |
| **M-07** | Extrapolación plana de outrights implica diferencial de tasas que colapsa a cero | Metodología | Media | Mitigado |
| **M-08** | Delta por fórmula cerrada sin documentar el supuesto; sin theta; "rho" mal nombrado | Metodología | Media | Corregido |
| **M-09** | Curvas sin ordenar ni deduplicar: resultados arbitrarios en silencio | Metodología | Media | Corregido |
| **R-04** | El importador descarta filas en silencio | Robustez | Media | Corregido |
| **R-05** | Nombres de hoja y coordenadas de celda fijos en el código | Robustez | Media | Corregido |
| **R-06** | Lectura de `request.POST['campo']` sin validación dentro de `except Exception` | Robustez | Media | Corregido |
| **R-07** | La dependencia declarada no es la que el código importa | Robustez | Media | Corregido |
| **R-08** | Sin índices de base de datos en los campos por los que se filtra | Robustez | Media | Corregido |
| **R-09** | Llamada a servicio externo dentro de la petición, sin caché ni tiempo de vida | Robustez | Media | Corregido |
| **S-14** | Archivos `.pyc` versionados y ausencia de `.gitignore` | Seguridad | Baja | Corregido |
| **M-10** | Convención de días desconocida cae silenciosamente en base 360 | Metodología | Baja | Corregido |
| **R-10** | Archivo temporal no se elimina si ocurre una excepción | Robustez | Baja | Corregido |
| **R-11** | `except:` desnudo | Robustez | Baja | Corregido |
| **R-12** | NumPy como dependencia para interpolar linealmente entre dos puntos | Robustez | Baja | Corregido |
| **R-13** | Coincidencia parcial de encabezados puede enlazar la columna equivocada | Robustez | Baja | Mitigado |

### Pendientes propios de `forward_v2`

Hallazgos abiertos en el proyecto nuevo, registrados aquí para trazabilidad.

| ID | Título | Categoría | Severidad | Estado |
|---|---|---|---|---|
| **P-06** | `accounts/tests/` vacío: el límite de intentos de login no tiene cobertura propia | Robustez | Baja | **Pendiente** |
| ~~P-01~~ | ~~La política de extrapolación "Puntos" es idéntica a "Lineal"~~ | Metodología | Media | Resuelto |
| ~~P-05~~ | ~~Sin `.dockerignore`~~ | Seguridad | Media | Resuelto |
| ~~P-07~~ | ~~El libro generado queda fuera de `.gitignore`~~ | Robustez | Baja | Resuelto |
| ~~P-02~~ | ~~`services/excel_export.py` no existe~~ | Robustez | Media | Resuelto |
| ~~P-03~~ | ~~Plantillas incompletas~~ | Robustez | Media | Resuelto |
| ~~P-04~~ | ~~Suite de tests vacía~~ | Robustez | Alta | Resuelto: 337 tests |

**P-01 · Detalle (resuelto).** `EXTRAP_METHODS` declaraba tres políticas y el
formulario ofrecía las tres, pero `Curve._extrapolate` terminaba en la misma
expresión para `"Lineal"` y `"Puntos"`. Ahora cada política tiene semántica
propia:

```python
# core/curves.py
if self.extrap == "Puntos":
    span = xs[-1] - xs[0]
    slope = (ys[-1] - ys[0]) / span if span else 0.0
    anchor_x, anchor_y = (xs[0], ys[0]) if left else (xs[-1], ys[-1])
    return anchor_y + slope * (x - anchor_x)
```

`"Lineal"` prolonga la pendiente del **segmento extremo**; `"Puntos"` prolonga la
pendiente **promedio de toda la curva**, medida entre el primer y el último nodo.
Sobre una curva de outrights, mantener esa pendiente promedio equivale a mantener
constante el ritmo de acumulación de puntos forward —el diferencial de tasas
implícito— en lugar de perpetuar el diferencial marginal del último tramo, que es
el más ruidoso por falta de liquidez.

Verificado por ejecución sobre la curva `FWDUSDCLP` del libro Cordada (nodos de 1
a 62 días):

| Plazo | Plana | Lineal | Puntos |
|---:|---:|---:|---:|
| 0,5 d | 892,210000 | 892,212500 | 892,211475 |
| 100 d | 892,030000 | 891,993226 | 891,917869 |
| 365 d | 892,030000 | 891,736774 | 891,135902 |

Las tres políticas producen ahora resultados distintos. `"Lineal"` sigue siendo
la predeterminada porque es la que reproduce la planilla Cordada.

**P-05 · Detalle (resuelto).** El `Dockerfile` hace `COPY . .`. Se agregó un
`.dockerignore` que excluye `.env`, `*.sqlite3`, `docs/`, los libros `.xlsx`/`.xlsm`
y los artefactos de test, de modo que la imagen ya no puede arrastrar credenciales
del árbol de trabajo. Es la misma causa raíz de **S-08**.

**P-07 · Detalle (resuelto).** `Valorizador_Forwards.xlsx` se agregó a
`.gitignore`: es un artefacto generado por `scripts/build_excel_model.py`, no
código fuente.

---

## 2. Hallazgos de seguridad

### S-01 · Clave de API de Gemini válida publicada en `.env` versionado

**Severidad: Crítica · Estado en v2: Corregido**

**Qué encontré.** El archivo `.env` está versionado en el repositorio público y
contiene una clave de API de Google Gemini con el prefijo `AIza`, formato de una
credencial real y activa.

**Dónde.** `/.env`, línea 4. Confirmado en el índice de git:

```
$ git ls-files | head
.env
.env.example
06052026 CalculadoraForward Cordada_v2.xlsm
...
db.sqlite3
```

**Evidencia.**

```bash
# .env (versionado)
SECRET_KEY=your-secret-key-here
DEBUG=True
DATABASE_URL=sqlite:///db.sqlite3
GEMINI_API_KEY=AIzaSyAVMjrurDuxqYhiEnn3xIcgamUHfbFVUWI
```

El repositorio no tiene `.gitignore` y el único commit se titula literalmente
*"Include all files without ignore"*, lo que indica que la inclusión fue
deliberada.

Además `.env.example` existe y **no** contiene la clave, lo que confirma que el
autor conocía el patrón correcto y lo omitió.

**Por qué importa.** La credencial está comprometida desde el momento en que se
publicó. Los repositorios públicos de GitHub son rastreados continuamente por
robots que extraen claves de API en cuestión de minutos. Las consecuencias son
consumo facturado a la cuenta del dueño, posible bloqueo por abuso, y —según los
permisos del proyecto de Google Cloud asociado— acceso a otros servicios.

**Impacto cuantificado.** La clave permite consumo ilimitado de la API de Gemini
hasta el tope de cuota del proyecto. Combinada con **S-02** (endpoint público),
cualquier persona en internet podía consumirla sin siquiera extraerla del
repositorio.

**Cómo se resolvió en v2.**

```gitignore
# .gitignore
# Credenciales — lo que faltaba en el repositorio original
.env
*.pem
*.key

# Base de datos local
db.sqlite3
db.sqlite3-journal
*.sqlite3
```

```python
# config/settings.py
GEMINI_API_KEY = env('GEMINI_API_KEY')
GEMINI_MODEL = env('GEMINI_MODEL', 'gemini-2.0-flash')
ASSISTANT_ENABLED = bool(GEMINI_API_KEY)
```

Sin clave la funcionalidad se desactiva sola en lugar de romper la aplicación, y
sólo se versiona `.env.example` con los campos vacíos y la instrucción explícita:

```
# .env.example
# Copia este archivo a .env y complétalo. NUNCA subas .env al repositorio.
```

> **Acción inmediata requerida.** Ver §5. La corrección en v2 no revoca la clave
> ya expuesta: eso sólo puede hacerlo el dueño de la cuenta.

---

### S-02 · Endpoint `api_chat` abierto a internet

**Severidad: Crítica · Estado en v2: Corregido**

**Qué encontré.** El endpoint del asistente está exento de CSRF y su decorador
de autenticación está **comentado**, con un comentario que explicita que la
decisión fue consciente.

**Dónde.** `valorizador/views.py`, líneas 908-910.

**Evidencia.**

```python
# v1: valorizador/views.py:905-912
from django.views.decorators.csrf import csrf_exempt
import json

@csrf_exempt
# @login_required  # Let's keep it open for now or require login if we manage sessions
def api_chat(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
```

La ruta está publicada en `valorizador/urls.py`:

```python
path('api/chat/', views.api_chat, name='api_chat'),
```

**Por qué importa.** Cualquier persona en internet puede hacer POST a
`/api/chat/` y obtener respuestas de Gemini facturadas al proyecto, sin límite
de frecuencia, sin límite de tamaño de mensaje y sin límite de historial. Es un
proxy gratuito hacia un servicio de pago.

Agravantes:

- No hay límite de longitud del mensaje ni del historial: el atacante controla
  la cantidad de tokens facturados por petición.
- La excepción se devuelve al cliente en texto plano (**S-11**), lo que facilita
  el diagnóstico de la infraestructura.
- El código consulta la cartera del usuario autenticado; con sesión válida, un
  ataque CSRF desde un sitio de terceros podía disparar la consulta con las
  credenciales de la víctima.

**Cómo se resolvió en v2.** Sesión obligatoria, POST obligatorio, CSRF activo,
límite de frecuencia por usuario, y truncado de entrada:

```python
# valorizador/views.py
@login_required
@require_POST
def api_chat(request):
    if not getattr(settings, 'ASSISTANT_ENABLED', False):
        return JsonResponse(
            {'error': 'El asistente no está configurado en este despliegue.'}, status=503
        )

    clave = f'chat_rate_{request.user.pk}'
    usados = cache.get(clave, 0)
    if usados >= 30:
        return JsonResponse(
            {'error': 'Alcanzaste el límite de consultas por hora.'}, status=429
        )
    cache.set(clave, usados + 1, 3600)
    ...
    mensaje = (payload.get('message') or '').strip()[:4000]
    historial = payload.get('history', [])[-10:]
```

No queda ningún `csrf_exempt` en el proyecto.

---

### S-03 · Fuga de datos entre usuarios

**Severidad: Crítica · Estado en v2: Corregido**

**Qué encontré.** Las vistas de listado, el panel y las exportaciones consultan
la base de datos **sin filtrar por dueño**. Todo usuario autenticado ve la
cartera de forwards de todos los demás: contrapartes, folios, nocionales,
precios pactados y valorizaciones.

**Dónde.** `valorizador/views.py`, múltiples ubicaciones.

**Evidencia.**

```python
# v1: valorizador/views.py:29,33  (dashboard)
contratos_list = ContratoForward.objects.filter(status='Vigente')
...
ultima_val = ValorizacionGuardada.objects.first()
```

```python
# v1: valorizador/views.py:97  (curvas_list)
conjuntos = ConjuntoCurvas.objects.all()
```

```python
# v1: valorizador/views.py:349  (contratos_list)
contratos = ContratoForward.objects.filter(status='Vigente')
```

```python
# v1: valorizador/views.py:462  (contratos_export_csv)
contratos = ContratoForward.objects.filter(status='Vigente')
```

```python
# v1: valorizador/views.py:647  (valorizaciones_list)
vals = ValorizacionGuardada.objects.all()
```

```python
# v1: valorizador/views.py:767  (upload_excel)
carteras = Cartera.objects.all()
```

**El detalle que confirma que fue un descuido y no una decisión:** una sola
vista sí filtra correctamente.

```python
# v1: valorizador/views.py:326-329
@login_required
def carteras_list(request):
    from .models import Cartera
    carteras = Cartera.objects.filter(created_by=request.user)
    return render(request, 'valorizador/carteras_list.html', {'carteras': carteras})
```

La intención de aislar por usuario existía —el campo `created_by` está en todos
los modelos— pero no se aplicó de forma consistente.

Agravante en el panel: `ValorizacionGuardada.objects.first()` con
`ordering = ['-created_at']` significa que **el panel de cada usuario muestra la
última valorización de cualquier usuario del sistema**, incluidos su MtM total y
su desglose por contraparte.

**Por qué importa.** La información expuesta es comercialmente sensible: con qué
bancos opera una empresa, a qué precios y por qué montos. En un sistema
multiempresa esto es una violación directa de confidencialidad. Basta con
registrarse —el registro está abierto— para acceder.

**Cómo se resolvió en v2.** Un único punto de control en el modelo, usado en
todas las vistas:

```python
# valorizador/models.py
class OwnedQuerySet(models.QuerySet):
    def for_user(self, user):
        """Filtra por dueño. El staff ve todo."""
        if user.is_staff:
            return self
        return self.filter(created_by=user)
```

```python
# valorizador/views.py
contratos = ContratoForward.objects.for_user(user).filter(status='Vigente')
ultima_val = ValorizacionGuardada.objects.for_user(user).first()
active_curves = ConjuntoCurvas.objects.for_user(user).filter(is_active=True).first()
```

Además `created_by` pasó a ser obligatorio y con borrado en cascada, de modo que
no puede existir un objeto huérfano que escape del filtro:

```python
# valorizador/models.py
created_by = models.ForeignKey(
    settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='contratos'
)
```

---

### S-04 · Acceso y borrado de objetos ajenos por identificador

**Severidad: Crítica · Estado en v2: Corregido**

**Qué encontré.** Todas las vistas que operan sobre un objeto identificado por
clave primaria lo recuperan sin comprobar la propiedad. Un usuario puede leer,
editar, duplicar y **borrar** objetos de otro simplemente cambiando el número en
la URL.

**Dónde.** `valorizador/views.py`, líneas 144, 162, 269, 278, 453, 653, 739, 755
y 526.

**Evidencia.**

```python
# v1: valorizador/views.py:451-457
@login_required
def contrato_delete(request, pk):
    contrato = get_object_or_404(ContratoForward, pk=pk)
    if request.method == 'POST':
        contrato.delete()
        messages.success(request, 'Contrato eliminado.')
    return redirect('contratos_list')
```

Mismo patrón en:

| Línea | Vista | Efecto de la falta de control |
|---:|---|---|
| 144 | `curvas_edit` | Editar el conjunto de curvas de otro usuario |
| 162 | `curvas_detail` | Leer curvas ajenas |
| 269 | `curvas_delete` | **Borrar** curvas ajenas |
| 278 | `curvas_duplicate` | Copiar curvas ajenas a la cuenta propia |
| 453 | `contrato_delete` | **Borrar** contratos ajenos |
| 653 | `valorizacion_detail` | Leer valorizaciones ajenas línea por línea |
| 739 | `valorizacion_export_csv` | **Exportar** la cartera valorizada de otro |
| 755 | `valorizacion_delete` | **Borrar** valorizaciones ajenas |

Y en la vista de valorización, el mismo problema por otra vía: los contratos a
valorizar se toman de una consulta global filtrada sólo por los identificadores
que envía el cliente.

```python
# v1: valorizador/views.py:526
selected_contracts = ContratoForward.objects.filter(pk__in=selected_ids)
```

Enviando un rango de identificadores en el POST, un usuario obtiene una
valorización completa de la cartera de otro, con contraparte, nocional, precio
pactado y MtM de cada operación.

**Por qué importa.** Es lectura y destrucción de datos de terceros con una
petición trivial. No requiere herramientas ni conocimiento: basta cambiar un
número en la barra de direcciones.

**Cómo se resolvió en v2.** El filtro de dueño se aplica **dentro** del
`get_object_or_404`, de modo que un identificador ajeno devuelve 404 y ni
siquiera revela que el objeto existe:

```python
# valorizador/views.py
contrato = get_object_or_404(ContratoForward.objects.for_user(request.user), pk=pk)
conjunto = get_object_or_404(ConjuntoCurvas.objects.for_user(request.user), pk=pk)
val = get_object_or_404(ValorizacionGuardada.objects.for_user(request.user), pk=pk)
```

Y en la valorización, el filtro de dueño precede al filtro por identificadores:

```python
# valorizador/views.py
contratos_qs = ContratoForward.objects.for_user(user).filter(status='Vigente')
...
elegidos = list(contratos_qs.filter(pk__in=seleccion)) if seleccion else list(contratos_qs)
```

Además, toda operación destructiva exige POST con `@require_POST`, no sólo por
convención sino como decorador efectivo.

---

### S-05 · Base de datos versionada con datos reales

**Severidad: Alta · Estado en v2: Corregido**

**Qué encontré.** `db.sqlite3` (204 KB) está versionada y contiene datos de
producción.

**Dónde.** `/db.sqlite3`, en el índice de git.

**Evidencia.** Contenido extraído del archivo versionado:

```
auth_user                          1 registro
valorizador_contratoforward        4 registros
valorizador_conjuntocurvas         3 registros
valorizador_puntocurva            88 registros
valorizador_valorizacionguardada   9 registros
valorizador_cartera                2 registros
```

```
id | contraparte  | lado   | nocional  | precio fwd | spot inicio | vencimiento
 1 | BTG Pactual  | Compra | 1.000.000 |    886,94  |     887,71  | 2026-07-07
 2 | Bice         | Compra | 2.000.000 |    893,35  |     894,25  | 2026-07-13
 3 | Bice         | Compra | 2.000.000 |    889,98  |     890,33  | 2026-06-12
 4 | Banco Chile  | Compra |   400.000 |    450,00  |     430,00  | 2026-08-29
```

```
usuario | correo         | superusuario | hash
admin   | admin@test.com | sí           | pbkdf2_sha256$1200000$...
```

**Por qué importa.**

1. Expone públicamente relaciones comerciales reales: con qué bancos opera la
   empresa, a qué precios y por qué montos.
2. Expone el hash de la contraseña del superusuario. Aunque PBKDF2 con 1.200.000
   iteraciones es resistente, si la contraseña es débil o reutilizada, es
   crackeable sin límite de intentos y sin dejar rastro.
3. Un binario de base de datos en el control de versiones genera conflictos
   irresolubles y crece el repositorio en cada commit.

**Cómo se resolvió en v2.** `db.sqlite3` y `*.sqlite3` están en `.gitignore`
desde el inicio. El estado inicial se reproduce con un comando, no con un
binario versionado:

```bash
python manage.py cargar_demo --usuario demo
```

El comando genera una contraseña aleatoria si no se indica una, en lugar de
distribuir credenciales conocidas:

```python
# valorizador/management/commands/cargar_demo.py
if not clave:
    from django.utils.crypto import get_random_string
    clave = get_random_string(16)
    self.stdout.write(self.style.WARNING(
        f'Usuario "{username}" creado con clave: {clave}'
    ))
```

---

### S-06 · Configuración insegura por defecto

**Severidad: Alta · Estado en v2: Corregido**

**Qué encontré.** Los ajustes de Django están configurados para desarrollo y sin
red de seguridad para producción.

**Dónde.** `forward_project/settings.py`, líneas 8-13 y ausencias en todo el
archivo.

**Evidencia.**

```python
# v1: forward_project/settings.py:8-13
SECRET_KEY = os.getenv('SECRET_KEY', 'django-insecure-default-secret-key-for-dev')
DEBUG = os.getenv('DEBUG', 'True') == 'True'
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')

ALLOWED_HOSTS = ['*']
```

Y no aparece en ninguna parte del archivo:
`SECURE_SSL_REDIRECT`, `SESSION_COOKIE_SECURE`, `CSRF_COOKIE_SECURE`,
`SECURE_HSTS_SECONDS`, `SECURE_CONTENT_TYPE_NOSNIFF`, `SECURE_REFERRER_POLICY`,
`X_FRAME_OPTIONS`, `SESSION_COOKIE_HTTPONLY`, `CSRF_TRUSTED_ORIGINS`,
`SECURE_PROXY_SSL_HEADER`.

Detalle de cada problema:

| Ajuste | Valor v1 | Consecuencia |
|---|---|---|
| `DEBUG` | `True` por defecto | Un despliegue sin variables de entorno expone trazas completas, consultas SQL y valores de configuración en cada error |
| `ALLOWED_HOSTS` | `['*']` fijo | Habilita ataques de envenenamiento de cabecera `Host` |
| `SECRET_KEY` | Default conocido y **publicado en este mismo repositorio** | Permite falsificar sesiones y tokens de recuperación de contraseña |
| Cookies | Sin `Secure` ni `SameSite` | La cookie de sesión viaja por HTTP en claro |
| HSTS | Ausente | Sin protección contra degradación a HTTP |
| `X_FRAME_OPTIONS` | Ausente (Django trae `DENY` por defecto, pero no está declarado) | — |

El `.env` versionado confirma que `DEBUG=True` era el valor efectivo, y como el
`Dockerfile` hace `COPY . .` sin `.dockerignore`, **la imagen de producción
incluye ese `.env` con `DEBUG=True` y la clave de Gemini**.

**Cómo se resolvió en v2.** `DEBUG` seguro por defecto y arranque bloqueado si
falta la clave en producción:

```python
# config/settings.py
DEBUG = env_bool('DEBUG', False)

SECRET_KEY = env('SECRET_KEY')
if not SECRET_KEY:
    if DEBUG:
        SECRET_KEY = 'django-insecure-solo-para-desarrollo-local-no-usar-en-produccion'
    else:
        raise ImproperlyConfigured(
            'SECRET_KEY es obligatoria cuando DEBUG=False. ...'
        )

ALLOWED_HOSTS = env_list('ALLOWED_HOSTS', 'localhost,127.0.0.1' if DEBUG else '')
CSRF_TRUSTED_ORIGINS = env_list('CSRF_TRUSTED_ORIGINS')
```

Cabeceras y cookies:

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

Y el mínimo de contraseña se subió de 8 a 10 caracteres.

---

### S-07 · Libro operativo con cartera real versionado

**Severidad: Alta · Estado en v2: Corregido**

**Qué encontré.** El archivo `06052026 CalculadoraForward Cordada_v2.xlsm`
(3,0 MB) está versionado en el repositorio público. Contiene la cartera de
forwards vigentes con contrapartes, folios, nocionales, precios pactados y el
MtM contable, además de hojas históricas.

**Dónde.** Raíz del repositorio. También `contratos.xlsx`,
`contrato_test.xlsx`, `curvas_descuento.xlsx`, `curvas_descuento_v2.xlsx`,
`curva_test_forward_2.xlsx` y `test_curvas_fwd.xlsx`.

**Evidencia.** Contenido de la hoja *Forwards Cordada 31-05*, fila 5 en adelante:

```
Ref     Contraparte    Vcto        Monto      TC inicio  Fwd Contrato   MTM
756929  BTG Pactual    2026-07-07  1.000.000  887,71     886,94         -5.096.628,95
118039  Bice           2026-07-13  2.000.000  894,25     893,35          2.592.812,56
116845  Bice           2026-06-12  2.000.000  890,33     889,98         -4.346.625,78
                                                          Total          -6.850.442,17
```

La celda `S13` está rotulada *"(Patrimonio) Reserva de Cobertura"* con valor
−7.567.438,67: es información de estados financieros.

**Por qué importa.** Se publica la posición de derivados de la empresa, con
identificación de contrapartes bancarias y el impacto patrimonial. Es
información que normalmente sólo se revela agregada en notas a los estados
financieros.

**Cómo se resolvió en v2.** No hay libros con datos reales en el repositorio.
El caso de referencia se reproduce con datos ya públicos en el propio comando de
demostración, y `.gitignore` excluye los archivos temporales de Excel
(`~$*.xls*`). El lector `CordadaWorkbook` recibe el libro como carga del usuario,
nunca desde el árbol de fuentes.

---

### S-08 · Contenedor como root y sin `.dockerignore`

**Severidad: Media · Estado en v2: Mitigado**

**Qué encontré.** El `Dockerfile` no define usuario, de modo que el proceso
`gunicorn` corre como `root` dentro del contenedor. Tampoco hay `.dockerignore`,
por lo que `COPY . .` copia `.env`, `db.sqlite3`, el directorio `.git` completo y
los `.pyc` a la imagen.

**Dónde.** `/Dockerfile`.

**Evidencia.**

```dockerfile
# v1: Dockerfile
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN python manage.py collectstatic --noinput
EXPOSE 8080
CMD ["gunicorn", "forward_project.wsgi:application", "--bind", "0.0.0.0:8080"]
```

No hay `USER`. No existe `.dockerignore` en el repositorio.

**Por qué importa.** Una vulnerabilidad de ejecución remota en la aplicación se
convierte en `root` dentro del contenedor, lo que amplía notablemente el impacto
de una fuga de aislamiento. Además, la imagen publicada contiene la clave de
Gemini y la base de datos con la cartera: cualquiera que descargue la imagen
obtiene ambas cosas aunque el repositorio se hubiera limpiado.

**Cómo se resolvió en v2.** Usuario sin privilegios, con identificador fijo:

```dockerfile
# Dockerfile
# Se ejecuta como usuario sin privilegios: el original corría todo como root.
RUN useradd --create-home --uid 10001 appuser \
 && mkdir -p /app/staticfiles /app/media \
 && chown -R appuser:appuser /app

USER appuser
```

Se agregó además una comprobación de salud y ajustes explícitos de gunicorn.

**Mitigado, no cerrado:** `forward_v2` tampoco tiene `.dockerignore` (hallazgo
**P-05**). El `.gitignore` impide que `.env` llegue al repositorio, pero un
`docker build` desde un árbol de trabajo local sí lo copiaría a la imagen.

---

### S-09 · Estado global compartido entre usuarios

**Severidad: Media · Estado en v2: Corregido**

**Qué encontré.** Activar un conjunto de curvas desactiva el conjunto activo de
**todos** los usuarios del sistema.

**Dónde.** `valorizador/views.py`, línea 301, y línea 823.

**Evidencia.**

```python
# v1: valorizador/views.py:298-304
@login_required
def curvas_activate(request, pk):
    if request.method == 'POST':
        ConjuntoCurvas.objects.update(is_active=False)          # ← toda la tabla
        ConjuntoCurvas.objects.filter(pk=pk).update(is_active=True)
        messages.success(request, 'Conjunto activado.')
    return redirect('curvas_list')
```

Mismo patrón en la carga del libro:

```python
# v1: valorizador/views.py:823
ConjuntoCurvas.objects.exclude(pk=conjunto.pk).update(is_active=False)
```

**Por qué importa.** No es sólo una molestia de usabilidad: el conjunto activo
determina qué curvas se ofrecen por defecto al valorizar. Un usuario puede,
inadvertidamente, hacer que otro valorice con las curvas equivocadas. Además, la
vista no verifica la propiedad del conjunto que activa (**S-04**).

**Cómo se resolvió en v2.** Alcance limitado al usuario, dentro de una
transacción y con verificación de propiedad:

```python
# valorizador/views.py
@login_required
@require_POST
def curvas_activate(request, pk):
    conjunto = get_object_or_404(ConjuntoCurvas.objects.for_user(request.user), pk=pk)
    with transaction.atomic():
        ConjuntoCurvas.objects.filter(created_by=request.user).update(is_active=False)
        ConjuntoCurvas.objects.filter(pk=conjunto.pk).update(is_active=True)
```

---

### S-10 · Deduplicación global de folios

**Severidad: Media · Estado en v2: Corregido**

**Qué encontré.** La importación de contratos descarta cualquier folio que ya
exista en la base de datos, **de cualquier usuario**.

**Dónde.** `valorizador/views.py`, líneas 406-412; y línea 872 para la carga del
libro.

**Evidencia.**

```python
# v1: valorizador/views.py:406-412
existing_folios = set(ContratoForward.objects.values_list('folio', flat=True))
imported = 0
skipped = 0
for c in data:
    if c.get('folio') and c['folio'] in existing_folios:
        skipped += 1
        continue
```

```python
# v1: valorizador/views.py:872
if folio_str and ContratoForward.objects.filter(folio=folio_str).exists():
    continue
```

**Por qué importa.** Dos clientes distintos pueden legítimamente tener el mismo
número de folio: los folios los asigna cada banco, no el sistema. Con esta
lógica, el primer usuario que carga el folio `118039` impide para siempre que
cualquier otro usuario lo cargue. El mensaje que ve el segundo usuario es
"omitidos (folio duplicado)", sin ninguna pista de que el duplicado pertenece a
otra cuenta. Es además un canal de fuga de información: permite enumerar qué
folios existen en el sistema.

**Cómo se resolvió en v2.** Alcance por usuario, tanto en la importación como en
la restricción del modelo y en la validación del formulario:

```python
# valorizador/views.py
existentes = set(
    ContratoForward.objects.filter(created_by=request.user)
    .values_list('folio', flat=True)
)
```

```python
# valorizador/forms.py
qs = ContratoForward.objects.filter(created_by=self.user, folio=folio)
if self.instance.pk:
    qs = qs.exclude(pk=self.instance.pk)
if qs.exists():
    self.add_error('folio', 'Ya tienes un contrato con este folio.')
```

---

### S-11 · Detalle de excepciones devuelto al cliente

**Severidad: Media · Estado en v2: Corregido**

**Qué encontré.** Las excepciones de Python se muestran al usuario en texto
plano, revelando rutas del sistema de archivos, nombres de tablas y detalles de
la infraestructura.

**Dónde.** `valorizador/views.py`, líneas 138-139, 319-320, 392-393, 435-436,
443, 543-544, 638-639, 894-895, 1001-1004.

**Evidencia.**

```python
# v1: valorizador/views.py:1001-1004
except Exception as e:
    import traceback
    traceback.print_exc()
    return JsonResponse({'error': str(e)}, status=500)
```

```python
# v1: valorizador/views.py:392-393
except Exception as e:
    messages.error(request, f'Error: {e}')
```

```python
# v1: valorizador/views.py:138-139
except Exception as e:
    return JsonResponse({'error': str(e)}, status=500)
```

**Por qué importa.** Combinado con **S-02** (endpoint público), un atacante
externo obtiene información de reconocimiento gratis. Y para el usuario final,
un mensaje como `invalid literal for int() with base 10: ''` no comunica nada
útil.

**Cómo se resolvió en v2.** Traza completa al log del servidor, mensaje genérico
al cliente:

```python
# valorizador/views.py
except Exception as exc:
    log.exception('Error en el asistente')
    return JsonResponse(
        {'error': 'El asistente no está disponible en este momento.'}, status=502
    )
```

Los errores previsibles se validan antes de que ocurran, en los formularios.

---

### S-12 · Sin límite de intentos de inicio de sesión

**Severidad: Media · Estado en v2: Corregido**

**Qué encontré.** El formulario de inicio de sesión usa `LoginView` sin ninguna
protección contra fuerza bruta.

**Dónde.** `accounts/urls.py`, línea 8.

**Evidencia.**

```python
# v1: accounts/urls.py
path('login/', auth_views.LoginView.as_view(template_name='accounts/login.html'), name='login'),
```

No hay `django-axes`, ni límite por IP, ni retardo progresivo, ni CAPTCHA. El
registro está abierto (`accounts/views.py`), de modo que un atacante puede
además crear cuentas libremente.

**Por qué importa.** Con el hash del superusuario expuesto (**S-05**) y sin
límite de intentos, la superficie de ataque contra las credenciales es amplia.
El sistema tampoco registra los intentos fallidos.

**Cómo se resolvió en v2.**

```python
# accounts/views.py
MAX_INTENTOS = 10
VENTANA_SEGUNDOS = 900

class LoginRateLimitedView(auth_views.LoginView):
    def _clave(self):
        ip = self.request.META.get('HTTP_X_FORWARDED_FOR', '').split(',')[0].strip()
        ip = ip or self.request.META.get('REMOTE_ADDR', 'desconocida')
        return f'login_intentos_{ip}'

    def post(self, request, *args, **kwargs):
        if cache.get(self._clave(), 0) >= MAX_INTENTOS:
            messages.error(request, 'Demasiados intentos fallidos. Espera unos minutos antes de reintentar.')
            return self.form_invalid(self.get_form())
        return super().post(request, *args, **kwargs)
```

Con el backend de caché por defecto (memoria local) el contador es por proceso;
para producción hay que configurar Redis o Memcached, y así está documentado en
`ARQUITECTURA.md` §6.1.

---

### S-13 · Límite de tamaño de archivo inexistente

**Severidad: Media · Estado en v2: Corregido**

**Qué encontré.** El único ajuste relacionado con cargas es
`FILE_UPLOAD_MAX_MEMORY_SIZE`, que **no es un límite de tamaño de subida**: es
el umbral a partir del cual Django vuelca el archivo a disco en lugar de
mantenerlo en memoria. No hay tope efectivo.

**Dónde.** `forward_project/settings.py`, última línea.

**Evidencia.**

```python
# v1: forward_project/settings.py
FILE_UPLOAD_MAX_MEMORY_SIZE = 10485760  # 10MB
```

`DATA_UPLOAD_MAX_MEMORY_SIZE` no está definido, de modo que rige el valor por
defecto de Django (2,5 MB) para el cuerpo de la petición, pero **los archivos
subidos están excluidos de ese límite**. Los formularios de carga tampoco
validan tamaño ni extensión:

```python
# v1: valorizador/forms.py
class CurveFileUploadForm(forms.Form):
    file = forms.FileField(
        label='Archivo CSV/Excel',
        widget=forms.ClearableFileInput(attrs={'accept': '.csv,.xlsx,.xls'}),
    )
```

El atributo `accept` es una sugerencia del navegador, no una validación del
servidor. Y las vistas ni siquiera usan estos formularios: leen
`request.FILES['file']` directamente.

**Por qué importa.** Un archivo `.xlsm` malicioso de gran tamaño se procesa con
`openpyxl` en memoria y puede agotar los recursos del servidor. Sin límite y sin
validación de extensión, es un vector de denegación de servicio trivial.

**Cómo se resolvió en v2.** Límite efectivo en tres capas:

```python
# config/settings.py
FILE_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024
DATA_UPLOAD_MAX_MEMORY_SIZE = 20 * 1024 * 1024
MAX_UPLOAD_SIZE = int(env('MAX_UPLOAD_SIZE', 20 * 1024 * 1024))
```

```python
# valorizador/forms.py
class ArchivoUploadForm(forms.Form):
    EXTENSIONES = ('.csv', '.txt', '.xlsx', '.xlsm', '.xls')

    def clean_archivo(self):
        f = self.cleaned_data['archivo']
        if not f.name.lower().endswith(self.EXTENSIONES):
            raise forms.ValidationError(f'Extensión no soportada. Usa: {", ".join(self.EXTENSIONES)}')
        limite = getattr(settings, 'MAX_UPLOAD_SIZE', 20 * 1024 * 1024)
        if f.size > limite:
            raise forms.ValidationError(
                f'El archivo pesa {f.size / 1e6:.1f} MB y el límite es {limite / 1e6:.0f} MB.'
            )
        return f
```

Y todas las vistas de carga usan efectivamente este formulario.

---

### S-14 · Archivos compilados versionados y sin `.gitignore`

**Severidad: Baja · Estado en v2: Corregido**

**Qué encontré.** 26 archivos `.pyc` versionados y ausencia total de
`.gitignore`.

**Evidencia.**

```
$ git ls-files | grep -c pyc
26
$ git show HEAD:.gitignore
fatal: path '.gitignore' does not exist in 'HEAD'
```

**Por qué importa.** Menor por sí solo, pero es la causa raíz de **S-01**,
**S-05** y **S-07**: sin `.gitignore` no hay nada que impida versionar
credenciales, bases de datos y libros con datos de clientes. El nombre del commit
—*"Include all files without ignore"*— indica que se optó activamente por no
tenerlo.

**Cómo se resolvió en v2.** `.gitignore` completo desde el primer commit, con
las credenciales en primer lugar y un comentario que explica por qué.

---

## 3. Hallazgos de metodología

### M-01 · Extrapolación plana donde la planilla extrapola linealmente

**Severidad: Alta · Estado en v2: Corregido**

Este es el hallazgo metodológico central del informe.

**Qué encontré.** El motor extrapola **plano** en ambos extremos de ambas
curvas: fuera del rango de nodos devuelve el valor del nodo extremo. La planilla
operativa que este sistema pretende reemplazar extrapola **linealmente**. Como
el primer nodo de la curva de descuento `CLP423` está en **92 días**, todo
contrato con plazo residual menor a 92 días se descuenta con una tasa
equivocada.

**Dónde.** `valorizador/services/interpolation.py`, líneas 13-18.

**Evidencia.**

```python
# v1: valorizador/services/interpolation.py:3-18
def interp(x, xs, ys):
    """Linear interpolation matching Excel's custom interp() function.

    For values outside the range, extrapolate flat (use nearest value).
    """
    xs = np.array(xs, dtype=float)
    ys = np.array(ys, dtype=float)
    x = float(x)

    if x <= xs[0]:
        return float(ys[0])
    if x >= xs[-1]:
        return float(ys[-1])

    return float(np.interp(x, xs, ys))
```

El *docstring* afirma que replica la función `interp()` de la planilla. No lo
hace: la planilla extrapola linealmente.

**Agravante: el motor no avisa.** La comprobación de extrapolación en la curva
de descuento sólo mira el extremo largo:

```python
# v1: valorizador/services/valuation.py:117-120
if days_to_mat < fwd_xs[0] or days_to_mat > fwd_xs[-1]:
    flags.append('Fwd extrapolado: plazo fuera del rango')
if days_to_mat > disc_xs[-1]:                                  # ← sólo el extremo largo
    flags.append('Descuento extrapolado a largo plazo')
```

Ejecutando el motor original sobre los tres contratos del libro Cordada, la
lista de banderas de los tres sale **vacía**.

**Impacto cuantificado.** Valorización al 31-05-2026, spot 892,89, interpolación
lineal, ACT/360, capitalización compuesta, sin ajuste de días hábiles.

Tasa de descuento aplicada:

| Folio | Días | Tasa v1 (plana) | Tasa planilla (lineal) | Error |
|---|---:|---:|---:|---:|
| 756929 | 37 | 3,482310 % | 3,404065 % | **+7,82 pb** |
| 118039 | 43 | 3,482310 % | 3,412601 % | **+6,97 pb** |
| 116845 | 12 | 3,482310 % | 3,368499 % | **+11,38 pb** |

La tasa lineal correcta se obtiene prolongando la pendiente del primer tramo:

```
m = (3,61177 − 3,48231) / (183 − 92) = 0,0014226484 % por día
r(37) = 3,48231 − 0,0014226484 · 55 = 3,404065 %      ← celda P5 del libro
r(43) = 3,48231 − 0,0014226484 · 49 = 3,412601 %      ← celda P6
r(12) = 3,48231 − 0,0014226484 · 80 = 3,368499 %      ← celda P7
```

MtM resultante:

| Folio | Nocional | MtM motor v1 | MtM planilla | MtM motor v2 | Diferencia v1 − planilla |
|---|---:|---:|---:|---:|---:|
| 756929 | USD 1.000.000 | −5.096.232,74 | −5.096.628,95 | −5.096.628,95 | **+396,21** |
| 118039 | USD 2.000.000 | 2.592.603,88 | 2.592.812,56 | 2.592.812,56 | **−208,68** |
| 116845 | USD 2.000.000 | −4.346.466,35 | −4.346.625,78 | −4.346.625,78 | **+159,43** |
| **Total** | USD 5.000.000 | **−6.850.095,21** | **−6.850.442,17** | **−6.850.442,17** | **+346,96** |

Y los agregados contables:

| Concepto | Motor v2 (lineal) | Libro Cordada |
|---|---:|---:|
| MtM total | −6.850.442,17 | −6.850.442,171624668 |
| Componente spot | −7.567.438,67 | −7.567.438,666818179 |
| Puntos forward | 716.996,50 | 716.996,4951935108 |

**Con extrapolación lineal el motor v2 reproduce la planilla al centavo en los
tres contratos y en los tres agregados.**

**Por qué importa.** No es un error de redondeo sino de método: la diferencia
escala con el nocional y con la distancia al primer nodo, y tiene signo
sistemático (con curva al alza, la extrapolación plana sobreestima la tasa corta
para todos los contratos). Impide además la conciliación contra la planilla, que
es el único control disponible.

**Cómo se resolvió en v2.** Tres políticas explícitas, seleccionables por
corrida, con lineal como valor por defecto:

```python
# core/curves.py
EXTRAP_METHODS = ("Plana", "Lineal", "Puntos")

def _extrapolate(self, x: float, *, left: bool) -> float:
    xs, ys = self.xs, self.ys
    if self.extrap == "Plana":
        return ys[0] if left else ys[-1]

    if left:
        x0, x1, y0, y1 = xs[0], xs[1], ys[0], ys[1]
        anchor_x, anchor_y = x0, y0
    else:
        x0, x1, y0, y1 = xs[-2], xs[-1], ys[-2], ys[-1]
        anchor_x, anchor_y = x1, y1

    slope = (y1 - y0) / (x1 - x0) if x1 != x0 else 0.0

    if self.extrap == "Lineal":
        return anchor_y + slope * (x - anchor_x)
```

Y la advertencia cubre **ambos extremos de ambas curvas**:

```python
# core/valuation.py
if disc_curve.is_outside(days_to_mat):
    flags.append(
        f"Descuento extrapolado: plazo {days_to_mat}d "
        f"fuera de [{int(disc_curve.min_tenor)}, {int(disc_curve.max_tenor)}]"
    )
```

Verificado: los tres contratos del ejemplo salen ahora con la bandera
`Descuento extrapolado: plazo 37d fuera de [92, 1461]`.

El formulario deja explícita la implicancia de cada opción:

```python
# valorizador/forms.py
extrap_method = forms.ChoiceField(
    choices=[
        ('Lineal', 'Lineal (replica la planilla Cordada)'),
        ('Plana', 'Plana (mantiene el nodo extremo)'),
        ('Puntos', 'Puntos forward constantes'),
    ],
    initial='Lineal', label='Extrapolación',
    help_text='La planilla original extrapola linealmente. La app v1 lo hacía plano, '
              'lo que produce diferencias en plazos menores al primer nodo.',
)
```

---

### M-02 · Convención 30/360 declarada pero no implementada

**Severidad: Alta · Estado en v2: Corregido**

**Qué encontré.** La opción "30/360" está disponible en la interfaz pero produce
exactamente el mismo resultado que ACT/360: sólo cambia la base del año a 360 y
deja el numerador en días corridos. El propio comentario del código lo admite.

**Dónde.** `valorizador/services/valuation.py`, líneas 34-41.

**Evidencia.**

```python
# v1: valorizador/services/valuation.py:34-41
if day_count == 'ACT/365':
    year_days = 365.0
elif day_count == '30/360':
    # Simplify 30/360 to 360 year base for factor, days already calendar
    # A true 30/360 would recalculate days_to_mat
    year_days = 360.0
else:
    year_days = 360.0
```

**Verificación por ejecución.** Mismo contrato (folio 756929), cambiando sólo la
convención:

| Convención | Factor de descuento | MtM |
|---|---:|---:|
| ACT/360 | 0,9964880473 | −5.096.232,74 |
| **30/360** | **0,9964880473** | **−5.096.232,74** |
| ACT/365 | 0,9965360728 | −5.096.478,35 |

30/360 es bit a bit idéntica a ACT/360.

**Por qué importa.** El usuario cree estar aplicando una convención y está
aplicando otra. En instrumentos donde 30/360 es la convención contractual, el
resultado es sencillamente incorrecto, y el sistema no da ninguna señal.

**Cómo se resolvió en v2.** Cinco convenciones, cada una con su propio numerador
y denominador:

```python
# core/daycount.py
DAY_COUNT_CONVENTIONS = (
    "ACT/360", "ACT/365",
    "30/360",        # 30/360 US (Bond Basis)
    "30E/360",       # 30/360 Europea (ISDA/Eurobond)
    "ACT/ACT",       # ACT/ACT ISDA
)

def _days_30_360_us(d1: date, d2: date) -> int:
    """30/360 US (Bond Basis), regla NASD."""
    dd1, dd2 = d1.day, d2.day
    if _is_last_day_of_february(d1) and _is_last_day_of_february(d2):
        dd2 = 30
    if _is_last_day_of_february(d1):
        dd1 = 30
    if dd2 == 31 and dd1 >= 30:
        dd2 = 30
    if dd1 == 31:
        dd1 = 30
    return 360 * (d2.year - d1.year) + 30 * (d2.month - d1.month) + (dd2 - dd1)
```

Verificación de que ahora sí difieren:

| Desde | Hasta | ACT | 30/360 US | 30E/360 |
|---|---|---:|---:|---:|
| 2026-02-28 | 2026-03-31 | 31 | **30** | **32** |
| 2024-02-29 | 2024-08-31 | 184 | **180** | **181** |
| 2025-12-31 | 2026-12-31 | 365 | 360 | 360 |

Y sobre el MtM (contrato de 92 días corridos, USD 1.000.000):

| Convención | Fracción de año | Factor | MtM |
|---|---:|---:|---:|
| ACT/360 | 0,25555556 | 0,9912903576 | −4.997.702,26 |
| ACT/365 | 0,25205479 | 0,9914091538 | −4.998.301,18 |
| 30/360 | 0,25000000 | 0,9914788887 | −4.998.652,76 |
| 30E/360 | 0,25000000 | 0,9914788887 | −4.998.652,76 |
| ACT/ACT | 0,25205479 | 0,9914091538 | −4.998.301,18 |

---

### M-03 · Interpolación log-lineal nunca aplicada al descuento

**Severidad: Alta · Estado en v2: Corregido**

**Qué encontré.** Al seleccionar "Log-Lineal", el motor aplica log-lineal a la
curva forward y **mantiene interpolación lineal en la tasa de descuento**. Un
comentario en el código explica la razón: el logaritmo de una tasa negativa
falla.

**Dónde.** `valorizador/services/valuation.py`, líneas 122-131.

**Evidencia.**

```python
# v1: valorizador/services/valuation.py:122-131
# Interpolation Method
if interp_method == 'Log-Lineal':
    fwd_bbg = interp_log_linear(days_to_mat, fwd_xs, fwd_ys)
    # Assuming discount rates can be negative or 0, log-linear usually applies to discount factors
    # For simplicity in this engine, we do linear on rates if Log-Linear is chosen, or log-linear on DF
    # We'll stick to linear on rates since log-linear on negative rates fails
    disc_rate = interp(days_to_mat, disc_xs, disc_ys)
else:
    fwd_bbg = interp(days_to_mat, fwd_xs, fwd_ys)
    disc_rate = interp(days_to_mat, disc_xs, disc_ys)
```

El comentario identifica correctamente la solución ("log-linear usually applies
to discount factors") y opta por no implementarla.

**Agravante: cuando sí se aplica, con valores no positivos devuelve basura.**

```python
# v1: valorizador/services/interpolation.py:20-35
def interp_log_linear(x, xs, ys):
    """Log-linear interpolation. ys must be strictly positive."""
    ...
    # Avoid log(0) or negative
    ys = np.maximum(ys, 1e-10)
    ln_y = np.interp(x, xs, np.log(ys))
    return float(np.exp(ln_y))
```

El recorte a `1e-10` no evita el problema: lo enmascara. Verificación con una
curva de nodos 30 d → −0,25 %, 180 d → 0,10 %, 360 d → 0,60 %:

```
interp_log_linear(60, ...) = 6,309573444801934e-09
```

Es decir, para un plazo de 60 días la función devuelve una tasa de
0,0000000063 % en lugar de aproximadamente −0,04 %. No es una aproximación: es
un número sin relación con la curva, devuelto sin ninguna advertencia.

**Por qué importa.** El usuario selecciona un método metodológicamente distinto
y obtiene el mismo resultado de siempre en la pieza que más importa (el
descuento). Y si alguna vez el código llegara a aplicarse sobre tasas cercanas a
cero o negativas, el resultado sería silenciosamente incorrecto.

**Cómo se resolvió en v2.** La interpolación log-lineal se aplica sobre los
**factores de descuento**, que son siempre positivos:

```python
# core/curves.py
def _zero_from_df(self, days: float) -> float:
    """Interpola log-linealmente en factores y devuelve la tasa equivalente."""
    xs = self.curve.xs
    dfs = self._node_factors()
    ...
    log_df_curve = Curve(
        f"{self.curve.name}::logDF", list(xs), [math.log(df) for df in dfs],
        interp="Lineal", extrap=self.curve.extrap,
    )
    log_df = log_df_curve.value(x)
    df = math.exp(log_df)
    ...
    return ((1.0 / df) ** (1.0 / t) - 1.0) * 100.0
```

Esto equivale a suponer tasa forward instantánea constante entre nodos, que es
el estándar de mercado, y **tolera tasas cero o negativas**. Verificación sobre
la misma curva con tasas negativas:

| Plazo | Tasa v1 (log-lineal sobre tasas) | Tasa v2 (log-lineal sobre factores) |
|---:|---:|---:|
| 60 d | 0,0000000063 % | **−0,040147 %** |
| 200 d | 0,1220284936 % | **+0,199801 %** |

Impacto sobre la curva `CLP423` real (tramo interpolado):

| Plazo | Lineal sobre tasas | Log-lineal sobre factores | Diferencia |
|---:|---:|---:|---:|
| 120 d | 3,522144 % | 3,543036 % | 2,09 pb |
| 150 d | 3,564823 % | 3,582962 % | 1,81 pb |
| 300 d | 3,729221 % | 3,734140 % | 0,49 pb |

---

### M-04 · Ajuste de días hábiles ignora los feriados chilenos

**Severidad: Alta · Estado en v2: Corregido**

**Qué encontré.** La convención "ModifiedFollowing" sólo mueve sábados y
domingos. Ningún feriado chileno está considerado.

**Dónde.** `valorizador/services/valuation.py`, líneas 4-10.

**Evidencia.**

```python
# v1: valorizador/services/valuation.py:4-10
def get_next_business_day(d):
    """Simple modified following for weekends."""
    if d.weekday() == 5: # Saturday
        return d + timedelta(days=2)
    if d.weekday() == 6: # Sunday
        return d + timedelta(days=1)
    return d
```

Además, la implementación no es "modified following": un *modified following*
real retrocede si el ajuste cruza de mes. Esta versión siempre avanza.

**Verificación.** Fechas de 2026 que son feriado en Chile:

| Fecha | Día | Feriado | v1 devuelve | Correcto |
|---|---|---|---|---|
| 2026-01-01 | jue | Año Nuevo | 2026-01-01 | 2026-01-02 |
| 2026-04-03 | vie | Viernes Santo | 2026-04-03 | 2026-04-06 |
| 2026-05-01 | vie | Día del Trabajo | 2026-05-01 | 2026-05-04 |
| 2026-09-18 | vie | Independencia | 2026-09-18 | 2026-09-21 |
| 2026-12-25 | vie | Navidad | 2026-12-25 | 2026-12-28 |
| 2026-12-31 | jue | Feriado bancario | 2026-12-31 | 2027-01-04 |

En los seis casos el motor original devuelve la misma fecha, es decir, la trata
como día hábil.

**Por qué importa.** El ajuste del vencimiento cambia el plazo residual, y el
plazo residual determina tanto el punto interpolado de la curva como el factor
de descuento. Un vencimiento que cae el 18 de septiembre se valoriza con 3 días
menos de los que corresponden. El sesgo es sistemático a la baja.

**Cómo se resolvió en v2.** Módulo `core/calendars.py` con los feriados legales
chilenos, incluidas las reglas de traslado:

```python
# core/calendars.py
def _traslado_lunes(d: date) -> date:
    """
    Ley 20.215: los feriados del 29 de junio y 12 de octubre se trasladan al
    lunes de la misma semana si caen martes, miércoles o jueves, y al lunes de
    la semana siguiente si caen viernes.
    """
    wd = d.weekday()
    if wd in (1, 2, 3):
        return d - timedelta(days=wd)
    if wd == 4:
        return d + timedelta(days=3)
    return d
```

```python
# core/calendars.py
def _traslado_iglesias(year: int) -> date:
    """
    Ley 20.299: Día de las Iglesias Evangélicas y Protestantes.
    Base 31 de octubre. Si cae martes se adelanta al viernes anterior (27-oct);
    si cae miércoles se posterga al viernes siguiente (2-nov).
    """
```

Incluye el feriado bancario del 31 de diciembre, el feriado puente de Fiestas
Patrias, el solsticio de junio (Ley 21.357, tabulado 2021-2030), Viernes y
Sábado Santo derivados de Pascua, y un calendario conjunto CL+US para forwards
con entrega:

```python
# core/calendars.py
class JointCalendar(Calendar):
    """Unión de calendarios: un día es hábil sólo si lo es en todos."""
```

Las cinco convenciones de ajuste están implementadas correctamente, incluido el
retroceso de mes:

```python
# core/calendars.py
if convention == "ModifiedFollowing":
    adj = self.next_business_day(d)
    if adj.month != d.month:
        return self.prev_business_day(d)
    return adj
```

Verificación: `2026-12-31` con `Following` → `2027-01-04`; con
`ModifiedFollowing` → `2026-12-30`.

---

### M-05 · CVA/DVA sin exposición esperada, sin severidad, sin neteo

**Severidad: Alta · Estado en v2: Corregido**

**Qué encontré.** El ajuste por riesgo de crédito se calcula como un porcentaje
fijo del MtM de hoy, con un spread único de 50 puntos base para todas las
contrapartes, sin severidad, sin probabilidad de supervivencia acumulada y sin
reconocer neteo. Además, **sobrescribe el MtM**.

**Dónde.** `valorizador/services/valuation.py`, líneas 147-157.

**Evidencia.**

```python
# v1: valorizador/services/valuation.py:147-157
cva = 0.0
dva = 0.0
if calc_cva:
    # Simple CVA/DVA estimation (1% LGD * PD proxy based on tenor)
    credit_spread = 0.005 # 50 bps spread
    risk_proxy = credit_spread * (days_to_mat / year_days)
    if mtm > 0:
        cva = mtm * risk_proxy
    elif mtm < 0:
        dva = abs(mtm) * risk_proxy
    mtm = mtm - cva + dva
```

**Cinco defectos distintos:**

| # | Defecto | Consecuencia |
|---|---|---|
| 1 | Usa el MtM de hoy como exposición esperada de toda la vida | Un forward at-the-money tiene CVA **cero** |
| 2 | `PD ≈ spread × t`, sin severidad `(1−R)` ni supervivencia acumulada | El modelo no distingue entre un emisor con recovery 0 % y uno con 60 % |
| 3 | Spread fijo de 50 pb para toda contraparte | No diferencia riesgo de crédito entre bancos |
| 4 | Cálculo operación por operación | Ignora el neteo del contrato marco |
| 5 | `mtm = mtm - cva + dva` | El MtM reportado queda contaminado |

**Impacto cuantificado del defecto 1.** Forward de venta de USD 1.000.000 a 365
días, pactado exactamente al forward de mercado (`K = F₀ = 892,36`):

| Enfoque | MtM | CVA | DVA |
|---|---:|---:|---:|
| v1 (`mtm × spread × t`) | 0,00 | **0,00** | **0,00** |
| v2 (Bachelier + intensidad, 100 pb, R=40 %, σ=12 %) | 0,00 | **286.672,82** | **172.677,24** |

El modelo v1 declara riesgo de crédito nulo en una operación cuya exposición
esperada positiva es estrictamente mayor que cero durante todo el año. La razón
es analítica: para un forward at-the-money,

```
EPE(t) = σ_F · √t · N · DF · φ(0) = 0,3989 · σ_F · √t · N · DF  >  0
```

**Impacto cuantificado del defecto 4.** Cartera Cordada, contraparte Bice con
dos operaciones de signo opuesto (+2.592.813 y −4.346.626):

| | CVA total | DVA total |
|---|---:|---:|
| Con neteo | 41.944,30 | 27.979,14 |
| Sin neteo | 48.085,73 | 31.664,72 |
| **Sobrestimación por ignorar el neteo** | **+14,6 %** | **+13,2 %** |

**Impacto cuantificado del defecto 5.** Folio 756929 con CVA activado en el
motor v1:

```
mtm reportado                 = −5.093.613,84
spot_component + fwd_points   = −5.096.232,74
```

El MtM guardado deja de ser igual a la suma de sus componentes, de modo que la
propia descomposición contable queda inconsistente. Y `total_mtm` de la cartera
pasa a ser una mezcla de valor razonable y ajuste de crédito, imposible de
desagregar después.

**Comparación completa sobre la cartera Cordada:**

| Folio | MtM | CVA v1 | DVA v1 | CVA v2 | DVA v2 |
|---|---:|---:|---:|---:|---:|
| 756929 | −5.096.628,95 | 0,00 | 2.619,10 | 9.318,36 | 8.691,40 |
| 118039 | +2.592.812,56 | 1.548,49 | 0,00 | 27.065,83 | 14.780,90 |
| 116845 | −4.346.625,78 | 0,00 | 724,44 | 5.560,11 | 4.506,84 |
| **Total** | −6.850.442,17 | **1.548,49** | **3.343,54** | **41.944,30** | **27.979,14** |

**Cómo se resolvió en v2.** Modelo de intensidad de default con exposición
esperada en forma cerrada:

```python
# core/credit.py
@property
def hazard(self) -> float:
    """Intensidad de default implícita en el spread."""
    lgd = max(self.lgd, 1e-6)
    return (self.spread_bp / 10_000.0) / lgd

def survival(self, t_years: float) -> float:
    return math.exp(-self.hazard * max(t_years, 0.0))
```

```python
# core/credit.py
def expected_exposure(*, sign, strike, forward, notional, vol_abs, t_years, discount):
    """Exposición esperada positiva (EPE) y negativa (ENE) de un forward FX en t."""
    m = sign * (strike - forward) * notional * discount
    v = vol_abs * math.sqrt(max(t_years, 0.0)) * notional * discount
    if v <= 0:
        return max(m, 0.0), max(-m, 0.0)
    z = m / v
    epe = m * _Phi(z) + v * _phi(z)
    ene = -m * _Phi(-z) + v * _phi(-z)
    return epe, ene
```

Neteo sobre el conjunto de la contraparte:

```python
# core/credit.py
if netting:
    v = math.sqrt(netted_var)
    if v > 0:
        z = netted_value / v
        epe_set = netted_value * _Phi(z) + v * _phi(z)
        ene_set = -netted_value * _Phi(-z) + v * _phi(-z)
```

Spread y recovery por contraparte, no fijos:

```python
# valorizador/models.py
class Contraparte(TimeStampedModel):
    spread_bp = models.DecimalField('spread de crédito (bp)', ..., default=100,
                                    help_text='CDS o proxy por rating.')
    recovery = models.DecimalField('tasa de recuperación', ..., default=0.4)
    tiene_isda_neteo = models.BooleanField('contrato marco con neteo', default=True)
```

Y el MtM ya no se contamina: `mtm` y `mtm_ajustado` son campos separados en el
resultado, en el modelo y en la exportación.

```python
# core/valuation.py
lines[i]["mtm_ajustado"] = round(lines[i]["mtm"] - alloc["cva"] + alloc["dva"], 2)
```

---

### M-06 · `spot_inicio` poblado con el spot de la fecha de valorización

**Severidad: Alta · Estado en v2: Corregido**

**Qué encontré.** El cargador del libro asigna a **todos** los contratos el
tipo de cambio de la fecha de valorización como si fuera el spot del día en que
se pactó la operación.

**Dónde.** `valorizador/views.py`, línea 882.

**Evidencia.**

```python
# v1: valorizador/views.py:875-886
ContratoForward.objects.create(
    counterparty=str(contraparte).strip(),
    folio=folio_str,
    side=str(operacion).strip() if operacion else 'Venta',
    base_ccy=str(moneda).strip() if moneda else 'USD',
    notional=Decimal(str(round(float(monto), 2))),
    fwd_price=Decimal(str(round(float(precio_fwd), 4))) if precio_fwd else Decimal('0'),
    spot_inicio=Decimal(str(tc_spot)),        # ← tc_spot es el spot de HOY
    maturity_date=fecha_vcto,
    cartera=cartera,
    created_by=request.user,
)
```

`tc_spot` proviene de la celda `B5` de la hoja de valorización, que es el tipo de
cambio de la fecha de valorización (892,89 al 31-05-2026), no el del día de
suscripción de cada contrato.

**Por qué importa.** Con `S₀ = S_t`, el componente spot es idénticamente cero:

```
Componente spot = ε · (S₀ − S_t) · N · DF = 0
```

y por lo tanto todo el MtM se clasifica como puntos forward. La descomposición
que la aplicación muestra, exporta y guarda pierde completamente su sentido
económico y contable: bajo contabilidad de coberturas, el componente spot es la
reserva de cobertura en ORI y los puntos forward son el costo de la cobertura.
Ver `METODOLOGIA.md` §2.3.

**El dato existe en el libro.** La hoja de valorización tiene la columna
`H4: "Tipo de Cambio al Inicio del Contrato"`, con los valores correctos por
folio:

```
Ref     Tipo de Cambio al Inicio
756929  887,71
118039  894,25
116845  890,33
```

El cargador simplemente no la leía.

**Impacto cuantificado.** Con `S₀` correcto, folio 756929:

```
Componente spot = −5.162.209,39
Puntos forward  =     65.580,44
```

Con `S₀ = 892,89` (el que asignaba la v1):

```
Componente spot =          0,00
Puntos forward  = −5.096.628,95
```

El 100 % del resultado queda mal clasificado.

**Cómo se resolvió en v2.** El lector mapea el spot al inicio por folio desde la
propia hoja de valorización:

```python
# valorizador/services/cordada_excel.py
def _spot_inicio_por_folio(self) -> dict[str, float]:
    """Lee la columna 'Tipo de Cambio al Inicio' de la hoja de valorización."""
    ws = self._find_sheet(r'forwards\s+cordada')
    header_row, i_spot = self._locate_header(ws, r'tipo de cambio al inicio')
    _, i_ref = self._locate_header(ws, r'^ref$')
    if header_row is None or i_spot is None or i_ref is None:
        self.warnings.append(
            'No se pudo mapear el tipo de cambio al inicio por folio; el componente '
            'spot quedará en cero hasta que lo completes manualmente.'
        )
        return {}
    ...
```

Verificado: el lector extrae correctamente `887,71`, `894,25` y `890,33` para
los tres folios.

El formulario de alta manual además **exige** el dato:

```python
# valorizador/forms.py
if not data.get('spot_inicio'):
    self.add_error(
        'spot_inicio',
        'Indica el tipo de cambio del día en que se pactó la operación. '
        'Sin ese dato no se puede separar el resultado en componente spot y '
        'puntos forward.',
    )
```

Y el motor levanta una bandera cuando falta, en lugar de calcular en silencio:

```python
# core/valuation.py
if S0 <= 0:
    flags.append("Falta el tipo de cambio al inicio: la descomposición spot/puntos no es confiable")
```

---

### M-07 · Extrapolación plana de outrights implica diferencial de tasas nulo

**Severidad: Media · Estado en v2: Mitigado**

**Qué encontré.** La misma función `interp` que extrapola plano en la curva de
descuento lo hace también en la curva de outrights. En el extremo largo eso
tiene una implicación económica que probablemente nadie pretendía.

**Dónde.** `valorizador/services/interpolation.py`, líneas 16-17.

**Por qué importa.** Un outright constante más allá del último nodo implica
puntos forward constantes, y por la relación de paridad cubierta

```
p(d) = S · (d/360) · (r_CLP − r_USD) / (1 + r_USD · d/360)
```

un `p(d)` constante con `d` creciente exige que el diferencial `r_CLP − r_USD`
tienda a cero. Es decir: la extrapolación plana de outrights afirma
implícitamente que el diferencial de tasas colapsa en el largo plazo, algo que
contradice la propia curva de descuento del sistema (que sube de 3,48 % a 4,59 %
entre 92 y 1.825 días).

**Cómo se resolvió en v2.** La documentación del módulo lo declara
explícitamente y se agregó la política `Puntos`:

```python
# core/curves.py (docstring)
# 2. La extrapolación era siempre plana. Para una curva de forwards outright eso
#    es incorrecto: un outright plano más allá del último nodo implica que los
#    puntos forward dejan de crecer, es decir, un diferencial de tasas que
#    colapsa a cero. Se agrega la política `puntos` (mantiene constante la
#    pendiente de puntos forward), y se marca siempre el resultado como
#    extrapolado.
```

**Cerrado:** la rama `"Puntos"` ya tiene semántica propia —prolonga la pendiente
promedio entre el primer y el último nodo, no la del último segmento— y las tres
políticas dan resultados distintos (ver **P-01**). El aviso de extrapolación
funciona en ambos extremos de ambas curvas, que es lo que impide el error
silencioso.

---

### M-08 · Delta sin supuesto documentado, sin theta, "rho" mal nombrado

**Severidad: Media · Estado en v2: Corregido**

**Qué encontré.** El delta se calcula con una fórmula cerrada cuyo supuesto no
está documentado, no existe theta, y se llama "rho" a lo que es un DV01.

**Dónde.** `valorizador/services/valuation.py`, líneas 159-172.

**Evidencia.**

```python
# v1: valorizador/services/valuation.py:159-172
delta = 0.0
rho = 0.0
if calc_greeks:
    # Delta: change in MTM if spot increases by 1 unit
    # spot_component = signo * (spot_inicio - (spot_val + 1)) * notional * disc_factor
    delta = -1 * signo * notional * disc_factor

    # Rho: change in MTM if disc rate increases by 1 bp (0.01%)
    disc_rate_up = disc_rate + 0.01
    disc_factor_up = 1.0 / ((1.0 + disc_rate_up / 100.0) ** (days_to_mat / year_days))
    mtm_up = signo * (fwd_contract - fwd_bbg) * notional * disc_factor_up
    if calc_cva:
        mtm_up = mtm_up - (mtm_up * risk_proxy if mtm_up > 0 else 0) + (abs(mtm_up) * risk_proxy if mtm_up < 0 else 0)
    rho = mtm_up - mtm
```

**Problemas:**

1. **La fórmula del delta es correcta pero el supuesto no está declarado.**
   `−ε·N·DF` vale sólo si la curva de outrights se desplaza 1:1 con el spot
   manteniendo constantes los puntos forward. El comentario que acompaña la
   línea deriva la fórmula desde el *componente spot*, no desde el MtM, lo que
   sugiere que la coincidencia fue accidental.
2. **No hay theta.** El paso del tiempo es la principal fuente de variación de un
   forward con delta cubierto, y no se mide.
3. **No hay gamma declarada.** Que sea cero es una propiedad relevante del
   producto; omitirla no es lo mismo que declararla.
4. **Nomenclatura confusa.** "Rho" en la convención habitual designa la
   sensibilidad a la tasa libre de riesgo de una opción; lo que aquí se calcula
   es un DV01 respecto de la curva de descuento.
5. **Contaminación con CVA.** Si `calc_cva` está activo, el "rho" mezcla la
   sensibilidad de la tasa con la del ajuste de crédito.

**Agravante en la vista de detalle:** hay una segunda implementación de las
mismas fórmulas, replicada a mano para valorizaciones antiguas:

```python
# v1: valorizador/views.py:670-685
if total_delta == 0 and total_rho == 0 and lineas:
    for l in lineas:
        signo = 1 if l.side == 'Venta' else -1
        if l.notional and l.disc_factor:
            total_delta += -1 * signo * float(l.notional) * float(l.disc_factor)
            ...
            year_days = 360.0
            disc_rate_up = float(l.disc_rate or 0) + 0.01
```

Dos implementaciones de la misma fórmula, con `year_days` fijo en 360 en la
segunda, ignorando la convención con la que se corrió la valorización original.

**Cómo se resolvió en v2.** Todas las sensibilidades por bump y revaluación con
el mismo código de valorización, y el supuesto declarado en el comentario:

```python
# core/valuation.py
if config.calc_greeks:
    # Delta: la curva de outrights se desplaza 1:1 con el spot manteniendo
    # constantes los puntos forward. Se calcula por bump y revaluación para
    # que sea consistente con el resto del motor.
    f_up = fwd_curve.shifted(additive=1.0).value(days_to_mat)
    mtm_spot_up = eps * (K - f_up) * N * df
    delta = mtm_spot_up - mtm

    bump_pct = St * 0.01
    f_up_pct = fwd_curve.shifted(additive=bump_pct).value(days_to_mat)
    delta_pct = eps * (K - f_up_pct) * N * df - mtm

    disc_up = disc_curve.shifted_bp(1.0)
    df_up = disc_up.factor(days_to_mat, year_fraction)
    dv01 = eps * (K - F) * N * df_up - mtm

    # Theta: un día de paso del tiempo con curvas congeladas.
    theta = _theta_one_day(contract, market, config, fwd_curve, disc_curve, mtm)
```

Gamma se declara explícitamente:

```python
# core/valuation.py
"gamma": 0.0,  # el payoff es lineal en el forward: gamma exacta = 0
```

`rho` se mantiene como alias retrocompatible de `dv01`. Verificación empírica de
la consistencia:

```
MtM(S−1) = −1.864.084,37
MtM(S)   = −6.850.442,17
MtM(S+1) = −11.836.799,98

Delta por diferencias centradas = −4.986.357,81
Delta reportado por el motor    = −4.986.357,81
Gamma empírica = MtM(S+1) − 2·MtM(S) + MtM(S−1) = −0,01   (ruido de redondeo)
```

Y theta aporta información nueva: el folio 116845 tiene theta de −17.527,38
frente a −1.445,45 del folio 756929, pese a tener MtM similares, porque rueda
sobre un tramo de la curva nueve veces más empinado.

---

### M-09 · Curvas sin ordenar ni deduplicar

**Severidad: Media · Estado en v2: Corregido**

**Qué encontré.** El motor asume que los nodos vienen ordenados por plazo y sin
duplicados, sin verificarlo.

**Dónde.** `valorizador/services/interpolation.py` (usa `np.interp`, cuyo
comportamiento con `xp` no monótono es indefinido) y
`valorizador/services/valuation.py`, líneas 114-115.

**Evidencia.**

```python
# v1: valorizador/services/valuation.py:114-115
fwd_xs, fwd_ys = fwd_curve['xs'], fwd_curve['ys']
disc_xs, disc_ys = disc_curve['xs'], disc_curve['ys']
```

El orden depende de la consulta que arma el diccionario:

```python
# v1: valorizador/services/valuation.py:248
puntos = PuntoCurva.objects.filter(conjunto=conjunto).order_by('nombre', 'tenor_days')
```

Funciona por casualidad. Pero nada impide cargar dos nodos con el mismo plazo
—no hay restricción de unicidad en el modelo v1— y en ese caso las
comprobaciones de rango (`xs[0]`, `xs[-1]`) y la interpolación producen
resultados arbitrarios sin ninguna señal.

**Cómo se resolvió en v2.** Normalización en el constructor de la curva:

```python
# core/curves.py
def __post_init__(self):
    if len(self.xs) != len(self.ys):
        raise ValueError(f"Curva '{self.name}': plazos y valores de distinto largo.")
    if not self.xs:
        raise ValueError(f"Curva '{self.name}': sin nodos.")
    ...
    # Ordena y colapsa nodos duplicados quedándose con el último valor.
    merged: dict[float, float] = {}
    for x, y in zip(self.xs, self.ys):
        merged[float(x)] = float(y)
    pairs = sorted(merged.items())
    self.xs = [p[0] for p in pairs]
    self.ys = [p[1] for p in pairs]
```

Y una restricción a nivel de base de datos:

```python
# valorizador/models.py
models.UniqueConstraint(
    fields=['conjunto', 'nombre', 'tenor_days'], name='punto_unico_por_curva',
)
```

El importador además informa cuántos plazos colapsó.

---

### M-10 · Convención de días desconocida cae silenciosamente en base 360

**Severidad: Baja · Estado en v2: Corregido**

**Evidencia.**

```python
# v1: valorizador/services/valuation.py:34-41
if day_count == 'ACT/365':
    year_days = 365.0
elif day_count == '30/360':
    year_days = 360.0
else:
    year_days = 360.0        # ← cualquier cosa cae acá
```

Un valor mal escrito en el POST (`'ACT/365 '` con espacio, `'act/365'` en
minúsculas) se convierte silenciosamente en ACT/360.

**Cómo se resolvió en v2.** Validación explícita con error:

```python
# core/daycount.py
raise ValueError(
    f"Convención '{convention}' desconocida. Disponibles: {DAY_COUNT_CONVENTIONS}"
)
```

```python
# core/valuation.py
def validate(self) -> None:
    if self.day_count not in DAY_COUNT_CONVENTIONS:
        raise ValueError(f"day_count '{self.day_count}' no soportado.")
    ...
```

Y el formulario sólo ofrece valores de la tupla canónica.

---

## 4. Hallazgos de robustez y calidad

### R-01 · La carga del libro Cordada está rota

**Severidad: Alta · Estado en v2: Corregido**

**Qué encontré.** La vista `upload_excel` importa `ExcelLoader`, cuyo módulo
importa tres modelos que **no existen** en `models.py`. La importación lanza
`ImportError` que queda capturado por un `except Exception` genérico, de modo que
la funcionalidad falla siempre, en silencio, con un mensaje incomprensible.

**Dónde.** `valorizador/views.py`, línea 783, y
`valorizador/services/excel_loader.py`, línea 4.

**Evidencia.**

```python
# v1: valorizador/services/excel_loader.py:4
from ..models import Valorizacion, CurvaForward, CurvaDescuento, ContratoForward
```

Modelos efectivamente definidos en `valorizador/models.py`:

```
ConjuntoCurvas, PuntoCurva, Cartera, ContratoForward,
ValorizacionGuardada, LineaValorizacion
```

`Valorizacion`, `CurvaForward` y `CurvaDescuento` **no existen**. Son nombres de
una versión anterior del modelo de datos que nunca se actualizó.

La importación ocurre dentro del bloque `try` de la vista:

```python
# v1: valorizador/views.py:778-784
try:
    import tempfile, os
    with tempfile.NamedTemporaryFile(delete=False, suffix='.xlsm') as tmp:
        for chunk in archivo.chunks():
            tmp.write(chunk)
        tmp_path = tmp.name

    from .services.excel_loader import ExcelLoader     # ← ImportError garantizado
    loader = ExcelLoader(tmp_path, user=request.user)
```

y el manejador la convierte en un mensaje al usuario:

```python
# v1: valorizador/views.py:894-895
except Exception as e:
    messages.error(request, f'Error: {e}')
```

**Agravante:** la variable `loader` nunca se usa. Las líneas siguientes vuelven
a abrir el archivo con `openpyxl` directamente. El import es enteramente
innecesario y es lo único que rompe la funcionalidad.

**Por qué importa.** La carga del libro Cordada es la funcionalidad principal
del sistema: es lo que conecta la planilla operativa con la aplicación. **Nunca
funcionó.** El usuario recibe un mensaje como
`Error: cannot import name 'Valorizacion' from 'valorizador.models'` sin ninguna
indicación de qué hacer. Y como el error no se registra en el log, la falla es
invisible para quien opera el sistema.

Además, el archivo temporal queda en el disco porque `os.unlink` está después
del punto de falla (**R-10**).

**Cómo se resolvió en v2.** El lector es una clase autocontenida que no importa
modelos:

```python
# valorizador/services/cordada_excel.py
class CordadaWorkbook:
    """Extrae curvas, spot, fecha y contratos de un libro Cordada."""

    def __init__(self, path_or_file):
        import openpyxl
        self.wb = openpyxl.load_workbook(path_or_file, data_only=True)
        self.warnings: list[str] = []
```

La persistencia ocurre en la vista, dentro de una transacción, y los errores se
registran con traza:

```python
# valorizador/views.py
except Exception as exc:
    log.exception('Error procesando libro Cordada')
    messages.error(request, f'No se pudo procesar el libro: {exc}')
    return {'ok': False, 'avisos': [str(exc)]}
finally:
    try:
        os.unlink(tmp_path)
    except OSError:
        pass
```

Verificado en ejecución: el lector v2 extrae correctamente del libro real la
fecha (2026-05-31), el spot (892,89), 2 curvas con 28 y 18 nodos, y los 3
contratos con su spot al inicio.

---

### R-02 · Cero tests

**Severidad: Alta · Estado en v2: Corregido**

**Qué encontré.** El repositorio no contiene ningún test. No hay directorio
`tests/`, ni archivos `test_*.py`, ni `pytest.ini`, ni `conftest.py`, ni
configuración de integración continua.

**Evidencia.**

```
$ find . -iname 'test*.py' -o -iname 'conftest*' -o -iname 'pytest*' | grep -v '.git/'
(sin resultados)
```

El único archivo con "test" en el nombre es `test_curvas_fwd.xlsx`, un libro de
datos.

**Por qué importa.** Sin tests:

- Los hallazgos **M-01** a **M-05** habrían sido detectados por un único test de
  reconciliación contra la planilla.
- El hallazgo **R-01** habría sido detectado por cualquier test que importara el
  módulo.
- No hay forma de refactorizar sin riesgo.
- No hay forma de demostrar que un cambio no rompió un cálculo.

Para un sistema que produce cifras que entran a estados financieros, la ausencia
de pruebas automatizadas es en sí misma un hallazgo de control interno.

**Cómo se resolvió en v2.** Suite de **337 tests, todos en verde**, repartidos
entre el motor y la aplicación:

```
$ python -m pytest
337 passed, 338 subtests passed in 22.16s
```

| Archivo | Tests | Qué cubre |
|---|---:|---|
| `core/tests/test_valuation.py` | 54 | MtM, descomposición, banderas, griegas, cartera, escenarios, reconciliación Cordada |
| `core/tests/test_curves.py` | 39 | Interpolación, extrapolación, factores, curvas degeneradas |
| `core/tests/test_calendars.py` | 33 | Feriados chilenos y de EE.UU., reglas de traslado, convenciones de ajuste |
| `core/tests/test_credit.py` | 25 | Exposición esperada, supervivencia, neteo, asignación por operación |
| `core/tests/test_daycount.py` | 24 | Las cinco convenciones y los casos donde difieren |
| `valorizador/tests/test_views.py` | 45 | Aislamiento por usuario, flujo completo, filtros, validación |
| `valorizador/tests/test_importers.py` | 48 | Parseo de números y fechas, informe de errores por fila |
| `valorizador/tests/test_models.py` | 26 | Restricciones, `for_user`, adaptadores `to_core`/`as_curves` |
| `valorizador/tests/test_commands.py` | 17 | `cargar_demo` y sus valores de referencia |
| `valorizador/tests/test_cordada_excel.py` | 13 | Lectura del libro por patrón y por encabezado |
| `valorizador/tests/test_format_tags.py` | 13 | Formatos chilenos |
| **Total** | **337** | 175 en el motor, 162 en la aplicación |

Los 175 tests de `core/tests/` **no necesitan base de datos**: el motor recibe
*dataclasses* y devuelve diccionarios. Es el beneficio directo de haberlo
separado de Django.

Las seis áreas críticas que este informe identificó están cubiertas: la
reconciliación Cordada al centavo, las convenciones de días con casos donde
difieren, las tres políticas de extrapolación, los feriados chilenos de 2026, el
aislamiento por usuario en cada ruta con `<pk>`, y la exposición esperada
positiva de un forward at-the-money.

Infraestructura:

```ini
# pytest.ini
[pytest]
DJANGO_SETTINGS_MODULE = config.settings
python_files = test_*.py
addopts = -q
```

> **Nota operativa.** El proyecto usa
> `CompressedManifestStaticFilesStorage`, de modo que hay que ejecutar
> `python manage.py collectstatic --noinput` antes de correr los tests de
> vistas; sin eso fallan con
> `ValueError: Missing staticfiles manifest entry`.

**Pendiente menor:** `accounts/tests/` sigue vacío, de modo que el límite de
intentos de login no tiene cobertura propia (hallazgo **P-06**).

---

### R-03 · `if 'sensibilidad' in locals()` y variables potencialmente sin asignar

**Severidad: Alta · Estado en v2: Corregido**

**Qué encontré.** La vista de valorización pasa datos al template inspeccionando
el espacio de nombres local en tiempo de ejecución.

**Dónde.** `valorizador/views.py`, líneas 564-583.

**Evidencia.**

```python
# v1: valorizador/views.py:564-583
context = {
    'conjuntos': conjuntos,
    'contratos': contratos,
    ...
    'sensibilidad': getattr(request, '_sensibilidad', None)
}

if 'sensibilidad' in locals():
    context['sensibilidad'] = sensibilidad

return render(request, 'valorizador/valorizar.html', context)
```

Dos problemas en cuatro líneas:

1. `getattr(request, '_sensibilidad', None)` es código muerto: nada asigna
   `_sensibilidad` al objeto `request` en ninguna parte del proyecto.
2. `if 'sensibilidad' in locals()` es introspección del espacio de nombres para
   sustituir un flujo de control explícito. La variable `sensibilidad` se asigna
   sólo dentro de un `try` anidado en dos condicionales (líneas 540-541).

Además, en la rama `POST` con formulario incompleto, varias variables quedan
definidas sólo por casualidad: `selected_etiqueta` se asigna en la línea 495 y
`shock_max` en la 514-517, ambas dentro del bloque `if request.method == 'POST'`.
Si en el futuro alguien agrega un `return` temprano, se producirá un
`UnboundLocalError`.

**Por qué importa.** El código es frágil y opaco. Es imposible razonar sobre qué
recibe el template sin simular la ejecución mentalmente. Y `locals()` no está
garantizado por el modelo de datos de Python como una API estable para este uso.

**Cómo se resolvió en v2.** Flujo explícito, con las variables inicializadas
antes de cualquier bifurcación:

```python
# valorizador/views.py
result = sensibilidad = None
contratos_qs = ContratoForward.objects.for_user(user).filter(status='Vigente')

if request.method == 'POST':
    form = ValorizarForm(request.POST, user=user)
    if form.is_valid():
        ...
        try:
            result = price_portfolio([c.to_core() for c in elegidos], market, config)
            result['conjunto_id'] = conjunto.pk
            sensibilidad = sensitivity_matrix(...)
        except Exception as exc:
            log.exception('Error al valorizar')
            messages.error(request, f'Error al valorizar: {exc}')
    else:
        messages.error(request, 'Revisa los parámetros del formulario.')
else:
    form = ValorizarForm(initial=initial, user=user)
    contratos_qs = contratos_qs.filter(base_ccy='USD')

return render(request, 'valorizador/valorizar.html', {
    'form': form, 'contratos': contratos_qs, 'result': result, ...
})
```

---

### R-04 · El importador descarta filas en silencio

**Severidad: Media · Estado en v2: Corregido**

**Qué encontré.** El importador de CSV/Excel descarta cualquier fila que no
pueda interpretar, sin registrar ni informar el motivo. Un archivo con un
encabezado mal escrito importa cero contratos y el usuario no sabe por qué.

**Dónde.** `valorizador/services/csv_loader.py`, líneas 216-228.

**Evidencia.**

```python
# v1: valorizador/services/csv_loader.py:216-228
for row in rows:
    notional = parse_number(find_col(row, ['notional', 'monto', 'nominal', 'amount']), 'amount')
    fwd_price = parse_number(find_col(row, ['fwd_price', 'precio fwd', ...]))
    mat_date = parse_date(find_col(row, ['maturity_date', 'vcto', 'vencimiento', ...]))

    if notional is None or fwd_price is None or mat_date is None:
        continue                                    # ← sin registro

    side = parse_side(find_col(row, ['side', 'operacion', ...]))
    if side is None:
        continue                                    # ← sin registro
```

El único mensaje que recibe el usuario es genérico:

```python
# v1: valorizador/views.py:441
messages.error(request, 'No se detectaron contratos válidos.')
```

**Por qué importa.** Un archivo con la columna "Vencimiento" escrita
"Fecha de término" importa cero filas. El usuario no tiene forma de saber si el
problema es el formato de fecha, el nombre de la columna, el separador decimal o
el delimitador. En la práctica esto lleva a cargar los datos a mano, que es lo
que la funcionalidad venía a evitar.

**Cómo se resolvió en v2.** Cada importación devuelve `(filas, errores)` con el
motivo por fila y el número de línea:

```python
# valorizador/services/importers.py
if notional is None:
    motivos.append('falta el monto')
elif notional <= 0:
    motivos.append(f'monto no positivo ({notional})')
if fwd_price is None:
    motivos.append('falta el precio forward')
...
if motivos:
    errors.append(f'Fila {i} descartada: ' + '; '.join(motivos) + '.')
    continue
```

Con avisos adicionales de calidad de datos:

```python
# valorizador/services/importers.py
if curve_type != 'forward' and points:
    vals = [p['value'] for p in points]
    if vals and max(abs(v) for v in vals) < 0.5:
        errors.append(
            'Aviso: las tasas parecen venir en fracción (0,0348) en vez de '
            'porcentaje (3,48). Revisa las unidades antes de guardar.'
        )
```

```python
# valorizador/services/importers.py
if spot_inicio <= 0:
    errors.append(
        f'Fila {i}: sin tipo de cambio al inicio. Se importa igual, pero la '
        f'descomposición en componente spot y puntos forward quedará en cero.'
    )
```

Y la vista los muestra:

```python
# valorizador/views.py
for e in errores:
    messages.warning(request, e)
```

---

### R-05 · Nombres de hoja y coordenadas de celda fijos en el código

**Severidad: Media · Estado en v2: Corregido**

**Qué encontré.** El cargador del libro depende de nombres de hoja que incluyen
el día del mes y de coordenadas de celda absolutas.

**Dónde.** `valorizador/views.py`, líneas 795, 797, 800, 808, 828, 837, 851-868.

**Evidencia.**

```python
# v1: valorizador/views.py:794-802
for sn in wb.sheetnames:
    if 'Forwards Cordada 31' in sn or 'Forwards Cordada' in sn:
        ws = wb[sn]
        b5 = ws['B5'].value                    # ← celda fija
        ...
        c1 = ws['C1'].value                    # ← celda fija
```

```python
# v1: valorizador/views.py:806-810
ws_datos = wb['Datos'] if 'Datos' in wb.sheetnames else None
if ws_datos:
    d7 = ws_datos['D7'].value                  # ← celda fija
```

```python
# v1: valorizador/views.py:828,837
for row in ws_cm.iter_rows(min_row=2, max_row=29, min_col=1, max_col=2, values_only=True):
...
for row in ws_cm.iter_rows(min_row=2, max_row=29, min_col=3, max_col=4, values_only=True):
```

```python
# v1: valorizador/views.py:852-868
contraparte = row[0].value
folio = row[1].value
fecha_vcto_raw = row[7].value                  # ← índices posicionales fijos
monto = row[9].value
moneda = row[10].value
precio_fwd = row[11].value
...
operacion = row[4].value if len(row) > 4 else None
```

**Por qué importa.** La hoja del libro real se llama `Forwards Cordada 31-05`.
El libro del mes siguiente se llamará `Forwards Cordada 30-06`, y aunque el
segundo patrón `'Forwards Cordada'` lo capture, cualquier cambio de posición de
columna o de fila rompe la carga. El límite `max_row=29` de `CURVE MASTER`
trunca las curvas si se agregan plazos: en el libro real la curva forward tiene
**28 nodos**, con lo que el margen es de una sola fila.

Y las fallas son silenciosas: filas que no cumplen las condiciones se saltan con
`continue`, sin registro.

**Cómo se resolvió en v2.** Localización por patrón y por encabezado:

```python
# valorizador/services/cordada_excel.py
def _find_sheet(self, *patterns: str):
    for pat in patterns:
        rx = re.compile(pat, re.IGNORECASE)
        for name in self.wb.sheetnames:
            if rx.search(name):
                return self.wb[name]
    return None
```

```python
# valorizador/services/cordada_excel.py
@staticmethod
def _locate_header(ws, pattern: str, max_row: int = 12):
    rx = re.compile(pattern, re.IGNORECASE)
    for r_i, row in enumerate(ws.iter_rows(min_row=1, max_row=max_row, values_only=True), 1):
        for c_i, cell in enumerate(row):
            if isinstance(cell, str) and rx.search(cell):
                return r_i, c_i
    return None, None
```

Las columnas de contratos se ubican por nombre de encabezado, con búsqueda
exacta primero y parcial después. Las curvas se leen hasta que se acaban los
datos y se detectan **todos** los pares `dia_X` / `c_X`, no sólo los dos
primeros:

```python
# valorizador/services/cordada_excel.py
m = re.match(r'^dia[_\s]*(.+)$', h, re.IGNORECASE)
if not m or i + 1 >= len(headers):
    continue
curve_name = m.group(1).strip().upper()
```

Y cada cosa que no se encuentra genera un aviso visible:

```python
# valorizador/services/cordada_excel.py
self.warnings.append("No se encontró la hoja 'CURVE MASTER'.")
self.warnings.append("'CURVE MASTER' no tenía pares (dia_X, c_X) reconocibles.")
self.warnings.append('La hoja de contratos vigentes no tenía filas utilizables.')
```

---

### R-06 · Lectura de `request.POST['campo']` sin validación

**Severidad: Media · Estado en v2: Corregido**

**Qué encontré.** Los objetos se construyen leyendo directamente el diccionario
`request.POST`, dentro de un `except Exception` genérico que muestra el error
crudo de Python.

**Dónde.** `valorizador/views.py`, líneas 368-393.

**Evidencia.**

```python
# v1: valorizador/views.py:368-393
if request.method == 'POST':
    try:
        cartera_id = request.POST.get('cartera_id')
        cartera = Cartera.objects.filter(id=cartera_id).first() if cartera_id else None

        ContratoForward.objects.create(
            counterparty=request.POST['counterparty'],
            folio=request.POST.get('folio', ''),
            side=request.POST['side'],
            ...
            notional=Decimal(request.POST['notional']),
            fwd_price=Decimal(request.POST['fwd_price']),
            spot_inicio=Decimal(request.POST.get('spot_inicio', '0')),
            start_date=request.POST.get('start_date') or None,
            maturity_date=request.POST['maturity_date'],
            ...
        )
        messages.success(request, 'Contrato agregado.')
        return redirect('contratos_list')
    except Exception as e:
        messages.error(request, f'Error: {e}')
```

Consecuencias concretas:

| Entrada | Resultado |
|---|---|
| Nocional negativo | Se guarda; el motor lo excluye después con una bandera |
| `notional = "abc"` | `decimal.InvalidOperation: [<class 'decimal.ConversionSyntax'>]` en pantalla |
| Campo `counterparty` ausente | `MultiValueDictKeyError: 'counterparty'` en pantalla |
| Vencimiento anterior al inicio | Se guarda sin objeción |
| `side = "cualquier cosa"` | Se guarda; el motor lo interpreta como Compra |
| `cartera_id` de otro usuario | La cartera ajena se asigna al contrato (línea 371 no filtra por dueño) |

**Cómo se resolvió en v2.** `ModelForm` con validación declarativa, más
restricciones en la base de datos:

```python
# valorizador/forms.py
class ContratoForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = ContratoForward
        fields = [...]

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        if user is not None:
            self.fields['cartera'].queryset = Cartera.objects.filter(created_by=user)
            self.fields['contraparte_ref'].queryset = Contraparte.objects.filter(created_by=user)

    def clean(self):
        data = super().clean()
        start, mat = data.get('start_date'), data.get('maturity_date')
        if start and mat and mat < start:
            self.add_error('maturity_date', 'El vencimiento no puede ser anterior al inicio.')
        ...
```

El *queryset* de cartera acotado al usuario cierra además la asignación de
carteras ajenas.

---

### R-07 · La dependencia declarada no es la que el código importa

**Severidad: Media · Estado en v2: Corregido**

**Qué encontré.** `requirements.txt` declara `google-genai`, pero el código
importa `google.generativeai`, que es el módulo del paquete
`google-generativeai`. Son dos SDK distintos con APIs incompatibles.

**Dónde.** `/requirements.txt` línea 7 y `valorizador/views.py` línea 902.

**Evidencia.**

```
# v1: requirements.txt
google-genai>=0.2.0
```

```python
# v1: valorizador/views.py:902
import google.generativeai as genai
```

```python
# v1: valorizador/views.py:985-988
model = genai.GenerativeModel(
    'gemini-2.5-flash',
    system_instruction=system_instruction
)
```

`genai.GenerativeModel` y `model.start_chat` pertenecen a la API de
`google-generativeai`. El SDK `google-genai` usa `genai.Client()`.

**Por qué importa.** Un despliegue limpio que instale exactamente
`requirements.txt` falla al importar el módulo. El import está en el nivel
superior del archivo `views.py` (línea 902), de modo que el error se produce al
cargar el módulo de vistas: **la aplicación completa no arranca**, no sólo el
asistente. En el entorno del desarrollador funcionaba porque el paquete correcto
estaba instalado por otra vía.

**Cómo se resolvió en v2.** Dependencia correcta y declarada como opcional:

```
# requirements.txt
# Asistente opcional. Si no se instala, la app funciona igual: el endpoint
# devuelve 503 y el widget no se muestra.
google-generativeai>=0.8.0
```

Y el import es local a la vista, con degradación elegante:

```python
# valorizador/views.py
try:
    import google.generativeai as genai
except ImportError:
    return JsonResponse(
        {'error': 'Falta la dependencia google-generativeai en el servidor.'}, status=503
    )
```

Así, la ausencia del paquete afecta sólo al asistente, no a la aplicación.

---

### R-08 · Sin índices de base de datos

**Severidad: Media · Estado en v2: Corregido**

**Qué encontré.** Ningún modelo declara índices, pese a que todas las consultas
filtran por los mismos campos.

**Dónde.** `valorizador/models.py`, bloques `class Meta` de todos los modelos.

**Evidencia.**

```python
# v1: valorizador/models.py:90-93
class Meta:
    ordering = ['maturity_date']
    verbose_name = 'Contrato forward'
    verbose_name_plural = 'Contratos forward'
```

No hay `indexes`, ni `db_index=True` en ningún campo, ni `constraints`. Las
consultas recurrentes son `filter(status='Vigente')`, `filter(created_by=...)`,
`filter(cartera_id=...)` y `order_by('maturity_date')`.

**Por qué importa.** Con las decenas de registros de la base actual es
irrelevante. Con una cartera de miles de contratos y varios usuarios, cada carga
del panel implica recorridos completos de tabla. Es deuda técnica barata de
pagar ahora y cara después.

**Cómo se resolvió en v2.** Índices compuestos alineados con el patrón real de
consulta:

```python
# valorizador/models.py
indexes = [models.Index(fields=['created_by', 'status', 'maturity_date'])]   # ContratoForward
indexes = [models.Index(fields=['created_by', '-valuation_date'])]           # ConjuntoCurvas
```

Más las restricciones de integridad:

```python
# valorizador/models.py
constraints = [
    models.CheckConstraint(condition=models.Q(notional__gt=0), name='notional_positivo'),
    models.CheckConstraint(condition=models.Q(fwd_price__gt=0), name='precio_fwd_positivo'),
]
```

---

### R-09 · Llamada a servicio externo dentro de la petición

**Severidad: Media · Estado en v2: Corregido**

**Qué encontré.** La vista de creación de curvas llama a un servicio externo
(`mindicador.cl`) de forma síncrona para precargar el spot, sin caché.

**Dónde.** `valorizador/views.py`, líneas 108-115 y 127-139.

**Evidencia.**

```python
# v1: valorizador/views.py:108-115
spot_default = ''
try:
    r = urllib.request.urlopen('https://mindicador.cl/api/dolar', timeout=5)
    data = json.loads(r.read())
    if data.get('serie'):
        spot_default = str(round(data['serie'][0]['valor'], 2))
except Exception:
    pass
```

```python
# v1: valorizador/views.py:127-139
@login_required
def fetch_dolar_spot(request):
    """AJAX endpoint to fetch current USD/CLP from mindicador.cl."""
    try:
        r = urllib.request.urlopen('https://mindicador.cl/api/dolar', timeout=5)
        ...
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)
```

**Problemas:**

1. Cada visita a `/curvas/crear/` bloquea hasta 5 segundos si el servicio
   externo está lento. Con varios usuarios se agotan los *workers* de gunicorn.
2. Sin caché: `N` visitas producen `N` llamadas al servicio de un tercero.
3. El primer bloque traga la excepción con `pass`: si el servicio cambia de
   formato, el campo aparece vacío sin ninguna explicación.
4. El segundo devuelve `str(e)` al cliente (**S-11**).
5. El valor obtenido es el Dólar Observado publicado, que no necesariamente es
   el tipo de cambio con el que se debe valorizar (que en la planilla es el
   spot de la fecha, celda `B5`). Sustituir uno por otro introduce un error de
   datos.

**Cómo se resolvió en v2.** La funcionalidad se eliminó. El spot se toma del
conjunto de curvas o lo ingresa el usuario explícitamente:

```python
# valorizador/forms.py
spot_val = forms.DecimalField(
    label='Tipo de cambio de valorización', max_digits=12, decimal_places=4,
    required=False,
    help_text='Si lo dejas vacío se usa el spot del conjunto de curvas.',
)
```

Si se quisiera reincorporar la precarga automática, debe hacerse con caché de al
menos un día y fuera del camino crítico de la petición.

---

### R-10 · Archivo temporal no se elimina si ocurre una excepción

**Severidad: Baja · Estado en v2: Corregido**

**Evidencia.**

```python
# v1: valorizador/views.py:778-895
try:
    with tempfile.NamedTemporaryFile(delete=False, suffix='.xlsm') as tmp:
        ...
        tmp_path = tmp.name
    ...
    os.unlink(tmp_path)            # ← línea 888, sólo se alcanza si todo salió bien
    ...
except Exception as e:
    messages.error(request, f'Error: {e}')
```

Combinado con **R-01** (la carga **siempre** falla), cada intento de subir el
libro deja un archivo de 3 MB en `/tmp` que nunca se borra.

**Cómo se resolvió en v2.** Bloque `finally`:

```python
# valorizador/views.py
finally:
    try:
        os.unlink(tmp_path)
    except OSError:
        pass
```

---

### R-11 · `except:` desnudo

**Severidad: Baja · Estado en v2: Corregido**

**Evidencia.**

```python
# v1: valorizador/views.py:656-661
config = {}
if val.config_json:
    try:
        config = json.loads(val.config_json)
    except:
        pass
```

Un `except:` sin tipo captura también `KeyboardInterrupt` y `SystemExit`.

**Cómo se resolvió en v2.** El campo es `JSONField`, de modo que no hay que
deserializar a mano:

```python
# valorizador/models.py
config_json = models.JSONField('configuración', default=dict)
```

```python
# valorizador/views.py
'config': val.config_json or {},
```

---

### R-12 · NumPy para interpolar linealmente entre dos puntos

**Severidad: Baja · Estado en v2: Corregido**

**Evidencia.**

```
# v1: requirements.txt
numpy>=1.24.0
```

```python
# v1: valorizador/services/interpolation.py:1-18
import numpy as np

def interp(x, xs, ys):
    xs = np.array(xs, dtype=float)
    ys = np.array(ys, dtype=float)
    ...
    return float(np.interp(x, xs, ys))
```

NumPy es el único uso de la biblioteca en todo el proyecto, para una operación
de dos líneas. Además, convertir listas a `ndarray` en cada llamada, dentro del
bucle de valorización de una cartera, es más lento que la aritmética directa.

**Cómo se resolvió en v2.** `core/` usa exclusivamente la biblioteca estándar
(`math`, `bisect`, `datetime`, `dataclasses`, `functools`). NumPy no está en
`requirements.txt`.

```python
# core/curves.py
from bisect import bisect_left
...
i = bisect_left(xs, x)
if i < len(xs) and xs[i] == x:
    return ys[i]
x0, x1 = xs[i - 1], xs[i]
y0, y1 = ys[i - 1], ys[i]
w = (x - x0) / (x1 - x0)
```

---

### R-13 · Coincidencia parcial de encabezados puede enlazar la columna equivocada

**Severidad: Baja · Estado en v2: Mitigado**

**Qué encontré.** El importador busca columnas primero por coincidencia exacta y
luego por coincidencia parcial en cualquier dirección.

**Dónde.** `valorizador/services/csv_loader.py`, líneas 23-32.

**Evidencia.**

```python
# v1: valorizador/services/csv_loader.py:23-32
# Partial match
for cand in candidates:
    cn = normalize(cand)
    if len(cn) < 3:
        continue
    for k in keys:
        kn = normalize(k)
        if cn in kn or kn in cn:
            return row[k]
```

Con el libro Cordada, buscar `'monto'` como candidato de nocional puede enlazar
`"Monto FWD Contrato"` o `"Monto FWD BBG"` si el orden de las columnas cambia,
porque `'monto' in 'monto fwd contrato'` es verdadero. El resultado sería un
nocional 887 veces mayor que el real, sin ninguna alarma.

Además, `parse_number(val, kind='rate')` declara un parámetro `kind` que nunca se
usa en el cuerpo de la función.

**Cómo se resolvió en v2.** Se mantiene la estrategia de dos fases (exacta y
luego parcial), que es necesaria para tolerar variaciones reales de encabezado,
pero ahora la fila descartada o dudosa se informa, y cuando se recurre al
respaldo posicional se avisa explícitamente:

```python
# valorizador/services/importers.py
if used_positional and points:
    errors.append(
        'Aviso: no se reconocieron los encabezados; se usó la primera columna '
        'como plazo y la segunda como valor.'
    )
```

**Mitigado, no cerrado.** La coincidencia parcial sigue pudiendo enlazar una
columna equivocada. El control efectivo es la vista previa antes de confirmar la
importación, que muestra los valores interpretados fila por fila.

---

## 5. Acciones inmediatas para el dueño del repositorio

Las tres primeras son urgentes y deben ejecutarse **en este orden**. Revocar la
clave antes de reescribir el historial: mientras la clave siga siendo válida, la
reescritura no aporta seguridad porque el contenido ya fue clonado e indexado.

### Paso 1 — Revocar la clave de Gemini (ahora)

1. Entrar a [Google AI Studio](https://aistudio.google.com/apikey) o a la consola
   de Google Cloud del proyecto asociado.
2. Localizar la clave `AIzaSyAVMjrurDuxqYhiEnn3xIcgamUHfbFVUWI` y **eliminarla**.
   No basta con restringirla.
3. Generar una clave nueva y guardarla únicamente en el `.env` local y en el
   gestor de secretos del entorno de despliegue.
4. Revisar la facturación y las métricas de uso del proyecto desde el
   2026-08-06 (fecha del commit) para detectar consumo no autorizado.
5. Aplicar restricciones a la clave nueva: por API, y por dirección IP si el
   despliegue tiene IP fija.

```bash
# Verificar que la clave antigua ya no funciona
curl -s -o /dev/null -w "%{http_code}\n" \
  "https://generativelanguage.googleapis.com/v1beta/models?key=AIzaSyAVMjrurDuxqYhiEnn3xIcgamUHfbFVUWI"
# Debe devolver 400 o 403, no 200
```

### Paso 2 — Rotar el resto de las credenciales

- Cambiar la contraseña del usuario `admin` de la base de datos versionada, y de
  cualquier cuenta que comparta esa contraseña.
- Generar una `SECRET_KEY` nueva. La del repositorio
  (`django-insecure-default-secret-key-for-dev`) es pública y permite falsificar
  sesiones y tokens de recuperación de contraseña.

```bash
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

- Invalidar las sesiones activas tras cambiar la clave:

```bash
python manage.py clearsessions
```

### Paso 3 — Purgar el historial de git

Requiere [`git-filter-repo`](https://github.com/newren/git-filter-repo).

```bash
# 1. Instalar la herramienta
pip install git-filter-repo

# 2. Trabajar sobre un clon fresco y espejado (git-filter-repo lo exige)
cd /tmp
git clone --mirror https://github.com/gafarina/forward.git forward-limpio.git
cd forward-limpio.git

# 3. Respaldo antes de tocar nada
cp -r /tmp/forward-limpio.git /tmp/forward-respaldo.git

# 4. Eliminar del historial completo los archivos sensibles
git filter-repo --force \
  --invert-paths \
  --path .env \
  --path db.sqlite3 \
  --path "06052026 CalculadoraForward Cordada_v2.xlsm" \
  --path contratos.xlsx \
  --path contrato_test.xlsx \
  --path curvas_descuento.xlsx \
  --path curvas_descuento_v2.xlsx \
  --path curva_test_forward_2.xlsx \
  --path test_curvas_fwd.xlsx \
  --path-glob '*.pyc' \
  --path-glob '__pycache__/*'

# 5. Verificar que ya no aparecen
git log --all --oneline -- .env db.sqlite3     # sin resultados
git rev-list --objects --all | grep -iE '\.env$|db\.sqlite3|\.pyc$|\.xlsm$'   # sin resultados

# 6. Reescribir el remoto (destructivo: coordinar con cualquier colaborador)
git remote add origin https://github.com/gafarina/forward.git
git push --force --mirror origin
```

Después del push forzado:

```bash
# 7. Pedir a GitHub que purgue la caché de objetos huérfanos
#    (los commits antiguos siguen accesibles por SHA hasta que GitHub los recolecta)
#    Abrir un ticket en https://support.github.com/ solicitando la eliminación
#    de las referencias en caché del repositorio.

# 8. Cada colaborador debe reclonar. Un `git pull` sobre un clon antiguo
#    reintroduce el historial purgado.
```

> **Advertencia.** La purga del historial **no es suficiente por sí sola**. El
> repositorio fue público: la clave, la base de datos y el libro con la cartera
> deben considerarse comprometidos de forma permanente. La reescritura evita
> exposición futura, no revierte la pasada. Por eso el paso 1 va primero.

**Alternativa más simple y a veces preferible:** si el repositorio no tiene
historia de valor ni colaboradores externos, es más limpio archivarlo o
eliminarlo y publicar uno nuevo desde un árbol de trabajo limpio con
`.gitignore` correcto desde el primer commit.

### Paso 4 — Impedir que vuelva a ocurrir

```bash
# Crear .gitignore ANTES del primer commit del repositorio nuevo
cat > .gitignore <<'EOF'
.env
*.pem
*.key
db.sqlite3
*.sqlite3
__pycache__/
*.py[cod]
staticfiles/
media/
*.log
.venv/
venv/
~$*.xls*
EOF

# Y un .dockerignore, que ninguno de los dos proyectos tiene todavía
cat > .dockerignore <<'EOF'
.git
.env
*.sqlite3
__pycache__/
*.py[cod]
.pytest_cache/
.venv/
venv/
staticfiles/
media/
EOF
```

Activar la detección de secretos en GitHub:

- **Settings → Code security → Secret scanning**: activar, junto con *Push
  protection* (bloquea el push que contiene una credencial reconocible).
- **Settings → Code security → Dependabot alerts**: activar.

Y un gancho local que revisa antes de cada commit:

```bash
pip install pre-commit detect-secrets

cat > .pre-commit-config.yaml <<'EOF'
repos:
  - repo: https://github.com/Yelp/detect-secrets
    rev: v1.5.0
    hooks:
      - id: detect-secrets
  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v4.6.0
    hooks:
      - id: check-added-large-files
        args: ['--maxkb=500']
      - id: detect-private-key
EOF

pre-commit install
```

### Paso 5 — Corregir el aislamiento por usuario (si la instancia está en línea)

Si hay un despliegue accesible con más de un usuario registrado, los hallazgos
**S-03** y **S-04** son explotables ahora mismo. Mitigación mínima mientras se
migra:

1. Suspender el registro abierto de usuarios.
2. Dejar una sola cuenta activa hasta corregir los filtros.
3. O bien poner la aplicación tras una autenticación de red (VPN, lista de IP)
   mientras tanto.

### Paso 6 — Migrar

Los hallazgos de metodología (**M-01** a **M-06**) implican que las cifras
producidas por el sistema anterior no coinciden con la planilla. Antes de
sustituir cualquier proceso:

1. Correr la reconciliación del caso Cordada contra el motor nuevo:

```bash
python manage.py cargar_demo --usuario demo
# y comparar la valorización con extrapolación Lineal, ACT/360, compuesta,
# contra los valores de referencia que el propio comando imprime
```

2. Revalorizar el histórico con el motor nuevo y cuantificar la diferencia por
   período antes de cambiar la fuente de las cifras contables.
3. Documentar el cambio de metodología (extrapolación lineal, 30/360 real,
   calendario chileno, CVA por exposición esperada) como cambio de estimación,
   con su fecha de aplicación.

---

## 6. Resumen de verificación

Todas las afirmaciones numéricas de este informe fueron reproducidas ejecutando
código, no estimadas.

| Afirmación | Método de verificación |
|---|---|
| `.env` versionado con clave `AIza…` | `git ls-files` y lectura del archivo en el índice |
| `db.sqlite3` con 4 contratos y 1 superusuario | Consulta SQL directa sobre el archivo versionado |
| Diferencias de MtM +396,21 / −208,68 / +159,43 | Ejecución del motor v1 y del motor v2 sobre los mismos insumos |
| Tasas 3,404065 / 3,412601 / 3,368499 % | Celdas `P5`, `P6`, `P7` del libro, reproducidas por extrapolación lineal |
| Reconciliación al centavo del motor v2 | Celdas `R5`-`R7`, `S5`-`S7`, `T5`-`T7`, `R9`, `S9`, `T9` |
| 30/360 idéntica a ACT/360 en v1 | Ejecución con ambas convenciones sobre el mismo contrato |
| Log-lineal v1 devuelve 6,31e-09 con tasas negativas | Ejecución de `interp_log_linear` |
| Feriados chilenos ignorados por v1 | Ejecución de `get_next_business_day` sobre 7 fechas |
| CVA at-the-money: 0,00 vs 286.672,82 | Ejecución de ambos modelos sobre el mismo contrato |
| Sobrestimación por ignorar neteo: +14,6 % | Ejecución con `netting=True` y `netting=False` |
| `excel_loader` importa modelos inexistentes | Análisis del AST de `models.py` y `excel_loader.py` |
| Cero tests en v1 · 337 tests en verde en v2 | Búsqueda exhaustiva de archivos y ejecución de `pytest` |
| `google-genai` declarado vs `google.generativeai` importado | Lectura de `requirements.txt` y del import |
| "Puntos" ya difiere de "Lineal" en v2 (P-01 resuelto) | Ejecución de las tres políticas sobre la misma curva |
| El generador de Excel reproduce los tres folios | Ejecución de `scripts/build_excel_model.py --desde-demo` |

---

**Documentos relacionados:** [`METODOLOGIA.md`](METODOLOGIA.md) ·
[`ARQUITECTURA.md`](ARQUITECTURA.md) · [`../README.md`](../README.md)
