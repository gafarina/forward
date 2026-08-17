"""
Importación de curvas y contratos desde CSV / Excel.

Mejoras respecto de `services/csv_loader.py` del original:

* Las filas rechazadas ya no desaparecen en silencio. Cada importación
  devuelve `(filas_ok, errores)` y la interfaz muestra por qué se descartó
  cada fila. Antes, un archivo con la columna "vencimiento" mal escrita
  importaba cero contratos sin explicar nada.
* El parser de números distingue separador de miles de separador decimal con
  una regla explícita y documentada, en lugar de heurísticas encadenadas.
* Las fechas aceptan formato ISO, dd/mm/aaaa, dd-mm-aaaa y serial de Excel.
* Se valida el rango de valores: plazos no negativos, montos positivos,
  precios positivos, y para curvas de descuento se detecta si vienen en
  fracción (0.0348) en lugar de porcentaje (3.48).
"""

from __future__ import annotations

import csv
import io
import re
import unicodedata
from datetime import date, datetime, timedelta

__all__ = ["import_curve_points", "import_contracts", "parse_number", "parse_date"]

_EXCEL_EPOCH = date(1899, 12, 30)  # Excel cuenta 1900 como bisiesto


# ──────────────────────────────────────────────────────────────────────
# Normalización
# ──────────────────────────────────────────────────────────────────────

def normalize(s) -> str:
    """Minúsculas, sin tildes, sin espacios extra."""
    if s is None:
        return ''
    txt = str(s).strip().lower()
    txt = unicodedata.normalize('NFKD', txt)
    txt = ''.join(ch for ch in txt if not unicodedata.combining(ch))
    return re.sub(r'\s+', ' ', txt)


def find_col(row: dict, candidates: list[str]):
    """Busca un valor en la fila probando varios nombres de columna."""
    keys = list(row.keys())
    norm_keys = {k: normalize(k) for k in keys}

    for cand in candidates:                       # coincidencia exacta primero
        cn = normalize(cand)
        for k, kn in norm_keys.items():
            if kn == cn:
                return row[k]

    for cand in candidates:                       # luego parcial
        cn = normalize(cand)
        if len(cn) < 3:
            continue
        for k, kn in norm_keys.items():
            if cn in kn or kn in cn:
                return row[k]
    return None


def parse_number(val):
    """
    Convierte texto a float manejando formato chileno y anglosajón.

    Regla: si aparecen ambos separadores, el que está más a la derecha es el
    decimal. Si sólo hay comas y una sola, es decimal; si hay varias, son
    separadores de miles. Lo mismo con los puntos.
    """
    if val is None or val == '':
        return None
    if isinstance(val, bool):
        return None
    if isinstance(val, (int, float)):
        return float(val) if val == val else None  # descarta NaN

    s = str(val).strip().replace('%', '').replace('$', '')
    s = re.sub(r'[\s ]', '', s)
    if not s:
        return None

    neg = s.startswith('(') and s.endswith(')')
    if neg:
        s = s[1:-1]

    dots, commas = s.count('.'), s.count(',')
    if dots and commas:
        if s.rindex(',') > s.rindex('.'):
            s = s.replace('.', '').replace(',', '.')
        else:
            s = s.replace(',', '')
    elif commas:
        s = s.replace(',', '.') if commas == 1 else s.replace(',', '')
    elif dots > 1:
        s = s.replace('.', '')

    try:
        out = float(s)
    except ValueError:
        return None
    return -out if neg else out


def parse_date(val):
    """Acepta date/datetime, ISO, dd/mm/aaaa, dd-mm-aaaa y serial de Excel."""
    if val is None or val == '':
        return None
    if isinstance(val, datetime):
        return val.date()
    if isinstance(val, date):
        return val
    if isinstance(val, (int, float)) and 1 < float(val) < 100_000:
        return _EXCEL_EPOCH + timedelta(days=int(val))

    s = str(val).strip()
    if len(s) >= 10 and s[4:5] == '-':
        try:
            return date.fromisoformat(s[:10])
        except ValueError:
            pass

    m = re.match(r'^(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{2,4})$', s)
    if m:
        d, mo, y = int(m.group(1)), int(m.group(2)), m.group(3)
        y = int('20' + y) if len(y) == 2 else int(y)
        try:
            return date(y, mo, d)
        except ValueError:
            return None
    return None


