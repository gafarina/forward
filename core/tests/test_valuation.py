"""
Tests del motor de valorización (`core.valuation`).

El test central es la reconciliación contra la planilla Cordada del
31-05-2026: los mismos nodos de curva y los mismos tres contratos del comando
`cargar_demo`, comparados contra los valores de la planilla celda por celda.
Si algo se mueve en interpolación, descuento o convenciones, este archivo lo
detecta antes que el usuario.
"""

import unittest
from datetime import date, timedelta

from core.curves import Curve
from core.valuation import (
    Contract,
    MarketData,
    PricingConfig,
    price_contract,
    price_portfolio,
    sensitivity_matrix,
)

# ── Datos de la planilla Cordada 31-05-2026 ───────────────────────────

FWD_NODOS = [
    (1, 892.21), (2, 892.205), (8, 892.19), (15, 892.13), (22, 892.105),
    (31, 892.06), (62, 892.03),
]
DESC_NODOS = [
    (92, 3.48231), (183, 3.61177), (271, 3.70649), (365, 3.78017),
    (731, 3.98414), (1096, 4.24534), (1461, 4.42915),
]
FECHA_VAL = date(2026, 5, 31)
SPOT_VAL = 892.89

# folio → (vencimiento, nocional, spot al inicio, precio pactado)
CONTRATOS = {
    "756929": (date(2026, 7, 7), 1_000_000, 887.71, 886.94),
    "118039": (date(2026, 7, 13), 2_000_000, 894.25, 893.35),
    "116845": (date(2026, 6, 12), 2_000_000, 890.33, 889.98),
}

# Valores de referencia leídos de la planilla.
PLANILLA = {
    "756929": {
        "fwd_mkt": 892.054193548387,
        "disc_rate": 3.404064945054945,
        "disc_factor": 0.9965655189778464,
        "mtm": -5_096_628.947701437,
        "spot_component": -5_162_209.388305195,
    },
    "118039": {
        "fwd_mkt": 892.0483870967741,
        "disc_rate": 3.412600769230769,
        "disc_factor": 0.9959998685432817,
        "mtm": 2_592_812.5610144176,
        "spot_component": 2_709_119.6424377537,
    },
    "116845": {
        "fwd_mkt": 892.1557142857143,
        "disc_rate": 3.368499010989011,
        "disc_factor": 0.9988962736232122,
        "mtm": -4_346_625.784937648,
        "spot_component": -5_114_348.920950738,
    },
}


def curvas_cordada() -> dict:
    """Curvas del libro Cordada, recreadas en cada llamada para no compartir estado."""
    return {
        "FWDUSDCLP": Curve("FWDUSDCLP", [x for x, _ in FWD_NODOS], [y for _, y in FWD_NODOS]),
        "CLP423": Curve("CLP423", [x for x, _ in DESC_NODOS], [y for _, y in DESC_NODOS]),
    }


def mercado_cordada(fecha=FECHA_VAL, spot=SPOT_VAL) -> MarketData:
    return MarketData(valuation_date=fecha, spot=spot, curves=curvas_cordada(),
                      label="Cordada 2026-05-31")


def contrato(folio, side="Venta") -> Contract:
    vcto, nocional, spot_ini, precio = CONTRATOS[folio]
    return Contract(
        notional=nocional, fwd_price=precio, maturity_date=vcto, side=side,
        spot_inicio=spot_ini, counterparty="Bice", folio=folio, id=folio,
    )


def config_cordada(**kwargs) -> PricingConfig:
    """Configuración que replica la planilla."""
    base = dict(
        day_count="ACT/360", interp_method="Lineal", extrap_method="Lineal",
        business_days="Exacto", calendar="CL", compounding="Compuesta",
        calc_greeks=True, calc_cva=False,
    )
    base.update(kwargs)
    return PricingConfig(**base)


