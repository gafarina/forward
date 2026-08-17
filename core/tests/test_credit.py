"""
Tests del ajuste por riesgo de crédito (`core.credit`).

El motor v1 calculaba `cva = mtm * spread * t` cuando el MtM era positivo. Eso
tiene tres consecuencias que estos tests fijan:

* un forward con MtM cero hoy daba CVA cero, cuando su exposición futura
  esperada es estrictamente positiva;
* no había severidad ni supervivencia acumulada;
* no había conjunto de neteo: el spread se aplicaba operación por operación.
"""

import math
import unittest

from core.credit import (
    DEFAULT_CREDIT,
    CreditProfile,
    cva_dva_netting_set,
    expected_exposure,
)


def _trade(key, sign, strike, notional, t_years, forward=900.0, df=0.95):
    """Operación de prueba con forward y factor de descuento constantes."""
    return {
        "sign": sign,
        "strike": strike,
        "notional": notional,
        "t_years": t_years,
        "forward_fn": lambda _t, f=forward: f,
        "discount_fn": lambda _t, d=df: d,
        "key": key,
    }


class PerfilDeCreditoTest(unittest.TestCase):
    """Intensidad de default y supervivencia."""

    def test_hazard_es_spread_sobre_lgd(self):
        """h = s / (1 - R). Con 200 bp y R = 0.4: 0.02/0.6 = 0.0333."""
        perfil = CreditProfile(spread_bp=200.0, recovery=0.40)
        self.assertAlmostEqual(perfil.lgd, 0.60, places=12)
        self.assertAlmostEqual(perfil.hazard, 0.02 / 0.60, places=12)
        self.assertAlmostEqual(perfil.hazard, 0.0333333333, places=9)

    def test_hazard_propio_usa_el_spread_propio(self):
        """El DVA se descuenta con la curva de crédito propia, no con la ajena."""
        perfil = CreditProfile(spread_bp=200.0, own_spread_bp=60.0, own_recovery=0.40)
        self.assertAlmostEqual(perfil.own_hazard, 0.006 / 0.60, places=12)
        self.assertLess(perfil.own_hazard, perfil.hazard)

    def test_supervivencia_es_exponencial_del_hazard(self):
        """S(t) = exp(-h·t) para varios plazos."""
        perfil = CreditProfile(spread_bp=200.0, recovery=0.40)
        for t in (0.25, 1.0, 2.5, 5.0):
            with self.subTest(t=t):
                self.assertAlmostEqual(
                    perfil.survival(t), math.exp(-perfil.hazard * t), places=12
                )

    def test_supervivencia_es_decreciente_y_esta_en_cero_uno(self):
        """S(0) = 1, S es estrictamente decreciente y nunca sale de (0, 1]."""
        perfil = CreditProfile(spread_bp=150.0)
        self.assertAlmostEqual(perfil.survival(0.0), 1.0, places=12)
        anterior = 1.0
        for t in (0.5, 1.0, 2.0, 5.0, 10.0, 30.0):
            s = perfil.survival(t)
            with self.subTest(t=t):
                self.assertGreater(s, 0.0)
                self.assertLessEqual(s, 1.0)
                self.assertLess(s, anterior)
            anterior = s

    def test_spread_cero_implica_supervivencia_uno(self):
        perfil = CreditProfile(spread_bp=0.0)
        self.assertEqual(perfil.hazard, 0.0)
        self.assertAlmostEqual(perfil.survival(10.0), 1.0, places=12)

    def test_recuperacion_total_no_divide_por_cero(self):
        """R = 1 (LGD = 0) se acota para no reventar el hazard."""
        perfil = CreditProfile(spread_bp=100.0, recovery=1.0)
        self.assertTrue(math.isfinite(perfil.hazard))
        self.assertEqual(perfil.lgd, 0.0)

    def test_volatilidad_relativa_se_convierte_a_absoluta(self):
        """Con vol relativa, σ_abs = σ_rel · nivel forward (Bachelier)."""
        perfil = CreditProfile(fx_vol=0.12, vol_is_relative=True)
        self.assertAlmostEqual(perfil.absolute_vol(900.0), 108.0, places=12)
        absoluta = CreditProfile(fx_vol=95.0, vol_is_relative=False)
        self.assertEqual(absoluta.absolute_vol(900.0), 95.0)

    def test_perfil_por_defecto_es_razonable(self):
        self.assertEqual(DEFAULT_CREDIT.spread_bp, 100.0)
        self.assertEqual(DEFAULT_CREDIT.recovery, 0.40)


