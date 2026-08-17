"""
Tests de curvas de mercado (`core.curves`).

Cubren interpolación, extrapolación, saneamiento de nodos y descuento. Dos
comportamientos que aquí se fijan eran bugs del motor v1:

* La extrapolación era siempre plana, aunque la planilla de referencia
  extrapola linealmente.
* La interpolación log-lineal nunca llegaba a la curva de descuento porque se
  aplicaba sobre las **tasas** y reventaba con tasas cero o negativas. La
  versión correcta interpola sobre los factores de descuento.
"""

import math
import unittest

from core.curves import (
    COMPOUNDING,
    EXTRAP_METHODS,
    INTERP_METHODS,
    Curve,
    DiscountCurve,
    discount_factor,
)


class InterpolacionTest(unittest.TestCase):
    """Interpolación dentro del rango de nodos."""

    def setUp(self):
        # Dos nodos: 30d → 1.0 y 90d → 2.0. Pendiente = 1/60 por día.
        self.curva = Curve("test", [30, 90], [1.0, 2.0], interp="Lineal", extrap="Plana")

    def test_punto_medio_exacto(self):
        """A mitad de camino (60d) la lineal debe dar exactamente 1.5."""
        self.assertAlmostEqual(self.curva.value(60), 1.5, places=12)

    def test_un_cuarto_del_tramo(self):
        """A 45d, un cuarto del tramo: 1.0 + 0.25 = 1.25."""
        self.assertAlmostEqual(self.curva.value(45), 1.25, places=12)

    def test_evaluar_en_un_nodo_devuelve_el_nodo(self):
        """Evaluar justo sobre un nodo no puede introducir error numérico."""
        self.assertEqual(self.curva.value(30), 1.0)
        self.assertEqual(self.curva.value(90), 2.0)

    def test_evaluar_en_un_nodo_interior(self):
        """Con tres nodos, el del medio también debe devolverse tal cual."""
        c = Curve("t3", [30, 60, 90], [1.0, 1.7, 2.0])
        self.assertEqual(c.value(60), 1.7)

    def test_interpolacion_escalonada_mantiene_el_nodo_izquierdo(self):
        """La escalonada devuelve el valor del nodo anterior, no una mezcla."""
        c = Curve("t", [30, 90], [1.0, 2.0], interp="Escalonada")
        self.assertEqual(c.value(60), 1.0)
        self.assertEqual(c.value(89.9), 1.0)
        self.assertEqual(c.value(90), 2.0)

    def test_interpolacion_log_lineal_es_geometrica(self):
        """
        Con valores positivos, la log-lineal en el punto medio es la media
        geométrica: sqrt(1·4) = 2, no la aritmética 2.5.
        """
        c = Curve("t", [30, 90], [1.0, 4.0], interp="Log-Lineal")
        self.assertAlmostEqual(c.value(60), 2.0, places=12)
        self.assertNotAlmostEqual(c.value(60), 2.5, places=6)

    def test_metodo_de_interpolacion_invalido_falla(self):
        """Un método no soportado debe rechazarse al construir la curva."""
        with self.assertRaises(ValueError):
            Curve("t", [1, 2], [1.0, 2.0], interp="Spline")

    def test_lista_de_metodos_publicada(self):
        """El formulario ofrece exactamente los métodos soportados."""
        self.assertEqual(INTERP_METHODS, ("Lineal", "Log-Lineal", "Escalonada"))
        self.assertEqual(EXTRAP_METHODS, ("Plana", "Lineal", "Puntos"))
        self.assertEqual(COMPOUNDING, ("Compuesta", "Simple", "Continua"))


