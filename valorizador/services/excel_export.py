"""
Exportación de una valorización guardada al libro Excel con fórmulas vivas.

La vista `valorizacion_export_xlsx` lo usa así:

    from .services.excel_export import build_workbook
    stream = build_workbook(val)          # -> io.BytesIO

La construcción del libro es exactamente la misma que la del script
`scripts/build_excel_model.py`: ambos delegan en `core.excel_model`, de modo que
la plantilla que se distribuye y el archivo que descarga un usuario desde la
aplicación son el mismo modelo, con las mismas fórmulas.

Lo único propio de este módulo es la traducción del modelo de datos de Django
(`ValorizacionGuardada` + `LineaValorizacion` + `ConjuntoCurvas`) a la estructura
plana `WorkbookData` que el constructor entiende, más la detección de las
combinaciones de configuración que el libro no puede reproducir con fórmulas
(por ejemplo capitalización simple o continua), que se informan como
advertencias en la portada en lugar de exportarse en silencio.
"""

from __future__ import annotations

import io
from datetime import date

from core.excel_model import (
    ALL_SHEETS,
    SH_CON,
    SH_CUR,
    SH_MET,
    SH_PAR,
    SH_POR,
    SH_REC,
    SH_SEN,
    SH_VAL,
    ContractRow,
    WorkbookData,
    build_workbook_bytes,
    build_workbook_object,
)

__all__ = ["build_workbook", "build_workbook_data", "HOJAS_EXPORTACION"]

# Hojas incluidas en la exportación desde la aplicación. Son las mismas que la
# plantilla; Griegas y Reconciliación se agregan porque la valorización guardada
# trae los valores del motor y así el usuario puede auditar la descarga.
HOJAS_EXPORTACION = ALL_SHEETS

_YEAR_BASIS = {
    "ACT/360": 360,
    "ACT/365": 365,
    "30/360": 360,
    "30E/360": 360,
    "ACT/ACT": 365,
}


# ──────────────────────────────────────────────────────────────────────
# Curvas
# ──────────────────────────────────────────────────────────────────────

def _nodos_por_curva(valorizacion) -> dict[str, list[tuple[float, float]]]:
    conjunto = getattr(valorizacion, "curve_set", None)
    if conjunto is None:
        return {}
    salida: dict[str, list[tuple[float, float]]] = {}
    for p in conjunto.puntos.all().order_by("nombre", "tenor_days"):
        salida.setdefault(p.nombre, []).append((float(p.tenor_days), float(p.value)))
    for nodos in salida.values():
        nodos.sort()
    return salida


def _elegir_curvas(nodos: dict[str, list], lineas) -> tuple[list, list, list[str]]:
    """
    El libro tiene un bloque para la curva forward y otro para la de descuento.
    Cuando la valorización usó más de una curva de cada tipo, se exporta la más
    utilizada por los contratos y se deja constancia en las advertencias.
    """
    advertencias: list[str] = []
    if not nodos:
        return [], [], ["La valorización no tiene un conjunto de curvas asociado: "
                        "los bloques de curvas del libro salen vacíos."]

    usos_fwd: dict[str, int] = {}
    usos_desc: dict[str, int] = {}
    for ln in lineas:
        contrato = getattr(ln, "contrato", None)
        if contrato is None:
            continue
        if contrato.fwd_curve in nodos:
            usos_fwd[contrato.fwd_curve] = usos_fwd.get(contrato.fwd_curve, 0) + 1
        if contrato.disc_curve in nodos:
            usos_desc[contrato.disc_curve] = usos_desc.get(contrato.disc_curve, 0) + 1

    def _mejor(usos: dict[str, int], predicado) -> str | None:
        if usos:
            return max(usos.items(), key=lambda kv: kv[1])[0]
        candidatos = [n for n in nodos if predicado(n)]
        return candidatos[0] if candidatos else None

    nombre_fwd = _mejor(usos_fwd, lambda n: n.upper().startswith("FWD"))
    nombre_desc = _mejor(usos_desc, lambda n: not n.upper().startswith("FWD"))

    if len(usos_fwd) > 1:
        advertencias.append(
            f"Los contratos usan {len(usos_fwd)} curvas forward distintas "
            f"({', '.join(sorted(usos_fwd))}); el libro exporta sólo '{nombre_fwd}'."
        )
    if len(usos_desc) > 1:
        advertencias.append(
            f"Los contratos usan {len(usos_desc)} curvas de descuento distintas "
            f"({', '.join(sorted(usos_desc))}); el libro exporta sólo '{nombre_desc}'."
        )
    if nombre_fwd is None:
        advertencias.append("No se encontró una curva forward en el conjunto de curvas.")
    if nombre_desc is None:
        advertencias.append("No se encontró una curva de descuento en el conjunto de curvas.")

    return nodos.get(nombre_fwd, []), nodos.get(nombre_desc, []), advertencias


# ──────────────────────────────────────────────────────────────────────
# Traducción del modelo de Django
# ──────────────────────────────────────────────────────────────────────

