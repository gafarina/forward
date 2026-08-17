"""
Tests del modelo de datos (`valorizador.models`) y de los formularios que lo
validan.

Dos invariantes de negocio se fijan aquí:

* `OwnedQuerySet.for_user` es el único punto por el que las vistas ven datos,
  y es lo que impide que un usuario acceda a la cartera de otro (en la v1 los
  listados no filtraban por dueño).
* El folio es único **por usuario**, no globalmente: dos clientes distintos
  pueden tener el mismo número de folio, y eso es legítimo.
"""

from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase

from core.curves import Curve
from valorizador.forms import ContratoForm
from valorizador.models import (
    Cartera,
    ConjuntoCurvas,
    Contraparte,
    ContratoForward,
    PuntoCurva,
    ValorizacionGuardada,
)

User = get_user_model()


def crear_usuario(username, **extra):
    return User.objects.create_user(
        username=username, password="clave-de-prueba-larga", **extra
    )


def crear_contrato(user, folio="1", **extra):
    datos = dict(
        counterparty="Bice",
        folio=folio,
        side="Venta",
        notional=Decimal("1000000"),
        fwd_price=Decimal("890.0000"),
        spot_inicio=Decimal("889.0000"),
        maturity_date=date(2026, 7, 13),
        created_by=user,
    )
    datos.update(extra)
    return ContratoForward.objects.create(**datos)


class OwnedQuerySetTest(TestCase):
    """`for_user` es la barrera de aislamiento entre clientes."""

    @classmethod
    def setUpTestData(cls):
        cls.ana = crear_usuario("ana")
        cls.beto = crear_usuario("beto")
        cls.admin = crear_usuario("admin", is_staff=True)
        cls.c_ana = crear_contrato(cls.ana, folio="A-1")
        cls.c_beto = crear_contrato(cls.beto, folio="B-1")

    def test_cada_usuario_solo_ve_lo_suyo(self):
        self.assertQuerySetEqual(
            ContratoForward.objects.for_user(self.ana), [self.c_ana]
        )
        self.assertQuerySetEqual(
            ContratoForward.objects.for_user(self.beto), [self.c_beto]
        )

    def test_el_staff_ve_todo(self):
        """El administrador necesita ver la instancia completa para soporte."""
        self.assertEqual(ContratoForward.objects.for_user(self.admin).count(), 2)

    def test_for_user_aplica_a_todos_los_modelos_con_dueno(self):
        Cartera.objects.create(nombre="Cordada", created_by=self.ana)
        ConjuntoCurvas.objects.create(
            label="C", valuation_date=date(2026, 5, 31),
            spot_usdclp=Decimal("892.89"), created_by=self.ana,
        )
        Contraparte.objects.create(nombre="Bice", created_by=self.ana)
        ValorizacionGuardada.objects.create(
            valuation_date=date(2026, 5, 31), created_by=self.ana
        )
        for modelo in (Cartera, ConjuntoCurvas, Contraparte, ValorizacionGuardada):
            with self.subTest(modelo=modelo.__name__):
                self.assertEqual(modelo.objects.for_user(self.ana).count(), 1)
                self.assertEqual(modelo.objects.for_user(self.beto).count(), 0)


