"""
Vistas del valorizador.

Notas sobre lo que cambió respecto del original:

* Toda consulta pasa por `for_user(request.user)`. En la v1, `contratos_list`,
  `curvas_list` y `valorizaciones_list` devolvían los objetos de **todos** los
  usuarios; con dos clientes en la misma instancia, cada uno veía y podía
  borrar la cartera del otro.
* `valorizar` usaba `if 'sensibilidad' in locals()` para pasar la matriz al
  template y dejaba variables sin asignar según la rama. Ahora es un flujo
  explícito con formulario validado.
* El endpoint del asistente estaba con `@csrf_exempt` y **sin** `login_required`:
  cualquiera en internet podía consumir la clave de Gemini del proyecto. Ahora
  exige sesión, respeta CSRF y tiene límite de frecuencia.
* Los borrados exigen POST (ya era así) y ahora además verifican propiedad.
"""

from __future__ import annotations

import csv
import json
import logging
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.db import transaction
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST, require_http_methods

from core.credit import CreditProfile
from core.valuation import MarketData, PricingConfig, price_portfolio, sensitivity_matrix

from .forms import (
    ArchivoUploadForm, CarteraForm, ConjuntoCurvasForm, ContraparteForm,
    ContratoForm, ValorizarForm,
)
from .models import (
    Cartera, ConjuntoCurvas, Contraparte, ContratoForward, LineaValorizacion,
    PuntoCurva, ValorizacionGuardada,
)
from .services.datos_ejemplo import cargar_datos_ejemplo
from .services.importers import import_contracts, import_curve_points

log = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────
# Datos de ejemplo
# ──────────────────────────────────────────────────────────────────────

@login_required
@require_POST
def datos_ejemplo(request):
    """
    Carga el conjunto de ejemplo para el usuario y lo deja listo para valorizar.

    Antes esto sólo existía como `manage.py cargar_demo`, de modo que para ver
    la aplicación funcionando había que tener acceso a la consola del servidor.
    """
    reset = request.POST.get('reset') == '1'
    try:
        resumen = cargar_datos_ejemplo(request.user, reset=reset)
    except Exception as exc:
        log.exception('Error cargando los datos de ejemplo')
        messages.error(request, f'No se pudieron cargar los datos de ejemplo: {exc}')
        return redirect('dashboard')

    messages.success(
        request,
        f'Datos de ejemplo cargados: {resumen["nodos"]} nodos de curva y '
        f'{resumen["contratos_totales"]} contratos en la cartera '
        f'"{resumen["cartera"].nombre}". El conjunto '
        f'"{resumen["conjunto"].label}" quedó activo.'
    )
    return redirect('valorizar')


# ──────────────────────────────────────────────────────────────────────
# Panel
# ──────────────────────────────────────────────────────────────────────

@login_required
def dashboard(request):
    user = request.user
    carteras = Cartera.objects.for_user(user)
    cartera_id = request.GET.get('cartera_id') or ''

    contratos = ContratoForward.objects.for_user(user).filter(status='Vigente')
    if cartera_id.isdigit():
        contratos = contratos.filter(cartera_id=int(cartera_id))

    ultima_val = ValorizacionGuardada.objects.for_user(user).first()
    active_curves = ConjuntoCurvas.objects.for_user(user).filter(is_active=True).first()

    # MtM por contraparte de la última valorización.
    cp_labels: list[str] = []
    cp_data: list[float] = []
    if ultima_val:
        lineas = ultima_val.lineas.all()
        if cartera_id.isdigit():
            lineas = lineas.filter(contrato__cartera_id=int(cartera_id))
        acumulado: dict[str, float] = {}
        for l in lineas:
            acumulado[l.counterparty] = acumulado.get(l.counterparty, 0.0) + float(l.mtm)
        ordenado = sorted(acumulado.items(), key=lambda kv: abs(kv[1]), reverse=True)
        cp_labels = [k for k, _ in ordenado]
        cp_data = [round(v, 2) for _, v in ordenado]

    # Curvas activas.
    fwd_dias = fwd_vals = desc_dias = desc_vals = []
    if active_curves:
        fwd = list(active_curves.puntos.filter(nombre='FWDUSDCLP').order_by('tenor_days'))
        desc = list(active_curves.puntos.filter(nombre='CLP423').order_by('tenor_days'))
        fwd_dias = [p.tenor_days for p in fwd]
        fwd_vals = [float(p.value) for p in fwd]
        desc_dias = [p.tenor_days for p in desc]
        desc_vals = [float(p.value) for p in desc]

    # Perfil de vencimientos: nocional por mes.
    venc: dict[str, float] = {}
    for c in contratos:
        clave = c.maturity_date.strftime('%Y-%m')
        venc[clave] = venc.get(clave, 0.0) + float(c.notional)
    venc_ordenado = sorted(venc.items())

    context = {
        'ultima_val': ultima_val,
        'carteras': carteras,
        'selected_cartera': int(cartera_id) if cartera_id.isdigit() else None,
        'num_conjuntos': ConjuntoCurvas.objects.for_user(user).count(),
        'num_contratos': contratos.count(),
        'num_valorizaciones': ValorizacionGuardada.objects.for_user(user).count(),
        'active_curves': active_curves,
        'contratos_compra': contratos.filter(side='Compra').count(),
        'contratos_venta': contratos.filter(side='Venta').count(),
        'total_nocional': sum(float(c.notional) for c in contratos),
        'proximos_vencimientos': contratos.order_by('maturity_date')[:5],
        'chart_cp_labels': json.dumps(cp_labels),
        'chart_cp_data': json.dumps(cp_data),
        'chart_fwd_dias': json.dumps(fwd_dias),
        'chart_fwd_tasas': json.dumps(fwd_vals),
        'chart_desc_dias': json.dumps(desc_dias),
        'chart_desc_tasas': json.dumps(desc_vals),
        'chart_venc_labels': json.dumps([k for k, _ in venc_ordenado]),
        'chart_venc_data': json.dumps([round(v, 2) for _, v in venc_ordenado]),
    }
    return render(request, 'valorizador/dashboard.html', context)


