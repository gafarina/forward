"""
Tests de calendarios de días hábiles (`core.calendars`).

Protegen las reglas legales chilenas de traslado de feriados, el feriado
bancario del 31 de diciembre y el ajuste de vencimientos. En el motor v1 el
"ajuste de días hábiles" sólo movía sábados y domingos: un vencimiento el 18
de septiembre no se movía, lo que dejaba el plazo (y por lo tanto el factor de
descuento y el punto interpolado de la curva) desplazado respecto de la
liquidación real.
"""

import unittest
from datetime import date

from core.calendars import (
    BUSINESS_DAY_CONVENTIONS,
    Calendar,
    chile_holidays,
    easter_sunday,
    get_calendar,
    us_holidays,
)


class PascuaTest(unittest.TestCase):
    """El Viernes y el Sábado Santo se derivan del Domingo de Resurrección."""

    CASOS = {
        2024: date(2024, 3, 31),
        2025: date(2025, 4, 20),
        2026: date(2026, 4, 5),
        2027: date(2027, 3, 28),
    }

    def test_domingos_de_pascua_conocidos(self):
        """Fechas publicadas de Pascua para 2024-2027."""
        for anio, esperado in self.CASOS.items():
            with self.subTest(anio=anio):
                self.assertEqual(
                    easter_sunday(anio), esperado,
                    msg=f"Pascua {anio} debería ser {esperado}.",
                )

    def test_pascua_siempre_cae_domingo(self):
        """Chequeo estructural sobre 60 años: el algoritmo nunca debe salirse."""
        for anio in range(1990, 2050):
            with self.subTest(anio=anio):
                self.assertEqual(easter_sunday(anio).weekday(), 6)

    def test_viernes_y_sabado_santo_son_feriados(self):
        """Los dos días previos a Pascua son feriados legales en Chile."""
        from datetime import timedelta

        for anio in (2025, 2026):
            pascua = easter_sunday(anio)
            feriados = chile_holidays(anio)
            with self.subTest(anio=anio):
                self.assertIn(pascua - timedelta(days=2), feriados)  # Viernes Santo
                self.assertIn(pascua - timedelta(days=1), feriados)  # Sábado Santo


