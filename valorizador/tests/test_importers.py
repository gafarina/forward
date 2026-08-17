"""
Tests de la importación de curvas y contratos
(`valorizador.services.importers`).

No tocan la base de datos ni el disco: los archivos se arman en memoria con
`io.BytesIO`. La mejora clave sobre el cargador v1 es que ninguna fila
desaparece en silencio: cada rechazo devuelve el número de fila y el motivo.
"""

import io
import unittest
from datetime import date, timedelta

from valorizador.services.importers import (
    import_contracts,
    import_curve_points,
    normalize,
    parse_date,
    parse_number,
    parse_side,
)


def archivo_csv(texto: str, nombre: str = "datos.csv") -> io.BytesIO:
    """Construye un archivo CSV en memoria con el atributo `.name` que exige el lector."""
    buf = io.BytesIO(texto.encode("utf-8"))
    buf.name = nombre
    return buf


class ParseNumberTest(unittest.TestCase):
    """
    Formato chileno y anglosajón conviven en los archivos que manda la mesa.
    La regla: si aparecen ambos separadores, el de más a la derecha es el
    decimal.
    """

    def test_formato_chileno_con_miles_y_decimales(self):
        """"1.234,56" es mil doscientos treinta y cuatro con 56."""
        self.assertAlmostEqual(parse_number("1.234,56"), 1234.56, places=10)

    def test_formato_anglosajon_con_miles_y_decimales(self):
        """"1,234.56" es el mismo número con los separadores invertidos."""
        self.assertAlmostEqual(parse_number("1,234.56"), 1234.56, places=10)

    def test_entero_sin_separadores(self):
        self.assertEqual(parse_number("1234"), 1234.0)

    def test_una_sola_coma_es_decimal(self):
        """"3,48" es una tasa, no tres mil cuatrocientos ochenta."""
        self.assertAlmostEqual(parse_number("3,48"), 3.48, places=10)

    def test_varias_comas_son_separador_de_miles(self):
        """"1,234,567" no puede tener dos decimales: son miles."""
        self.assertEqual(parse_number("1,234,567"), 1234567.0)

    def test_varios_puntos_son_separador_de_miles(self):
        self.assertEqual(parse_number("1.234.567"), 1234567.0)

    def test_parentesis_significan_negativo(self):
        """Notación contable: "(500)" es −500."""
        self.assertEqual(parse_number("(500)"), -500.0)
        self.assertAlmostEqual(parse_number("(1.234,56)"), -1234.56, places=10)

    def test_vacio_y_none_devuelven_none(self):
        """Una celda vacía no es cero: es un dato ausente."""
        self.assertIsNone(parse_number(""))
        self.assertIsNone(parse_number(None))

    def test_texto_no_numerico_devuelve_none(self):
        self.assertIsNone(parse_number("no aplica"))
        self.assertIsNone(parse_number("-"))

    def test_limpia_simbolos_de_moneda_y_porcentaje(self):
        self.assertAlmostEqual(parse_number("$ 892,89"), 892.89, places=10)
        self.assertAlmostEqual(parse_number("3,48 %"), 3.48, places=10)

    def test_acepta_numeros_nativos(self):
        """openpyxl entrega floats e ints directos."""
        self.assertEqual(parse_number(1234), 1234.0)
        self.assertAlmostEqual(parse_number(3.48), 3.48, places=10)
        self.assertEqual(parse_number(-500), -500.0)

    def test_los_booleanos_no_son_numeros(self):
        """True no debe convertirse en 1: sería un dato inventado."""
        self.assertIsNone(parse_number(True))
        self.assertIsNone(parse_number(False))

    def test_negativo_con_signo(self):
        self.assertEqual(parse_number("-500"), -500.0)