def parse_side(val):
    if val is None:
        return None
    s = normalize(val)
    if s.startswith(('comp', 'buy', 'purchase', 'long')) or s in ('c', 'b'):
        return 'Compra'
    if s.startswith(('vent', 'sell', 'sale', 'short')) or s in ('v', 's'):
        return 'Venta'
    return None


# ──────────────────────────────────────────────────────────────────────
# Lectura de archivos
# ──────────────────────────────────────────────────────────────────────

def read_file_rows(file_obj) -> list[dict]:
    """Devuelve las filas de un CSV o Excel como lista de diccionarios."""
    name = getattr(file_obj, 'name', '').lower()
    file_obj.seek(0)

    if name.endswith('.csv') or name.endswith('.txt'):
        content = file_obj.read()
        if isinstance(content, bytes):
            for enc in ('utf-8-sig', 'utf-8', 'latin-1'):
                try:
                    text = content.decode(enc)
                    break
                except UnicodeDecodeError:
                    continue
            else:
                text = content.decode('latin-1', errors='replace')
        else:
            text = content

        sample = text[:4096]
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=';,\t|')
            delimiter = dialect.delimiter
        except csv.Error:
            delimiter = ';' if sample.count(';') > sample.count(',') else ','

        reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
        return [r for r in reader if any(v not in (None, '') for v in r.values())]

    import openpyxl

    wb = openpyxl.load_workbook(file_obj, data_only=True, read_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    wb.close()
    if not rows:
        return []
    headers = [str(h) if h is not None else f'col_{i}' for i, h in enumerate(rows[0])]
    out = []
    for row in rows[1:]:
        if all(v is None for v in row):
            continue
        out.append(dict(zip(headers, row)))
    return out


# ──────────────────────────────────────────────────────────────────────
# Curvas
# ──────────────────────────────────────────────────────────────────────

_DAY_COLS = ['tenor_days', 'dias', 'días', 'plazo', 'dias corridos', 'days', 'tenor',
             'dia_clp423', 'dia_fwdusdclp', 'dia']
_FWD_COLS = ['value', 'valor', 'forward', 'fwd', 'precio', 'precio fwd', 'outright',
             'promedio', 'mid', 'c_fwdusdclp']
_DISC_COLS = ['value', 'rate_pct', 'rate', 'tasa', 'spot rate', 'market rate',
              'tasa cero', 'c_clp423']


def import_curve_points(file_obj, curve_type: str = 'forward') -> tuple[list[dict], list[str]]:
    """
    Importa nodos de curva. Devuelve (puntos, errores).

    `puntos` es una lista de {'tenor_days': int, 'value': float} ordenada y sin
    plazos duplicados (gana el último valor leído).
    """
    errors: list[str] = []
    try:
        rows = read_file_rows(file_obj)
    except Exception as exc:
        return [], [f'No se pudo leer el archivo: {exc}']

    if not rows:
        return [], ['El archivo no tiene filas de datos.']

    value_cols = _FWD_COLS if curve_type == 'forward' else _DISC_COLS

    points: list[dict] = []
    used_positional = False
    for i, row in enumerate(rows, start=2):
        days = parse_number(find_col(row, _DAY_COLS))
        val = parse_number(find_col(row, value_cols))

        if days is None or val is None:            # fallback posicional
            vals = list(row.values())
            if len(vals) >= 2:
                days = parse_number(vals[0]) if days is None else days
                val = parse_number(vals[1]) if val is None else val
                used_positional = True

        if days is None or val is None:
            errors.append(f'Fila {i}: no se pudo leer plazo y/o valor.')
            continue
        if days < 0:
            errors.append(f'Fila {i}: plazo negativo ({days}).')
            continue
        if curve_type == 'forward' and val <= 0:
            errors.append(f'Fila {i}: precio forward no positivo ({val}).')
            continue
        points.append({'tenor_days': int(round(days)), 'value': float(val)})

    if used_positional and points:
        errors.append(
            'Aviso: no se reconocieron los encabezados; se usó la primera columna '
            'como plazo y la segunda como valor.'
        )

    if curve_type != 'forward' and points:
        vals = [p['value'] for p in points]
        if vals and max(abs(v) for v in vals) < 0.5:
            errors.append(
                'Aviso: las tasas parecen venir en fracción (0,0348) en vez de '
                'porcentaje (3,48). Revisa las unidades antes de guardar.'
            )

    dedup: dict[int, float] = {}
    for p in points:
        dedup[p['tenor_days']] = p['value']
    ordered = [{'tenor_days': k, 'value': v} for k, v in sorted(dedup.items())]

    if len(ordered) < len(points):
        errors.append(f'Se colapsaron {len(points) - len(ordered)} plazos duplicados.')

    return ordered, errors


# ──────────────────────────────────────────────────────────────────────
# Contratos
# ──────────────────────────────────────────────────────────────────────

def import_contracts(file_obj) -> tuple[list[dict], list[str]]:
    """Importa contratos. Devuelve (contratos, errores) con motivo por fila."""
    errors: list[str] = []
    try:
        rows = read_file_rows(file_obj)
    except Exception as exc:
        return [], [f'No se pudo leer el archivo: {exc}']

    if not rows:
        return [], ['El archivo no tiene filas de datos.']

    contracts: list[dict] = []
    for i, row in enumerate(rows, start=2):
        motivos: list[str] = []

        notional = parse_number(find_col(row, ['notional', 'monto', 'nominal', 'amount', 'nocional']))
        fwd_price = parse_number(find_col(
            row, ['fwd_price', 'precio fwd', 'precio forward', 'forward', 'strike', 'precio']))
        mat_date = parse_date(find_col(
            row, ['maturity_date', 'vencim', 'vcto', 'vencimiento', 'fecha vcto',
                  'fecha vencimiento', 'fecha termino']))
        side = parse_side(find_col(
            row, ['side', 'operacion', 'operación', 'tipo', 'direccion',
                  'compra/venta', 'c/v', 'b/s', 'buy/sell']))

        if notional is None:
            motivos.append('falta el monto')
        elif notional <= 0:
            motivos.append(f'monto no positivo ({notional})')
        if fwd_price is None:
            motivos.append('falta el precio forward')
        elif fwd_price <= 0:
            motivos.append(f'precio forward no positivo ({fwd_price})')
        if mat_date is None:
            motivos.append('falta la fecha de vencimiento o no se pudo interpretar')
        if side is None:
            motivos.append('no se reconoció si es compra o venta')

        if motivos:
            errors.append(f'Fila {i} descartada: ' + '; '.join(motivos) + '.')
            continue

        start_date = parse_date(find_col(
            row, ['start_date', 'fecha inicio', 'inicio', 'fecha suscripcion']))
        if start_date and mat_date and mat_date < start_date:
            errors.append(f'Fila {i} descartada: el vencimiento es anterior al inicio.')
            continue

        spot_inicio = parse_number(find_col(
            row, ['spot_inicio', 'spot inicio', 'tipo de cambio al inicio', 'tc inicio',
                  'spot inicial'])) or 0.0
        if spot_inicio <= 0:
            errors.append(
                f'Fila {i}: sin tipo de cambio al inicio. Se importa igual, pero la '
                f'descomposición en componente spot y puntos forward quedará en cero.'
            )

        contracts.append({
            'counterparty': str(find_col(
                row, ['counterparty', 'contraparte', 'banco', 'contrapartida']) or '').strip(),
            'folio': str(find_col(
                row, ['folio', 'ref', 'referencia', 'nro', 'numero', 'num']) or '').strip(),
            'side': side,
            'modality': str(find_col(row, ['modality', 'modalidad']) or 'Compensacion'),
            'base_ccy': str(find_col(row, ['base_ccy', 'moneda', 'divisa', 'ccy']) or 'USD')[:3].upper(),
            'quote_ccy': str(find_col(row, ['quote_ccy', 'moneda cotizacion']) or 'CLP')[:3].upper(),
            'notional': notional,
            'fwd_price': fwd_price,
            'spot_inicio': spot_inicio,
            'start_date': start_date.isoformat() if start_date else None,
            'maturity_date': mat_date.isoformat(),
            'fwd_curve': str(find_col(row, ['fwd_curve', 'curva forward']) or 'FWDUSDCLP'),
            'disc_curve': str(find_col(row, ['disc_curve', 'curva descuento']) or 'CLP423'),
            'status': 'Vigente',
        })

    return contracts, errors