class FeriadosChilenosTest(unittest.TestCase):
    """Feriados fijos y reglas de traslado."""

    def test_fiestas_patrias_son_feriado(self):
        """18 y 19 de septiembre son feriados irrenunciables en todo año."""
        for anio in (2024, 2025, 2026, 2027):
            feriados = chile_holidays(anio)
            with self.subTest(anio=anio):
                self.assertIn(date(anio, 9, 18), feriados)
                self.assertIn(date(anio, 9, 19), feriados)

    def test_31_de_diciembre_es_feriado_bancario(self):
        """
        El 31 de diciembre es feriado bancario: no hay liquidación de cambio.
        Con `bancario=False` no debe aparecer, para poder distinguir el
        calendario legal del bancario.
        """
        self.assertIn(date(2026, 12, 31), chile_holidays(2026))
        self.assertNotIn(date(2026, 12, 31), chile_holidays(2026, bancario=False))
        self.assertFalse(get_calendar("CL").is_business_day(date(2026, 12, 31)))

    # -- Ley 20.215: 29 de junio y 12 de octubre ------------------------

    def test_traslado_al_lunes_previo_cuando_cae_martes(self):
        """29-06-2027 cae martes → se traslada al lunes 28-06-2027."""
        self.assertEqual(date(2027, 6, 29).weekday(), 1)
        feriados = chile_holidays(2027)
        self.assertIn(date(2027, 6, 28), feriados)
        self.assertNotIn(date(2027, 6, 29), feriados)

    def test_traslado_al_lunes_previo_cuando_cae_miercoles(self):
        """12-10-2022 cae miércoles → se traslada al lunes 10-10-2022."""
        self.assertEqual(date(2022, 10, 12).weekday(), 2)
        feriados = chile_holidays(2022)
        self.assertIn(date(2022, 10, 10), feriados)
        self.assertNotIn(date(2022, 10, 12), feriados)

    def test_traslado_al_lunes_previo_cuando_cae_jueves(self):
        """
        29-06-2023 y 12-10-2023 caen jueves → lunes de la misma semana
        (26-06 y 09-10 respectivamente).
        """
        self.assertEqual(date(2023, 6, 29).weekday(), 3)
        self.assertEqual(date(2023, 10, 12).weekday(), 3)
        feriados = chile_holidays(2023)
        self.assertIn(date(2023, 6, 26), feriados)
        self.assertNotIn(date(2023, 6, 29), feriados)
        self.assertIn(date(2023, 10, 9), feriados)
        self.assertNotIn(date(2023, 10, 12), feriados)

    def test_traslado_al_lunes_siguiente_cuando_cae_viernes(self):
        """
        Cuando cae viernes el feriado se posterga al lunes siguiente.
        29-06-2029 (viernes) → 02-07-2029; 12-10-2029 (viernes) → 15-10-2029.
        El caso de junio además cruza de mes, que es donde la regla suele
        implementarse mal.
        """
        self.assertEqual(date(2029, 6, 29).weekday(), 4)
        self.assertEqual(date(2029, 10, 12).weekday(), 4)
        feriados = chile_holidays(2029)
        self.assertIn(date(2029, 7, 2), feriados)
        self.assertNotIn(date(2029, 6, 29), feriados)
        self.assertIn(date(2029, 10, 15), feriados)
        self.assertNotIn(date(2029, 10, 12), feriados)

    def test_no_se_traslada_cuando_cae_lunes_o_fin_de_semana(self):
        """Lunes y fines de semana quedan en su fecha: 29-06-2026 es lunes."""
        self.assertEqual(date(2026, 6, 29).weekday(), 0)
        self.assertIn(date(2026, 6, 29), chile_holidays(2026))
        self.assertEqual(date(2024, 6, 29).weekday(), 5)  # sábado
        self.assertIn(date(2024, 6, 29), chile_holidays(2024))

    # -- Ley 20.299: Día de las Iglesias Evangélicas --------------------

    def test_iglesias_evangelicas_se_adelanta_si_el_31_cae_martes(self):
        """31-10-2023 es martes → el feriado se adelanta al viernes 27-10-2023."""
        self.assertEqual(date(2023, 10, 31).weekday(), 1)
        feriados = chile_holidays(2023)
        self.assertIn(date(2023, 10, 27), feriados)
        self.assertNotIn(date(2023, 10, 31), feriados)

    def test_iglesias_evangelicas_se_posterga_si_el_31_cae_miercoles(self):
        """31-10-2029 es miércoles → el feriado pasa al viernes 02-11-2029."""
        self.assertEqual(date(2029, 10, 31).weekday(), 2)
        feriados = chile_holidays(2029)
        self.assertIn(date(2029, 11, 2), feriados)
        self.assertNotIn(date(2029, 10, 31), feriados)

    def test_iglesias_evangelicas_se_queda_el_31_los_demas_dias(self):
        """31-10-2024 es jueves: no hay traslado, el feriado es el mismo 31."""
        self.assertEqual(date(2024, 10, 31).weekday(), 3)
        self.assertIn(date(2024, 10, 31), chile_holidays(2024))

    # -- Ley 20.215: puentes de Fiestas Patrias -------------------------

    def test_puente_de_fiestas_patrias_cuando_el_18_cae_martes(self):
        """18-09-2029 es martes → el lunes 17 también es feriado."""
        self.assertEqual(date(2029, 9, 18).weekday(), 1)
        self.assertIn(date(2029, 9, 17), chile_holidays(2029))

    def test_puente_de_fiestas_patrias_cuando_el_18_cae_miercoles(self):
        """18-09-2024 es miércoles → el viernes 20 también es feriado."""
        self.assertEqual(date(2024, 9, 18).weekday(), 2)
        self.assertIn(date(2024, 9, 20), chile_holidays(2024))