class ParseDateTest(unittest.TestCase):
    """Fechas en los cuatro formatos que aparecen en la práctica."""

    def test_formato_iso(self):
        self.assertEqual(parse_date("2026-07-13"), date(2026, 7, 13))
        self.assertEqual(parse_date("2026-07-13 00:00:00"), date(2026, 7, 13))

    def test_formato_dia_mes_anio_con_barras(self):
        """El formato local: dd/mm/aaaa, no mm/dd/aaaa."""
        self.assertEqual(parse_date("13/07/2026"), date(2026, 7, 13))
        self.assertEqual(parse_date("7/7/2026"), date(2026, 7, 7))

    def test_formato_dia_mes_anio_con_guiones(self):
        self.assertEqual(parse_date("13-07-2026"), date(2026, 7, 13))

    def test_anio_de_dos_digitos(self):
        self.assertEqual(parse_date("13/07/26"), date(2026, 7, 13))

    def test_serial_de_excel(self):
        """
        Excel cuenta desde el 30-12-1899 (trata 1900 como bisiesto), así que
        el serial 45000 corresponde al 15-03-2023 y el 46216 al 13-07-2026.
        """
        self.assertEqual(parse_date(45000), date(1899, 12, 30) + timedelta(days=45000))
        self.assertEqual(parse_date(45000), date(2023, 3, 15))
        self.assertEqual(parse_date(46216), date(2026, 7, 13))

    def test_objetos_date_y_datetime(self):
        from datetime import datetime

        self.assertEqual(parse_date(date(2026, 7, 13)), date(2026, 7, 13))
        self.assertEqual(parse_date(datetime(2026, 7, 13, 15, 30)), date(2026, 7, 13))

    def test_basura_devuelve_none(self):
        """Nada de adivinar: si no se entiende, es None y la fila se rechaza."""
        for basura in ("", None, "s/f", "vence pronto", "32/13/2026", "2026-13-45"):
            with self.subTest(valor=basura):
                self.assertIsNone(parse_date(basura))


class ParseSideYNormalizeTest(unittest.TestCase):
    """Reconocimiento del lado de la operación y normalización de encabezados."""

    def test_reconoce_compra(self):
        for v in ("Compra", "COMPRA", "compra", "Buy", "C", "long"):
            with self.subTest(valor=v):
                self.assertEqual(parse_side(v), "Compra")

    def test_reconoce_venta(self):
        for v in ("Venta", "VENTA", "Sell", "V", "short"):
            with self.subTest(valor=v):
                self.assertEqual(parse_side(v), "Venta")

    def test_lo_que_no_reconoce_es_none(self):
        for v in (None, "", "swap", "x"):
            with self.subTest(valor=v):
                self.assertIsNone(parse_side(v))

    def test_normalize_saca_tildes_y_espacios(self):
        self.assertEqual(normalize("  Días   Corridos "), "dias corridos")
        self.assertEqual(normalize("OPERACIÓN"), "operacion")
        self.assertEqual(normalize(None), "")