class FolioUnicoPorUsuarioTest(TestCase):
    """El folio identifica la operación dentro de la cartera de un cliente."""

    @classmethod
    def setUpTestData(cls):
        cls.ana = crear_usuario("ana")
        cls.beto = crear_usuario("beto")

    def datos_form(self, **extra):
        datos = {
            "counterparty": "Bice",
            "folio": "118039",
            "side": "Venta",
            "modality": "Compensacion",
            "base_ccy": "USD",
            "quote_ccy": "CLP",
            "notional": "1000000",
            "fwd_price": "893.35",
            "spot_inicio": "894.25",
            "maturity_date": "2026-07-13",
            "fwd_curve": "FWDUSDCLP",
            "disc_curve": "CLP423",
            "status": "Vigente",
        }
        datos.update(extra)
        return datos

    def test_dos_usuarios_distintos_pueden_repetir_el_folio(self):
        """No es un identificador global: cada cliente numera como quiere."""
        crear_contrato(self.ana, folio="118039")
        form = ContratoForm(self.datos_form(), user=self.beto)
        self.assertTrue(form.is_valid(), msg=form.errors.as_json())

    def test_el_mismo_usuario_no_puede_repetir_el_folio(self):
        crear_contrato(self.ana, folio="118039")
        form = ContratoForm(self.datos_form(), user=self.ana)
        self.assertFalse(form.is_valid())
        self.assertIn("folio", form.errors)
        self.assertIn("Ya tienes un contrato con este folio.", form.errors["folio"])

    def test_editar_un_contrato_no_choca_con_su_propio_folio(self):
        contrato = crear_contrato(self.ana, folio="118039")
        form = ContratoForm(self.datos_form(), instance=contrato, user=self.ana)
        self.assertTrue(form.is_valid(), msg=form.errors.as_json())

    def test_el_folio_vacio_no_genera_conflicto(self):
        """Un contrato sin folio es válido y no bloquea a los demás."""
        crear_contrato(self.ana, folio="")
        form = ContratoForm(self.datos_form(folio=""), user=self.ana)
        self.assertTrue(form.is_valid(), msg=form.errors.as_json())

    def test_el_formulario_exige_el_tipo_de_cambio_al_inicio(self):
        """Sin S₀ no se puede separar componente spot de puntos forward."""
        form = ContratoForm(self.datos_form(spot_inicio=""), user=self.ana)
        self.assertFalse(form.is_valid())
        self.assertIn("spot_inicio", form.errors)

    def test_el_formulario_rechaza_vencimiento_anterior_al_inicio(self):
        form = ContratoForm(
            self.datos_form(start_date="2026-08-01", maturity_date="2026-07-13"),
            user=self.ana,
        )
        self.assertFalse(form.is_valid())
        self.assertIn("maturity_date", form.errors)

    def test_el_formulario_solo_ofrece_las_carteras_del_usuario(self):
        """El desplegable no puede filtrar datos de otro cliente."""
        mia = Cartera.objects.create(nombre="Mía", created_by=self.ana)
        Cartera.objects.create(nombre="Ajena", created_by=self.beto)
        form = ContratoForm(user=self.ana)
        self.assertQuerySetEqual(form.fields["cartera"].queryset, [mia])


class ContratoForwardTest(TestCase):
    """Validación y conversión al motor."""

    @classmethod
    def setUpTestData(cls):
        cls.user = crear_usuario("ana")
        cls.cartera = Cartera.objects.create(nombre="Cordada", created_by=cls.user)

    def test_clean_rechaza_vencimiento_anterior_al_inicio(self):
        c = ContratoForward(
            counterparty="Bice", side="Venta",
            notional=Decimal("1000000"), fwd_price=Decimal("890"),
            start_date=date(2026, 8, 1), maturity_date=date(2026, 7, 13),
            created_by=self.user,
        )
        with self.assertRaises(ValidationError) as ctx:
            c.clean()
        self.assertIn("maturity_date", ctx.exception.error_dict)

    def test_clean_acepta_vencimiento_igual_al_inicio(self):
        """Un overnight parte y vence el mismo día: es válido."""
        c = ContratoForward(
            counterparty="Bice", side="Venta",
            notional=Decimal("1000000"), fwd_price=Decimal("890"),
            start_date=date(2026, 7, 13), maturity_date=date(2026, 7, 13),
            created_by=self.user,
        )
        c.clean()  # no debe levantar

    def test_clean_sin_fecha_de_inicio_no_falla(self):
        c = ContratoForward(
            counterparty="Bice", side="Venta",
            notional=Decimal("1000000"), fwd_price=Decimal("890"),
            maturity_date=date(2026, 7, 13), created_by=self.user,
        )
        c.clean()

    def test_signo_venta_es_mas_uno_y_compra_menos_uno(self):
        venta = crear_contrato(self.user, folio="V", side="Venta")
        compra = crear_contrato(self.user, folio="C", side="Compra")
        self.assertEqual(venta.to_core().sign, 1)
        self.assertEqual(compra.to_core().sign, -1)

    def test_to_core_mapea_todos_los_campos(self):
        c = crear_contrato(
            self.user, folio="118039", cartera=self.cartera,
            counterparty="Bice", side="Venta",
            notional=Decimal("2000000"), fwd_price=Decimal("893.3500"),
            spot_inicio=Decimal("894.2500"), maturity_date=date(2026, 7, 13),
        )
        core = c.to_core()
        self.assertEqual(core.id, c.pk)
        self.assertEqual(core.folio, "118039")
        self.assertEqual(core.counterparty, "Bice")
        self.assertEqual(core.side, "Venta")
        self.assertEqual(core.notional, 2_000_000.0)
        self.assertAlmostEqual(core.fwd_price, 893.35, places=6)
        self.assertAlmostEqual(core.spot_inicio, 894.25, places=6)
        self.assertEqual(core.maturity_date, date(2026, 7, 13))
        self.assertEqual(core.base_ccy, "USD")
        self.assertEqual(core.quote_ccy, "CLP")
        self.assertEqual(core.fwd_curve, "FWDUSDCLP")
        self.assertEqual(core.disc_curve, "CLP423")
        self.assertEqual(core.cartera, "Cordada")

    def test_to_core_sin_cartera_deja_el_nombre_vacio(self):
        core = crear_contrato(self.user, folio="X").to_core()
        self.assertEqual(core.cartera, "")

    def test_la_cartera_cuenta_solo_los_contratos_vigentes(self):
        crear_contrato(self.user, folio="1", cartera=self.cartera)
        crear_contrato(self.user, folio="2", cartera=self.cartera, status="Liquidado")
        self.assertEqual(self.cartera.n_contratos, 1)

    def test_notional_por_moneda_agrupa_por_divisa(self):
        crear_contrato(self.user, folio="1", cartera=self.cartera)
        crear_contrato(self.user, folio="2", cartera=self.cartera,
                       base_ccy="EUR", notional=Decimal("500000"))
        self.assertEqual(
            self.cartera.notional_por_moneda(), {"USD": 1_000_000.0, "EUR": 500_000.0}
        )

    def test_borrar_la_cartera_no_borra_los_contratos(self):
        """`on_delete=SET_NULL`: los contratos sobreviven sin cartera."""
        c = crear_contrato(self.user, folio="1", cartera=self.cartera)
        self.cartera.delete()
        c.refresh_from_db()
        self.assertIsNone(c.cartera)


