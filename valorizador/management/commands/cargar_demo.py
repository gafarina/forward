"""
Carga los datos de ejemplo del valorizador (caso de referencia 31-05-2026).

El conjunto de datos y la lógica de carga viven en
`valorizador.services.datos_ejemplo`, porque los comparte con el botón
"Cargar datos de ejemplo" de la interfaz. Este comando sólo agrega la parte
propia de la línea de comandos: crear el usuario y fijarle una clave.

    python manage.py cargar_demo --usuario demo --clave <clave>
"""

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction

from valorizador.services.datos_ejemplo import (
    CONTRAPARTES,
    CONTRATOS,
    DESC_NODOS,
    ETIQUETA_CONJUNTO,
    FECHA_VALORIZACION,
    FWD_NODOS,
    NOMBRE_CARTERA,
    REFERENCIA_PLANILLA,
    SPOT_VALORIZACION,
    cargar_datos_ejemplo,
)

__all__ = [
    'Command', 'CONTRATOS', 'CONTRAPARTES', 'DESC_NODOS', 'ETIQUETA_CONJUNTO',
    'FECHA_VALORIZACION', 'FWD_NODOS', 'NOMBRE_CARTERA', 'SPOT_VALORIZACION',
]


class Command(BaseCommand):
    help = 'Carga el conjunto de datos de ejemplo (caso de referencia 31-05-2026).'

    def add_arguments(self, parser):
        parser.add_argument('--usuario', default='demo')
        parser.add_argument('--clave', default=None,
                            help='Si no se indica, se genera una aleatoria y se imprime.')
        parser.add_argument('--reset', action='store_true',
                            help='Borra los datos previos del usuario antes de cargar.')

    @transaction.atomic
    def handle(self, *args, **opts):
        User = get_user_model()
        username = opts['usuario']
        clave = opts['clave']

        user, creado = User.objects.get_or_create(
            username=username, defaults={'email': f'{username}@example.com'}
        )
        if creado:
            if not clave:
                from django.utils.crypto import get_random_string
                clave = get_random_string(16)
                self.stdout.write(self.style.WARNING(
                    f'Usuario "{username}" creado con clave: {clave}'
                ))
            user.set_password(clave)
            user.save()
        elif clave:
            user.set_password(clave)
            user.save()

        resumen = cargar_datos_ejemplo(user, reset=opts['reset'])

        self.stdout.write(self.style.SUCCESS(
            f'Demo cargada para "{username}": {resumen["nodos"]} nodos de '
            f'curva y {resumen["contratos_nuevos"]} contratos nuevos '
            f'({resumen["contratos_totales"]} en total).'
        ))
        self.stdout.write(
            'Valores de referencia de la planilla (extrapolación lineal, ACT/360, '
            'compuesta):\n' + REFERENCIA_PLANILLA
        )