class ExposicionEsperadaTest(unittest.TestCase):
    """EPE y ENE de un forward FX bajo el modelo normal."""

    BASE = dict(sign=1, strike=910.0, notional=1_000_000.0, t_years=1.0, discount=0.95)

    def test_con_volatilidad_cero_es_el_valor_deterministico(self):
        """
        Sin incertidumbre, EPE = max(V, 0) y ENE = max(-V, 0).
        V = ε·(K − F)·N·DF = (910 − 900)·1.000.000·0.95 = 9.500.000.
        """
        epe, ene = expected_exposure(forward=900.0, vol_abs=0.0, **self.BASE)
        self.assertAlmostEqual(epe, 9_500_000.0, places=4)
        self.assertAlmostEqual(ene, 0.0, places=10)

        epe2, ene2 = expected_exposure(forward=920.0, vol_abs=0.0, **self.BASE)
        self.assertAlmostEqual(epe2, 0.0, places=10)
        self.assertAlmostEqual(ene2, 9_500_000.0, places=4)

    def test_con_valor_cero_y_volatilidad_positiva_epe_igual_ene_y_positivas(self):
        """
        Éste es exactamente el caso que el CVA del motor original daba cero:
        un forward en el dinero (K = F) tiene MtM cero hoy pero exposición
        futura esperada estrictamente positiva. Por simetría de la normal,
        EPE = ENE = v·φ(0) = v/√(2π).
        """
        vol_abs = 108.0
        epe, ene = expected_exposure(forward=910.0, vol_abs=vol_abs, **self.BASE)
        v = vol_abs * 1.0 * 1_000_000.0 * 0.95
        self.assertGreater(epe, 0.0)
        self.assertAlmostEqual(epe, ene, places=6)
        self.assertAlmostEqual(epe, v / math.sqrt(2 * math.pi), places=4)

    def test_epe_crece_con_la_volatilidad(self):
        """A mayor volatilidad, mayor exposición esperada positiva."""
        anterior = -1.0
        for vol in (0.0, 20.0, 60.0, 120.0, 200.0):
            epe, _ = expected_exposure(forward=910.0, vol_abs=vol, **self.BASE)
            with self.subTest(vol=vol):
                self.assertGreater(epe, anterior)
            anterior = epe

    def test_epe_crece_con_el_plazo(self):
        """La difusión escala con √t: a mayor plazo, mayor EPE."""
        base = dict(sign=1, strike=910.0, notional=1_000_000.0,
                    discount=0.95, forward=910.0, vol_abs=108.0)
        anterior = -1.0
        for t in (0.0, 0.25, 1.0, 4.0):
            epe, _ = expected_exposure(t_years=t, **base)
            with self.subTest(t=t):
                self.assertGreater(epe, anterior)
            anterior = epe

    def test_epe_menos_ene_es_el_valor_esperado(self):
        """Identidad E[max(V,0)] − E[max(−V,0)] = E[V] = V₀."""
        epe, ene = expected_exposure(forward=880.0, vol_abs=108.0, **self.BASE)
        valor = (910.0 - 880.0) * 1_000_000.0 * 0.95
        self.assertAlmostEqual(epe - ene, valor, places=3)

    def test_el_signo_invierte_epe_y_ene(self):
        """Una compra y una venta idénticas intercambian EPE y ENE."""
        venta = expected_exposure(forward=880.0, vol_abs=108.0, **self.BASE)
        compra_args = dict(self.BASE, sign=-1)
        compra = expected_exposure(forward=880.0, vol_abs=108.0, **compra_args)
        self.assertAlmostEqual(venta[0], compra[1], places=6)
        self.assertAlmostEqual(venta[1], compra[0], places=6)


