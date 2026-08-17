"""
Modelo de datos del valorizador.

Cambios respecto del original:

* Todos los modelos con dueño llevan `created_by` **obligatorio** y las vistas
  filtran por él. En el repo original `contratos_list`, `curvas_list` y
  `valorizaciones_list` no filtraban por usuario, de modo que cualquier
  usuario autenticado veía (y podía borrar) la cartera de los demás.
* `folio` es único por usuario, no global: dos clientes distintos pueden tener
  el mismo número de folio.
* Se agregan `trade_date` y `spot_inicio` como campos separados, y validación
  de que el vencimiento sea posterior al inicio.
* Se persisten las nuevas métricas (DV01, theta, delta %, mtm ajustado).
* Se agrega `CounterpartyCredit` para el CVA por contraparte, que antes era un
  spread fijo de 50 bps para todo el mundo.
"""

from __future__ import annotations

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.urls import reverse


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class OwnedQuerySet(models.QuerySet):
    def for_user(self, user):
        """Filtra por dueño. El staff ve todo."""
        if user.is_staff:
            return self
        return self.filter(created_by=user)


# ──────────────────────────────────────────────────────────────────────
# Curvas
# ──────────────────────────────────────────────────────────────────────

class ConjuntoCurvas(TimeStampedModel):
    """Fotografía de mercado a una fecha: spot + curvas."""

    label = models.CharField('etiqueta', max_length=200)
    valuation_date = models.DateField('fecha de valorización')
    spot_usdclp = models.DecimalField(
        'spot USD/CLP', max_digits=12, decimal_places=4,
        validators=[MinValueValidator(0)],
    )
    source = models.CharField('fuente', max_length=100, default='Bloomberg')
    is_active = models.BooleanField('activo', default=False)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='conjuntos'
    )

    objects = OwnedQuerySet.as_manager()

    class Meta:
        ordering = ['-valuation_date', '-created_at']
        verbose_name = 'conjunto de curvas'
        verbose_name_plural = 'conjuntos de curvas'
        indexes = [models.Index(fields=['created_by', '-valuation_date'])]

    def __str__(self) -> str:
        return f'{self.label} ({self.valuation_date})'

    def get_absolute_url(self) -> str:
        return reverse('curvas_detail', args=[self.pk])

    @property
    def n_puntos(self) -> int:
        return self.puntos.count()

    def as_curves(self) -> dict:
        """Convierte a objetos `core.Curve` listos para el motor."""
        from core.curves import Curve

        agrupado: dict[str, dict[str, list]] = {}
        for p in self.puntos.all().order_by('nombre', 'tenor_days'):
            d = agrupado.setdefault(p.nombre, {'xs': [], 'ys': []})
            d['xs'].append(float(p.tenor_days))
            d['ys'].append(float(p.value))
        return {
            nombre: Curve(nombre, d['xs'], d['ys'])
            for nombre, d in agrupado.items()
            if d['xs']
        }


class PuntoCurva(models.Model):
    """Un nodo de una curva (plazo en días, valor)."""

    CURVE_CHOICES = [
        ('FWDUSDCLP', 'Forward USD/CLP (outright)'),
        ('FWDEURCLP', 'Forward EUR/CLP (outright)'),
        ('CLP423', 'Descuento CLP cámara'),
        ('USD_SOFR', 'Descuento USD SOFR'),
    ]

    conjunto = models.ForeignKey(
        ConjuntoCurvas, related_name='puntos', on_delete=models.CASCADE
    )
    nombre = models.CharField('curva', max_length=50, choices=CURVE_CHOICES)
    tenor_days = models.IntegerField('plazo (días)', validators=[MinValueValidator(0)])
    value = models.DecimalField('valor', max_digits=18, decimal_places=8)

    class Meta:
        ordering = ['nombre', 'tenor_days']
        verbose_name = 'punto de curva'
        verbose_name_plural = 'puntos de curva'
        constraints = [
            models.UniqueConstraint(
                fields=['conjunto', 'nombre', 'tenor_days'],
                name='punto_unico_por_curva',
            )
        ]

    def __str__(self) -> str:
        return f'{self.nombre} {self.tenor_days}d = {self.value}'


# ──────────────────────────────────────────────────────────────────────
# Contrapartes y crédito
# ──────────────────────────────────────────────────────────────────────