class ExtrapolacionTest(unittest.TestCase):
    """
    Extrapolación fuera del rango. El motor v1 sólo tenía la plana, lo que
    producía diferencias contra la planilla en todo plazo menor al primer nodo.
    """

    def setUp(self):
        self.plana = Curve("p", [30, 90], [1.0, 2.0], extrap="Plana")
        self.lineal = Curve("l", [30, 90], [1.0, 2.0], extrap="Lineal")

    def test_plana_mantiene_el_nodo_extremo(self):
        """Fuera de rango la plana repite el primer o el último valor."""
        self.assertEqual(self.plana.value(10), 1.0)
        self.assertEqual(self.plana.value(400), 2.0)

    def test_lineal_reproduce_la_pendiente_de_los_dos_nodos_extremos(self):
        """
        Pendiente = (2.0-1.0)/(90-30) = 1/60 por día.
        A 120d: 2.0 + (1/60)·30 = 2.5.
        A 0d:   1.0 + (1/60)·(0-30) = 0.5.
        """
        pendiente = (2.0 - 1.0) / (90 - 30)
        self.assertAlmostEqual(self.lineal.value(120), 2.0 + pendiente * 30, places=12)
        self.assertAlmostEqual(self.lineal.value(120), 2.5, places=12)
        self.assertAlmostEqual(self.lineal.value(0), 1.0 + pendiente * (0 - 30), places=12)
        self.assertAlmostEqual(self.lineal.value(0), 0.5, places=12)

    def test_plana_y_lineal_difieren_numericamente(self):
        """La diferencia entre ambas políticas es material, no de redondeo."""
        self.assertNotAlmostEqual(self.plana.value(120), self.lineal.value(120), places=6)
        self.assertAlmostEqual(self.lineal.value(120) - self.plana.value(120), 0.5, places=12)
        self.assertAlmostEqual(self.plana.value(0) - self.lineal.value(0), 0.5, places=12)

    def test_is_outside_marca_el_rango(self):
        """`is_outside` es lo que dispara el aviso de extrapolación en la app."""
        self.assertTrue(self.lineal.is_outside(29.9))
        self.assertTrue(self.lineal.is_outside(90.1))
        self.assertFalse(self.lineal.is_outside(30))
        self.assertFalse(self.lineal.is_outside(90))
        self.assertEqual(self.lineal.min_tenor, 30)
        self.assertEqual(self.lineal.max_tenor, 90)

    def test_metodo_de_extrapolacion_invalido_falla(self):
        with self.assertRaises(ValueError):
            Curve("t", [1, 2], [1.0, 2.0], extrap="Cúbica")


class SaneamientoDeNodosTest(unittest.TestCase):
    """
    Nodos duplicados o desordenados. En el v1 el usuario podía guardar una
    curva no monótona y la interpolación devolvía basura sin avisar.
    """

    def test_los_nodos_quedan_ordenados(self):
        """Aunque se carguen desordenados, la curva se ordena por plazo."""
        c = Curve("t", [90, 30, 60], [3.0, 1.0, 2.0])
        self.assertEqual(c.xs, [30.0, 60.0, 90.0])
        self.assertEqual(c.ys, [1.0, 2.0, 3.0])
        self.assertAlmostEqual(c.value(45), 1.5, places=12)

    def test_los_plazos_duplicados_se_colapsan_al_ultimo_valor(self):
        """Un plazo repetido deja un solo nodo, con el último valor cargado."""
        c = Curve("t", [30, 30, 90], [1.0, 1.5, 2.0])
        self.assertEqual(len(c), 2)
        self.assertEqual(c.xs, [30.0, 90.0])
        self.assertEqual(c.ys, [1.5, 2.0])

    def test_largos_distintos_fallan(self):
        with self.assertRaises(ValueError):
            Curve("t", [1, 2, 3], [1.0, 2.0])

    def test_curva_sin_nodos_falla(self):
        with self.assertRaises(ValueError):
            Curve("t", [], [])

    def test_curva_de_un_solo_nodo_es_constante(self):
        """Con un único nodo la curva devuelve ese valor en cualquier plazo."""
        c = Curve("t", [90], [3.5])
        self.assertEqual(len(c), 1)
        for plazo in (0, 1, 90, 5000):
            with self.subTest(plazo=plazo):
                self.assertEqual(c.value(plazo), 3.5)

    def test_shifted_desplaza_todos_los_nodos(self):
        """`shifted` es la base de los escenarios: aditivo y multiplicativo."""
        c = Curve("t", [30, 90], [1.0, 2.0])
        aditivo = c.shifted(additive=0.5)
        self.assertEqual(aditivo.ys, [1.5, 2.5])
        multiplicativo = c.shifted(multiplicative=0.10)
        self.assertAlmostEqual(multiplicativo.ys[0], 1.1, places=12)
        self.assertAlmostEqual(multiplicativo.ys[1], 2.2, places=12)
        self.assertEqual(c.ys, [1.0, 2.0], msg="`shifted` no debe mutar la curva original.")

    def test_to_points_devuelve_la_representacion_serializable(self):
        c = Curve("t", [90, 30], [2.0, 1.0])
        self.assertEqual(
            c.to_points(),
            [{"tenor_days": 30, "value": 1.0}, {"tenor_days": 90, "value": 2.0}],
        )