class ReconciliacionCordadaTest(unittest.TestCase):
    """
    Test dorado: los tres contratos de la planilla Cordada al 31-05-2026.

    Cualquier cambio en la extrapolación, el conteo de días, la capitalización
    o la interpolación rompe este test. Es la definición operativa de
    "la aplicación cuadra con la planilla".
    """

    def setUp(self):
        self.market = mercado_cordada()
        self.config = config_cordada()

    def test_forward_de_mercado_por_contrato(self):
        """El outright interpolado/extrapolado en el plazo residual."""
        for folio, esperado in PLANILLA.items():
            with self.subTest(folio=folio):
                r = price_contract(contrato(folio), self.market, self.config)
                self.assertAlmostEqual(r["fwd_mkt"], esperado["fwd_mkt"], places=2)

    def test_tasa_de_descuento_por_contrato(self):
        """
        La tasa de descuento sale de extrapolar linealmente la curva CLP423
        por debajo de su primer nodo (92 días), que es lo que hace la planilla.
        """
        for folio, esperado in PLANILLA.items():
            with self.subTest(folio=folio):
                r = price_contract(contrato(folio), self.market, self.config)
                self.assertAlmostEqual(r["disc_rate"], esperado["disc_rate"], places=2)

    def test_factor_de_descuento_por_contrato(self):
        """DF = (1 + r)^(-t) con t en ACT/360."""
        for folio, esperado in PLANILLA.items():
            with self.subTest(folio=folio):
                r = price_contract(contrato(folio), self.market, self.config)
                self.assertAlmostEqual(r["disc_factor"], esperado["disc_factor"], places=8)

    def test_mtm_por_contrato(self):
        """MtM = ε·(K − F)·N·DF, en pesos, contra la planilla."""
        for folio, esperado in PLANILLA.items():
            with self.subTest(folio=folio):
                r = price_contract(contrato(folio), self.market, self.config)
                self.assertAlmostEqual(r["mtm"], esperado["mtm"], places=2)

    def test_componente_spot_por_contrato(self):
        """Componente spot = ε·(S₀ − S_t)·N·DF."""
        for folio, esperado in PLANILLA.items():
            with self.subTest(folio=folio):
                r = price_contract(contrato(folio), self.market, self.config)
                self.assertAlmostEqual(
                    r["spot_component"], esperado["spot_component"], places=2
                )

    def test_la_descomposicion_suma_exactamente_el_mtm(self):
        """
        MtM = componente spot + puntos forward, sin residuo de redondeo a la
        precisión con la que se reportan los tres campos (dos decimales de
        peso). La comparación se hace sobre la suma redondeada porque los
        valores viven en punto flotante binario y −5.162.209,39 + 65.580,44
        no da exactamente −5.096.628,95 en base 2.
        """
        for folio in PLANILLA:
            with self.subTest(folio=folio):
                r = price_contract(contrato(folio), self.market, self.config)
                self.assertEqual(
                    round(r["spot_component"] + r["fwd_points"], 2), r["mtm"]
                )
                self.assertNotEqual(r["fwd_points"], 0.0)

    def test_plazos_residuales(self):
        """Con business_days='Exacto' el plazo es la diferencia de calendario."""
        esperados = {"756929": 37, "118039": 43, "116845": 12}
        for folio, dias in esperados.items():
            with self.subTest(folio=folio):
                r = price_contract(contrato(folio), self.market, self.config)
                self.assertEqual(r["days_to_mat"], dias)
                self.assertAlmostEqual(r["year_fraction"], dias / 360.0, places=8)

    def test_total_de_cartera_contra_la_planilla(self):
        """La suma de los tres MtM de la planilla es el total de la cartera."""
        res = price_portfolio(
            [contrato(f) for f in CONTRATOS], self.market, self.config
        )
        esperado = round(sum(v["mtm"] for v in PLANILLA.values()), 2)
        self.assertAlmostEqual(res["totals"]["total_mtm"], esperado, places=2)
        self.assertEqual(res["diagnostics"]["valued"], 3)
        self.assertEqual(res["diagnostics"]["failed"], 0)


