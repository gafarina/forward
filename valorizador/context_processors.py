from django.conf import settings


def app_flags(request):
    """Expone flags de configuración a los templates."""
    return {
        'ASSISTANT_ENABLED': getattr(settings, 'ASSISTANT_ENABLED', False),
        'APP_VERSION': '2.0.0',
    }
