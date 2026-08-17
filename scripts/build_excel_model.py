#!/usr/bin/env python
"""
Genera el libro `Valorizador_Forwards.xlsx`: un valorizador de forwards FX
USD/CLP en Excel **con fórmulas vivas**, no con valores pegados.

Uso
---
    python scripts/build_excel_model.py --salida /ruta/Valorizador_Forwards.xlsx
    python scripts/build_excel_model.py --desde-demo --salida ./Valorizador_Forwards.xlsx

    # sólo algunas hojas
    python scripts/build_excel_model.py --hojas Parámetros,Curvas,Contratos,Valorización

    # cargar curvas y contratos desde CSV en vez de la demo
    python scripts/build_excel_model.py --curva-fwd fwd.csv --curva-desc desc.csv \
        --contratos ops.csv --fecha 2026-05-31 --spot 892.89

Sin `--desde-demo` y sin archivos de entrada el libro sale en blanco: 60 nodos
por curva y 100 filas de contratos, todas con sus fórmulas ya escritas, listo
para que el usuario cargue sus propios datos.

La lógica de construcción vive en `core.excel_model`, que este script se limita
a manejar desde la línea de comandos y que `valorizador/services/excel_export.py`
reutiliza para exportar una valorización guardada.
"""

from __future__ import annotations

import argparse
import csv
import sys
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.excel_model import (  # noqa: E402  (necesita el sys.path de arriba)
    ALL_SHEETS,
    ContractRow,
    VERSION,
    WorkbookData,
    build_workbook_bytes,
    build_workbook_object,
    compute_reference,
    demo_data,
    save_workbook,
)

__all__ = [
    "WorkbookData",
    "ContractRow",
    "build_workbook_object",
    "build_workbook_bytes",
    "save_workbook",
    "compute_reference",
    "demo_data",
    "main",
]


# ──────────────────────────────────────────────────────────────────────
# Lectura de CSV
# ──────────────────────────────────────────────────────────────────────

def _parse_fecha(texto: str) -> date:
    texto = (texto or "").strip()
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(texto, fmt).date()
        except ValueError:
            continue
    raise argparse.ArgumentTypeError(
        f"Fecha '{texto}' no reconocida. Use AAAA-MM-DD o DD-MM-AAAA."
    )


def _num(texto) -> float:
    """Acepta 1.234,56 y 1234.56."""
    s = str(texto).strip().replace(" ", "")
    if not s:
        return 0.0
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".")
    return float(s)


def _leer_curva(ruta: Path) -> list[tuple[float, float]]:
    """CSV de dos columnas: días, valor. Ignora encabezado si no es numérico."""
    nodos: list[tuple[float, float]] = []
    with open(ruta, newline="", encoding="utf-8-sig") as fh:
        for fila in csv.reader(fh, delimiter=_sniff(ruta)):
            if len(fila) < 2:
                continue
            try:
                nodos.append((_num(fila[0]), _num(fila[1])))
            except ValueError:
                continue          # encabezado
    return sorted(nodos)


def _sniff(ruta: Path) -> str:
    with open(ruta, encoding="utf-8-sig") as fh:
        primera = fh.readline()
    return ";" if primera.count(";") > primera.count(",") else ","


def _leer_contratos(ruta: Path) -> list[ContractRow]:
    """
    CSV con encabezado. Columnas reconocidas (mayúsculas/acentos indiferentes):
    folio, contraparte, cartera, operacion, modalidad, moneda, nocional,
    precio, spot_inicio, fecha_inicio, vencimiento.
    """
    alias = {
        "folio": "folio",
        "contraparte": "counterparty",
        "counterparty": "counterparty",
        "cartera": "cartera",
        "operacion": "side",
        "operación": "side",
        "side": "side",
        "modalidad": "modality",
        "moneda": "base_ccy",
        "nocional": "notional",
        "notional": "notional",
        "precio": "fwd_price",
        "precio_fwd": "fwd_price",
        "precio_pactado": "fwd_price",
        "fwd_price": "fwd_price",
        "spot_inicio": "spot_inicio",
        "spot_inicial": "spot_inicio",
        "fecha_inicio": "start_date",
        "inicio": "start_date",
        "vencimiento": "maturity_date",
        "fecha_vencimiento": "maturity_date",
        "maturity": "maturity_date",
    }
    filas: list[ContractRow] = []
    with open(ruta, newline="", encoding="utf-8-sig") as fh:
        lector = csv.DictReader(fh, delimiter=_sniff(ruta))
        for cruda in lector:
            datos: dict = {}
            for k, v in cruda.items():
                if k is None:
                    continue
                campo = alias.get(k.strip().lower().replace(" ", "_"))
                if not campo:
                    continue
                if campo in ("notional", "fwd_price", "spot_inicio"):
                    datos[campo] = _num(v)
                elif campo in ("start_date", "maturity_date"):
                    datos[campo] = _parse_fecha(v) if str(v).strip() else None
                else:
                    datos[campo] = (v or "").strip()
            if datos.get("notional"):
                filas.append(ContractRow(**datos))
    return filas