class RegresionExtrapolacionTest(unittest.TestCase):
    """
    Regresión de la discrepancia de la app v1.

    La v1 extrapolaba **plano** la curva de descuento: para un plazo menor al
    primer nodo (92 días) usaba la tasa de 92 días tal cual, en vez de
    prolongar la pendiente de los dos primeros nodos como hace la planilla.
    Los tres contratos de la demo vencen antes de 92 días, así que ninguno
    cuadraba. La diferencia es de cientos de pesos por contrato: pequeña en
    términos relativos, pero suficiente para que la conciliación con la
    contraparte no cierre.
    """

    def test_con_extrapolacion_plana_no_cuadra_con_la_planilla(self):
        """Con 'Plana' ningún contrato reproduce el MtM de la planilla."""
        market = mercado_cordada()
        plana = config_cordada(extrap_method="Plana")
        for folio, esperado in PLANILLA.items():
            with self.subTest(folio=folio):
                r = price_contract(contrato(folio), market, plana)
                self.assertNotAlmostEqual(r["mtm"], esperado["mtm"], places=2)

    def test_la_diferencia_es_del_orden_de_cientos_de_pesos(self):
        """
        Magnitud del error de la v1, contrato por contrato: entre 100 y 1.000
        pesos. Si algún día la extrapolación plana coincidiera, o la diferencia
        se disparara, este test lo señala.
        """
        market = mercado_cordada()
        plana = config_cordada(extrap_method="Plana")
        for folio, esperado in PLANILLA.items():
            with self.subTest(folio=folio):
                r = price_contract(contrato(folio), market, plana)
                diferencia = abs(r["mtm"] - esperado["mtm"])
                self.assertGreater(diferencia, 100.0)
                self.assertLess(diferencia, 1_000.0)

    def test_con_extrapolacion_plana_la_tasa_es_la_del_primer_nodo(self):
        """La causa raíz: los tres plazos toman la tasa de 92 días (3.48231 %)."""
        market = mercado_cordada()
        plana = config_cordada(extrap_method="Plana")
        for folio in PLANILLA:
            with self.subTest(folio=folio):
                r = price_contract(contrato(folio), market, plana)
                self.assertAlmostEqual(r["disc_rate"], 3.48231, places=6)

    def test_la_extrapolacion_lineal_prolonga_la_pendiente(self):
        """
        Con 'Lineal' la tasa a 43 días se obtiene de la recta que pasa por los
        nodos de 92 y 183 días:
            r(43) = 3.48231 + (3.61177 − 3.48231)/(183 − 92)·(43 − 92)
                  = 3.4126007692...
        """
        pendiente = (3.61177 - 3.48231) / (183 - 92)
        esperado = 3.48231 + pendiente * (43 - 92)
        r = price_contract(contrato("118039"), mercado_cordada(), config_cordada())
        self.assertAlmostEqual(r["disc_rate"], esperado, places=6)
        self.assertAlmostEqual(esperado, PLANILLA["118039"]["disc_rate"], places=9)