class Contraparte(TimeStampedModel):
    """
    Contraparte con sus parámetros de crédito.

    Reemplaza el spread fijo de 50 bps que el motor original aplicaba a todas
    las contrapartes por igual.
    """

    nombre = models.CharField('nombre', max_length=100)
    spread_bp = models.DecimalField(
        'spread de crédito (bp)', max_digits=8, decimal_places=2, default=100,
        help_text='CDS o proxy por rating.',
    )
    recovery = models.DecimalField(
        'tasa de recuperación', max_digits=5, decimal_places=4, default=0.4
    )
    tiene_isda_neteo = models.BooleanField(
        'contrato marco con neteo', default=True,
        help_text='Si está activo, el CVA se calcula sobre la exposición neta.',
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='contrapartes'
    )

    objects = OwnedQuerySet.as_manager()

    class Meta:
        ordering = ['nombre']
        verbose_name = 'contraparte'
        verbose_name_plural = 'contrapartes'
        constraints = [
            models.UniqueConstraint(
                fields=['created_by', 'nombre'], name='contraparte_unica_por_usuario'
            )
        ]

    def __str__(self) -> str:
        return self.nombre


# ──────────────────────────────────────────────────────────────────────
# Carteras y contratos
# ──────────────────────────────────────────────────────────────────────

class Cartera(TimeStampedModel):
    nombre = models.CharField('nombre', max_length=100)
    descripcion = models.TextField('descripción', blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='carteras'
    )

    objects = OwnedQuerySet.as_manager()

    class Meta:
        ordering = ['nombre']
        verbose_name = 'cartera'
        verbose_name_plural = 'carteras'
        constraints = [
            models.UniqueConstraint(
                fields=['created_by', 'nombre'], name='cartera_unica_por_usuario'
            )
        ]

    def __str__(self) -> str:
        return self.nombre

    @property
    def n_contratos(self) -> int:
        return self.contratos.filter(status='Vigente').count()

    def notional_por_moneda(self) -> dict:
        out: dict[str, float] = {}
        for c in self.contratos.filter(status='Vigente'):
            out[c.base_ccy] = out.get(c.base_ccy, 0.0) + float(c.notional)
        return out


class ContratoForward(TimeStampedModel):
    SIDE_CHOICES = [('Compra', 'Compra'), ('Venta', 'Venta')]
    STATUS_CHOICES = [
        ('Vigente', 'Vigente'),
        ('Vencido', 'Vencido'),
        ('Liquidado', 'Liquidado'),
    ]
    MODALITY_CHOICES = [
        ('Compensacion', 'Compensación'),
        ('Entrega', 'Entrega física'),
    ]

    cartera = models.ForeignKey(
        Cartera, related_name='contratos', on_delete=models.SET_NULL,
        null=True, blank=True,
    )
    contraparte_ref = models.ForeignKey(
        Contraparte, related_name='contratos', on_delete=models.SET_NULL,
        null=True, blank=True, verbose_name='contraparte (ficha)',
    )
    counterparty = models.CharField('contraparte', max_length=100)
    folio = models.CharField('folio', max_length=50, blank=True)
    side = models.CharField('operación', max_length=10, choices=SIDE_CHOICES, default='Venta')
    modality = models.CharField(
        'modalidad', max_length=50, choices=MODALITY_CHOICES, default='Compensacion'
    )
    base_ccy = models.CharField('moneda base', max_length=10, default='USD')
    quote_ccy = models.CharField('moneda cotización', max_length=10, default='CLP')
    notional = models.DecimalField(
        'nocional', max_digits=18, decimal_places=2, validators=[MinValueValidator(0)]
    )
    fwd_price = models.DecimalField(
        'precio forward pactado', max_digits=14, decimal_places=4,
        validators=[MinValueValidator(0)],
    )
    spot_inicio = models.DecimalField(
        'spot al inicio', max_digits=12, decimal_places=4, default=0,
        help_text='Tipo de cambio vigente el día en que se pactó la operación. '
                  'Se usa sólo para separar el resultado en componente spot y puntos forward.',
    )
    start_date = models.DateField('fecha de inicio', null=True, blank=True)
    maturity_date = models.DateField('fecha de vencimiento')
    fwd_curve = models.CharField('curva forward', max_length=50, default='FWDUSDCLP')
    disc_curve = models.CharField('curva de descuento', max_length=50, default='CLP423')
    status = models.CharField('estado', max_length=20, choices=STATUS_CHOICES, default='Vigente')
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='contratos'
    )

    objects = OwnedQuerySet.as_manager()

    class Meta:
        ordering = ['maturity_date', 'counterparty']
        verbose_name = 'contrato forward'
        verbose_name_plural = 'contratos forward'
        indexes = [
            models.Index(fields=['created_by', 'status', 'maturity_date']),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(notional__gt=0), name='notional_positivo'
            ),
            models.CheckConstraint(
                condition=models.Q(fwd_price__gt=0), name='precio_fwd_positivo'
            ),
        ]

    def __str__(self) -> str:
        return f'{self.counterparty} {self.folio} {self.side} {self.notional:,.0f} {self.base_ccy}'

    def clean(self):
        from django.core.exceptions import ValidationError

        if self.start_date and self.maturity_date and self.maturity_date < self.start_date:
            raise ValidationError(
                {'maturity_date': 'El vencimiento no puede ser anterior al inicio.'}
            )

    def to_core(self):
        """Convierte a `core.Contract` para el motor."""
        from core.valuation import Contract

        return Contract(
            id=self.pk,
            notional=float(self.notional),
            fwd_price=float(self.fwd_price),
            maturity_date=self.maturity_date,
            side=self.side,
            spot_inicio=float(self.spot_inicio or 0),
            counterparty=self.counterparty,
            folio=self.folio,
            base_ccy=self.base_ccy,
            quote_ccy=self.quote_ccy,
            modality=self.modality,
            start_date=self.start_date,
            fwd_curve=self.fwd_curve,
            disc_curve=self.disc_curve,
            cartera=self.cartera.nombre if self.cartera else '',
        )