class ImportCurvePointsTest(unittest.TestCase):
    """Importación de nodos de curva."""

    def test_csv_bien_formado_con_encabezados_en_espanol(self):
        """Encabezados "Días" y "Valor" se reconocen sin ayuda."""
        csv = "Días;Valor\n1;892,21\n8;892,19\n62;892,03\n"
        puntos, errores = import_curve_points(archivo_csv(csv), "forward")
        self.assertEqual(
            puntos,
            [
                {"tenor_days": 1, "value": 892.21},
                {"tenor_days": 8, "value": 892.19},
                {"tenor_days": 62, "value": 892.03},
            ],
        )
        self.assertEqual(errores, [])

    def test_encabezados_en_ingles_de_curva_de_descuento(self):
        csv = "tenor_days,rate_pct\n92,3.48231\n183,3.61177\n"
        puntos, errores = import_curve_points(archivo_csv(csv), "descuento")
        self.assertEqual(len(puntos), 2)
        self.assertAlmostEqual(puntos[0]["value"], 3.48231, places=8)
        self.assertEqual(errores, [])

    def test_encabezados_irreconocibles_caen_al_modo_posicional_y_avisan(self):
        """
        Si no se reconoce ninguna columna se usa la primera como plazo y la
        segunda como valor, pero el usuario tiene que enterarse.
        """
        csv = "aaa;bbb\n30;892,10\n60;892,05\n"
        puntos, errores = import_curve_points(archivo_csv(csv), "forward")
        self.assertEqual(len(puntos), 2)
        self.assertEqual(puntos[0], {"tenor_days": 30, "value": 892.10})
        self.assertTrue(
            any("no se reconocieron los encabezados" in e for e in errores),
            msg="El modo posicional debe avisarse siempre.",
        )

    def test_los_nodos_quedan_ordenados_por_plazo(self):
        csv = "Días;Valor\n62;892,03\n1;892,21\n8;892,19\n"
        puntos, _ = import_curve_points(archivo_csv(csv), "forward")
        self.assertEqual([p["tenor_days"] for p in puntos], [1, 8, 62])

    def test_plazos_duplicados_se_colapsan_y_se_avisa(self):
        """Gana el último valor leído y se informa cuántos se colapsaron."""
        csv = "Días;Valor\n30;892,10\n30;892,15\n60;892,05\n"
        puntos, errores = import_curve_points(archivo_csv(csv), "forward")
        self.assertEqual(len(puntos), 2)
        self.assertEqual(puntos[0], {"tenor_days": 30, "value": 892.15})
        self.assertTrue(any("plazos duplicados" in e for e in errores))

    def test_detecta_tasas_en_fraccion_en_vez_de_porcentaje(self):
        """0,0348 en vez de 3,48: es el error de carga más caro y más callado."""
        csv = "Días;Tasa\n92;0,0348231\n183;0,0361177\n"
        puntos, errores = import_curve_points(archivo_csv(csv), "descuento")
        self.assertEqual(len(puntos), 2)
        self.assertTrue(
            any("fraccion" in e.lower() or "fracción" in e.lower() for e in errores),
            msg="Debe avisar cuando las tasas parecen venir en fracción.",
        )

    def test_no_avisa_de_fraccion_cuando_las_tasas_son_porcentajes(self):
        csv = "Días;Tasa\n92;3,48231\n183;3,61177\n"
        _, errores = import_curve_points(archivo_csv(csv), "descuento")
        self.assertFalse(any("fracción" in e.lower() for e in errores))

    def test_plazo_negativo_se_rechaza_con_el_numero_de_fila(self):
        csv = "Días;Valor\n-5;892,10\n60;892,05\n"
        puntos, errores = import_curve_points(archivo_csv(csv), "forward")
        self.assertEqual(len(puntos), 1)
        self.assertTrue(any(e.startswith("Fila 2") and "negativo" in e for e in errores))

    def test_precio_forward_no_positivo_se_rechaza(self):
        csv = "Días;Valor\n30;0\n60;892,05\n"
        puntos, errores = import_curve_points(archivo_csv(csv), "forward")
        self.assertEqual(len(puntos), 1)
        self.assertTrue(any("no positivo" in e for e in errores))

    def test_archivo_sin_filas_de_datos(self):
        puntos, errores = import_curve_points(archivo_csv("Días;Valor\n"), "forward")
        self.assertEqual(puntos, [])
        self.assertEqual(errores, ["El archivo no tiene filas de datos."])

    def test_valores_negativos_son_validos_en_una_curva_de_descuento(self):
        """Una tasa cero o negativa es un dato legítimo, no un error."""
        csv = "Días;Tasa\n92;-0,25\n183;1,10\n"
        puntos, _ = import_curve_points(archivo_csv(csv), "descuento")
        self.assertEqual(len(puntos), 2)
        self.assertAlmostEqual(puntos[0]["value"], -0.25, places=8)