class SignosYCasosBordeTest(unittest.TestCase):
    """Simetría de signo y validaciones de entrada."""

    def setUp(self):
        self.market = mercado_cordada()
        self.config = config_cordada()

    def test_el_signo_del_contrato(self):
        """ε = +1 para Venta y −1 para Compra."""
        self.assertEqual(contrato("756929", side="Venta").sign, 1)
        self.assertEqual(contrato("756929", side="Compra").sign, -1)

    def test_compra_y_venta_identicas_tienen_mtm_opuesto(self):
        """Una compra y una venta espejo suman exactamente cero."""
        venta = price_contract(contrato("118039", "Venta"), self.market, self.config)
        compra = price_contract(contrato("118039", "Compra"), self.market, self.config)
        self.assertAlmostEqual(venta["mtm"], -compra["mtm"], places=6)
        self.assertEqual(venta["mtm"] + compra["mtm"], 0.0)
        self.assertEqual(venta["spot_component"] + compra["spot_component"], 0.0)
        self.assertEqual(venta["fwd_points"] + compra["fwd_points"], 0.0)

    def test_una_cartera_espejo_tiene_mtm_total_cero(self):
        """A nivel de cartera la compensación también debe ser exacta."""
        res = price_portfolio(
            [contrato("118039", "Venta"), contrato("118039", "Compra")],
            self.market, self.config,
        )
        self.assertEqual(res["totals"]["total_mtm"], 0.0)
        self.assertEqual(res["totals"]["total_delta"], 0.0)

    def test_precio_pactado_igual_al_forward_de_mercado_da_mtm_cero(self):
        """Si K = F el contrato está en el dinero: MtM y puntos forward nulos."""
        market = mercado_cordada()
        fwd = market.curves["FWDUSDCLP"]
        curva = Curve(fwd.name, list(fwd.xs), list(fwd.ys),
                      interp="Lineal", extrap="Lineal")
        f_mercado = curva.value(43)

        c = Contract(notional=2_000_000, fwd_price=f_mercado,
                     maturity_date=date(2026, 7, 13), side="Venta",
                     spot_inicio=894.25, folio="ATM")
        r = price_contract(c, market, self.config)
        self.assertAlmostEqual(r["fwd_mkt"], f_mercado, places=6)
        self.assertEqual(r["mtm"], 0.0)
        self.assertIsNone(r["error"])

    def test_contrato_vencido_queda_con_error(self):
        """Un vencimiento anterior a la fecha de valorización no se valoriza."""
        c = Contract(notional=1_000_000, fwd_price=890.0,
                     maturity_date=date(2026, 5, 30), side="Venta",
                     spot_inicio=890.0, folio="VENCIDO")
        r = price_contract(c, self.market, self.config)
        self.assertIsNotNone(r["error"])
        self.assertIsNone(r["mtm"])
        self.assertIn("vencido", " ".join(r["flags"]).lower())

    def test_el_contrato_vencido_se_excluye_de_los_totales(self):
        """El total de la cartera sólo suma las líneas válidas."""
        vencido = Contract(notional=1_000_000, fwd_price=890.0,
                           maturity_date=date(2026, 5, 30), side="Venta",
                           spot_inicio=890.0, folio="VENCIDO")
        solos = price_portfolio([contrato("118039")], self.market, self.config)
        con_vencido = price_portfolio(
            [contrato("118039"), vencido], self.market, self.config
        )
        self.assertEqual(
            con_vencido["totals"]["total_mtm"], solos["totals"]["total_mtm"]
        )
        self.assertEqual(con_vencido["diagnostics"]["valued"], 1)
        self.assertEqual(con_vencido["diagnostics"]["failed"], 1)
        self.assertEqual(len(con_vencido["lines"]), 2)

    def test_vence_hoy_se_valoriza_pero_avisa(self):
        """Plazo cero es válido (DF = 1), pero merece una advertencia."""
        c = Contract(notional=1_000_000, fwd_price=890.0,
                     maturity_date=FECHA_VAL, side="Venta",
                     spot_inicio=890.0, folio="HOY")
        r = price_contract(c, self.market, self.config)
        self.assertIsNone(r["error"])
        self.assertEqual(r["days_to_mat"], 0)
        self.assertAlmostEqual(r["disc_factor"], 1.0, places=10)
        self.assertIn("Vence hoy", r["flags"])

    def test_nocional_cero_queda_con_error(self):
        c = Contract(notional=0, fwd_price=890.0, maturity_date=date(2026, 7, 13),
                     side="Venta", spot_inicio=890.0, folio="N0")
        r = price_contract(c, self.market, self.config)
        self.assertIsNotNone(r["error"])
        self.assertIn("Nocional no positivo", r["flags"])

    def test_nocional_negativo_queda_con_error(self):
        """El lado se expresa con `side`, no con el signo del nocional."""
        c = Contract(notional=-1_000_000, fwd_price=890.0,
                     maturity_date=date(2026, 7, 13), side="Venta",
                     spot_inicio=890.0, folio="NNEG")
        r = price_contract(c, self.market, self.config)
        self.assertIsNotNone(r["error"])
        self.assertIn("Nocional no positivo", r["flags"])

    def test_precio_no_positivo_queda_con_error(self):
        for precio in (0, -890.0):
            with self.subTest(precio=precio):
                c = Contract(notional=1_000_000, fwd_price=precio,
                             maturity_date=date(2026, 7, 13), side="Venta",
                             spot_inicio=890.0, folio="K0")
                r = price_contract(c, self.market, self.config)
                self.assertIsNotNone(r["error"])
                self.assertIn("Precio forward pactado inválido", r["flags"])

    def test_spot_de_valorizacion_no_positivo_queda_con_error(self):
        market = mercado_cordada(spot=0.0)
        r = price_contract(contrato("118039"), market, self.config)
        self.assertIsNotNone(r["error"])
        self.assertIn("Spot de valorización inválido", r["flags"])

    def test_sin_spot_de_inicio_avisa_y_no_descompone(self):
        """Sin S₀ la separación spot/puntos no es confiable: se deja en cero."""
        c = Contract(notional=1_000_000, fwd_price=890.0,
                     maturity_date=date(2026, 7, 13), side="Venta",
                     spot_inicio=0.0, folio="SINS0")
        r = price_contract(c, self.market, self.config)
        self.assertIsNone(r["error"])
        self.assertEqual(r["spot_component"], 0.0)
        self.assertEqual(r["fwd_points"], r["mtm"])
        self.assertTrue(any("tipo de cambio al inicio" in f for f in r["flags"]))

    def test_curva_faltante_produce_un_error_explicito(self):
        """Si falta la curva de descuento el contrato no se valoriza en silencio."""
        market = MarketData(
            valuation_date=FECHA_VAL, spot=SPOT_VAL,
            curves={"FWDUSDCLP": curvas_cordada()["FWDUSDCLP"]},
        )
        r = price_contract(contrato("118039"), market, self.config)
        self.assertIsNotNone(r["error"])
        self.assertIn("CLP423", r["error"])

    def test_configuracion_invalida_falla_al_validar(self):
        """PricingConfig.validate rechaza parámetros no soportados."""
        for campo, valor in [
            ("day_count", "ACT/366"), ("interp_method", "Spline"),
            ("extrap_method", "Cúbica"), ("business_days", "Siguiente"),
            ("compounding", "Trimestral"),
        ]:
            with self.subTest(campo=campo):
                with self.assertRaises(ValueError):
                    PricingConfig(**{campo: valor}).validate()