def build_workbook_data(valorizacion) -> WorkbookData:
    """Convierte una `ValorizacionGuardada` en la estructura que arma el libro."""
    lineas = list(
        valorizacion.lineas.select_related("contrato").all().order_by("maturity_date", "folio")
    )
    config = valorizacion.config_json or {}
    day_count = config.get("day_count", "ACT/360")
    compounding = config.get("compounding", "Compuesta")
    extrap = config.get("extrap_method", "Lineal")
    interp = config.get("interp_method", "Lineal")
    business_days = config.get("business_days", "Exacto")

    fwd_nodes, desc_nodes, advertencias = _elegir_curvas(
        _nodos_por_curva(valorizacion), lineas
    )

    if extrap not in ("Lineal", "Plana"):
        advertencias.append(
            f"La valorización usó extrapolación '{extrap}', que el libro no reproduce; "
            f"se exporta como 'Lineal'. Revise la hoja Reconciliación."
        )
        extrap = "Lineal"
    if interp != "Lineal":
        advertencias.append(
            f"La valorización usó interpolación '{interp}'. El libro interpola siempre en forma "
            f"lineal, de modo que los forwards y tasas de la hoja Valorización pueden diferir de "
            f"los del motor. La hoja Reconciliación lo mostrará."
        )
    if compounding != "Compuesta":
        advertencias.append(
            f"La valorización usó capitalización '{compounding}'. El libro descuenta siempre con "
            f"DF = (1 + tasa/100)^(−t). La hoja Reconciliación marcará las diferencias."
        )
    if day_count not in ("ACT/360", "ACT/365"):
        advertencias.append(
            f"La convención '{day_count}' cuenta días de forma distinta a los días corridos. "
            f"El libro usa días corridos / base anual, por lo que la fracción de año puede diferir."
        )
    if business_days != "Exacto":
        advertencias.append(
            f"Los vencimientos se ajustaron con la convención '{business_days}'. El libro exporta "
            f"las fechas ya ajustadas, de modo que los plazos coinciden, pero al editar una fecha "
            f"de vencimiento el libro no vuelve a ajustarla a día hábil."
        )
    if float(valorizacion.total_cva or 0) or float(valorizacion.total_dva or 0):
        advertencias.append(
            "La valorización incluye CVA/DVA. El libro no los calcula: el MtM de la hoja "
            "Valorización es el MtM sin ajuste por crédito."
        )

    contratos: list[ContractRow] = []
    referencia: list[dict] = []
    for ln in lineas:
        contrato = getattr(ln, "contrato", None)
        contratos.append(
            ContractRow(
                folio=ln.folio or "",
                counterparty=ln.counterparty or "",
                cartera=ln.cartera_nombre or "",
                side=ln.side or "Venta",
                modality=getattr(contrato, "modality", "") or "Compensacion",
                base_ccy=ln.currency or "USD",
                notional=float(ln.notional),
                fwd_price=float(ln.fwd_contract),
                spot_inicio=float(ln.spot_inicio or 0),
                start_date=getattr(contrato, "start_date", None),
                maturity_date=ln.maturity_date,
            )
        )
        referencia.append(
            {
                "folio": ln.folio or "",
                "counterparty": ln.counterparty or "",
                "days": int(ln.days_to_mat or 0),
                "year_fraction": float(ln.year_fraction or 0),
                "fwd_mkt": float(ln.fwd_mkt or 0),
                "disc_rate": float(ln.disc_rate or 0),
                "disc_factor": float(ln.disc_factor or 0),
                "mtm": float(ln.mtm or 0),
                "spot_component": float(ln.spot_component or 0),
                "fwd_points": float(ln.fwd_points or 0),
                "delta": float(ln.delta or 0),
                "dv01": float(ln.dv01 or 0),
            }
        )

    if referencia:
        advertencias.append(
            "Las columnas 'motor' de la hoja Reconciliación son las de la valorización guardada, "
            "redondeadas a dos decimales al persistirse; una diferencia de hasta 0,005 CLP frente "
            "al Excel es sólo ese redondeo."
        )

    etiqueta = valorizacion.label or "Cartera"
    conjunto = getattr(valorizacion, "curve_set", None)

    return WorkbookData(
        valuation_date=valorizacion.valuation_date or date.today(),
        spot=float(valorizacion.spot or 0),
        fwd_nodes=fwd_nodes,
        desc_nodes=desc_nodes,
        contracts=contratos,
        base_anual=_YEAR_BASIS.get(day_count, 360),
        extrap=extrap,
        day_count=day_count,
        compounding=compounding,
        label=etiqueta,
        titulo=f"Valorización de Forwards FX — {etiqueta}",
        fuente=(
            f"{conjunto.label} · {conjunto.source}" if conjunto is not None
            else "Valorización guardada"
        ),
        shock_max=5.0,
        referencia=referencia,
        advertencias=advertencias,
    )


# ──────────────────────────────────────────────────────────────────────
# API pública
# ──────────────────────────────────────────────────────────────────────

def build_workbook(valorizacion) -> io.BytesIO:
    """
    Devuelve un `.xlsx` en memoria con la valorización indicada.

    El libro trae las hojas Parámetros, Curvas, Contratos, Valorización,
    Sensibilidad, Griegas, Reconciliación y Metodología, más la portada. Todas
    las cifras de la hoja Valorización son fórmulas que dependen de las celdas
    azules: el usuario puede cambiar el spot, un nodo de curva o el nocional de
    una operación y ver el efecto sin volver a la aplicación.
    """
    data = build_workbook_data(valorizacion)
    return build_workbook_bytes(data, HOJAS_EXPORTACION)


def build_workbook_object_for(valorizacion):
    """Variante que devuelve el objeto openpyxl (útil en tests)."""
    return build_workbook_object(build_workbook_data(valorizacion), HOJAS_EXPORTACION)