class FactorDeDescuentoTest(unittest.TestCase):
    """Las tres capitalizaciones contra valores calculados a mano."""

    def test_compuesta(self):
        """r = 5 %, t = 0.5 → 1.05^(-0.5) = 0.975900072948533."""
        self.assertAlmostEqual(
            discount_factor(5.0, 0.5, "Compuesta"), 1.05 ** -0.5, places=12
        )
        self.assertAlmostEqual(discount_factor(5.0, 0.5, "Compuesta"), 0.9759000729, places=9)

    def test_simple(self):
        """r = 5 %, t = 0.5 → 1/(1 + 0.025) = 0.975609756097561."""
        self.assertAlmostEqual(discount_factor(5.0, 0.5, "Simple"), 1 / 1.025, places=12)
        self.assertAlmostEqual(discount_factor(5.0, 0.5, "Simple"), 0.9756097561, places=9)

    def test_continua(self):
        """r = 5 %, t = 0.5 → exp(-0.025) = 0.975309912028333."""
        self.assertAlmostEqual(
            discount_factor(5.0, 0.5, "Continua"), math.exp(-0.025), places=12
        )
        self.assertAlmostEqual(discount_factor(5.0, 0.5, "Continua"), 0.9753099120, places=9)

    def test_orden_relativo_de_las_tres(self):
        """
        Para r = 5 % y t = 0.5 la misma tasa nominal descuenta distinto:
        Compuesta (0.975900) > Simple (0.975610) > Continua (0.975310).
        La continua es siempre la más agresiva porque ln(1+r) < r.
        """
        simple = discount_factor(5.0, 0.5, "Simple")
        continua = discount_factor(5.0, 0.5, "Continua")
        compuesta = discount_factor(5.0, 0.5, "Compuesta")
        self.assertGreater(compuesta, simple)
        self.assertGreater(simple, continua)

    def test_plazo_cero_da_factor_uno(self):
        for comp in COMPOUNDING:
            with self.subTest(comp=comp):
                self.assertAlmostEqual(discount_factor(5.0, 0.0, comp), 1.0, places=12)

    def test_tasa_cero_da_factor_uno(self):
        for comp in COMPOUNDING:
            with self.subTest(comp=comp):
                self.assertAlmostEqual(discount_factor(0.0, 1.5, comp), 1.0, places=12)

    def test_tasa_negativa_da_factor_mayor_que_uno(self):
        """Una tasa negativa capitaliza al revés: el factor supera 1."""
        for comp in COMPOUNDING:
            with self.subTest(comp=comp):
                self.assertGreater(discount_factor(-1.0, 1.0, comp), 1.0)

    def test_capitalizacion_desconocida_falla(self):
        with self.assertRaises(ValueError):
            discount_factor(5.0, 0.5, "Trimestral")

    def test_factor_simple_indefinido_falla_en_vez_de_dividir_por_cero(self):
        """Con 1 + r·t <= 0 el descuento simple no existe: debe avisar."""
        with self.assertRaises(ValueError):
            discount_factor(-200.0, 1.0, "Simple")


