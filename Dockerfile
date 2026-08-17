FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update \
 && apt-get install -y --no-install-recommends curl \
 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Se ejecuta como usuario sin privilegios: el original corría todo como root.
RUN useradd --create-home --uid 10001 appuser \
 && mkdir -p /app/staticfiles /app/media \
 && chown -R appuser:appuser /app

USER appuser

# collectstatic necesita una SECRET_KEY cualquiera en tiempo de build.
RUN SECRET_KEY=build-only DEBUG=False ALLOWED_HOSTS=localhost \
    python manage.py collectstatic --noinput

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD curl -fsS http://localhost:8080/accounts/login/ || exit 1

CMD ["gunicorn", "config.wsgi:application", \
     "--bind", "0.0.0.0:8080", \
     "--workers", "3", \
     "--timeout", "120", \
     "--access-logfile", "-"]