# ──────────────────────────────────────────────────────────────────────
# Curvas
# ──────────────────────────────────────────────────────────────────────

@login_required
def curvas_list(request):
    conjuntos = ConjuntoCurvas.objects.for_user(request.user)
    return render(request, 'valorizador/curvas_list.html', {'conjuntos': conjuntos})


@login_required
def curvas_create(request):
    return _curvas_form(request, None)


@login_required
def curvas_edit(request, pk):
    conjunto = get_object_or_404(ConjuntoCurvas.objects.for_user(request.user), pk=pk)
    return _curvas_form(request, conjunto)


def _curvas_form(request, conjunto):
    if request.method == 'POST':
        form = ConjuntoCurvasForm(request.POST, instance=conjunto)
        fwd_raw = request.POST.get('fwd_points', '[]')
        desc_raw = request.POST.get('desc_points', '[]')
        try:
            fwd_points = json.loads(fwd_raw)
            desc_points = json.loads(desc_raw)
        except json.JSONDecodeError:
            fwd_points = desc_points = []
            messages.error(request, 'No se pudieron leer los puntos de curva enviados.')

        if not fwd_points:
            form.add_error(None, 'Carga al menos un punto en la curva forward.')
        if not desc_points:
            form.add_error(None, 'Carga al menos un punto en la curva de descuento.')

        if form.is_valid():
            with transaction.atomic():
                obj = form.save(commit=False)
                if conjunto is None:
                    obj.created_by = request.user
                if not obj.label:
                    obj.label = f'Curvas {obj.valuation_date}'
                obj.save()
                obj.puntos.all().delete()
                PuntoCurva.objects.bulk_create([
                    PuntoCurva(conjunto=obj, nombre='FWDUSDCLP',
                               tenor_days=int(p['tenor_days']),
                               value=Decimal(str(p['value'])))
                    for p in fwd_points
                ] + [
                    PuntoCurva(conjunto=obj, nombre='CLP423',
                               tenor_days=int(p['tenor_days']),
                               value=Decimal(str(p['value'])))
                    for p in desc_points
                ])
            messages.success(request, f'Conjunto "{obj.label}" guardado.')
            return redirect('curvas_list')
    else:
        initial = {}
        if conjunto is None:
            initial = {
                'valuation_date': date.today(),
                'label': f'Curvas {date.today()}',
                'source': 'Bloomberg',
            }
        form = ConjuntoCurvasForm(instance=conjunto, initial=initial)

    fwd_json = desc_json = '[]'
    if conjunto is not None:
        fwd_json = json.dumps([
            {'tenor_days': p.tenor_days, 'value': float(p.value)}
            for p in conjunto.puntos.filter(nombre='FWDUSDCLP').order_by('tenor_days')
        ])
        desc_json = json.dumps([
            {'tenor_days': p.tenor_days, 'value': float(p.value)}
            for p in conjunto.puntos.filter(nombre='CLP423').order_by('tenor_days')
        ])

    return render(request, 'valorizador/curvas_form.html', {
        'form': form,
        'editing': conjunto is not None,
        'conjunto': conjunto,
        'fwd_points_json': fwd_json,
        'desc_points_json': desc_json,
    })


@login_required
def curvas_detail(request, pk):
    conjunto = get_object_or_404(ConjuntoCurvas.objects.for_user(request.user), pk=pk)
    fwd = [{'tenor_days': p.tenor_days, 'value': float(p.value)}
           for p in conjunto.puntos.filter(nombre='FWDUSDCLP').order_by('tenor_days')]
    desc = [{'tenor_days': p.tenor_days, 'value': float(p.value)}
            for p in conjunto.puntos.filter(nombre='CLP423').order_by('tenor_days')]

    fwd_v = [p['value'] for p in fwd]
    desc_v = [p['value'] for p in desc]

    # Puntos forward implícitos respecto del spot: informativo y útil para
    # detectar curvas cargadas con la unidad equivocada.
    spot = float(conjunto.spot_usdclp)
    puntos_fwd = [{'tenor_days': p['tenor_days'], 'value': round(p['value'] - spot, 4)}
                  for p in fwd]

    return render(request, 'valorizador/curvas_detail.html', {
        'conjunto': conjunto,
        'fwd_json': json.dumps(fwd),
        'desc_json': json.dumps(desc),
        'puntos_fwd_json': json.dumps(puntos_fwd),
        'spot_json': json.dumps(spot),
        'fwd_count': len(fwd),
        'desc_count': len(desc),
        'fwd_min': min(fwd_v) if fwd_v else 0,
        'fwd_max': max(fwd_v) if fwd_v else 0,
        'fwd_spread': round(max(fwd_v) - min(fwd_v), 4) if fwd_v else 0,
        'desc_min': round(min(desc_v), 4) if desc_v else 0,
        'desc_max': round(max(desc_v), 4) if desc_v else 0,
        'desc_spread': round(max(desc_v) - min(desc_v), 4) if desc_v else 0,
    })