class AvisosDeExtrapolacionTest(unittest.TestCase):
    """Las banderas de extrapolación son la trazabilidad del resultado."""

    def test_aparece_el_aviso_de_descuento_extrapolado(self):
        """Los tres plazos (12, 37 y 43 días) están bajo el primer nodo (92)."""
        market = mercado_cordada()
        config = config_cordada()
        for folio in CONTRATOS:
            with self.subTest(folio=folio):
                r = price_contract(contrato(folio), market, config)
                avisos = [f for f in r["flags"] if "Descuento extrapolado" in f]
                self.assertEqual(len(avisos), 1)
                self.assertIn("[92, 1461]", avisos[0])

    def test_aparece_el_aviso_de_forward_extrapolado(self):
        """Un vencimiento más allá del último nodo forward (62 días) lo activa."""
        c = Contract(notional=1_000_000, fwd_price=890.0,
                     maturity_date=date(2027, 5, 31), side="Venta",
                     spot_inicio=890.0, folio="LARGO")
        r = price_contract(c, mercado_cordada(), config_cordada())
        self.assertTrue(any("Forward extrapolado" in f for f in r["flags"]))

    def test_no_hay_aviso_de_forward_cuando_el_plazo_esta_dentro_de_la_curva(self):
        r = price_contract(contrato("118039"), mercado_cordada(), config_cordada())
        self.assertFalse(any("Forward extrapolado" in f for f in r["flags"]))

    def test_los_diagnosticos_cuentan_las_lineas_extrapoladas(self):
        res = price_portfolio(
            [contrato(f) for f in CONTRATOS], mercado_cordada(), config_cordada()
        )
        self.assertEqual(res["diagnostics"]["extrapolated"], 3)
        self.assertEqual(res["diagnostics"]["with_warnings"], 3)