class AjusteDeVencimientosTest(unittest.TestCase):
    """`Calendar.adjust` bajo las distintas convenciones."""

    def setUp(self):
        self.cal = get_calendar("CL")

    def test_modified_following_mueve_al_siguiente_habil(self):
        """
        El 18-09-2026 es viernes feriado; el 19 (sábado) y el 20 (domingo)
        tampoco son hábiles. ModifiedFollowing lleva el vencimiento al lunes
        21-09-2026, que sigue dentro de septiembre.
        """
        self.assertFalse(self.cal.is_business_day(date(2026, 9, 18)))
        self.assertEqual(
            self.cal.adjust(date(2026, 9, 18), "ModifiedFollowing"), date(2026, 9, 21)
        )

    def test_modified_following_retrocede_si_cruza_de_mes(self):
        """
        El 31-12-2026 es feriado bancario y el siguiente hábil es el 04-01-2027
        (el 1 de enero es feriado y el 2 y 3 son fin de semana). Como cambia de
        mes, ModifiedFollowing retrocede al 30-12-2026.
        """
        self.assertEqual(
            self.cal.adjust(date(2026, 12, 31), "Following"), date(2027, 1, 4)
        )
        self.assertEqual(
            self.cal.adjust(date(2026, 12, 31), "ModifiedFollowing"), date(2026, 12, 30),
            msg="ModifiedFollowing no puede empujar el vencimiento a otro mes.",
        )

    def test_preceding_y_modified_preceding(self):
        """Preceding retrocede; ModifiedPreceding avanza si cruzaría de mes."""
        self.assertEqual(self.cal.adjust(date(2026, 9, 18), "Preceding"), date(2026, 9, 17))
        # 01-01-2027 es feriado y viernes: Preceding se iría a 2026.
        self.assertEqual(self.cal.adjust(date(2027, 1, 1), "Preceding"), date(2026, 12, 30))
        self.assertEqual(
            self.cal.adjust(date(2027, 1, 1), "ModifiedPreceding"), date(2027, 1, 4)
        )

    def test_exacto_no_toca_la_fecha(self):
        """La convención 'Exacto' es la que replica la planilla: no ajusta nada."""
        self.assertEqual(self.cal.adjust(date(2026, 9, 18), "Exacto"), date(2026, 9, 18))

    def test_un_dia_habil_no_se_mueve_en_ninguna_convencion(self):
        """Si la fecha ya es hábil, ninguna convención debe alterarla."""
        habil = date(2026, 6, 12)
        self.assertTrue(self.cal.is_business_day(habil))
        for conv in BUSINESS_DAY_CONVENTIONS:
            with self.subTest(conv=conv):
                self.assertEqual(self.cal.adjust(habil, conv), habil)

    def test_convencion_desconocida_falla(self):
        """Un valor de convención inválido debe reventar explícitamente."""
        with self.assertRaises(ValueError):
            self.cal.adjust(date(2026, 9, 18), "SiguienteMasOMenos")


class CalendarioConjuntoTest(unittest.TestCase):
    """El USD/CLP con entrega liquida sólo si es hábil en Chile y en EE.UU."""

    def test_thanksgiving_no_es_habil_en_el_calendario_conjunto(self):
        """
        26-11-2026 (Thanksgiving, cuarto jueves de noviembre) es día hábil en
        Chile pero no en EE.UU.; en el calendario conjunto no es hábil.
        """
        dia = date(2026, 11, 26)
        self.assertEqual(dia.weekday(), 3)
        self.assertIn(dia, us_holidays(2026))
        self.assertTrue(get_calendar("CL").is_business_day(dia))
        self.assertFalse(get_calendar("US").is_business_day(dia))
        self.assertFalse(
            get_calendar("CL+US").is_business_day(dia),
            msg="El calendario conjunto debe ser la unión de los feriados.",
        )

    def test_fiestas_patrias_no_es_habil_en_el_conjunto_pero_si_en_eeuu(self):
        """El caso simétrico: 18-09-2026 es hábil en EE.UU. y feriado en Chile."""
        dia = date(2026, 9, 18)
        self.assertTrue(get_calendar("US").is_business_day(dia))
        self.assertFalse(get_calendar("CL").is_business_day(dia))
        self.assertFalse(get_calendar("CL+US").is_business_day(dia))

    def test_calendario_nulo_solo_descarta_fines_de_semana(self):
        """'NULL' sirve para reproducir la v1: sólo sábados y domingos."""
        nulo = get_calendar("NULL")
        self.assertTrue(nulo.is_business_day(date(2026, 9, 18)))
        self.assertFalse(nulo.is_business_day(date(2026, 9, 19)))  # sábado

    def test_calendario_no_registrado_falla(self):
        """Pedir un calendario inexistente debe fallar, no caer a uno vacío."""
        with self.assertRaises(ValueError):
            get_calendar("BR")

    def test_calendario_admite_feriados_extra(self):
        """`extra` permite agregar cierres puntuales (censo, paro bancario)."""
        cal = Calendar("CL+extra", chile_holidays, extra=frozenset({date(2026, 6, 17)}))
        self.assertFalse(cal.is_business_day(date(2026, 6, 17)))
        self.assertTrue(get_calendar("CL").is_business_day(date(2026, 6, 17)))


