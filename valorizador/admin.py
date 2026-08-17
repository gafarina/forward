from django.contrib import admin

from .models import (
    Cartera, ConjuntoCurvas, Contraparte, ContratoForward,
    LineaValorizacion, PuntoCurva, ValorizacionGuardada,
)


class PuntoCurvaInline(admin.TabularInline):
    model = PuntoCurva
    extra = 0


@admin.register(ConjuntoCurvas)
class ConjuntoCurvasAdmin(admin.ModelAdmin):
    list_display = ['label', 'valuation_date', 'spot_usdclp', 'source', 'is_active',
                    'n_puntos', 'created_by', 'created_at']
    list_filter = ['is_active', 'source', 'created_by']
    search_fields = ['label']
    date_hierarchy = 'valuation_date'
    inlines = [PuntoCurvaInline]


@admin.register(PuntoCurva)
class PuntoCurvaAdmin(admin.ModelAdmin):
    list_display = ['conjunto', 'nombre', 'tenor_days', 'value']
    list_filter = ['nombre']


@admin.register(Contraparte)
class ContraparteAdmin(admin.ModelAdmin):
    list_display = ['nombre', 'spread_bp', 'recovery', 'tiene_isda_neteo', 'created_by']
    list_filter = ['tiene_isda_neteo']
    search_fields = ['nombre']


@admin.register(Cartera)
class CarteraAdmin(admin.ModelAdmin):
    list_display = ['nombre', 'n_contratos', 'created_by', 'created_at']
    search_fields = ['nombre']


@admin.register(ContratoForward)
class ContratoForwardAdmin(admin.ModelAdmin):
    list_display = ['folio', 'counterparty', 'side', 'notional', 'base_ccy',
                    'fwd_price', 'maturity_date', 'status', 'cartera', 'created_by']
    list_filter = ['side', 'status', 'base_ccy', 'cartera']
    search_fields = ['folio', 'counterparty']
    date_hierarchy = 'maturity_date'
    autocomplete_fields = ['contraparte_ref']


class LineaValorizacionInline(admin.TabularInline):
    model = LineaValorizacion
    extra = 0
    can_delete = False
    readonly_fields = ['folio', 'counterparty', 'side', 'maturity_date', 'notional',
                       'mtm', 'spot_component', 'fwd_points']


@admin.register(ValorizacionGuardada)
class ValorizacionGuardadaAdmin(admin.ModelAdmin):
    list_display = ['label', 'valuation_date', 'total_mtm', 'total_spot',
                    'total_fwdpoints', 'num_contracts', 'created_by', 'created_at']
    list_filter = ['valuation_date', 'created_by']
    date_hierarchy = 'valuation_date'
    inlines = [LineaValorizacionInline]


@admin.register(LineaValorizacion)
class LineaValorizacionAdmin(admin.ModelAdmin):
    list_display = ['valorizacion', 'folio', 'counterparty', 'side', 'mtm',
                    'spot_component', 'fwd_points', 'cva']
