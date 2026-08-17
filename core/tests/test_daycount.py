"""
Tests de las convenciones de conteo de días (`core.daycount`).

Cada caso 30/360 lleva el cálculo hecho a mano en el docstring, porque la
regla NASD tiene cuatro ajustes encadenados cuyo orden importa y no es
verificable a ojo.
"""

import unittest
from datetime import date

from core.daycount import (
    DAY_COUNT_CONVENTIONS,
    day_count_days,
    day_count_fraction,
    year_basis,
)


class ActualConventionsTest(unittest.TestCase):
    """ACT/360 y ACT/365 son días corridos sobre base fija."""

    def test_act_360_cuenta_dias_corridos_sobre_base_360(self):
        """Del 31-05-2026 al 07-07-2026 hay 37 días corridos: 37/360."""
        d1, d2 = date(2026, 5, 31), date(2026, 7, 7)
        self.assertEqual((d2 - d1).days, 37)
        self.assertAlmostEqual(
            day_count_fraction(d1, d2, "ACT/360"), 37 / 360.0, places=12,
            msg="ACT/360 debe ser días corridos dividido por 360.",
        )

    def test_act_365_usa_base_365(self):
        """Mismo tramo de 37 días, ahora sobre base 365: 37/365."""
        d1, d2 = date(2026, 5, 31), date(2026, 7, 7)
        self.assertAlmostEqual(
            day_count_fraction(d1, d2, "ACT/365"), 37 / 365.0, places=12,
            msg="ACT/365 debe ser días corridos dividido por 365.",
        )

    def test_un_anio_completo_no_bisiesto(self):
        """01-01-2023 a 01-01-2024: 365 días. ACT/365 = 1 exacto, ACT/360 > 1."""
        d1, d2 = date(2023, 1, 1), date(2024, 1, 1)
        self.assertEqual(day_count_days(d1, d2, "ACT/360"), 365)
        self.assertAlmostEqual(day_count_fraction(d1, d2, "ACT/365"), 1.0, places=12)
        self.assertAlmostEqual(day_count_fraction(d1, d2, "ACT/360"), 365 / 360.0, places=12)

    def test_fraccion_es_cero_en_el_mismo_dia(self):
        """Un plazo nulo no devenga: la fracción de año debe ser exactamente 0."""
        d = date(2026, 5, 31)
        for conv in DAY_COUNT_CONVENTIONS:
            with self.subTest(conv=conv):
                self.assertEqual(
                    day_count_fraction(d, d, conv), 0.0,
                    msg=f"{conv} debe dar fracción cero para d1 == d2.",
                )

    def test_convencion_desconocida_falla_explicitamente(self):
        """Una convención mal escrita debe reventar, no caer a un default silencioso."""
        with self.assertRaises(ValueError):
            day_count_fraction(date(2026, 1, 1), date(2026, 2, 1), "ACT/366")

    def test_year_basis_reporta_la_base_nominal(self):
        """La base nominal alimenta el eje de tasas de los reportes."""
        self.assertEqual(year_basis("ACT/360"), 360.0)
        self.assertEqual(year_basis("ACT/365"), 365.0)
        self.assertEqual(year_basis("ACT/ACT"), 365.25)
        self.assertEqual(year_basis("30/360"), 360.0)