@login_required
@require_POST
def curvas_delete(request, pk):
    conjunto = get_object_or_404(ConjuntoCurvas.objects.for_user(request.user), pk=pk)
    conjunto.delete()
    messages.success(request, 'Conjunto eliminado.')
    return redirect('curvas_list')


@login_required
@require_POST
def curvas_duplicate(request, pk):
    original = get_object_or_404(ConjuntoCurvas.objects.for_user(request.user), pk=pk)
    with transaction.atomic():
        nuevo = ConjuntoCurvas.objects.create(
            label=f'{original.label} (copia)',
            valuation_date=original.valuation_date,
            spot_usdclp=original.spot_usdclp,
            source=original.source,
            created_by=request.user,
        )
        PuntoCurva.objects.bulk_create([
            PuntoCurva(conjunto=nuevo, nombre=p.nombre,
                       tenor_days=p.tenor_days, value=p.value)
            for p in original.puntos.all()
        ])
    messages.success(request, f'Conjunto duplicado: "{nuevo.label}".')
    return redirect('curvas_list')


@login_required
@require_POST
def curvas_activate(request, pk):
    conjunto = get_object_or_404(ConjuntoCurvas.objects.for_user(request.user), pk=pk)
    with transaction.atomic():
        ConjuntoCurvas.objects.filter(created_by=request.user).update(is_active=False)
        ConjuntoCurvas.objects.filter(pk=conjunto.pk).update(is_active=True)
    messages.success(request, f'"{conjunto.label}" es ahora el conjunto activo.')
    return redirect('curvas_list')


@login_required
@require_POST
def curvas_import_points(request):
    """Importa nodos de curva desde archivo y los devuelve al formulario."""
    form = ArchivoUploadForm(request.POST, request.FILES)
    if not form.is_valid():
        return JsonResponse({'error': '; '.join(form.errors['archivo'])}, status=400)

    curve_type = request.POST.get('type', 'forward')
    try:
        points, errores = import_curve_points(form.cleaned_data['archivo'], curve_type)
    except Exception as exc:
        log.exception('Error importando curva')
        return JsonResponse({'error': f'No se pudo procesar el archivo: {exc}'}, status=400)

    if not points:
        return JsonResponse(
            {'error': 'No se detectaron filas válidas.', 'detalles': errores}, status=400
        )
    return JsonResponse({'points': points, 'avisos': errores})


# ──────────────────────────────────────────────────────────────────────
# Carteras y contrapartes
# ──────────────────────────────────────────────────────────────────────

@login_required
def carteras_list(request):
    carteras = Cartera.objects.for_user(request.user)
    return render(request, 'valorizador/carteras_list.html', {'carteras': carteras})


@login_required
def cartera_create(request):
    if request.method == 'POST':
        form = CarteraForm(request.POST)
        if form.is_valid():
            obj = form.save(commit=False)
            obj.created_by = request.user
            obj.save()
            messages.success(request, f'Cartera "{obj.nombre}" creada.')
            return redirect('carteras_list')
    else:
        form = CarteraForm()
    return render(request, 'valorizador/cartera_form.html', {'form': form})


@login_required
@require_POST
def cartera_delete(request, pk):
    cartera = get_object_or_404(Cartera.objects.for_user(request.user), pk=pk)
    cartera.delete()
    messages.success(request, 'Cartera eliminada. Los contratos quedaron sin cartera.')
    return redirect('carteras_list')


@login_required
def contrapartes_list(request):
    if request.method == 'POST':
        form = ContraparteForm(request.POST)
        if form.is_valid():
            obj = form.save(commit=False)
            obj.created_by = request.user
            obj.save()
            messages.success(request, f'Contraparte "{obj.nombre}" guardada.')
            return redirect('contrapartes_list')
    else:
        form = ContraparteForm()
    return render(request, 'valorizador/contrapartes_list.html', {
        'contrapartes': Contraparte.objects.for_user(request.user),
        'form': form,
    })


# ──────────────────────────────────────────────────────────────────────
# Contratos
# ──────────────────────────────────────────────────────────────────────

