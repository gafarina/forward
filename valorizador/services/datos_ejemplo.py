"""
Conjunto de datos de ejemplo del valorizador.

Reproduce el caso de referencia al 31-05-2026: dos curvas, tres forwards de
venta y las contrapartes correspondientes. Sirve para dos cosas:

* que un usuario nuevo tenga algo que mirar sin cargar un archivo, y
* que la aplicación se pueda comparar contra la planilla operativa, porque los
  nodos y los contratos son exactamente los de ese libro.

La carga vive acá y no en el comando de gestión porque la usan dos entradas:
`manage.py cargar_demo` (despliegues y tests) y el botón "Cargar datos de
ejemplo" de la interfaz. Es idempotente: correrla dos veces deja el mismo
estado.

Valores que la planilla calculó para estos contratos, con extrapolación lineal,
ACT/360 y capitalización compuesta:

    756929   MTM -5.096.628,95   Componente spot -5.162.209,39
    118039   MTM  2.592.812,56   Componente spot  2.709.119,64
    116845   MTM -4.346.625,78   Componente spot -5.114.348,92
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from django.db import transaction

from ..models import (
    Cartera, ConjuntoCurvas, Contraparte, ContratoForward, PuntoCurva,
)

__all__ = [
    "CONTRATOS",
    "CONTRAPARTES",
    "DESC_NODOS",
    "ETIQUETA_CONJUNTO",
    "FECHA_VALORIZACION",
    "FWD_NODOS",
    "NOMBRE_CARTERA",
    "REFERENCIA_PLANILLA",
    "SPOT_VALORIZACION",
    "cargar_datos_ejemplo",
]

FWD_NODOS = [
    (1, 892.21), (2, 892.205), (8, 892.19), (15, 892.13), (22, 892.105),
    (31, 892.06), (62, 892.03),
]
DESC_NODOS = [
    (92, 3.48231), (183, 3.61177), (271, 3.70649), (365, 3.78017),
    (731, 3.98414), (1096, 4.24534), (1461, 4.42915),
]
CONTRATOS = [
    # folio, contraparte, vencimiento, nocional, spot inicio, precio pactado
    ('756929', 'BTG Pactual', date(2026, 7, 7), 1_000_000, 887.71, 886.94),
    ('118039', 'Bice', date(2026, 7, 13), 2_000_000, 894.25, 893.35),
    ('116845', 'Bice', date(2026, 6, 12), 2_000_000, 890.33, 889.98),
]
CONTRAPARTES = [('BTG Pactual', 90), ('Bice', 75)]

SPOT_VALORIZACION = Decimal('892.89')
FECHA_VALORIZACION = date(2026, 5, 31)

NOMBRE_CARTERA = 'Ejemplo'
ETIQUETA_CONJUNTO = f'Carga de ejemplo {FECHA_VALORIZACION}'
FUENTE_CONJUNTO = 'Carga de ejemplo'

# Etiquetas que usaban las versiones anteriores. Se reutilizan en vez de dejar
# un conjunto huérfano al lado del nuevo cuando alguien ya había cargado la
# demostración.
_ETIQUETAS_ANTERIORES = ('Cordada 2026-05-31',)
_CARTERAS_ANTERIORES = ('Cordada',)

REFERENCIA_PLANILLA = (
    '  756929  MTM -5.096.628,95   Componente spot -5.162.209,39\n'
    '  118039  MTM  2.592.812,56   Componente spot  2.709.119,64\n'
    '  116845  MTM -4.346.625,78   Componente spot -5.114.348,92'
)


def _cartera(user) -> Cartera:
    cartera = (
        Cartera.objects.filter(created_by=user, nombre=NOMBRE_CARTERA).first()
        or Cartera.objects.filter(created_by=user, nombre__in=_CARTERAS_ANTERIORES).first()
    )
    if cartera is None:
        return Cartera.objects.create(
            created_by=user, nombre=NOMBRE_CARTERA,
            descripcion='Cartera de ejemplo para probar el valorizador.',
        )
    if cartera.nombre != NOMBRE_CARTERA:
        cartera.nombre = NOMBRE_CARTERA
        cartera.save(update_fields=['nombre'])
    return cartera


def _conjunto(user) -> ConjuntoCurvas:
    conjunto = (
        ConjuntoCurvas.objects.filter(created_by=user, label=ETIQUETA_CONJUNTO).first()
        or ConjuntoCurvas.objects.filter(
            created_by=user, label__in=_ETIQUETAS_ANTERIORES).first()
    )
    if conjunto is None:
        conjunto = ConjuntoCurvas(created_by=user)
    conjunto.label = ETIQUETA_CONJUNTO
    conjunto.valuation_date = FECHA_VALORIZACION
    conjunto.spot_usdclp = SPOT_VALORIZACION
    conjunto.source = FUENTE_CONJUNTO
    conjunto.is_active = True
    conjunto.save()
    return conjunto


@transaction.atomic
def cargar_datos_ejemplo(user, *, reset: bool = False) -> dict:
    """
    Deja el conjunto de ejemplo cargado y activo para `user`.

    Con `reset=True` borra antes las carteras, curvas, contrapartes y contratos
    del usuario. Devuelve un resumen con lo que se creó.
    """
    if reset:
        ContratoForward.objects.filter(created_by=user).delete()
        ConjuntoCurvas.objects.filter(created_by=user).delete()
        Cartera.objects.filter(created_by=user).delete()
        Contraparte.objects.filter(created_by=user).delete()

    cartera = _cartera(user)

    for nombre, spread in CONTRAPARTES:
        Contraparte.objects.get_or_create(
            created_by=user, nombre=nombre,
            defaults={'spread_bp': Decimal(spread), 'recovery': Decimal('0.40')},
        )

    ConjuntoCurvas.objects.filter(created_by=user).update(is_active=False)
    conjunto = _conjunto(user)

    conjunto.puntos.all().delete()
    PuntoCurva.objects.bulk_create(
        [PuntoCurva(conjunto=conjunto, nombre='FWDUSDCLP',
                    tenor_days=d, value=Decimal(str(v))) for d, v in FWD_NODOS]
        + [PuntoCurva(conjunto=conjunto, nombre='CLP423',
                      tenor_days=d, value=Decimal(str(v))) for d, v in DESC_NODOS]
    )

    creados = 0
    for folio, cp, vcto, nocional, spot_ini, precio in CONTRATOS:
        _, nuevo = ContratoForward.objects.get_or_create(
            created_by=user, folio=folio,
            defaults={
                'counterparty': cp,
                'cartera': cartera,
                'side': 'Venta',
                'modality': 'Compensacion',
                'base_ccy': 'USD',
                'quote_ccy': 'CLP',
                'notional': Decimal(str(nocional)),
                'fwd_price': Decimal(str(precio)),
                'spot_inicio': Decimal(str(spot_ini)),
                'maturity_date': vcto,
                'contraparte_ref': Contraparte.objects.filter(
                    created_by=user, nombre=cp).first(),
            },
        )
        creados += int(nuevo)

    return {
        'cartera': cartera,
        'conjunto': conjunto,
        'nodos': len(FWD_NODOS) + len(DESC_NODOS),
        'contratos_nuevos': creados,
        'contratos_totales': len(CONTRATOS),
    }