class Treinta360UsTest(unittest.TestCase):
    """
    Casos límite de la regla NASD (30/360 US, Bond Basis).

    Reglas, en orden:
      1. Si D1 y D2 son ambos el último día de febrero, D2 = 30.
      2. Si D1 es el último día de febrero, D1 = 30.
      3. Si D2 = 31 y D1 >= 30, D2 = 30.
      4. Si D1 = 31, D1 = 30.
    Luego: días = 360·(a2-a1) + 30·(m2-m1) + (D2-D1).
    """

    def test_31_enero_a_28_febrero_anio_no_bisiesto(self):
        """
        31-01-2023 → 28-02-2023.
        Regla 4: D1 31 → 30. D2 queda en 28 (la regla 1 exige que *ambos*
        extremos sean fin de febrero). 30·(2-1) + (28-30) = 28 días.
        """
        self.assertEqual(day_count_days(date(2023, 1, 31), date(2023, 2, 28), "30/360"), 28)

    def test_31_enero_a_29_febrero_anio_bisiesto(self):
        """
        31-01-2024 → 29-02-2024.
        Regla 4: D1 = 30. D2 = 29. 30·1 + (29-30) = 29 días.
        """
        self.assertEqual(day_count_days(date(2024, 1, 31), date(2024, 2, 29), "30/360"), 29)

    def test_fin_de_febrero_no_bisiesto_a_31_de_marzo(self):
        """
        28-02-2023 → 31-03-2023.
        Regla 2: D1 es fin de febrero → 30. Regla 3: D2 = 31 y D1 >= 30 → 30.
        30·(3-2) + (30-30) = 30 días. El mes de febrero "se completa" a 30.
        """
        self.assertEqual(day_count_days(date(2023, 2, 28), date(2023, 3, 31), "30/360"), 30)

    def test_fin_de_febrero_bisiesto_a_31_de_marzo(self):
        """
        29-02-2024 → 31-03-2024.
        Mismo resultado que el año no bisiesto: 30 días. La convención elimina
        justamente la diferencia entre 28 y 29 de febrero.
        """
        self.assertEqual(day_count_days(date(2024, 2, 29), date(2024, 3, 31), "30/360"), 30)
        self.assertEqual(
            day_count_days(date(2023, 2, 28), date(2023, 3, 31), "30/360"),
            day_count_days(date(2024, 2, 29), date(2024, 3, 31), "30/360"),
            msg="El fin de febrero bisiesto y el no bisiesto deben tratarse igual.",
        )

    def test_fin_de_febrero_a_fin_de_febrero_es_un_anio_exacto(self):
        """
        28-02-2023 → 29-02-2024: ambos son fin de febrero.
        Regla 1: D2 = 30. Regla 2: D1 = 30. 360·1 + 30·0 + 0 = 360 días = 1 año.
        """
        self.assertEqual(day_count_days(date(2023, 2, 28), date(2024, 2, 29), "30/360"), 360)
        self.assertAlmostEqual(
            day_count_fraction(date(2023, 2, 28), date(2024, 2, 29), "30/360"), 1.0, places=12
        )

    def test_fin_de_febrero_a_28_de_febrero_de_anio_bisiesto_no_activa_la_regla_1(self):
        """
        28-02-2023 → 28-02-2024. El 28-02-2024 **no** es fin de febrero (2024 es
        bisiesto), así que la regla 1 no aplica. Sólo la regla 2: D1 = 30.
        360·1 + 30·0 + (28-30) = 358 días.
        """
        self.assertEqual(day_count_days(date(2023, 2, 28), date(2024, 2, 28), "30/360"), 358)

    def test_30_versus_31_al_final_del_periodo(self):
        """
        30-04-2026 → 31-05-2026: regla 3 (D2 = 31 con D1 >= 30) → D2 = 30.
        30·1 + (30-30) = 30 días, aunque en el calendario hay 31.
        """
        self.assertEqual(day_count_days(date(2026, 4, 30), date(2026, 5, 31), "30/360"), 30)
        self.assertEqual((date(2026, 5, 31) - date(2026, 4, 30)).days, 31)

    def test_31_a_31_de_dos_meses_despues(self):
        """
        31-05-2026 → 31-07-2026: regla 4 lleva D1 a 30, luego la regla 3 lleva
        D2 a 30. 30·2 + 0 = 60 días, contra 61 corridos.
        """
        self.assertEqual(day_count_days(date(2026, 5, 31), date(2026, 7, 31), "30/360"), 60)
        self.assertEqual((date(2026, 7, 31) - date(2026, 5, 31)).days, 61)

    def test_29_a_31_no_activa_la_regla_del_31(self):
        """
        29-04-2026 → 31-05-2026: D1 = 29 < 30, así que D2 se queda en 31.
        30·1 + (31-29) = 32 días.
        """
        self.assertEqual(day_count_days(date(2026, 4, 29), date(2026, 5, 31), "30/360"), 32)


class Treinta360EuropeaTest(unittest.TestCase):
    """30E/360 (Eurobond) contra 30/360 US."""

    def test_fin_de_febrero_a_31_de_marzo_es_donde_difieren(self):
        """
        28-02-2023 → 31-03-2023.
        30/360 US: D1 = 30 (regla de febrero) y D2 = 30 → 30 días.
        30E/360: no hay regla de febrero, D1 = 28 y D2 = 31 → 30 → 32 días.
        La diferencia es de 2 días, equivalente a 2/360 de año.
        """
        us = day_count_days(date(2023, 2, 28), date(2023, 3, 31), "30/360")
        eu = day_count_days(date(2023, 2, 28), date(2023, 3, 31), "30E/360")
        self.assertEqual(us, 30)
        self.assertEqual(eu, 32)
        self.assertEqual(eu - us, 2, msg="30E/360 no aplica la regla de fin de febrero.")
        self.assertAlmostEqual(
            day_count_fraction(date(2023, 2, 28), date(2023, 3, 31), "30E/360")
            - day_count_fraction(date(2023, 2, 28), date(2023, 3, 31), "30/360"),
            2 / 360.0,
            places=12,
        )

    def test_29_de_febrero_bisiesto_tambien_difiere(self):
        """29-02-2024 → 31-03-2024: US = 30 días, 30E/360 = 30·1 + (30-29) = 31."""
        self.assertEqual(day_count_days(date(2024, 2, 29), date(2024, 3, 31), "30/360"), 30)
        self.assertEqual(day_count_days(date(2024, 2, 29), date(2024, 3, 31), "30E/360"), 31)

    def test_coinciden_cuando_no_interviene_febrero(self):
        """Fuera de febrero, 31 → 30 en ambos extremos: las dos coinciden."""
        d1, d2 = date(2026, 5, 31), date(2026, 7, 31)
        self.assertEqual(
            day_count_days(d1, d2, "30/360"), day_count_days(d1, d2, "30E/360")
        )