class ConteoDeDiasHabilesTest(unittest.TestCase):
    """`add_business_days` y `business_days_between` cruzando feriados."""

    def setUp(self):
        self.cal = get_calendar("CL")

    def test_add_business_days_salta_el_18_y_19_de_septiembre(self):
        """
        Desde el jueves 17-09-2026, un día hábil no es el viernes 18 (feriado)
        ni el fin de semana: es el lunes 21-09-2026.
        """
        self.assertEqual(self.cal.add_business_days(date(2026, 9, 17), 1), date(2026, 9, 21))

    def test_add_business_days_varios_dias_sobre_el_mismo_feriado(self):
        """
        Desde el miércoles 16-09-2026: el hábil 1 es el jueves 17, el 2 es el
        lunes 21 (el viernes 18 es feriado y el 19-20 es fin de semana) y el 3
        es el martes 22.
        """
        self.assertEqual(self.cal.add_business_days(date(2026, 9, 16), 1), date(2026, 9, 17))
        self.assertEqual(self.cal.add_business_days(date(2026, 9, 16), 2), date(2026, 9, 21))
        self.assertEqual(self.cal.add_business_days(date(2026, 9, 16), 3), date(2026, 9, 22))

    def test_add_business_days_negativo_retrocede(self):
        """Con n negativo retrocede; desde el lunes 21-09-2026, -1 es el 17."""
        self.assertEqual(self.cal.add_business_days(date(2026, 9, 21), -1), date(2026, 9, 17))

    def test_add_business_days_cero_no_mueve(self):
        """n = 0 devuelve la misma fecha aunque sea feriado (no ajusta)."""
        self.assertEqual(self.cal.add_business_days(date(2026, 9, 18), 0), date(2026, 9, 18))

    def test_business_days_between_descuenta_los_feriados(self):
        """
        Del 16-09-2026 al 23-09-2026 hay 7 días corridos, 5 días de semana y
        sólo 4 hábiles: el viernes 18 es feriado (el 19 cae sábado).
        """
        self.assertEqual((date(2026, 9, 23) - date(2026, 9, 16)).days, 7)
        self.assertEqual(get_calendar("NULL").business_days_between(
            date(2026, 9, 16), date(2026, 9, 23)), 5)
        self.assertEqual(self.cal.business_days_between(
            date(2026, 9, 16), date(2026, 9, 23)), 4)

    def test_business_days_between_es_antisimetrica(self):
        """Invertir el orden cambia el signo."""
        a, b = date(2026, 9, 16), date(2026, 9, 23)
        self.assertEqual(
            self.cal.business_days_between(b, a), -self.cal.business_days_between(a, b)
        )

    def test_business_days_between_cruzando_fin_de_anio(self):
        """
        Del 29-12-2026 al 05-01-2027: el 31-12 (bancario), el 01-01 y el fin de
        semana no cuentan. Hábiles: 30-dic, 04-ene y 05-ene = 3.
        """
        self.assertEqual(
            self.cal.business_days_between(date(2026, 12, 29), date(2027, 1, 5)), 3
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