class GriegasTest(unittest.TestCase):
    """Sensibilidades: delta, gamma, DV01 y theta."""

    def setUp(self):
        self.market = mercado_cordada()
        self.config = config_cordada()

    def test_delta_es_menos_epsilon_por_nocional_por_factor(self):
        """
        Delta se calcula desplazando la curva de outrights 1 peso y
        revaluando; para un producto lineal el resultado exacto es −ε·N·DF.
        """
        for folio in CONTRATOS:
            for side, eps in (("Venta", 1), ("Compra", -1)):
                with self.subTest(folio=folio, side=side):
                    r = price_contract(contrato(folio, side), self.market, self.config)
                    esperado = -eps * r["notional"] * r["disc_factor"]
                    self.assertAlmostEqual(r["delta"], esperado, delta=0.01)

    def test_delta_pct_es_delta_por_un_uno_por_ciento_del_spot(self):
        """El delta porcentual escala linealmente con el tamaño del shock."""
        r = price_contract(contrato("118039"), self.market, self.config)
        self.assertAlmostEqual(r["delta_pct"], r["delta"] * SPOT_VAL * 0.01, delta=0.05)

    def test_gamma_es_exactamente_cero(self):
        """El payoff de un forward es lineal en el precio: no hay convexidad."""
        for folio in CONTRATOS:
            with self.subTest(folio=folio):
                r = price_contract(contrato(folio), self.market, self.config)
                self.assertEqual(r["gamma"], 0.0)

    def test_dv01_reduce_el_valor_absoluto_del_mtm(self):
        """
        Subir la curva de descuento 1 bp achica el factor y por lo tanto el
        valor absoluto del MtM, sea éste positivo o negativo.
        """
        for folio in CONTRATOS:
            for side in ("Venta", "Compra"):
                with self.subTest(folio=folio, side=side):
                    r = price_contract(contrato(folio, side), self.market, self.config)
                    self.assertNotEqual(r["mtm"], 0.0)
                    self.assertLess(
                        abs(r["mtm"] + r["dv01"]), abs(r["mtm"]),
                        msg="Una subida de tasas debe acercar el MtM a cero.",
                    )
                    self.assertEqual(
                        (r["dv01"] > 0), (r["mtm"] < 0),
                        msg="El DV01 debe tener el signo contrario al MtM.",
                    )

    def test_rho_es_un_alias_de_dv01(self):
        """Se mantiene por retrocompatibilidad con el reporte de la v1."""
        r = price_contract(contrato("118039"), self.market, self.config)
        self.assertEqual(r["rho"], r["dv01"])

    def test_theta_reproduce_la_revalorizacion_a_un_dia(self):
        """
        Theta es la variación del MtM por el paso de un día con las curvas
        congeladas. Se compara contra revalorizar el mismo contrato al día
        siguiente con el mismo mercado.
        """
        for folio in CONTRATOS:
            with self.subTest(folio=folio):
                hoy = price_contract(contrato(folio), self.market, self.config)
                manana = price_contract(
                    contrato(folio),
                    mercado_cordada(fecha=FECHA_VAL + timedelta(days=1)),
                    self.config,
                )
                self.assertAlmostEqual(
                    hoy["theta_1d"], manana["mtm"] - hoy["mtm"], delta=0.02
                )

    def test_theta_de_un_contrato_con_mtm_positivo(self):
        """
        El folio 118039 tiene MtM positivo (+2,59 MM). Al pasar un día el
        plazo se acorta, el factor de descuento sube hacia 1 y el MtM
        positivo se acerca a su valor no descontado: theta debe ser negativo
        y del orden de miles de pesos, no de millones.
        """
        r = price_contract(contrato("118039"), self.market, self.config)
        self.assertGreater(r["mtm"], 0.0)
        manana = price_contract(
            contrato("118039"),
            mercado_cordada(fecha=FECHA_VAL + timedelta(days=1)),
            self.config,
        )
        self.assertAlmostEqual(r["theta_1d"], manana["mtm"] - r["mtm"], delta=0.02)
        self.assertLess(r["theta_1d"], 0.0)
        self.assertLess(abs(r["theta_1d"]), 100_000.0)

    def test_sin_griegas_los_campos_quedan_en_cero(self):
        """`calc_greeks=False` debe ahorrar el cálculo, no dejar basura."""
        config = config_cordada(calc_greeks=False)
        r = price_contract(contrato("118039"), self.market, config)
        self.assertEqual(r["delta"], 0.0)
        self.assertEqual(r["dv01"], 0.0)
        self.assertEqual(r["theta_1d"], 0.0)
        self.assertIsNotNone(r["mtm"])


