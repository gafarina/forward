# Cómo ejecutar la aplicación en tu PC

Guía paso a paso para levantar el Valorizador de Forwards en local y verlo en Chrome.

Ruta del proyecto:

```
C:\Users\GastónAndrésFarinaZe\OneDrive - Grant Thornton Chile\trabajo\forward_v2
```

---

## Uso diario (el entorno ya está instalado)

### Paso 1 — Abrir PowerShell en la carpeta del proyecto

Abrí el **Explorador de archivos**, navegá hasta la carpeta `forward_v2`, hacé clic en la
barra de direcciones, escribí `powershell` y presioná Enter. Se abre una terminal ya
posicionada en la carpeta correcta.

Alternativa: abrí PowerShell desde el menú Inicio y pegá este comando (las comillas son
obligatorias porque la ruta tiene espacios):

```powershell
cd "C:\Users\GastónAndrésFarinaZe\OneDrive - Grant Thornton Chile\trabajo\forward_v2"
```

### Paso 2 — Levantar el servidor

```powershell
.\.venv\Scripts\python.exe manage.py runserver
```

Deberías ver algo así:

```
Starting development server at http://127.0.0.1:8000/
Quit the server with CTRL-BREAK.
```

**Dejá esa ventana abierta.** Si la cerrás, el servidor se apaga.

### Paso 3 — Abrir Chrome

Andá a:

```
http://127.0.0.1:8000
```

### Paso 4 — Para detener el servidor

En la ventana de PowerShell, presioná `Ctrl + C`.

---

## Primera vez: crear tu usuario

La base de datos arranca vacía, así que no hay con qué iniciar sesión. Dos opciones:

**Opción A — desde la web:** en la pantalla de login, hacé clic en *"Crear una cuenta"*.
La contraseña debe tener **mínimo 10 caracteres** y no puede ser sólo números ni una
contraseña común (son validaciones del proyecto).

**Opción B — desde la terminal** (te da además acceso al panel admin en
`http://127.0.0.1:8000/admin/`). Con el servidor detenido, o en una segunda ventana de
PowerShell:

```powershell
.\.venv\Scripts\python.exe manage.py createsuperuser
```

Te va a pedir usuario, email (podés dejarlo vacío) y contraseña. La contraseña **no se ve
mientras la escribís** — es normal, seguí escribiendo y presioná Enter.

---

## Instalación desde cero (PC nueva, o si borraste `.venv`)

### Paso 1 — Verificar que Python está instalado

```powershell
python --version
```

Debe responder `Python 3.11` o superior. Si dice que el comando no existe, instalá Python
desde https://www.python.org/downloads/ marcando la casilla **"Add Python to PATH"**.

### Paso 2 — Crear el entorno virtual

Parado en la carpeta del proyecto:

```powershell
python -m venv .venv
```

Crea la carpeta `.venv` con una instalación de Python aislada. Esto evita conflictos de
versiones con otros proyectos (el proyecto necesita Django 5.1, y una 5.2 lo rompe).

### Paso 3 — Instalar las dependencias

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Tarda un par de minutos.

### Paso 4 — Crear el archivo `.env`

Copiá la plantilla:

```powershell
Copy-Item .env.example .env
```

Generá una clave secreta:

```powershell
.\.venv\Scripts\python.exe -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

Abrí `.env` con el Bloc de notas y completalo así (pegando la clave que te imprimió el
comando anterior después del `=`):

```
SECRET_KEY=pega-aqui-la-clave-generada
DEBUG=True
ALLOWED_HOSTS=localhost,127.0.0.1
CSRF_TRUSTED_ORIGINS=
GEMINI_API_KEY=
GEMINI_MODEL=gemini-2.0-flash
LOG_LEVEL=INFO
MAX_UPLOAD_SIZE=20971520
```

`GEMINI_API_KEY` vacía deja el asistente desactivado; la aplicación funciona igual y el
widget simplemente no aparece.

### Paso 5 — Crear la base de datos

```powershell
.\.venv\Scripts\python.exe manage.py migrate
```

Genera el archivo `db.sqlite3` con todas las tablas.

### Paso 6 — Crear tu usuario y levantar el servidor

Seguí las secciones *"Primera vez: crear tu usuario"* y *"Uso diario"* de más arriba.

---

## Problemas frecuentes

**`No se pudo importar Django` o `ModuleNotFoundError`**
Estás usando el Python del sistema en vez del del entorno virtual. Asegurate de escribir
el comando completo `.\.venv\Scripts\python.exe manage.py ...`, no `python manage.py ...`.

**`Error: That port is already in use.`**
Ya hay un servidor corriendo. O lo usás como está (andá a `http://127.0.0.1:8000`), o
lo matás:

```powershell
Get-Process python | Stop-Process -Force
```

O levantás este en otro puerto:

```powershell
.\.venv\Scripts\python.exe manage.py runserver 127.0.0.1:8001
```

**`No se puede cargar el archivo Activate.ps1` (política de ejecución)**
No hace falta activar el entorno virtual. Usar `.\.venv\Scripts\python.exe` directamente
evita ese problema por completo.

**La página no carga en Chrome**
Verificá que la ventana de PowerShell siga abierta y mostrando el mensaje de
`Starting development server`. Usá `127.0.0.1`, no `localhost:8000/index.html` ni `https://`.

**`ImproperlyConfigured: SECRET_KEY es obligatoria`**
Falta el archivo `.env` o no tiene `DEBUG=True`. Revisá el Paso 4 de la instalación.

---

## Notas

- `runserver` es el servidor de **desarrollo** de Django: sólo para tu PC. No lo expongas
  a la red ni lo uses en producción (para eso está el `Dockerfile` con gunicorn).
- Los datos viven en `db.sqlite3`, en la carpeta del proyecto. Si borrás ese archivo,
  perdés usuarios y carteras, y hay que volver a correr `migrate`.
- Ni `.env` ni `db.sqlite3` ni `.venv` se versionan (están en `.gitignore`).