class ConjuntoCurvasTest(TestCase):
    """Conversión del conjunto guardado a los objetos que consume el motor."""

    @classmethod
    def setUpTestData(cls):
        cls.user = crear_usuario("ana")
        cls.conjunto = ConjuntoCurvas.objects.create(
            label="Cordada 2026-05-31", valuation_date=date(2026, 5, 31),
            spot_usdclp=Decimal("892.8900"), created_by=cls.user,
        )
        # Se cargan desordenados a propósito.
        PuntoCurva.objects.bulk_create([
            PuntoCurva(conjunto=cls.conjunto, nombre="FWDUSDCLP",
                       tenor_days=d, value=Decimal(str(v)))
            for d, v in [(62, 892.03), (1, 892.21), (8, 892.19)]
        ] + [
            PuntoCurva(conjunto=cls.conjunto, nombre="CLP423",
                       tenor_days=d, value=Decimal(str(v)))
            for d, v in [(183, 3.61177), (92, 3.48231)]
        ])

    def test_as_curves_devuelve_objetos_curve_por_nombre(self):
        curvas = self.conjunto.as_curves()
        self.assertEqual(set(curvas), {"FWDUSDCLP", "CLP423"})
        for nombre, curva in curvas.items():
            with self.subTest(curva=nombre):
                self.assertIsInstance(curva, Curve)
                self.assertEqual(curva.name, nombre)

    def test_los_nodos_quedan_ordenados_por_plazo(self):
        """Aunque se guarden desordenados, el motor los recibe ordenados."""
        curvas = self.conjunto.as_curves()
        self.assertEqual(curvas["FWDUSDCLP"].xs, [1.0, 8.0, 62.0])
        self.assertEqual(curvas["FWDUSDCLP"].ys, [892.21, 892.19, 892.03])
        self.assertEqual(curvas["CLP423"].xs, [92.0, 183.0])

    def test_la_curva_resultante_interpola(self):
        curvas = self.conjunto.as_curves()
        # Punto medio entre 92d (3.48231) y 183d (3.61177) en 137.5 días.
        esperado = (3.48231 + 3.61177) / 2
        self.assertAlmostEqual(curvas["CLP423"].value(137.5), esperado, places=8)

    def test_n_puntos_cuenta_todos_los_nodos(self):
        self.assertEqual(self.conjunto.n_puntos, 5)

    def test_un_conjunto_sin_puntos_devuelve_un_diccionario_vacio(self):
        vacio = ConjuntoCurvas.objects.create(
            label="Vacío", valuation_date=date(2026, 5, 31),
            spot_usdclp=Decimal("892.89"), created_by=self.user,
        )
        self.assertEqual(vacio.as_curves(), {})

    def test_no_se_pueden_repetir_plazos_dentro_de_una_curva(self):
        """La restricción de unicidad evita curvas ambiguas en la base."""
        from django.db import IntegrityError, transaction

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                PuntoCurva.objects.create(
                    conjunto=self.conjunto, nombre="FWDUSDCLP",
                    tenor_days=1, value=Decimal("999"),
                )

    def test_borrar_el_conjunto_borra_sus_puntos(self):
        pk = self.conjunto.pk
        self.conjunto.delete()
        self.assertEqual(PuntoCurva.objects.filter(conjunto_id=pk).count(), 0)