class CarteraTest(unittest.TestCase):
    """`price_portfolio`: totales, agrupación y diagnósticos."""

    def setUp(self):
        self.market = mercado_cordada()
        self.config = config_cordada()
        self.contratos = [contrato(f) for f in CONTRATOS]

    def test_los_totales_son_la_suma_de_las_lineas_validas(self):
        res = price_portfolio(self.contratos, self.market, self.config)
        validas = [l for l in res["lines"] if not l["error"]]
        for clave, campo in [
            ("total_mtm", "mtm"), ("total_spot", "spot_component"),
            ("total_fwdpoints", "fwd_points"), ("total_notional", "notional"),
            ("total_delta", "delta"), ("total_dv01", "dv01"),
            ("total_theta", "theta_1d"),
        ]:
            with self.subTest(total=clave):
                self.assertAlmostEqual(
                    res["totals"][clave], round(sum(l[campo] for l in validas), 2),
                    places=2,
                )

    def test_el_total_spot_mas_los_puntos_da_el_mtm_total(self):
        res = price_portfolio(self.contratos, self.market, self.config)
        t = res["totals"]
        self.assertAlmostEqual(
            t["total_spot"] + t["total_fwdpoints"], t["total_mtm"], places=2
        )

    def test_diagnosticos_cuentan_validos_fallidos_y_avisos(self):
        vencido = Contract(notional=1_000_000, fwd_price=890.0,
                           maturity_date=date(2026, 5, 1), side="Venta",
                           spot_inicio=890.0, folio="VENCIDO")
        malo = Contract(notional=-5, fwd_price=890.0,
                        maturity_date=date(2026, 7, 1), side="Venta",
                        spot_inicio=890.0, folio="MALO")
        res = price_portfolio(self.contratos + [vencido, malo], self.market, self.config)
        d = res["diagnostics"]
        self.assertEqual(d["valued"], 3)
        self.assertEqual(d["failed"], 2)
        self.assertEqual(d["with_warnings"], 3)
        self.assertEqual(d["valued"] + d["failed"], len(res["lines"]))

    def test_agrupacion_por_contraparte(self):
        """El resumen por contraparte suma nocional y MtM de cada una."""
        cs = [contrato("756929"), contrato("118039")]
        cs[0].counterparty = "BTG Pactual"
        cs[1].counterparty = "Bice"
        res = price_portfolio(cs, self.market, self.config)
        self.assertEqual(set(res["por_contraparte"]), {"BTG Pactual", "Bice"})
        self.assertEqual(res["por_contraparte"]["Bice"]["n"], 1)
        self.assertAlmostEqual(
            res["por_contraparte"]["Bice"]["mtm"],
            PLANILLA["118039"]["mtm"], places=2,
        )

    def test_la_cartera_conserva_la_configuracion_usada(self):
        """La corrida deja trazabilidad de los parámetros aplicados."""
        res = price_portfolio(self.contratos, self.market, self.config)
        self.assertEqual(res["config"]["extrap_method"], "Lineal")
        self.assertEqual(res["config"]["day_count"], "ACT/360")
        self.assertEqual(res["config"]["compounding"], "Compuesta")
        self.assertEqual(res["valuation_date"], "2026-05-31")
        self.assertEqual(res["spot"], SPOT_VAL)

    def test_cartera_vacia_no_falla(self):
        res = price_portfolio([], self.market, self.config)
        self.assertEqual(res["totals"]["total_mtm"], 0.0)
        self.assertEqual(res["diagnostics"]["valued"], 0)

    def test_con_cva_activado_el_mtm_ajustado_se_separa_del_mtm(self):
        """El CVA/DVA por contraparte modifica el MtM ajustado, no el bruto."""
        config = config_cordada(calc_cva=True, netting=True)
        res = price_portfolio(self.contratos, self.market, config)
        self.assertNotEqual(res["totals"]["total_cva"], 0.0)
        self.assertNotEqual(
            res["totals"]["total_mtm_ajustado"], res["totals"]["total_mtm"]
        )
        for linea in res["lines"]:
            with self.subTest(folio=linea["folio"]):
                self.assertAlmostEqual(
                    linea["mtm_ajustado"],
                    linea["mtm"] - linea["cva"] + linea["dva"],
                    places=2,
                )


