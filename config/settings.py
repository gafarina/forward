"""
Configuración del proyecto.

Diferencias de seguridad respecto del original:

* `SECRET_KEY` no tiene default en producción: si `DEBUG=False` y no está
  definida, el proyecto se niega a arrancar en lugar de usar una clave
  conocida y publicada.
* `DEBUG` es False por defecto. Antes el default era True, de modo que un
  despliegue sin variables de entorno quedaba con el depurador expuesto.
* `ALLOWED_HOSTS` se lee del entorno. Antes era `['*']` fijo.
* Se agregan cabeceras de seguridad y cookies seguras cuando DEBUG es False.
* Ninguna credencial vive en el repositorio: `.env` está en `.gitignore` y
  sólo se versiona `.env.example`.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent

# El runner de Django fuerza DEBUG=False durante los tests, y con el
# almacenamiento de estáticos con manifiesto eso obliga a haber corrido
# `collectstatic` antes de poder ejecutar la suite. Se detecta la corrida de
# tests para usar el almacenamiento simple.
TESTING = 'test' in sys.argv or 'PYTEST_CURRENT_TEST' in os.environ

# Carga .env si python-dotenv está disponible (opcional en producción).
try:
    from dotenv import load_dotenv

    load_dotenv(BASE_DIR / '.env')
except ImportError:  # pragma: no cover
    pass


def env(key: str, default=None, *, required: bool = False):
    val = os.getenv(key, default)
    if required and not val:
        raise ImproperlyConfigured(
            f'Falta la variable de entorno obligatoria {key}. '
            f'Copia .env.example a .env y complétala.'
        )
    return val


def env_bool(key: str, default: bool = False) -> bool:
    return str(os.getenv(key, str(default))).strip().lower() in ('1', 'true', 'yes', 'on')


def env_list(key: str, default: str = '') -> list[str]:
    return [x.strip() for x in os.getenv(key, default).split(',') if x.strip()]


DEBUG = env_bool('DEBUG', False)

SECRET_KEY = env('SECRET_KEY')
if not SECRET_KEY:
    if DEBUG:
        SECRET_KEY = 'django-insecure-solo-para-desarrollo-local-no-usar-en-produccion'
    else:
        raise ImproperlyConfigured(
            'SECRET_KEY es obligatoria cuando DEBUG=False. '
            "Genera una con: python -c \"from django.core.management.utils import "
            'get_random_secret_key; print(get_random_secret_key())"'
        )

ALLOWED_HOSTS = env_list('ALLOWED_HOSTS', 'localhost,127.0.0.1' if DEBUG else '')
CSRF_TRUSTED_ORIGINS = env_list('CSRF_TRUSTED_ORIGINS')

# Clave del asistente. Si no está, la funcionalidad se desactiva sola en vez
# de romper la aplicación.
GEMINI_API_KEY = env('GEMINI_API_KEY')
GEMINI_MODEL = env('GEMINI_MODEL', 'gemini-2.0-flash')
ASSISTANT_ENABLED = bool(GEMINI_API_KEY)

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.humanize',
    'valorizador',
    'accounts',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'valorizador.context_processors.app_flags',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'
ASGI_APPLICATION = 'config.asgi.application'

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': env('SQLITE_PATH', BASE_DIR / 'db.sqlite3'),
    }
}

# Soporte opcional para Postgres vía DATABASE_URL, sin dependencias extra.
_db_url = env('DATABASE_URL')
if _db_url and _db_url.startswith(('postgres://', 'postgresql://')):
    from urllib.parse import urlparse

    u = urlparse(_db_url)
    DATABASES['default'] = {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': u.path.lstrip('/'),
        'USER': u.username or '',
        'PASSWORD': u.password or '',
        'HOST': u.hostname or '',
        'PORT': str(u.port or ''),
        'CONN_MAX_AGE': 600,
    }

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
     'OPTIONS': {'min_length': 10}},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = 'es-cl'
TIME_ZONE = 'America/Santiago'
USE_I18N = True
USE_TZ = True

STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STORAGES = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {
        'BACKEND': (
            'django.contrib.staticfiles.storage.StaticFilesStorage' if TESTING
            else 'whitenoise.storage.CompressedManifestStaticFilesStorage'
        ),
    },
}

MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

LOGIN_URL = '/accounts/login/'
LOGIN_REDIRECT_URL = '/'
LOGOUT_REDIRECT_URL = '/accounts/login/'

# Límites de carga: un .xlsm de la calculadora pesa ~3 MB.
FILE_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024
DATA_UPLOAD_MAX_MEMORY_SIZE = 20 * 1024 * 1024
MAX_UPLOAD_SIZE = int(env('MAX_UPLOAD_SIZE', 20 * 1024 * 1024))

# ── Seguridad ────────────────────────────────────────────────────────
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

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'simple': {'format': '{levelname} {asctime} {name} {message}', 'style': '{'},
    },
    'handlers': {
        'console': {'class': 'logging.StreamHandler', 'formatter': 'simple'},
    },
    'root': {'handlers': ['console'], 'level': env('LOG_LEVEL', 'INFO')},
    'loggers': {
        'valorizador': {'handlers': ['console'], 'level': 'INFO', 'propagate': False},
    },
}