class CurvaDeDescuentoTest(unittest.TestCase):
    """`DiscountCurve`: tasas cero, factores e interpolación log-lineal."""

    def test_lineal_devuelve_la_tasa_interpolada_de_la_curva(self):
        """Con interpolación lineal la tasa cero es la de la curva subyacente."""
        c = Curve("d", [90, 180], [3.0, 4.0], interp="Lineal")
        dc = DiscountCurve(c, compounding="Compuesta", basis=360.0)
        self.assertAlmostEqual(dc.zero_rate(135), 3.5, places=12)
        self.assertAlmostEqual(
            dc.factor(135), discount_factor(3.5, 135 / 360.0, "Compuesta"), places=12
        )

    def test_factor_admite_una_fraccion_de_anio_externa(self):
        """El motor pasa la fracción de la convención elegida, no días/base."""
        c = Curve("d", [90, 180], [3.0, 4.0])
        dc = DiscountCurve(c, compounding="Compuesta", basis=360.0)
        self.assertAlmostEqual(
            dc.factor(135, 0.25), discount_factor(3.5, 0.25, "Compuesta"), places=12
        )

    def test_log_lineal_interpola_sobre_factores_no_sobre_tasas(self):
        """
        Con Log-Lineal, el factor del punto medio debe ser la media geométrica
        de los factores de los nodos: DF(135) = sqrt(DF(90)·DF(180)).
        Y no debe coincidir con aplicar la log-lineal a las tasas.
        """
        c = Curve("d", [90, 180], [3.0, 6.0], interp="Log-Lineal")
        dc = DiscountCurve(c, compounding="Compuesta", basis=360.0)

        df90 = discount_factor(3.0, 90 / 360.0, "Compuesta")
        df180 = discount_factor(6.0, 180 / 360.0, "Compuesta")
        self.assertAlmostEqual(dc.factor(135), math.sqrt(df90 * df180), places=12)

        tasa_log_lineal_ingenua = math.sqrt(3.0 * 6.0)  # media geométrica de tasas
        self.assertNotAlmostEqual(dc.zero_rate(135), tasa_log_lineal_ingenua, places=4)

    def test_log_lineal_tolera_una_tasa_cero(self):
        """
        Regresión del bug del v1: la log-lineal sobre tasas hacía log(0) y por
        eso el motor original simplemente no la aplicaba a la curva de
        descuento. Interpolando sobre factores, una tasa cero es inofensiva.
        """
        c = Curve("d", [90, 180], [0.0, 2.0], interp="Log-Lineal")
        dc = DiscountCurve(c, compounding="Compuesta", basis=360.0)
        df = dc.factor(135)
        self.assertTrue(math.isfinite(df))
        self.assertAlmostEqual(dc.factor(90), 1.0, places=12)  # tasa 0 → factor 1
        df180 = discount_factor(2.0, 0.5, "Compuesta")
        self.assertAlmostEqual(df, math.sqrt(1.0 * df180), places=12)

    def test_log_lineal_tolera_una_tasa_negativa(self):
        """Mismo caso con tasa negativa: el factor es > 1 y el cálculo no falla."""
        c = Curve("d", [90, 180], [-0.75, 1.5], interp="Log-Lineal")
        dc = DiscountCurve(c, compounding="Compuesta", basis=360.0)
        df90 = discount_factor(-0.75, 0.25, "Compuesta")
        df180 = discount_factor(1.5, 0.5, "Compuesta")
        self.assertGreater(df90, 1.0)
        self.assertAlmostEqual(dc.factor(135), math.sqrt(df90 * df180), places=12)
        self.assertTrue(math.isfinite(dc.zero_rate(135)))

    def test_log_lineal_reproduce_los_nodos(self):
        """Sobre un nodo, la tasa recuperada desde el factor vuelve al original."""
        c = Curve("d", [90, 180, 365], [3.0, 3.6, 4.2], interp="Log-Lineal")
        dc = DiscountCurve(c, compounding="Compuesta", basis=360.0)
        for x, y in zip(c.xs, c.ys):
            with self.subTest(plazo=x):
                self.assertAlmostEqual(dc.zero_rate(x), y, places=9)

    def test_log_lineal_con_capitalizacion_continua_y_simple(self):
        """La conversión factor → tasa debe invertir cada capitalización."""
        for comp in ("Continua", "Simple", "Compuesta"):
            with self.subTest(comp=comp):
                c = Curve("d", [90, 180], [3.0, 4.0], interp="Log-Lineal")
                dc = DiscountCurve(c, compounding=comp, basis=360.0)
                self.assertAlmostEqual(dc.zero_rate(180), 4.0, places=9)

    def test_shifted_bp_mueve_la_tasa_exactamente_un_punto_base(self):
        """1 bp = 0.01 en tasa expresada en porcentaje."""
        c = Curve("d", [90, 180], [3.0, 4.0])
        dc = DiscountCurve(c, compounding="Compuesta", basis=360.0)
        up = dc.shifted_bp(1.0)
        self.assertAlmostEqual(up.zero_rate(90) - dc.zero_rate(90), 0.01, places=12)
        self.assertAlmostEqual(up.zero_rate(135) - dc.zero_rate(135), 0.01, places=12)
        self.assertEqual(up.curve.ys, [3.01, 4.01])
        self.assertLess(up.factor(135), dc.factor(135), msg="Subir la tasa baja el factor.")

    def test_shifted_bp_no_muta_la_curva_original(self):
        c = Curve("d", [90, 180], [3.0, 4.0])
        dc = DiscountCurve(c, compounding="Compuesta", basis=360.0)
        dc.shifted_bp(50.0)
        self.assertEqual(dc.curve.ys, [3.0, 4.0])

    def test_delega_el_rango_a_la_curva_subyacente(self):
        c = Curve("d", [90, 1461], [3.0, 4.4])
        dc = DiscountCurve(c)
        self.assertEqual(dc.min_tenor, 90)
        self.assertEqual(dc.max_tenor, 1461)
        self.assertTrue(dc.is_outside(37))
        self.assertFalse(dc.is_outside(365))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()


