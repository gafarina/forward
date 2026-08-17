"""
Formularios.

El original construía los objetos leyendo `request.POST['campo']` directo, sin
validación: un nocional negativo, una fecha inválida o un campo faltante
terminaban en un `except Exception` genérico que mostraba el error crudo de
Python al usuario. Acá se usan ModelForm con validación declarativa.
"""

from __future__ import annotations

from datetime import date

from django import forms
from django.conf import settings

from core.calendars import BUSINESS_DAY_CONVENTIONS
from core.curves import COMPOUNDING, EXTRAP_METHODS, INTERP_METHODS
from core.daycount import DAY_COUNT_CONVENTIONS

from .models import Cartera, ContratoForward, Contraparte, ConjuntoCurvas


class BootstrapMixin:
    """Agrega clases CSS coherentes a todos los widgets."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            widget = field.widget
            css = 'input'
            if isinstance(widget, forms.Select):
                css = 'select'
            elif isinstance(widget, forms.CheckboxInput):
                css = 'checkbox'
            elif isinstance(widget, forms.Textarea):
                css = 'textarea'
            widget.attrs['class'] = (widget.attrs.get('class', '') + ' ' + css).strip()


class CarteraForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = Cartera
        fields = ['nombre', 'descripcion']
        widgets = {'descripcion': forms.Textarea(attrs={'rows': 3})}


class ContraparteForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = Contraparte
        fields = ['nombre', 'spread_bp', 'recovery', 'tiene_isda_neteo']

    def clean_recovery(self):
        r = self.cleaned_data['recovery']
        if not (0 <= r < 1):
            raise forms.ValidationError('La tasa de recuperación debe estar entre 0 y 1.')
        return r


class ContratoForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = ContratoForward
        fields = [
            'cartera', 'counterparty', 'contraparte_ref', 'folio', 'side', 'modality',
            'base_ccy', 'quote_ccy', 'notional', 'fwd_price', 'spot_inicio',
            'start_date', 'maturity_date', 'fwd_curve', 'disc_curve', 'status',
        ]
        widgets = {
            'start_date': forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'),
            'maturity_date': forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        if user is not None:
            self.fields['cartera'].queryset = Cartera.objects.filter(created_by=user)
            self.fields['contraparte_ref'].queryset = Contraparte.objects.filter(created_by=user)
        self.fields['cartera'].required = False
        self.fields['contraparte_ref'].required = False
        self.fields['start_date'].required = False

    def clean(self):
        data = super().clean()
        start, mat = data.get('start_date'), data.get('maturity_date')
        if start and mat and mat < start:
            self.add_error('maturity_date', 'El vencimiento no puede ser anterior al inicio.')

        folio = (data.get('folio') or '').strip()
        if folio and self.user is not None:
            qs = ContratoForward.objects.filter(created_by=self.user, folio=folio)
            if self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                self.add_error('folio', 'Ya tienes un contrato con este folio.')

        if not data.get('spot_inicio'):
            self.add_error(
                'spot_inicio',
                'Indica el tipo de cambio del día en que se pactó la operación. '
                'Sin ese dato no se puede separar el resultado en componente spot y '
                'puntos forward.',
            )
        return data


class ConjuntoCurvasForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = ConjuntoCurvas
        fields = ['label', 'valuation_date', 'spot_usdclp', 'source']
        widgets = {
            'valuation_date': forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'),
        }

    def clean_valuation_date(self):
        d = self.cleaned_data['valuation_date']
        if d > date.today():
            raise forms.ValidationError('La fecha de valorización no puede ser futura.')
        return d


class ArchivoUploadForm(forms.Form):
    """Carga de archivo con validación de tamaño y extensión."""

    EXTENSIONES = ('.csv', '.txt', '.xlsx', '.xlsm', '.xls')

    archivo = forms.FileField(label='Archivo')

    def clean_archivo(self):
        f = self.cleaned_data['archivo']
        nombre = f.name.lower()
        if not nombre.endswith(self.EXTENSIONES):
            raise forms.ValidationError(
                f'Extensión no soportada. Usa: {", ".join(self.EXTENSIONES)}'
            )
        limite = getattr(settings, 'MAX_UPLOAD_SIZE', 20 * 1024 * 1024)
        if f.size > limite:
            raise forms.ValidationError(
                f'El archivo pesa {f.size / 1e6:.1f} MB y el límite es {limite / 1e6:.0f} MB.'
            )
        return f


class ValorizarForm(BootstrapMixin, forms.Form):
    """Parámetros de una corrida de valorización."""

    conjunto = forms.ModelChoiceField(
        queryset=ConjuntoCurvas.objects.none(), label='Conjunto de curvas'
    )
    etiqueta = forms.CharField(required=False, label='Etiqueta', max_length=200)
    fecha_valoracion = forms.DateField(
        label='Fecha de valorización',
        widget=forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'),
    )
    spot_val = forms.DecimalField(
        label='Tipo de cambio de valorización', max_digits=12, decimal_places=4,
        required=False,
        help_text='Si lo dejas vacío se usa el spot del conjunto de curvas.',
    )
    moneda = forms.ChoiceField(
        choices=[('USD', 'USD'), ('EUR', 'EUR'), ('CLP', 'CLP')], initial='USD',
        label='Moneda base',
    )
    cartera = forms.ModelChoiceField(
        queryset=Cartera.objects.none(), required=False, label='Cartera',
        empty_label='Todas',
    )

    day_count = forms.ChoiceField(
        choices=[(c, c) for c in DAY_COUNT_CONVENTIONS], initial='ACT/360',
        label='Conteo de días',
    )
    interp_method = forms.ChoiceField(
        choices=[(c, c) for c in INTERP_METHODS], initial='Lineal',
        label='Interpolación',
    )
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
    business_days = forms.ChoiceField(
        choices=[(c, c) for c in BUSINESS_DAY_CONVENTIONS], initial='Exacto',
        label='Ajuste de días hábiles',
    )
    calendar = forms.ChoiceField(
        choices=[('CL', 'Chile'), ('CL+US', 'Chile + EE.UU.'), ('NULL', 'Sólo fines de semana')],
        initial='CL', label='Calendario',
    )
    compounding = forms.ChoiceField(
        choices=[(c, c) for c in COMPOUNDING], initial='Compuesta',
        label='Capitalización del descuento',
    )

    calc_greeks = forms.BooleanField(required=False, initial=True, label='Calcular sensibilidades')
    calc_cva = forms.BooleanField(required=False, initial=False, label='Calcular CVA / DVA')
    netting = forms.BooleanField(
        required=False, initial=True, label='Aplicar neteo por contraparte',
    )
    spread_bp = forms.DecimalField(
        required=False, initial=100, label='Spread de crédito (bp)', max_digits=8, decimal_places=2
    )
    recovery = forms.DecimalField(
        required=False, initial=0.40, label='Tasa de recuperación', max_digits=5, decimal_places=4
    )
    fx_vol = forms.DecimalField(
        required=False, initial=0.12, label='Volatilidad FX anual', max_digits=6, decimal_places=4
    )

    shock_max = forms.DecimalField(
        required=False, initial=5, label='Shock máximo (%)', max_digits=6, decimal_places=2
    )
    contract_ids = forms.CharField(required=False, widget=forms.HiddenInput)

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if user is not None:
            self.fields['conjunto'].queryset = ConjuntoCurvas.objects.filter(created_by=user)
            self.fields['cartera'].queryset = Cartera.objects.filter(created_by=user)

    def clean_shock_max(self):
        s = self.cleaned_data.get('shock_max')
        if s is None:
            return 5
        if not (0 < float(s) <= 50):
            raise forms.ValidationError('El shock debe estar entre 0 % y 50 %.')
        return s

    def selected_ids(self) -> list[int]:
        raw = self.cleaned_data.get('contract_ids') or ''
        return [int(x) for x in raw.split(',') if x.strip().isdigit()]