class ConjuntoDeNeteoTest(unittest.TestCase):
    """
    CVA/DVA sobre un conjunto de neteo. Es el punto central de la mejora sobre
    el motor v1, que aplicaba el spread operación por operación.
    """

    def setUp(self):
        self.credito = CreditProfile(
            spread_bp=200.0, recovery=0.40, own_spread_bp=120.0, fx_vol=0.12
        )

    def test_conjunto_vacio_no_falla(self):
        res = cva_dva_netting_set([], self.credito)
        self.assertEqual(res["cva"], 0.0)
        self.assertEqual(res["dva"], 0.0)
        self.assertEqual(res["por_operacion"], {})

    def test_operaciones_ya_vencidas_dan_cva_cero(self):
        """Sin horizonte no hay exposición futura que ajustar."""
        res = cva_dva_netting_set([_trade("a", 1, 910.0, 1e6, 0.0)], self.credito)
        self.assertEqual(res["cva"], 0.0)
        self.assertEqual(res["dva"], 0.0)

    def test_spread_cero_da_cva_cero(self):
        """Sin probabilidad de default no hay ajuste, por grande que sea la EPE."""
        sin_riesgo = CreditProfile(spread_bp=0.0, own_spread_bp=0.0, fx_vol=0.12)
        trades = [_trade("a", 1, 910.0, 1e6, 1.0), _trade("b", -1, 890.0, 2e6, 2.0)]
        res = cva_dva_netting_set(trades, sin_riesgo, netting=True)
        self.assertEqual(res["cva"], 0.0)
        self.assertEqual(res["dva"], 0.0)

    def test_cva_es_positivo_aunque_el_valor_de_hoy_sea_cero(self):
        """
        Regresión del bug del v1: con K = F el MtM de hoy es cero y el motor
        original daba CVA cero. La exposición futura esperada no lo es.
        """
        res = cva_dva_netting_set(
            [_trade("a", 1, 900.0, 1e6, 2.0, forward=900.0)], self.credito
        )
        self.assertGreater(res["cva"], 0.0)
        self.assertGreater(res["dva"], 0.0)

    def test_el_neteo_no_da_beneficio_si_todas_van_en_el_mismo_sentido(self):
        """
        Dos ventas con el mismo precio pactado y el mismo vencimiento no se
        compensan entre sí: el CVA con neteo debe ser igual al CVA sin neteo.
        Es la cota que hay que respetar para no subestimar el ajuste.
        """
        trades = [
            _trade("a", 1, 910.0, 1_000_000.0, 1.0),
            _trade("b", 1, 910.0, 2_000_000.0, 1.0),
        ]
        con = cva_dva_netting_set(trades, self.credito, netting=True)
        sin = cva_dva_netting_set(trades, self.credito, netting=False)
        self.assertGreater(con["cva"], 0.0)
        self.assertAlmostEqual(con["cva"], sin["cva"], delta=0.02)

    def test_el_neteo_reduce_el_cva_con_operaciones_de_signo_opuesto(self):
        """
        Una compra y una venta con la misma contraparte se compensan: el CVA
        del conjunto neteado es estrictamente menor que la suma de los CVA
        individuales.
        """
        trades = [
            _trade("a", 1, 910.0, 1_000_000.0, 1.0),
            _trade("b", -1, 905.0, 600_000.0, 1.0),
        ]
        con = cva_dva_netting_set(trades, self.credito, netting=True)
        sin = cva_dva_netting_set(trades, self.credito, netting=False)
        self.assertLess(con["cva"], sin["cva"])
        self.assertLessEqual(con["dva"], sin["dva"])

    def test_operaciones_espejo_se_cancelan_por_completo(self):
        """
        Una venta y una compra idénticas dejan al conjunto sin exposición:
        con neteo el CVA es cero; sin neteo, no.
        """
        trades = [
            _trade("a", 1, 910.0, 1_000_000.0, 1.0),
            _trade("b", -1, 910.0, 1_000_000.0, 1.0),
        ]
        con = cva_dva_netting_set(trades, self.credito, netting=True)
        sin = cva_dva_netting_set(trades, self.credito, netting=False)
        self.assertAlmostEqual(con["cva"], 0.0, places=6)
        self.assertGreater(sin["cva"], 0.0)

    def test_el_neteo_nunca_aumenta_el_cva(self):
        """Cota general: CVA(neteado) <= CVA(sin neteo) en cualquier cartera."""
        carteras = [
            [_trade("a", 1, 910.0, 1e6, 1.0)],
            [_trade("a", 1, 910.0, 1e6, 1.0), _trade("b", 1, 880.0, 3e6, 2.0)],
            [_trade("a", 1, 910.0, 1e6, 1.0), _trade("b", -1, 930.0, 5e5, 0.5)],
            [_trade("a", -1, 870.0, 2e6, 3.0), _trade("b", 1, 950.0, 4e6, 1.5)],
        ]
        for i, trades in enumerate(carteras):
            with self.subTest(cartera=i):
                con = cva_dva_netting_set(trades, self.credito, netting=True)
                sin = cva_dva_netting_set(trades, self.credito, netting=False)
                self.assertLessEqual(con["cva"], sin["cva"] + 1e-6)

    def test_la_suma_de_las_asignaciones_reproduce_el_cva_del_conjunto(self):
        """El CVA del conjunto se reparte íntegro entre las operaciones."""
        trades = [
            _trade("a", 1, 910.0, 1_000_000.0, 1.0),
            _trade("b", -1, 905.0, 600_000.0, 2.0),
            _trade("c", 1, 880.0, 2_000_000.0, 1.5),
        ]
        for netting in (True, False):
            with self.subTest(netting=netting):
                res = cva_dva_netting_set(trades, self.credito, netting=netting)
                self.assertEqual(set(res["por_operacion"]), {"a", "b", "c"})
                suma_cva = sum(v["cva"] for v in res["por_operacion"].values())
                suma_dva = sum(v["dva"] for v in res["por_operacion"].values())
                self.assertAlmostEqual(suma_cva, res["cva"], delta=0.05)
                self.assertAlmostEqual(suma_dva, res["dva"], delta=0.05)

    def test_el_cva_crece_con_el_spread(self):
        """A peor calidad crediticia de la contraparte, mayor ajuste."""
        trades = [_trade("a", 1, 910.0, 1e6, 2.0)]
        anterior = -1.0
        for bp in (0.0, 50.0, 150.0, 400.0):
            res = cva_dva_netting_set(
                trades, CreditProfile(spread_bp=bp, recovery=0.40, fx_vol=0.12)
            )
            with self.subTest(bp=bp):
                self.assertGreater(res["cva"], anterior)
            anterior = res["cva"]

    def test_el_perfil_de_exposicion_es_coherente(self):
        """El perfil devuelto tiene un paso por mes y supervivencia decreciente."""
        res = cva_dva_netting_set([_trade("a", 1, 910.0, 1e6, 2.0)], self.credito)
        perfil = res["perfil"]
        self.assertEqual(len(perfil), 24)  # steps_per_year = 12, horizonte 2 años
        self.assertAlmostEqual(perfil[-1]["t"], 2.0, places=6)
        supervivencias = [p["supervivencia"] for p in perfil]
        self.assertEqual(supervivencias, sorted(supervivencias, reverse=True))
        self.assertTrue(all(p["epe"] >= 0 for p in perfil))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
