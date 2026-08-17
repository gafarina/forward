"""
Tests del comando `cargar_demo`.

El comando es la referencia del proyecto: carga exactamente los nodos y los
contratos del libro Cordada 31-05-2026 para poder comparar la aplicación
contra la planilla. Estos tests verifican que sea idempotente (se ejecuta en
cada despliegue de demo) y que los datos que deja en la base reproduzcan, a
través del ORM y del motor, los valores de la planilla.
"""

from datetime import date
from decimal import Decimal
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase

from core.valuation import MarketData, PricingConfig, price_portfolio
from valorizador.services.datos_ejemplo import (
    CONTRATOS,
    DESC_NODOS,
    ETIQUETA_CONJUNTO,
    FECHA_VALORIZACION,
    FWD_NODOS,
    NOMBRE_CARTERA,
    SPOT_VALORIZACION,
)
from valorizador.models import (
    Cartera,
    ConjuntoCurvas,
    Contraparte,
    ContratoForward,
    PuntoCurva,
)

User = get_user_model()

# Valores de la planilla Cordada, por folio.
PLANILLA = {
    "756929": {"mtm": -5_096_628.947701437, "spot": -5_162_209.388305195},
    "118039": {"mtm": 2_592_812.5610144176, "spot": 2_709_119.6424377537},
    "116845": {"mtm": -4_346_625.784937648, "spot": -5_114_348.920950738},
}


def cargar(usuario="demo", **opts):
    salida = StringIO()
    call_command("cargar_demo", usuario=usuario, clave="clave-demo-larga",
                 stdout=salida, stderr=StringIO(), **opts)
    return salida.getvalue()


class CargarDemoTest(TestCase):
    """Carga del caso de demostración."""

    def test_crea_el_usuario_la_cartera_las_curvas_y_los_contratos(self):
        cargar()
        user = User.objects.get(username="demo")
        self.assertTrue(user.check_password("clave-demo-larga"))
        self.assertEqual(Cartera.objects.filter(created_by=user).count(), 1)
        self.assertEqual(Contraparte.objects.filter(created_by=user).count(), 2)
        self.assertEqual(ConjuntoCurvas.objects.filter(created_by=user).count(), 1)
        self.assertEqual(ContratoForward.objects.filter(created_by=user).count(), 3)

    def test_el_conjunto_queda_activo_con_la_fecha_y_el_spot_de_la_planilla(self):
        cargar()
        conjunto = ConjuntoCurvas.objects.get(created_by__username="demo")
        self.assertTrue(conjunto.is_active)
        self.assertEqual(conjunto.valuation_date, FECHA_VALORIZACION)
        self.assertEqual(conjunto.spot_usdclp, SPOT_VALORIZACION)
        self.assertEqual(conjunto.n_puntos, len(FWD_NODOS) + len(DESC_NODOS))

    def test_los_nodos_cargados_son_los_de_la_planilla(self):
        cargar()
        conjunto = ConjuntoCurvas.objects.get(created_by__username="demo")
        fwd = list(conjunto.puntos.filter(nombre="FWDUSDCLP").order_by("tenor_days"))
        desc = list(conjunto.puntos.filter(nombre="CLP423").order_by("tenor_days"))
        self.assertEqual([p.tenor_days for p in fwd], [d for d, _ in FWD_NODOS])
        self.assertEqual([float(p.value) for p in fwd], [v for _, v in FWD_NODOS])
        self.assertEqual([p.tenor_days for p in desc], [d for d, _ in DESC_NODOS])
        self.assertEqual([float(p.value) for p in desc], [v for _, v in DESC_NODOS])

    def test_los_contratos_son_ventas_con_los_datos_de_la_planilla(self):
        cargar()
        for folio, cp, vcto, nocional, spot_ini, precio in CONTRATOS:
            with self.subTest(folio=folio):
                c = ContratoForward.objects.get(
                    created_by__username="demo", folio=folio
                )
                self.assertEqual(c.counterparty, cp)
                self.assertEqual(c.side, "Venta")
                self.assertEqual(c.maturity_date, vcto)
                self.assertEqual(c.notional, Decimal(str(nocional)))
                self.assertEqual(c.spot_inicio, Decimal(str(spot_ini)))
                self.assertEqual(c.fwd_price, Decimal(str(precio)))
                self.assertEqual(c.cartera.nombre, NOMBRE_CARTERA)
                self.assertIsNotNone(c.contraparte_ref)

    def test_las_etiquetas_no_llevan_el_nombre_del_cliente(self):
        """Los datos de ejemplo se identifican como tales, no por su origen."""
        cargar()
        conjunto = ConjuntoCurvas.objects.get(created_by__username="demo")
        cartera = Cartera.objects.get(created_by__username="demo")
        self.assertEqual(conjunto.label, ETIQUETA_CONJUNTO)
        self.assertEqual(cartera.nombre, NOMBRE_CARTERA)
        for texto in (conjunto.label, conjunto.source, cartera.nombre):
            self.assertNotIn("cordada", texto.lower())


