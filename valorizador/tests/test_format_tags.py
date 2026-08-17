"""
Tests de los filtros de formato (`valorizador.templatetags.format_tags`).

El formato local invierte los separadores respecto del de Python: los miles
llevan punto y los decimales coma. Un filtro que se equivoque acá muestra un
MtM de 5 millones como 5,10 y nadie lo nota hasta la conciliación.
"""

import unittest

from valorizador.templatetags.format_tags import (
    abs_val,
    color_mtm,
    formato_clp,
    formato_factor,
    formato_numero,
    formato_precio,
    formato_tasa,
    get_item,
)


class FormatoCLPTest(unittest.TestCase):
    def test_monto_con_separador_de_miles_chileno(self):
        self.assertEqual(formato_clp(-5096628.95), "$-5.096.629")
        self.assertEqual(formato_clp(2592812.56), "$2.592.813")
        self.assertEqual(formato_clp(0), "$0")

    def test_acepta_texto_numerico(self):
        self.assertEqual(formato_clp("1000000"), "$1.000.000")

    def test_lo_que_no_es_numero_pasa_sin_tocar(self):
        """Nunca romper el render por un dato ausente."""
        self.assertEqual(formato_clp(None), None)
        self.assertEqual(formato_clp("-"), "-")


class FormatoNumeroTest(unittest.TestCase):
    def test_dos_decimales_por_defecto(self):
        self.assertEqual(formato_numero(1234.5), "1.234,50")

    def test_decimales_configurables(self):
        self.assertEqual(formato_numero(1234.56789, 4), "1.234,5679")
        self.assertEqual(formato_numero(1234.6, 0), "1.235")

    def test_decimales_invalidos_caen_a_dos(self):
        self.assertEqual(formato_numero(1234.5, "muchos"), "1.234,50")

    def test_valor_no_numerico(self):
        self.assertEqual(formato_numero(None), None)


class OtrosFiltrosTest(unittest.TestCase):
    def test_formato_tasa_agrega_el_simbolo(self):
        self.assertEqual(formato_tasa(3.412600769), "3,4126%")
        self.assertEqual(formato_tasa(3.4126, 2), "3,41%")
        self.assertEqual(formato_tasa("x"), "x")

    def test_formato_factor_usa_ocho_decimales(self):
        """El factor de descuento se compara contra la planilla dígito a dígito."""
        self.assertEqual(formato_factor(0.9959998685432817), "0,99599987")
        self.assertEqual(formato_factor(None), None)

    def test_formato_precio_usa_cuatro_decimales(self):
        self.assertEqual(formato_precio(892.0483870967741), "892,0484")
        self.assertEqual(formato_precio("n/d"), "n/d")

    def test_color_mtm_distingue_ganancia_de_perdida(self):
        self.assertEqual(color_mtm(-1), "neg")
        self.assertEqual(color_mtm(0), "pos")
        self.assertEqual(color_mtm(1), "pos")
        self.assertEqual(color_mtm("x"), "")

    def test_abs_val(self):
        self.assertEqual(abs_val(-5.5), 5.5)
        self.assertEqual(abs_val(5.5), 5.5)
        self.assertEqual(abs_val("x"), "x")

    def test_get_item_accede_a_diccionarios(self):
        self.assertEqual(get_item({"a": 1}, "a"), 1)
        self.assertIsNone(get_item({"a": 1}, "b"))
        self.assertIsNone(get_item("no es un dict", "a"))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