@login_required
def contratos_list(request):
    contratos = ContratoForward.objects.for_user(request.user).select_related('cartera')
    estado = request.GET.get('estado', 'Vigente')
    if estado:
        contratos = contratos.filter(status=estado)

    cartera_id = request.GET.get('cartera', '')
    cartera_obj = None
    if cartera_id.isdigit():
        contratos = contratos.filter(cartera_id=int(cartera_id))
        cartera_obj = Cartera.objects.for_user(request.user).filter(pk=int(cartera_id)).first()

    q = request.GET.get('q', '').strip()
    if q:
        from django.db.models import Q
        contratos = contratos.filter(Q(counterparty__icontains=q) | Q(folio__icontains=q))

    return render(request, 'valorizador/contratos_list.html', {
        'contratos': contratos,
        'cartera_obj': cartera_obj,
        'carteras': Cartera.objects.for_user(request.user),
        'estado': estado,
        'q': q,
        'total_nocional': sum(float(c.notional) for c in contratos),
    })


@login_required
def contrato_create(request):
    if request.method == 'POST':
        form = ContratoForm(request.POST, user=request.user)
        if form.is_valid():
            obj = form.save(commit=False)
            obj.created_by = request.user
            if obj.contraparte_ref and not obj.counterparty:
                obj.counterparty = obj.contraparte_ref.nombre
            obj.save()
            messages.success(request, 'Contrato agregado.')
            return redirect('contratos_list')
    else:
        form = ContratoForm(user=request.user)
    return render(request, 'valorizador/contrato_form.html', {'form': form, 'editing': False})


@login_required
def contrato_edit(request, pk):
    contrato = get_object_or_404(ContratoForward.objects.for_user(request.user), pk=pk)
    if request.method == 'POST':
        form = ContratoForm(request.POST, instance=contrato, user=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, 'Contrato actualizado.')
            return redirect('contratos_list')
    else:
        form = ContratoForm(instance=contrato, user=request.user)
    return render(request, 'valorizador/contrato_form.html', {
        'form': form, 'editing': True, 'contrato': contrato,
    })


@login_required
@require_POST
def contrato_delete(request, pk):
    contrato = get_object_or_404(ContratoForward.objects.for_user(request.user), pk=pk)
    contrato.delete()
    messages.success(request, 'Contrato eliminado.')
    return redirect('contratos_list')


@login_required
def contratos_import(request):
    preview: list[dict] = []
    errores: list[str] = []

    if request.method == 'POST' and 'confirm' in request.POST:
        try:
            data = json.loads(request.POST.get('import_data', '[]'))
        except json.JSONDecodeError:
            messages.error(request, 'Los datos de importación no se pudieron leer.')
            return redirect('contratos_import')

        cartera_id = request.POST.get('cartera_id', '')
        cartera = None
        if cartera_id.isdigit():
            cartera = Cartera.objects.for_user(request.user).filter(pk=int(cartera_id)).first()

        existentes = set(
            ContratoForward.objects.filter(created_by=request.user)
            .values_list('folio', flat=True)
        )
        nuevos, omitidos = [], 0
        for c in data:
            folio = (c.get('folio') or '').strip()
            if folio and folio in existentes:
                omitidos += 1
                continue
            if folio:
                existentes.add(folio)
            try:
                nuevos.append(ContratoForward(
                    counterparty=c.get('counterparty', ''),
                    folio=folio,
                    side=c.get('side', 'Venta'),
                    modality=c.get('modality', 'Compensacion'),
                    base_ccy=c.get('base_ccy', 'USD'),
                    quote_ccy=c.get('quote_ccy', 'CLP'),
                    notional=Decimal(str(c['notional'])),
                    fwd_price=Decimal(str(c['fwd_price'])),
                    spot_inicio=Decimal(str(c.get('spot_inicio', 0))),
                    start_date=c.get('start_date') or None,
                    maturity_date=c['maturity_date'],
                    fwd_curve=c.get('fwd_curve', 'FWDUSDCLP'),
                    disc_curve=c.get('disc_curve', 'CLP423'),
                    cartera=cartera,
                    created_by=request.user,
                ))
            except (KeyError, InvalidOperation) as exc:
                errores.append(f'Fila con folio "{folio}" descartada: {exc}')

        with transaction.atomic():
            ContratoForward.objects.bulk_create(nuevos)

        msg = f'{len(nuevos)} contratos importados.'
        if omitidos:
            msg += f' {omitidos} omitidos por folio duplicado.'
        messages.success(request, msg)
        for e in errores:
            messages.warning(request, e)
        return redirect('contratos_list')

    if request.method == 'POST':
        form = ArchivoUploadForm(request.POST, request.FILES)
        if form.is_valid():
            try:
                preview, errores = import_contracts(form.cleaned_data['archivo'])
            except Exception as exc:
                log.exception('Error importando contratos')
                messages.error(request, f'No se pudo leer el archivo: {exc}')
            if not preview and not errores:
                messages.error(request, 'No se detectaron contratos válidos.')
        else:
            messages.error(request, '; '.join(form.errors.get('archivo', ['Archivo inválido.'])))
    else:
        form = ArchivoUploadForm()

    return render(request, 'valorizador/contrato_import.html', {
        'form': ArchivoUploadForm(),
        'preview': preview,
        'preview_json': json.dumps(preview, default=str),
        'errores': errores,
        'carteras': Cartera.objects.for_user(request.user),
    })