class ActActIsdaTest(unittest.TestCase):
    """ACT/ACT ISDA es la única convención con denominador variable."""

    def test_reparte_los_dias_entre_365_y_366_al_cruzar_un_bisiesto(self):
        """
        01-12-2023 → 01-03-2024 cruza el cambio de año hacia 2024 (bisiesto).
        Tramo 2023: 31 días sobre base 365.
        Tramo 2024: 60 días sobre base 366.
        Fracción = 31/365 + 60/366 = 0.24886593...
        """
        d1, d2 = date(2023, 12, 1), date(2024, 3, 1)
        esperado = 31 / 365.0 + 60 / 366.0
        self.assertAlmostEqual(day_count_fraction(d1, d2, "ACT/ACT"), esperado, places=12)
        self.assertNotAlmostEqual(
            day_count_fraction(d1, d2, "ACT/ACT"),
            (d2 - d1).days / 365.0,
            places=6,
            msg="Si diera lo mismo que ACT/365, el reparto por año no se estaría aplicando.",
        )

    def test_un_anio_bisiesto_completo_vale_exactamente_uno(self):
        """01-01-2024 → 01-01-2025: 366 días sobre base 366 = 1.0 exacto."""
        self.assertAlmostEqual(
            day_count_fraction(date(2024, 1, 1), date(2025, 1, 1), "ACT/ACT"), 1.0, places=12
        )

    def test_es_antisimetrica(self):
        """Invertir las fechas debe cambiar el signo, no romper el cálculo."""
        d1, d2 = date(2023, 12, 1), date(2024, 3, 1)
        self.assertAlmostEqual(
            day_count_fraction(d2, d1, "ACT/ACT"),
            -day_count_fraction(d1, d2, "ACT/ACT"),
            places=12,
        )


class RegresionBugV1Test(unittest.TestCase):
    """
    Regresión del bug del motor v1.

    En el repositorio original la opción "30/360" **no** calculaba días 30/360:
    sólo fijaba la base del año en 360 y seguía usando días corridos, con el
    comentario "Simplify 30/360 to 360 year base for factor, days already
    calendar". Es decir, 30/360 era ACT/360 renombrada, para *cualquier* par
    de fechas.

    Acá se fija ese contrato: existen pares de fechas donde 30/360 y ACT/360
    difieren. Se deja además documentado el resultado del par 31-ene → 28-feb
    que pide la especificación: bajo la regla NASD ese par concreto coincide
    con ACT/360 (28 días en ambas), porque ninguna de las cuatro reglas mueve
    la fecha final; el par que sí discrimina es el que cruza un mes de 31 días.
    """

    def test_31_enero_a_28_febrero_coincide_por_construccion_de_la_regla_nasd(self):
        """
        31-01-2023 → 28-02-2023: ACT/360 da 28/360 y 30/360 US también da
        28/360 (D1 31 → 30, D2 = 28). Coinciden por la aritmética de la regla,
        no porque la convención esté sin implementar: el test siguiente lo
        demuestra.
        """
        d1, d2 = date(2023, 1, 31), date(2023, 2, 28)
        self.assertEqual(day_count_days(d1, d2, "ACT/360"), 28)
        self.assertEqual(day_count_days(d1, d2, "30/360"), 28)

    def test_30_360_no_es_act_360_con_otra_base(self):
        """
        El bug de la v1 se detecta con cualquier par que cruce un mes de 31
        días. 31-01-2023 → 31-03-2023: 59 días corridos pero 60 días 30/360.
        Si 30/360 estuviera implementada como en la v1, las dos fracciones
        serían idénticas.
        """
        d1, d2 = date(2023, 1, 31), date(2023, 3, 31)
        self.assertEqual(day_count_days(d1, d2, "ACT/360"), 59)
        self.assertEqual(day_count_days(d1, d2, "30/360"), 60)
        self.assertNotAlmostEqual(
            day_count_fraction(d1, d2, "ACT/360"),
            day_count_fraction(d1, d2, "30/360"),
            places=10,
            msg="30/360 debe calcular sus propios días, no reutilizar los corridos.",
        )

    def test_el_mes_de_febrero_es_donde_mas_se_separan(self):
        """
        28-02-2023 → 31-03-2023: 31 días corridos frente a 30 días 30/360.
        La fracción 30/360 es *menor* que la ACT/360, lo que en un descuento a
        esa fecha se traduce en un factor de descuento más alto.
        """
        d1, d2 = date(2023, 2, 28), date(2023, 3, 31)
        self.assertEqual(day_count_days(d1, d2, "ACT/360"), 31)
        self.assertEqual(day_count_days(d1, d2, "30/360"), 30)
        self.assertLess(
            day_count_fraction(d1, d2, "30/360"),
            day_count_fraction(d1, d2, "ACT/360"),
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