class MatrizDeSensibilidadTest(unittest.TestCase):
    """`sensitivity_matrix`: escenarios de spot × curva."""

    def setUp(self):
        self.market = mercado_cordada()
        self.config = config_cordada()
        self.contratos = [contrato(f) for f in CONTRATOS]  # todos Venta

    def test_tamano_de_la_matriz(self):
        """n_points × n_points celdas, con los ejes en porcentaje."""
        for n in (3, 5, 7):
            with self.subTest(n=n):
                m = sensitivity_matrix(
                    self.contratos, self.market, self.config, shock_max=5.0, n_points=n
                )
                self.assertEqual(len(m["matrix"]), n)
                self.assertEqual(len(m["spot_shifts"]), n)
                self.assertEqual(len(m["curve_shifts"]), n)
                for fila in m["matrix"]:
                    self.assertEqual(len(fila["cells"]), n)

    def test_un_numero_par_de_puntos_se_corrige_a_cinco(self):
        """Sin celda central la matriz no tendría escenario base."""
        m = sensitivity_matrix(self.contratos, self.market, self.config, n_points=4)
        self.assertEqual(len(m["matrix"]), 5)

    def test_la_celda_central_coincide_con_el_mtm_base(self):
        """El escenario (0 %, 0 %) tiene que ser la valorización sin shock."""
        base = price_portfolio(self.contratos, self.market, self.config)
        m = sensitivity_matrix(
            self.contratos, self.market, self.config, shock_max=5.0, n_points=5
        )
        centro = m["matrix"][2]["cells"][2]
        self.assertEqual(m["matrix"][2]["spot_pct"], 0)
        self.assertEqual(centro["curve_pct"], 0)
        self.assertEqual(centro["mtm"], base["totals"]["total_mtm"])
        self.assertEqual(m["base_mtm"], base["totals"]["total_mtm"])

    def test_la_matriz_es_monotona_en_el_eje_de_spot(self):
        """
        Con la cartera completa del lado Venta, un spot más alto empeora el
        MtM. Las filas vienen ordenadas de mayor a menor spot, así que el MtM
        debe crecer al bajar por la matriz, en cada columna de curva.
        """
        m = sensitivity_matrix(
            self.contratos, self.market, self.config, shock_max=5.0, n_points=5
        )
        self.assertEqual(m["spot_shifts"], [5, 2.5, 0, -2.5, -5])
        for col in range(5):
            columna = [fila["cells"][col]["mtm"] for fila in m["matrix"]]
            with self.subTest(columna=col):
                self.assertEqual(
                    columna, sorted(columna),
                    msg="Para una cartera toda vendedora el MtM debe subir al bajar el spot.",
                )

    def test_min_y_max_acotan_todas_las_celdas(self):
        m = sensitivity_matrix(
            self.contratos, self.market, self.config, shock_max=5.0, n_points=5
        )
        celdas = [c["mtm"] for fila in m["matrix"] for c in fila["cells"]]
        self.assertEqual(m["min_mtm"], min(celdas))
        self.assertEqual(m["max_mtm"], max(celdas))

    def test_la_aproximacion_de_primer_orden_es_consistente_en_el_centro(self):
        """Sin revaluación completa, la celda central sigue siendo el base."""
        m = sensitivity_matrix(
            self.contratos, self.market, self.config,
            shock_max=5.0, n_points=5, full_revaluation=False,
        )
        self.assertFalse(m["full_revaluation"])
        self.assertEqual(m["matrix"][2]["cells"][2]["mtm"], m["base_mtm"])


class ConvencionesAlternativasTest(unittest.TestCase):
    """El resultado depende de las convenciones: aquí se verifica que importen."""

    def setUp(self):
        self.market = mercado_cordada()

    def test_cambiar_el_conteo_de_dias_cambia_el_factor(self):
        """ACT/365 descuenta menos que ACT/360 para el mismo plazo."""
        act360 = price_contract(contrato("118039"), self.market, config_cordada())
        act365 = price_contract(
            contrato("118039"), self.market, config_cordada(day_count="ACT/365")
        )
        self.assertGreater(act365["disc_factor"], act360["disc_factor"])
        self.assertNotEqual(act365["mtm"], act360["mtm"])

    def test_cambiar_la_capitalizacion_cambia_el_factor(self):
        factores = {}
        for comp in ("Compuesta", "Simple", "Continua"):
            r = price_contract(
                contrato("118039"), self.market, config_cordada(compounding=comp)
            )
            factores[comp] = r["disc_factor"]
        self.assertEqual(len(set(factores.values())), 3)

    def test_el_ajuste_de_dias_habiles_mueve_el_vencimiento(self):
        """
        Un vencimiento el 18-09-2026 (feriado) se corre al 21-09 con
        ModifiedFollowing y queda intacto con 'Exacto'.
        """
        c = Contract(notional=1_000_000, fwd_price=890.0,
                     maturity_date=date(2026, 9, 18), side="Venta",
                     spot_inicio=890.0, folio="FERIADO")
        exacto = price_contract(c, self.market, config_cordada())
        ajustado = price_contract(
            c, self.market, config_cordada(business_days="ModifiedFollowing")
        )
        self.assertFalse(exacto["maturity_adjusted"])
        self.assertEqual(exacto["maturity_date"], "2026-09-18")
        self.assertTrue(ajustado["maturity_adjusted"])
        self.assertEqual(ajustado["maturity_date"], "2026-09-21")
        self.assertEqual(ajustado["days_to_mat"], exacto["days_to_mat"] + 3)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