@login_required
def contratos_export_csv(request):
    contratos = ContratoForward.objects.for_user(request.user).filter(status='Vigente')
    response = HttpResponse(content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = 'attachment; filename="contratos.csv"'
    response.write('﻿')
    w = csv.writer(response, delimiter=';')
    w.writerow(['Contraparte', 'Folio', 'Operacion', 'Modalidad', 'Moneda', 'Monto',
                'Precio Fwd', 'Spot inicio', 'Inicio', 'Vencimiento', 'Cartera'])
    for c in contratos:
        w.writerow([c.counterparty, c.folio, c.side, c.modality, c.base_ccy, c.notional,
                    c.fwd_price, c.spot_inicio, c.start_date or '', c.maturity_date,
                    c.cartera.nombre if c.cartera else ''])
    return response


# ──────────────────────────────────────────────────────────────────────
# Valorizar
# ──────────────────────────────────────────────────────────────────────

def _build_config(cd: dict) -> PricingConfig:
    return PricingConfig(
        day_count=cd['day_count'],
        interp_method=cd['interp_method'],
        extrap_method=cd['extrap_method'],
        business_days=cd['business_days'],
        calendar=cd['calendar'],
        compounding=cd['compounding'],
        calc_greeks=cd.get('calc_greeks', True),
        calc_cva=cd.get('calc_cva', False),
        netting=cd.get('netting', True),
        credit=CreditProfile(
            spread_bp=float(cd.get('spread_bp') or 100),
            recovery=float(cd.get('recovery') or 0.4),
            own_spread_bp=float(cd.get('spread_bp') or 100) * 0.6,
            fx_vol=float(cd.get('fx_vol') or 0.12),
        ),
    )


@login_required
def valorizar(request):
    user = request.user
    activo = ConjuntoCurvas.objects.for_user(user).filter(is_active=True).first()

    initial = {
        'fecha_valoracion': activo.valuation_date if activo else date.today(),
        'conjunto': activo.pk if activo else None,
        'spot_val': activo.spot_usdclp if activo else None,
    }

    result = sensibilidad = None
    contratos_qs = ContratoForward.objects.for_user(user).filter(status='Vigente')

    if request.method == 'POST':
        form = ValorizarForm(request.POST, user=user)
        if form.is_valid():
            cd = form.cleaned_data
            conjunto = cd['conjunto']
            seleccion = form.selected_ids()

            contratos_qs = contratos_qs.filter(base_ccy=cd['moneda'])
            if cd.get('cartera'):
                contratos_qs = contratos_qs.filter(cartera=cd['cartera'])
            elegidos = list(contratos_qs.filter(pk__in=seleccion)) if seleccion else list(contratos_qs)

            if not elegidos:
                messages.error(request, 'No hay contratos seleccionados para valorizar.')
            else:
                config = _build_config(cd)
                spot = float(cd['spot_val']) if cd.get('spot_val') else float(conjunto.spot_usdclp)
                market = MarketData(
                    valuation_date=cd['fecha_valoracion'],
                    spot=spot,
                    curves=conjunto.as_curves(),
                    label=cd.get('etiqueta') or conjunto.label,
                )
                try:
                    result = price_portfolio([c.to_core() for c in elegidos], market, config)
                    result['conjunto_id'] = conjunto.pk
                    sensibilidad = sensitivity_matrix(
                        [c.to_core() for c in elegidos], market, config,
                        shock_max=float(cd['shock_max']),
                    )
                except Exception as exc:
                    log.exception('Error al valorizar')
                    messages.error(request, f'Error al valorizar: {exc}')
        else:
            messages.error(request, 'Revisa los parámetros del formulario.')
    else:
        form = ValorizarForm(initial=initial, user=user)
        contratos_qs = contratos_qs.filter(base_ccy='USD')

    return render(request, 'valorizador/valorizar.html', {
        'form': form,
        'contratos': contratos_qs,
        'result': result,
        'result_json': json.dumps(result, default=str) if result else '',
        'sensibilidad': sensibilidad,
        'conjuntos': ConjuntoCurvas.objects.for_user(user),
    })


@login_required
@require_POST
def valorizar_guardar(request):
    try:
        data = json.loads(request.POST.get('result_data', '{}'))
    except json.JSONDecodeError:
        messages.error(request, 'No se pudieron leer los resultados a guardar.')
        return redirect('valorizar')

    if not data.get('lines'):
        messages.error(request, 'No hay resultados que guardar.')
        return redirect('valorizar')

    conjunto = None
    conjunto_id = data.get('conjunto_id')
    if conjunto_id:
        conjunto = ConjuntoCurvas.objects.for_user(request.user).filter(pk=conjunto_id).first()

    t = data.get('totals', {})
    try:
        with transaction.atomic():
            val = ValorizacionGuardada.objects.create(
                valuation_date=data['valuation_date'],
                label=data.get('label', ''),
                curve_set=conjunto,
                spot=Decimal(str(data.get('spot', 0))),
                total_mtm=Decimal(str(t.get('total_mtm', 0))),
                total_mtm_ajustado=Decimal(str(t.get('total_mtm_ajustado', 0))),
                total_spot=Decimal(str(t.get('total_spot', 0))),
                total_fwdpoints=Decimal(str(t.get('total_fwdpoints', 0))),
                total_delta=Decimal(str(t.get('total_delta', 0))),
                total_dv01=Decimal(str(t.get('total_dv01', 0))),
                total_cva=Decimal(str(t.get('total_cva', 0))),
                total_dva=Decimal(str(t.get('total_dva', 0))),
                num_contracts=data.get('diagnostics', {}).get('valued', 0),
                config_json=data.get('config', {}),
                created_by=request.user,
            )
            lineas = []
            for line in data['lines']:
                if line.get('error'):
                    continue
                lineas.append(LineaValorizacion(
                    valorizacion=val,
                    contrato_id=line.get('contract_id'),
                    folio=line.get('folio', ''),
                    counterparty=line.get('counterparty', ''),
                    cartera_nombre=line.get('cartera', ''),
                    side=line.get('side', ''),
                    maturity_date=line['maturity_date'],
                    notional=Decimal(str(line['notional'])),
                    currency=line.get('currency', 'USD'),
                    spot_inicio=Decimal(str(line.get('spot_inicio', 0))),
                    spot_val=Decimal(str(line.get('spot_val', 0))),
                    fwd_contract=Decimal(str(line['fwd_contract'])),
                    fwd_mkt=Decimal(str(line.get('fwd_mkt', 0))),
                    days_to_mat=line.get('days_to_mat', 0),
                    year_fraction=Decimal(str(line.get('year_fraction', 0))),
                    disc_rate=Decimal(str(line.get('disc_rate', 0))),
                    disc_factor=Decimal(str(line.get('disc_factor', 0))),
                    mtm=Decimal(str(line['mtm'])),
                    mtm_ajustado=Decimal(str(line.get('mtm_ajustado', line['mtm']))),
                    spot_component=Decimal(str(line.get('spot_component', 0))),
                    fwd_points=Decimal(str(line.get('fwd_points', 0))),
                    delta=Decimal(str(line.get('delta', 0))),
                    dv01=Decimal(str(line.get('dv01', 0))),
                    theta_1d=Decimal(str(line.get('theta_1d', 0))),
                    cva=Decimal(str(line.get('cva', 0))),
                    dva=Decimal(str(line.get('dva', 0))),
                    flags=line.get('flags', []),
                ))
            LineaValorizacion.objects.bulk_create(lineas)
    except Exception as exc:
        log.exception('Error al guardar valorización')
        messages.error(request, f'Error al guardar: {exc}')
        return redirect('valorizar')

    messages.success(request, 'Valorización guardada.')
    return redirect('valorizacion_detail', pk=val.pk)


# ──────────────────────────────────────────────────────────────────────
# Valorizaciones guardadas
# ──────────────────────────────────────────────────────────────────────

@login_required
def valorizaciones_list(request):
    return render(request, 'valorizador/valorizaciones_list.html', {
        'valorizaciones': ValorizacionGuardada.objects.for_user(request.user),
    })


@login_required
def valorizacion_detail(request, pk):
    val = get_object_or_404(ValorizacionGuardada.objects.for_user(request.user), pk=pk)
    lineas = list(val.lineas.all())

    total_delta = float(val.total_delta)
    total_dv01 = float(val.total_dv01)
    base_mtm = float(val.total_mtm)

    # Mapa de calor de primer orden: exacto en spot (el producto es lineal) y
    # de primer orden en tasa.
    spot_shifts = [-20, -10, 0, 10, 20]
    rate_shifts = [100, 50, 0, -50, -100]
    heatmap = []
    max_abs = max(
        (abs(total_delta * s + total_dv01 * r) for s in spot_shifts for r in rate_shifts),
        default=0.0,
    ) or 1.0

    for rs in rate_shifts:
        fila = {'rate_shift': rs, 'cells': []}
        for ss in spot_shifts:
            shift = total_delta * ss + total_dv01 * rs
            intensidad = min(abs(shift) / max_abs, 1.0)
            if shift > 0:
                color = f'rgba(16, 185, 129, {0.08 + intensidad * 0.55:.3f})'
                clase = 'pos'
            elif shift < 0:
                color = f'rgba(206, 44, 44, {0.08 + intensidad * 0.55:.3f})'
                clase = 'neg'
            else:
                color, clase = 'transparent', ''
            fila['cells'].append({
                'spot_shift': ss,
                'new_mtm': base_mtm + shift,
                'mtm_shift': shift,
                'bg_color': color,
                'text_class': clase,
            })
        heatmap.append(fila)

    por_contraparte: dict[str, dict] = {}
    for l in lineas:
        d = por_contraparte.setdefault(
            l.counterparty or '(sin contraparte)',
            {'mtm': 0.0, 'notional': 0.0, 'cva': 0.0, 'n': 0},
        )
        d['mtm'] += float(l.mtm)
        d['notional'] += float(l.notional)
        d['cva'] += float(l.cva)
        d['n'] += 1

    return render(request, 'valorizador/valorizacion_detail.html', {
        'val': val,
        'lineas': lineas,
        'config': val.config_json or {},
        'total_delta': total_delta,
        'total_dv01': total_dv01,
        'total_theta': sum(float(l.theta_1d) for l in lineas),
        'total_cva': float(val.total_cva),
        'total_dva': float(val.total_dva),
        'spot_shifts': spot_shifts,
        'heatmap_matrix': heatmap,
        'por_contraparte': sorted(
            por_contraparte.items(), key=lambda kv: abs(kv[1]['mtm']), reverse=True
        ),
    })


@login_required
def valorizacion_export_csv(request, pk):
    val = get_object_or_404(ValorizacionGuardada.objects.for_user(request.user), pk=pk)
    response = HttpResponse(content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="valorizacion_{val.valuation_date}.csv"'
    response.write('﻿')
    w = csv.writer(response, delimiter=';')
    w.writerow(['Folio', 'Contraparte', 'Cartera', 'Operacion', 'Vcto', 'Monto', 'Moneda',
                'TC inicio', 'Fwd contrato', 'Dias', 'Fraccion anio', 'Fwd mercado',
                'TC valorizacion', 'Tasa desc %', 'Factor desc', 'MTM', 'MTM ajustado',
                'Componente spot', 'Puntos fwd', 'Delta', 'DV01', 'Theta 1d', 'CVA', 'DVA'])
    for l in val.lineas.all():
        w.writerow([l.folio, l.counterparty, l.cartera_nombre, l.side, l.maturity_date,
                    l.notional, l.currency, l.spot_inicio, l.fwd_contract, l.days_to_mat,
                    l.year_fraction, l.fwd_mkt, l.spot_val, l.disc_rate, l.disc_factor,
                    l.mtm, l.mtm_ajustado, l.spot_component, l.fwd_points, l.delta,
                    l.dv01, l.theta_1d, l.cva, l.dva])
    w.writerow(['TOTAL', '', '', '', '', '', '', '', '', '', '', '', '', '', '',
                val.total_mtm, val.total_mtm_ajustado, val.total_spot,
                val.total_fwdpoints, val.total_delta, val.total_dv01, '',
                val.total_cva, val.total_dva])
    return response


@login_required
def valorizacion_export_xlsx(request, pk):
    """Exporta la valorización a Excel con fórmulas vivas."""
    from .services.excel_export import build_workbook

    val = get_object_or_404(ValorizacionGuardada.objects.for_user(request.user), pk=pk)
    stream = build_workbook(val)
    response = HttpResponse(
        stream.getvalue(),
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )
    response['Content-Disposition'] = (
        f'attachment; filename="valorizacion_{val.valuation_date}.xlsx"'
    )
    return response


@login_required
@require_POST
def valorizacion_delete(request, pk):
    val = get_object_or_404(ValorizacionGuardada.objects.for_user(request.user), pk=pk)
    val.delete()
    messages.success(request, 'Valorización eliminada.')
    return redirect('valorizaciones_list')


# ──────────────────────────────────────────────────────────────────────
# Carga del libro Cordada
# ──────────────────────────────────────────────────────────────────────

@login_required
def upload_excel(request):
    resumen = None
    if request.method == 'POST':
        form = ArchivoUploadForm(request.POST, request.FILES)
        if form.is_valid():
            resumen = _procesar_libro_cordada(request, form.cleaned_data['archivo'])
            if resumen and resumen.get('ok'):
                return redirect('dashboard')
        else:
            messages.error(request, '; '.join(form.errors.get('archivo', ['Archivo inválido.'])))
    else:
        form = ArchivoUploadForm()

    return render(request, 'valorizador/upload.html', {
        'form': form,
        'carteras': Cartera.objects.for_user(request.user),
        'resumen': resumen,
    })


def _procesar_libro_cordada(request, archivo):
    import os
    import tempfile

    from .services.cordada_excel import CordadaWorkbook

    suffix = os.path.splitext(archivo.name)[1] or '.xlsm'
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        for chunk in archivo.chunks():
            tmp.write(chunk)
        tmp_path = tmp.name

    try:
        libro = CordadaWorkbook(tmp_path)
        fecha, spot = libro.valuation_date_and_spot()
        curvas = libro.curves()
        contratos = libro.contracts()
        avisos = list(libro.warnings)
        libro.close()

        if not curvas:
            messages.error(request, 'El libro no traía curvas utilizables.')
            return {'ok': False, 'avisos': avisos}

        fecha = fecha or date.today()
        spot = spot or 0

        cartera_id = request.POST.get('cartera_id', '')
        cartera = None
        if cartera_id.isdigit():
            cartera = Cartera.objects.for_user(request.user).filter(pk=int(cartera_id)).first()

        with transaction.atomic():
            ConjuntoCurvas.objects.filter(created_by=request.user).update(is_active=False)
            conjunto = ConjuntoCurvas.objects.create(
                label=f'Libro cargado {fecha}',
                valuation_date=fecha,
                spot_usdclp=Decimal(str(spot)),
                source='Libro Excel',
                is_active=True,
                created_by=request.user,
            )
            puntos = []
            for nombre, nodos in curvas.items():
                for p in nodos:
                    puntos.append(PuntoCurva(
                        conjunto=conjunto, nombre=nombre,
                        tenor_days=p['tenor_days'],
                        value=Decimal(str(round(p['value'], 8))),
                    ))
            PuntoCurva.objects.bulk_create(puntos)

            existentes = set(
                ContratoForward.objects.filter(created_by=request.user)
                .values_list('folio', flat=True)
            )
            nuevos = []
            for c in contratos:
                if c['folio'] and c['folio'] in existentes:
                    continue
                if c['folio']:
                    existentes.add(c['folio'])
                nuevos.append(ContratoForward(
                    counterparty=c['counterparty'], folio=c['folio'], side=c['side'],
                    modality=c['modality'], base_ccy=c['base_ccy'], quote_ccy=c['quote_ccy'],
                    notional=Decimal(str(c['notional'])),
                    fwd_price=Decimal(str(c['fwd_price'] or 0)),
                    spot_inicio=Decimal(str(c['spot_inicio'] or 0)),
                    start_date=c['start_date'], maturity_date=c['maturity_date'],
                    cartera=cartera, created_by=request.user,
                ))
            ContratoForward.objects.bulk_create(nuevos)

        for a in avisos:
            messages.warning(request, a)
        messages.success(
            request,
            f'Libro procesado: {len(puntos)} nodos de curva en {len(curvas)} curvas y '
            f'{len(nuevos)} contratos nuevos.'
        )
        return {
            'ok': True, 'fecha': fecha, 'spot': spot, 'curvas': list(curvas),
            'n_puntos': len(puntos), 'n_contratos': len(nuevos), 'avisos': avisos,
        }
    except Exception as exc:
        log.exception('Error procesando libro Cordada')
        messages.error(request, f'No se pudo procesar el libro: {exc}')
        return {'ok': False, 'avisos': [str(exc)]}
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


# ──────────────────────────────────────────────────────────────────────
# Asistente
# ──────────────────────────────────────────────────────────────────────

@login_required
@require_POST
def api_chat(request):
    """
    Asistente sobre la metodología y la cartera del usuario.

    A diferencia del original: exige sesión, respeta CSRF, limita la frecuencia
    y sólo expone datos del usuario autenticado.
    """
    from django.conf import settings

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

    try:
        payload = json.loads(request.body or '{}')
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Cuerpo de la solicitud inválido.'}, status=400)

    mensaje = (payload.get('message') or '').strip()[:4000]
    if not mensaje:
        return JsonResponse({'error': 'El mensaje es obligatorio.'}, status=400)

    historial = payload.get('history', [])[-10:]

    try:
        import google.generativeai as genai
    except ImportError:
        return JsonResponse(
            {'error': 'Falta la dependencia google-generativeai en el servidor.'}, status=503
        )

    try:
        genai.configure(api_key=settings.GEMINI_API_KEY)
        modelo = genai.GenerativeModel(
            settings.GEMINI_MODEL,
            system_instruction=_contexto_asistente(request.user),
        )
        chat = modelo.start_chat(history=[
            {'role': 'model' if m.get('role') == 'assistant' else 'user',
             'parts': [str(m.get('content', ''))[:4000]]}
            for m in historial
        ])
        respuesta = chat.send_message(mensaje)
        return JsonResponse({'response': respuesta.text})
    except Exception as exc:
        log.exception('Error en el asistente')
        return JsonResponse(
            {'error': 'El asistente no está disponible en este momento.'}, status=502
        )


def _contexto_asistente(user) -> str:
    contratos = ContratoForward.objects.filter(created_by=user, status='Vigente')
    n = contratos.count()
    lineas = [
        'Eres un asistente experto en valorización de forwards FX para el mercado chileno.',
        'Explicas metodología (interpolación, convenciones de días, descuento, griegas, CVA)',
        'en español, de forma clara y concisa. No inventas cifras: si no tienes el dato, lo dices.',
        '',
        f'Contexto del usuario {user.username}:',
    ]
    if n == 0:
        lineas.append('- No tiene contratos vigentes cargados.')
        return '\n'.join(lineas)

    por_moneda: dict[str, float] = {}
    for c in contratos:
        por_moneda[c.base_ccy] = por_moneda.get(c.base_ccy, 0.0) + float(c.notional)

    lineas.append(f'- {n} contratos vigentes.')
    for m, v in por_moneda.items():
        lineas.append(f'- Nocional total {m}: {v:,.2f}')

    ultima = ValorizacionGuardada.objects.filter(created_by=user).first()
    if ultima:
        lineas.append(
            f'- Última valorización: {ultima.valuation_date}, '
            f'MtM total {float(ultima.total_mtm):,.0f} CLP.'
        )
    lineas.append('- Detalle (hasta 50 contratos):')
    for c in contratos[:50]:
        lineas.append(
            f'  * {c.folio or "s/folio"} | {c.side} {float(c.notional):,.0f} {c.base_ccy} '
            f'@ {c.fwd_price} con {c.counterparty}, vence {c.maturity_date}'
        )
    return '\n'.join(lineas)