# ──────────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────────

def construir_argumentos() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="build_excel_model.py",
        description="Genera el valorizador de forwards FX en Excel con fórmulas vivas.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--salida", default="Valorizador_Forwards.xlsx",
                   help="Ruta del .xlsx a generar (por defecto ./Valorizador_Forwards.xlsx).")
    p.add_argument("--desde-demo", action="store_true",
                   help="Usa los datos del caso Cordada 31-05-2026 de cargar_demo.py.")
    p.add_argument("--curva-fwd", type=Path, help="CSV de la curva de outrights (días,valor).")
    p.add_argument("--curva-desc", type=Path, help="CSV de la curva de descuento (días,tasa %%).")
    p.add_argument("--contratos", type=Path, help="CSV de contratos con encabezado.")
    p.add_argument("--fecha", type=_parse_fecha, help="Fecha de valorización (AAAA-MM-DD).")
    p.add_argument("--spot", type=float, help="Spot de valorización CLP/USD.")
    p.add_argument("--base-anual", type=int, default=360, choices=(360, 365),
                   help="Base de la fracción de año (360 por defecto).")
    p.add_argument("--extrapolacion", default="Lineal", choices=("Lineal", "Plana"),
                   help="Método de extrapolación fuera del rango de nodos.")
    p.add_argument("--etiqueta", default="", help="Etiqueta de la cartera.")
    p.add_argument("--shock-max", type=float, default=5.0,
                   help="Amplitud máxima de la matriz de sensibilidad, en %%.")
    p.add_argument("--hojas", default="",
                   help="Lista separada por comas de las hojas a incluir. "
                        f"Disponibles: {', '.join(ALL_SHEETS)}.")
    p.add_argument("--silencioso", action="store_true", help="No imprime el resumen.")
    return p


def main(argv: list[str] | None = None) -> int:
    args = construir_argumentos().parse_args(argv)

    if args.desde_demo:
        data = demo_data()
    else:
        data = WorkbookData(
            valuation_date=args.fecha or date.today(),
            spot=args.spot if args.spot is not None else 0.0,
            label=args.etiqueta or "Cartera",
        )

    if args.curva_fwd:
        data.fwd_nodes = _leer_curva(args.curva_fwd)
    if args.curva_desc:
        data.desc_nodes = _leer_curva(args.curva_desc)
    if args.contratos:
        data.contracts = _leer_contratos(args.contratos)
    if args.fecha:
        data.valuation_date = args.fecha
    if args.spot is not None:
        data.spot = args.spot
    if args.etiqueta:
        data.label = args.etiqueta
    data.base_anual = args.base_anual
    data.day_count = "ACT/360" if args.base_anual == 360 else "ACT/365"
    data.extrap = args.extrapolacion
    data.shock_max = args.shock_max
    data.referencia = None       # se recalcula con los datos definitivos

    hojas = tuple(h.strip() for h in args.hojas.split(",") if h.strip()) or None
    if hojas:
        desconocidas = [h for h in hojas if h not in ALL_SHEETS]
        if desconocidas:
            raise SystemExit(
                f"Hoja(s) desconocida(s): {', '.join(desconocidas)}. "
                f"Disponibles: {', '.join(ALL_SHEETS)}."
            )

    salida = Path(args.salida).expanduser().resolve()
    salida.parent.mkdir(parents=True, exist_ok=True)
    save_workbook(data, str(salida), hojas)

    if not args.silencioso:
        ref = data.referencia or []
        print(f"Libro generado: {salida}")
        print(f"  versión del modelo   : {VERSION}")
        print(f"  fecha de valorización: {data.valuation_date}")
        print(f"  spot                 : {data.spot}")
        print(f"  nodos forward        : {len(data.fwd_nodes)}")
        print(f"  nodos descuento      : {len(data.desc_nodes)}")
        print(f"  contratos            : {len(data.contracts)} "
              f"(filas preparadas: {data.n_rows})")
        print(f"  extrapolación        : {data.extrap} | base anual: {data.base_anual}")
        if ref:
            print("  referencia del motor Python (para la hoja Reconciliación):")
            for item in ref:
                if not item:
                    continue
                print(f"    {item['folio']:>8}  d={item['days']:>4}  "
                      f"F={item['fwd_mkt']:.6f}  tasa={item['disc_rate']:.6f}  "
                      f"MtM={item['mtm']:,.2f}  spot={item['spot_component']:,.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