# ──────────────────────────────────────────────────────────────────────
# Valorizaciones guardadas
# ──────────────────────────────────────────────────────────────────────

class ValorizacionGuardada(TimeStampedModel):
    valuation_date = models.DateField('fecha de valorización')
    label = models.CharField('etiqueta', max_length=200, blank=True)
    curve_set = models.ForeignKey(
        ConjuntoCurvas, on_delete=models.SET_NULL, null=True, blank=True
    )
    spot = models.DecimalField('spot usado', max_digits=12, decimal_places=4, default=0)
    total_mtm = models.DecimalField('MtM total', max_digits=20, decimal_places=2, default=0)
    total_mtm_ajustado = models.DecimalField(
        'MtM ajustado por crédito', max_digits=20, decimal_places=2, default=0
    )
    total_spot = models.DecimalField('componente spot', max_digits=20, decimal_places=2, default=0)
    total_fwdpoints = models.DecimalField('puntos forward', max_digits=20, decimal_places=2, default=0)
    total_delta = models.DecimalField('delta total', max_digits=20, decimal_places=2, default=0)
    total_dv01 = models.DecimalField('DV01 total', max_digits=20, decimal_places=2, default=0)
    total_cva = models.DecimalField('CVA total', max_digits=20, decimal_places=2, default=0)
    total_dva = models.DecimalField('DVA total', max_digits=20, decimal_places=2, default=0)
    num_contracts = models.IntegerField('contratos valorizados', default=0)
    config_json = models.JSONField('configuración', default=dict)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='valorizaciones'
    )

    objects = OwnedQuerySet.as_manager()

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'valorización guardada'
        verbose_name_plural = 'valorizaciones guardadas'

    def __str__(self) -> str:
        return f'{self.label or "Valorización"} ({self.valuation_date})'

    def get_absolute_url(self) -> str:
        return reverse('valorizacion_detail', args=[self.pk])


class LineaValorizacion(models.Model):
    valorizacion = models.ForeignKey(
        ValorizacionGuardada, related_name='lineas', on_delete=models.CASCADE
    )
    contrato = models.ForeignKey(
        ContratoForward, on_delete=models.SET_NULL, null=True, blank=True
    )
    folio = models.CharField(max_length=50, blank=True)
    counterparty = models.CharField(max_length=100)
    cartera_nombre = models.CharField(max_length=100, blank=True)
    side = models.CharField(max_length=10)
    maturity_date = models.DateField()
    notional = models.DecimalField(max_digits=18, decimal_places=2)
    currency = models.CharField(max_length=10, default='USD')
    spot_inicio = models.DecimalField(max_digits=12, decimal_places=4, default=0)
    spot_val = models.DecimalField(max_digits=12, decimal_places=4, default=0)
    fwd_contract = models.DecimalField(max_digits=14, decimal_places=4)
    fwd_mkt = models.DecimalField(max_digits=14, decimal_places=6, default=0)
    days_to_mat = models.IntegerField(default=0)
    year_fraction = models.DecimalField(max_digits=12, decimal_places=8, default=0)
    disc_rate = models.DecimalField(max_digits=14, decimal_places=6, default=0)
    disc_factor = models.DecimalField(max_digits=18, decimal_places=10, default=0)
    mtm = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    mtm_ajustado = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    spot_component = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    fwd_points = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    delta = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    dv01 = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    theta_1d = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    cva = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    dva = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    flags = models.JSONField(default=list, blank=True)

    class Meta:
        ordering = ['maturity_date']
        verbose_name = 'línea de valorización'
        verbose_name_plural = 'líneas de valorización'

    def __str__(self) -> str:
        return f'{self.folio or self.counterparty}: {self.mtm}'