class ExtrapolacionPuntosTest(unittest.TestCase):
    """
    La política "Puntos" debe tener semántica propia, distinta de "Lineal".

    Protege el hallazgo P-01: en la primera versión de `core/curves.py` la rama
    `"Puntos"` retornaba exactamente la misma expresión que `"Lineal"`, de modo
    que el formulario ofrecía una opción que no hacía nada.

    "Lineal" prolonga la pendiente del último segmento; "Puntos" prolonga la
    pendiente promedio entre el primer y el último nodo, que sobre una curva de
    outrights equivale a mantener constante el ritmo de acumulación de puntos
    forward.
    """

    # Curva FWDUSDCLP del libro Cordada 31-05-2026.
    XS = [1, 2, 8, 15, 22, 31, 62]
    YS = [892.21, 892.205, 892.19, 892.13, 892.105, 892.06, 892.03]

    def _curva(self, extrap):
        return Curve("FWDUSDCLP", list(self.XS), list(self.YS), extrap=extrap)

    def test_las_tres_politicas_difieren_a_la_derecha(self):
        plana = self._curva("Plana").value(365)
        lineal = self._curva("Lineal").value(365)
        puntos = self._curva("Puntos").value(365)

        self.assertEqual(plana, self.YS[-1])
        self.assertNotAlmostEqual(lineal, puntos, places=4)
        self.assertNotAlmostEqual(plana, puntos, places=4)

    def test_las_tres_politicas_difieren_a_la_izquierda(self):
        plana = self._curva("Plana").value(0.5)
        lineal = self._curva("Lineal").value(0.5)
        puntos = self._curva("Puntos").value(0.5)

        self.assertEqual(plana, self.YS[0])
        self.assertNotAlmostEqual(lineal, puntos, places=6)

    def test_puntos_usa_la_pendiente_promedio_de_la_curva(self):
        pendiente = (self.YS[-1] - self.YS[0]) / (self.XS[-1] - self.XS[0])
        esperado = self.YS[-1] + pendiente * (365 - self.XS[-1])
        self.assertAlmostEqual(self._curva("Puntos").value(365), esperado, places=10)

    def test_lineal_usa_la_pendiente_del_ultimo_segmento(self):
        pendiente = (self.YS[-1] - self.YS[-2]) / (self.XS[-1] - self.XS[-2])
        esperado = self.YS[-1] + pendiente * (365 - self.XS[-1])
        self.assertAlmostEqual(self._curva("Lineal").value(365), esperado, places=10)

    def test_dentro_del_rango_las_tres_politicas_coinciden(self):
        """La extrapolación no debe alterar la interpolación entre nodos."""
        for plazo in (1, 12, 37, 43, 62):
            valores = {m: self._curva(m).value(plazo) for m in EXTRAP_METHODS}
            self.assertAlmostEqual(valores["Plana"], valores["Lineal"], places=12)
            self.assertAlmostEqual(valores["Plana"], valores["Puntos"], places=12)