class ImportContractsTest(unittest.TestCase):
    """
    Importación de contratos. El original descartaba las filas incompletas sin
    decir nada: un archivo con la columna de vencimiento mal escrita importaba
    cero contratos y no explicaba por qué.
    """

    ENCABEZADO = (
        "Contraparte;Folio;Operacion;Monto;Precio Fwd;TC inicio;Inicio;Vencimiento\n"
    )
    FILA_OK = "Bice;118039;Venta;2000000;893,35;894,25;2026-05-05;2026-07-13\n"

    def test_archivo_bien_formado(self):
        contratos, errores = import_contracts(archivo_csv(self.ENCABEZADO + self.FILA_OK))
        self.assertEqual(len(contratos), 1)
        self.assertEqual(errores, [])
        c = contratos[0]
        self.assertEqual(c["counterparty"], "Bice")
        self.assertEqual(c["folio"], "118039")
        self.assertEqual(c["side"], "Venta")
        self.assertEqual(c["notional"], 2_000_000.0)
        self.assertAlmostEqual(c["fwd_price"], 893.35, places=8)
        self.assertAlmostEqual(c["spot_inicio"], 894.25, places=8)
        self.assertEqual(c["maturity_date"], "2026-07-13")
        self.assertEqual(c["start_date"], "2026-05-05")
        self.assertEqual(c["base_ccy"], "USD")
        self.assertEqual(c["status"], "Vigente")

    def test_falta_el_vencimiento_produce_un_error_con_fila_y_motivo(self):
        """
        Mejora clave sobre el original. El mensaje tiene que decir *qué* fila y
        *por qué*, para que el usuario pueda corregir el archivo.
        """
        mala = "Bice;999;Venta;1000000;890,00;890,00;2026-05-05;\n"
        contratos, errores = import_contracts(
            archivo_csv(self.ENCABEZADO + mala + self.FILA_OK)
        )
        self.assertEqual(len(errores), 1)
        mensaje = errores[0]
        self.assertIn("Fila 2", mensaje)
        self.assertIn("vencimiento", mensaje.lower())

        self.assertEqual(len(contratos), 1, msg="Ninguna fila válida puede perderse.")
        self.assertEqual(contratos[0]["folio"], "118039")

    def test_el_numero_de_fila_apunta_a_la_fila_del_archivo(self):
        """La fila 1 es el encabezado, así que la primera de datos es la 2."""
        malas = (
            "A;1;Venta;1000000;890,00;890,00;;\n"       # fila 2: sin vencimiento
            + self.FILA_OK                              # fila 3: válida
            + "C;3;Venta;;890,00;890,00;;2026-08-01\n"  # fila 4: sin monto
        )
        contratos, errores = import_contracts(archivo_csv(self.ENCABEZADO + malas))
        self.assertEqual(len(contratos), 1)
        self.assertEqual(len(errores), 2)
        self.assertTrue(errores[0].startswith("Fila 2"))
        self.assertTrue(errores[1].startswith("Fila 4"))
        self.assertIn("monto", errores[1].lower())

    def test_una_fila_acumula_todos_sus_motivos_de_rechazo(self):
        """Un solo mensaje con todo lo que está mal, no uno por campo."""
        mala = "Sin datos;;;;;;\n"
        _, errores = import_contracts(archivo_csv(self.ENCABEZADO + mala))
        self.assertEqual(len(errores), 1)
        motivo = errores[0].lower()
        for esperado in ("monto", "precio forward", "vencimiento", "compra o venta"):
            with self.subTest(motivo=esperado):
                self.assertIn(esperado, motivo)

    def test_monto_no_positivo_se_rechaza_indicando_el_valor(self):
        mala = "Bice;999;Venta;-1000;890,00;890,00;;2026-07-13\n"
        contratos, errores = import_contracts(archivo_csv(self.ENCABEZADO + mala))
        self.assertEqual(contratos, [])
        self.assertIn("monto no positivo", errores[0].lower())

    def test_precio_no_positivo_se_rechaza(self):
        mala = "Bice;999;Venta;1000000;0;890,00;;2026-07-13\n"
        contratos, errores = import_contracts(archivo_csv(self.ENCABEZADO + mala))
        self.assertEqual(contratos, [])
        self.assertIn("precio forward no positivo", errores[0].lower())

    def test_lado_no_reconocido_se_rechaza(self):
        mala = "Bice;999;permuta;1000000;890,00;890,00;;2026-07-13\n"
        contratos, errores = import_contracts(archivo_csv(self.ENCABEZADO + mala))
        self.assertEqual(contratos, [])
        self.assertIn("compra o venta", errores[0].lower())

    def test_vencimiento_anterior_al_inicio_se_rechaza(self):
        mala = "Bice;999;Venta;1000000;890,00;890,00;2026-08-01;2026-07-13\n"
        contratos, errores = import_contracts(archivo_csv(self.ENCABEZADO + mala))
        self.assertEqual(contratos, [])
        self.assertIn("anterior al inicio", errores[0])

    def test_sin_tipo_de_cambio_al_inicio_se_importa_pero_se_avisa(self):
        """
        La fila es utilizable: sólo se pierde la descomposición spot/puntos.
        Se importa igual y se deja el aviso.
        """
        fila = "Bice;999;Venta;1000000;890,00;;2026-05-05;2026-07-13\n"
        contratos, errores = import_contracts(archivo_csv(self.ENCABEZADO + fila))
        self.assertEqual(len(contratos), 1)
        self.assertEqual(contratos[0]["spot_inicio"], 0.0)
        self.assertTrue(any("tipo de cambio al inicio" in e for e in errores))

    def test_ninguna_fila_valida_se_pierde_en_un_archivo_mixto(self):
        """Cinco filas, tres válidas: las tres tienen que llegar."""
        filas = (
            "A;1;Venta;1000000;890,00;889,00;;2026-07-13\n"
            "B;2;;1000000;890,00;889,00;;2026-07-13\n"       # sin lado
            "C;3;Compra;2000000;891,00;889,00;;2026-08-13\n"
            "D;4;Venta;1000000;890,00;889,00;;no se sabe\n"  # sin vencimiento
            "E;5;Venta;3000000;892,00;889,00;;2026-09-13\n"
        )
        contratos, errores = import_contracts(archivo_csv(self.ENCABEZADO + filas))
        self.assertEqual([c["folio"] for c in contratos], ["1", "3", "5"])
        self.assertEqual(len([e for e in errores if "descartada" in e]), 2)

    def test_reconoce_encabezados_alternativos(self):
        """Los archivos de la mesa usan nombres distintos para lo mismo."""
        csv = (
            "Banco;Referencia;C/V;Nominal;Strike;Spot inicial;Fecha Vcto\n"
            "Santander;X-1;compra;500000;885,10;884,00;13/07/2026\n"
        )
        contratos, errores = import_contracts(archivo_csv(csv))
        self.assertEqual(len(contratos), 1, msg=f"errores: {errores}")
        self.assertEqual(contratos[0]["counterparty"], "Santander")
        self.assertEqual(contratos[0]["folio"], "X-1")
        self.assertEqual(contratos[0]["side"], "Compra")
        self.assertEqual(contratos[0]["maturity_date"], "2026-07-13")

    def test_archivo_sin_filas_de_datos(self):
        contratos, errores = import_contracts(archivo_csv(self.ENCABEZADO))
        self.assertEqual(contratos, [])
        self.assertEqual(errores, ["El archivo no tiene filas de datos."])

    def test_separador_por_comas_tambien_funciona(self):
        csv = (
            "Contraparte,Folio,Operacion,Monto,Precio Fwd,TC inicio,Vencimiento\n"
            "Bice,777,Venta,1000000,890.00,889.00,2026-07-13\n"
        )
        contratos, errores = import_contracts(archivo_csv(csv))
        self.assertEqual(len(contratos), 1, msg=f"errores: {errores}")
        self.assertAlmostEqual(contratos[0]["fwd_price"], 890.0, places=8)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