class IdempotenciaTest(TestCase):
    """
    Correr el comando dos veces no puede duplicar nada: se ejecuta en cada
    despliegue del entorno de demostración.
    """

    def test_dos_corridas_no_duplican_contratos(self):
        cargar()
        primero = list(
            ContratoForward.objects.filter(created_by__username="demo")
            .order_by("folio").values_list("pk", "folio")
        )
        cargar()
        segundo = list(
            ContratoForward.objects.filter(created_by__username="demo")
            .order_by("folio").values_list("pk", "folio")
        )
        self.assertEqual(len(segundo), 3)
        self.assertEqual(primero, segundo, msg="Los contratos deben ser los mismos.")

    def test_dos_corridas_no_duplican_nodos_de_curva(self):
        cargar()
        cargar()
        conjuntos = ConjuntoCurvas.objects.filter(created_by__username="demo")
        self.assertEqual(conjuntos.count(), 1)
        self.assertEqual(
            PuntoCurva.objects.filter(conjunto__in=conjuntos).count(),
            len(FWD_NODOS) + len(DESC_NODOS),
        )

    def test_dos_corridas_no_duplican_carteras_ni_contrapartes(self):
        cargar()
        cargar()
        self.assertEqual(Cartera.objects.filter(created_by__username="demo").count(), 1)
        self.assertEqual(
            Contraparte.objects.filter(created_by__username="demo").count(), 2
        )

    def test_tres_corridas_siguen_dejando_el_mismo_estado(self):
        cargar()
        cargar()
        cargar()
        user = User.objects.get(username="demo")
        self.assertEqual(User.objects.filter(username="demo").count(), 1)
        self.assertEqual(ContratoForward.objects.filter(created_by=user).count(), 3)
        self.assertEqual(ConjuntoCurvas.objects.filter(created_by=user).count(), 1)

    def test_usuarios_distintos_tienen_datos_independientes(self):
        """La demo de un usuario no toca la del otro."""
        cargar("demo")
        cargar("otro")
        self.assertEqual(
            ContratoForward.objects.filter(created_by__username="demo").count(), 3
        )
        self.assertEqual(
            ContratoForward.objects.filter(created_by__username="otro").count(), 3
        )
        self.assertEqual(ContratoForward.objects.count(), 6)

    def test_la_opcion_reset_deja_una_sola_copia(self):
        cargar()
        cargar(reset=True)
        user = User.objects.get(username="demo")
        self.assertEqual(ContratoForward.objects.filter(created_by=user).count(), 3)
        self.assertEqual(ConjuntoCurvas.objects.filter(created_by=user).count(), 1)


class ReconciliacionDesdeElOrmTest(TestCase):
    """
    Tras `cargar_demo`, valorizar la cartera leyéndola desde la base debe
    reproducir la planilla. Cierra el circuito completo: modelo → `to_core()`
    → motor, no sólo el motor aislado.
    """

    @classmethod
    def setUpTestData(cls):
        cargar()
        cls.user = User.objects.get(username="demo")
        cls.conjunto = ConjuntoCurvas.objects.get(created_by=cls.user)

    def valorizar(self, **config_extra):
        contratos = list(
            ContratoForward.objects.filter(created_by=self.user, status="Vigente")
        )
        market = MarketData(
            valuation_date=self.conjunto.valuation_date,
            spot=float(self.conjunto.spot_usdclp),
            curves=self.conjunto.as_curves(),
            label=self.conjunto.label,
        )
        parametros = dict(
            day_count="ACT/360", interp_method="Lineal", extrap_method="Lineal",
            business_days="Exacto", calendar="CL", compounding="Compuesta",
        )
        parametros.update(config_extra)
        config = PricingConfig(**parametros)
        return price_portfolio([c.to_core() for c in contratos], market, config)

    def test_los_tres_contratos_reproducen_el_mtm_de_la_planilla(self):
        res = self.valorizar()
        self.assertEqual(res["diagnostics"]["valued"], 3)
        por_folio = {l["folio"]: l for l in res["lines"]}
        self.assertEqual(set(por_folio), set(PLANILLA))
        for folio, esperado in PLANILLA.items():
            with self.subTest(folio=folio):
                self.assertAlmostEqual(por_folio[folio]["mtm"], esperado["mtm"], places=2)

    def test_los_tres_contratos_reproducen_el_componente_spot(self):
        res = self.valorizar()
        por_folio = {l["folio"]: l for l in res["lines"]}
        for folio, esperado in PLANILLA.items():
            with self.subTest(folio=folio):
                self.assertAlmostEqual(
                    por_folio[folio]["spot_component"], esperado["spot"], places=2
                )

    def test_el_total_de_la_cartera_cuadra(self):
        res = self.valorizar()
        esperado = round(sum(v["mtm"] for v in PLANILLA.values()), 2)
        self.assertAlmostEqual(res["totals"]["total_mtm"], esperado, places=2)

    def test_con_extrapolacion_plana_no_cuadra(self):
        """Regresión: es la configuración con la que la v1 no conciliaba."""
        res = self.valorizar(extrap_method="Plana")
        por_folio = {l["folio"]: l for l in res["lines"]}
        for folio, esperado in PLANILLA.items():
            with self.subTest(folio=folio):
                self.assertNotAlmostEqual(
                    por_folio[folio]["mtm"], esperado["mtm"], places=2
                )

    def test_la_valorizacion_es_estable_entre_corridas_del_comando(self):
        """Volver a cargar la demo no cambia el resultado."""
        antes = self.valorizar()["totals"]["total_mtm"]
        cargar()
        self.conjunto.refresh_from_db()
        self.assertAlmostEqual(self.valorizar()["totals"]["total_mtm"], antes, places=2)


class SalidaDelComandoTest(TestCase):
    """El comando informa lo que hizo y los valores de referencia."""

    def test_imprime_el_resumen_con_los_valores_de_la_planilla(self):
        salida = cargar()
        self.assertIn("Demo cargada", salida)
        for folio in PLANILLA:
            with self.subTest(folio=folio):
                self.assertIn(folio, salida)

    def test_la_segunda_corrida_informa_cero_contratos_nuevos(self):
        cargar()
        salida = cargar()
        self.assertIn("0 contratos nuevos", salida)
        self.assertIn(f"{len(CONTRATOS)} en total", salida)
