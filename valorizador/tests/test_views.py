"""
Tests de las vistas: seguridad, aislamiento entre usuarios y flujo completo.

El foco es la vulnerabilidad de la v1: `contratos_list`, `curvas_list` y
`valorizaciones_list` no filtraban por dueño, y los detalles se resolvían con
`get_object_or_404(Modelo, pk=pk)` sin comprobar propiedad. Con dos clientes
en la misma instancia, cada uno veía —y podía borrar— la cartera del otro.

Los tests que renderizan una plantilla se saltan solos si la plantilla todavía
no existe en el árbol, porque las plantillas las escribe otro agente en
paralelo; los tests de seguridad (302, 404, 405) no dependen de ellas.
"""

import json
from datetime import date
from decimal import Decimal
from unittest import skipIf

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.template import TemplateDoesNotExist
from django.template.loader import get_template
from django.test import TestCase, override_settings
from django.urls import reverse

from valorizador.forms import ArchivoUploadForm
from valorizador.models import (
    Cartera,
    ConjuntoCurvas,
    Contraparte,
    ContratoForward,
    LineaValorizacion,
    PuntoCurva,
    ValorizacionGuardada,
)

User = get_user_model()
CLAVE = "clave-de-prueba-larga"

FWD_NODOS = [(1, 892.21), (2, 892.205), (8, 892.19), (15, 892.13),
             (22, 892.105), (31, 892.06), (62, 892.03)]
DESC_NODOS = [(92, 3.48231), (183, 3.61177), (271, 3.70649), (365, 3.78017),
              (731, 3.98414), (1096, 4.24534), (1461, 4.42915)]


def falta_plantilla(*nombres) -> bool:
    """True si alguna plantilla todavía no está en el árbol del proyecto."""
    for nombre in nombres:
        try:
            get_template(nombre)
        except TemplateDoesNotExist:
            return True
    return False


MOTIVO_PLANTILLA = "La plantilla todavía no existe en el proyecto (la escribe otro agente)."


def crear_usuario(username):
    return User.objects.create_user(username=username, password=CLAVE)


def crear_datos(user, sufijo=""):
    """Crea una cartera, un contrato, un conjunto de curvas y una valorización."""
    cartera = Cartera.objects.create(nombre=f"Cartera {sufijo}", created_by=user)
    contrato = ContratoForward.objects.create(
        cartera=cartera, counterparty=f"Banco {sufijo}", folio=f"F{sufijo}",
        side="Venta", notional=Decimal("2000000"), fwd_price=Decimal("893.3500"),
        spot_inicio=Decimal("894.2500"), maturity_date=date(2026, 7, 13),
        created_by=user,
    )
    conjunto = ConjuntoCurvas.objects.create(
        label=f"Curvas {sufijo}", valuation_date=date(2026, 5, 31),
        spot_usdclp=Decimal("892.8900"), created_by=user,
    )
    PuntoCurva.objects.bulk_create(
        [PuntoCurva(conjunto=conjunto, nombre="FWDUSDCLP", tenor_days=d,
                    value=Decimal(str(v))) for d, v in FWD_NODOS]
        + [PuntoCurva(conjunto=conjunto, nombre="CLP423", tenor_days=d,
                      value=Decimal(str(v))) for d, v in DESC_NODOS]
    )
    val = ValorizacionGuardada.objects.create(
        valuation_date=date(2026, 5, 31), label=f"Val {sufijo}",
        curve_set=conjunto, spot=Decimal("892.8900"),
        total_mtm=Decimal("-6850442.17"), created_by=user,
    )
    LineaValorizacion.objects.create(
        valorizacion=val, contrato=contrato, folio=contrato.folio,
        counterparty=contrato.counterparty, side="Venta",
        maturity_date=date(2026, 7, 13), notional=Decimal("2000000"),
        fwd_contract=Decimal("893.3500"), mtm=Decimal("2592812.56"),
    )
    return {"cartera": cartera, "contrato": contrato, "conjunto": conjunto,
            "valorizacion": val}


class LoginRequeridoTest(TestCase):
    """Ninguna vista de la aplicación puede responder a un anónimo."""

    @classmethod
    def setUpTestData(cls):
        cls.user = crear_usuario("ana")
        cls.datos = crear_datos(cls.user, "A")

    def urls(self):
        d = self.datos
        return [
            reverse("dashboard"),
            reverse("curvas_list"),
            reverse("curvas_create"),
            reverse("curvas_detail", args=[d["conjunto"].pk]),
            reverse("curvas_edit", args=[d["conjunto"].pk]),
            reverse("curvas_delete", args=[d["conjunto"].pk]),
            reverse("curvas_duplicate", args=[d["conjunto"].pk]),
            reverse("curvas_activate", args=[d["conjunto"].pk]),
            reverse("curvas_import_points"),
            reverse("carteras_list"),
            reverse("cartera_create"),
            reverse("cartera_delete", args=[d["cartera"].pk]),
            reverse("contrapartes_list"),
            reverse("contratos_list"),
            reverse("contrato_create"),
            reverse("contrato_edit", args=[d["contrato"].pk]),
            reverse("contrato_delete", args=[d["contrato"].pk]),
            reverse("contratos_import"),
            reverse("contratos_export_csv"),
            reverse("valorizar"),
            reverse("valorizar_guardar"),
            reverse("valorizaciones_list"),
            reverse("valorizacion_detail", args=[d["valorizacion"].pk]),
            reverse("valorizacion_export_csv", args=[d["valorizacion"].pk]),
            reverse("valorizacion_export_xlsx", args=[d["valorizacion"].pk]),
            reverse("valorizacion_delete", args=[d["valorizacion"].pk]),
            reverse("upload"),
            reverse("api_chat"),
            reverse("accounts:profile"),
        ]

    def test_un_anonimo_es_redirigido_al_login_en_todas_las_vistas(self):
        """Recorre el mapa de URLs completo: ninguna puede devolver 200."""
        for url in self.urls():
            for metodo in ("get", "post"):
                with self.subTest(url=url, metodo=metodo):
                    resp = getattr(self.client, metodo)(url)
                    self.assertEqual(
                        resp.status_code, 302,
                        msg=f"{metodo.upper()} {url} debería redirigir a login.",
                    )
                    self.assertIn("/accounts/login/", resp["Location"])


class AislamientoEntreUsuariosTest(TestCase):
    """
    Vulnerabilidad de la v1: los listados y detalles no filtraban por dueño.
    Ana no puede ver, editar ni borrar nada de Beto.
    """

    @classmethod
    def setUpTestData(cls):
        cls.ana = crear_usuario("ana")
        cls.beto = crear_usuario("beto")
        cls.de_ana = crear_datos(cls.ana, "A")
        cls.de_beto = crear_datos(cls.beto, "B")

    def setUp(self):
        self.client.login(username="ana", password=CLAVE)

    def test_detalle_de_objetos_ajenos_devuelve_404(self):
        """Un GET a un objeto de otro usuario es indistinguible de inexistente."""
        b = self.de_beto
        urls = [
            reverse("curvas_detail", args=[b["conjunto"].pk]),
            reverse("curvas_edit", args=[b["conjunto"].pk]),
            reverse("contrato_edit", args=[b["contrato"].pk]),
            reverse("valorizacion_detail", args=[b["valorizacion"].pk]),
            reverse("valorizacion_export_csv", args=[b["valorizacion"].pk]),
            reverse("valorizacion_export_xlsx", args=[b["valorizacion"].pk]),
        ]
        for url in urls:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 404)

    def test_borrar_objetos_ajenos_devuelve_404(self):
        """El POST destructivo tampoco puede alcanzar objetos de otro usuario."""
        b = self.de_beto
        urls = [
            reverse("curvas_delete", args=[b["conjunto"].pk]),
            reverse("curvas_duplicate", args=[b["conjunto"].pk]),
            reverse("curvas_activate", args=[b["conjunto"].pk]),
            reverse("cartera_delete", args=[b["cartera"].pk]),
            reverse("contrato_delete", args=[b["contrato"].pk]),
            reverse("valorizacion_delete", args=[b["valorizacion"].pk]),
        ]
        for url in urls:
            with self.subTest(url=url):
                self.assertEqual(self.client.post(url).status_code, 404)

    def test_los_objetos_ajenos_siguen_existiendo_tras_el_intento(self):
        """El 404 tiene que ser antes de tocar la base, no después."""
        b = self.de_beto
        self.client.post(reverse("contrato_delete", args=[b["contrato"].pk]))
        self.client.post(reverse("curvas_delete", args=[b["conjunto"].pk]))
        self.client.post(reverse("valorizacion_delete", args=[b["valorizacion"].pk]))
        self.assertTrue(ContratoForward.objects.filter(pk=b["contrato"].pk).exists())
        self.assertTrue(ConjuntoCurvas.objects.filter(pk=b["conjunto"].pk).exists())
        self.assertTrue(
            ValorizacionGuardada.objects.filter(pk=b["valorizacion"].pk).exists()
        )

    @skipIf(falta_plantilla("valorizador/contratos_list.html",
                            "valorizador/curvas_list.html",
                            "valorizador/valorizaciones_list.html",
                            "valorizador/carteras_list.html"), MOTIVO_PLANTILLA)
    def test_los_listados_no_contienen_objetos_de_otro_usuario(self):
        """Se comprueba sobre el contexto, no sobre el HTML renderizado."""
        casos = [
            ("contratos_list", "contratos", self.de_ana["contrato"], self.de_beto["contrato"]),
            ("curvas_list", "conjuntos", self.de_ana["conjunto"], self.de_beto["conjunto"]),
            ("valorizaciones_list", "valorizaciones",
             self.de_ana["valorizacion"], self.de_beto["valorizacion"]),
            ("carteras_list", "carteras", self.de_ana["cartera"], self.de_beto["cartera"]),
        ]
        for nombre, clave, mio, ajeno in casos:
            with self.subTest(vista=nombre):
                resp = self.client.get(reverse(nombre))
                self.assertEqual(resp.status_code, 200)
                objetos = list(resp.context[clave])
                self.assertIn(mio, objetos)
                self.assertNotIn(ajeno, objetos)

    @skipIf(falta_plantilla("valorizador/dashboard.html"), MOTIVO_PLANTILLA)
    def test_el_panel_solo_cuenta_los_datos_propios(self):
        resp = self.client.get(reverse("dashboard"))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context["num_contratos"], 1)
        self.assertEqual(resp.context["num_conjuntos"], 1)
        self.assertEqual(resp.context["num_valorizaciones"], 1)

    def test_la_exportacion_csv_solo_trae_los_contratos_propios(self):
        resp = self.client.get(reverse("contratos_export_csv"))
        self.assertEqual(resp.status_code, 200)
        contenido = resp.content.decode("utf-8")
        self.assertIn(self.de_ana["contrato"].folio, contenido)
        self.assertNotIn(self.de_beto["contrato"].folio, contenido)

    @skipIf(falta_plantilla("valorizador/valorizar.html"), MOTIVO_PLANTILLA)
    def test_el_selector_de_conjuntos_solo_ofrece_los_propios(self):
        resp = self.client.get(reverse("valorizar"))
        self.assertEqual(resp.status_code, 200)
        conjuntos = list(resp.context["form"].fields["conjunto"].queryset)
        self.assertIn(self.de_ana["conjunto"], conjuntos)
        self.assertNotIn(self.de_beto["conjunto"], conjuntos)

    def test_no_se_puede_valorizar_con_el_conjunto_de_otro_usuario(self):
        """El formulario acota el queryset: el pk ajeno no valida."""
        from valorizador.forms import ValorizarForm

        form = ValorizarForm(
            {"conjunto": self.de_beto["conjunto"].pk,
             "fecha_valoracion": "2026-05-31", "moneda": "USD",
             "day_count": "ACT/360", "interp_method": "Lineal",
             "extrap_method": "Lineal", "business_days": "Exacto",
             "calendar": "CL", "compounding": "Compuesta", "shock_max": "5"},
            user=self.ana,
        )
        self.assertFalse(form.is_valid())
        self.assertIn("conjunto", form.errors)


class MetodoHttpTest(TestCase):
    """Las vistas destructivas sólo aceptan POST."""

    @classmethod
    def setUpTestData(cls):
        cls.user = crear_usuario("ana")
        cls.datos = crear_datos(cls.user, "A")

    def setUp(self):
        self.client.login(username="ana", password=CLAVE)

    def test_las_vistas_destructivas_rechazan_get_con_405(self):
        d = self.datos
        urls = [
            reverse("curvas_delete", args=[d["conjunto"].pk]),
            reverse("curvas_duplicate", args=[d["conjunto"].pk]),
            reverse("curvas_activate", args=[d["conjunto"].pk]),
            reverse("curvas_import_points"),
            reverse("cartera_delete", args=[d["cartera"].pk]),
            reverse("contrato_delete", args=[d["contrato"].pk]),
            reverse("valorizar_guardar"),
            reverse("valorizacion_delete", args=[d["valorizacion"].pk]),
            reverse("api_chat"),
        ]
        for url in urls:
            with self.subTest(url=url):
                self.assertEqual(
                    self.client.get(url).status_code, 405,
                    msg=f"GET {url} no debería estar permitido.",
                )

    def test_un_get_no_borra_nada(self):
        """El 405 tiene que ocurrir antes de cualquier escritura."""
        d = self.datos
        self.client.get(reverse("contrato_delete", args=[d["contrato"].pk]))
        self.assertTrue(ContratoForward.objects.filter(pk=d["contrato"].pk).exists())

    def test_el_borrado_propio_por_post_si_funciona(self):
        d = self.datos
        resp = self.client.post(reverse("contrato_delete", args=[d["contrato"].pk]))
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(ContratoForward.objects.filter(pk=d["contrato"].pk).exists())


@override_settings(ASSISTANT_ENABLED=False, GEMINI_API_KEY=None)
class AsistenteTest(TestCase):
    """
    El endpoint del asistente. En la v1 estaba con `@csrf_exempt` y **sin**
    `login_required`: cualquiera en internet podía consumir la clave de Gemini
    del proyecto.
    """

    @classmethod
    def setUpTestData(cls):
        cls.user = crear_usuario("ana")

    def setUp(self):
        cache.clear()

    def test_sin_sesion_redirige_al_login(self):
        resp = self.client.post(
            reverse("api_chat"), data=json.dumps({"message": "hola"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/accounts/login/", resp["Location"])

    def test_con_sesion_pero_sin_clave_configurada_devuelve_503(self):
        """Sin GEMINI_API_KEY el asistente se desactiva solo, no revienta."""
        self.client.login(username="ana", password=CLAVE)
        resp = self.client.post(
            reverse("api_chat"), data=json.dumps({"message": "hola"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 503)
        self.assertIn("error", resp.json())

    def test_get_no_esta_permitido(self):
        self.client.login(username="ana", password=CLAVE)
        self.assertEqual(self.client.get(reverse("api_chat")).status_code, 405)

    @override_settings(ASSISTANT_ENABLED=True)
    def test_mensaje_vacio_se_rechaza_con_400(self):
        self.client.login(username="ana", password=CLAVE)
        resp = self.client.post(
            reverse("api_chat"), data=json.dumps({"message": "   "}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)

    @override_settings(ASSISTANT_ENABLED=True)
    def test_cuerpo_no_json_se_rechaza_con_400(self):
        self.client.login(username="ana", password=CLAVE)
        resp = self.client.post(
            reverse("api_chat"), data="{no es json", content_type="application/json"
        )
        self.assertEqual(resp.status_code, 400)

    @override_settings(ASSISTANT_ENABLED=True)
    def test_hay_limite_de_frecuencia_por_usuario(self):
        """Tras 30 consultas en la ventana, el endpoint responde 429."""
        self.client.login(username="ana", password=CLAVE)
        cache.set(f"chat_rate_{self.user.pk}", 30, 3600)
        resp = self.client.post(
            reverse("api_chat"), data=json.dumps({"message": "hola"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 429)


class CargaDeArchivosTest(TestCase):
    """`ArchivoUploadForm`: extensión y tamaño."""

    def test_rechaza_extension_no_permitida(self):
        archivo = SimpleUploadedFile(
            "malicioso.exe", b"MZ", content_type="application/octet-stream"
        )
        form = ArchivoUploadForm({}, {"archivo": archivo})
        self.assertFalse(form.is_valid())
        self.assertIn("Extensión no soportada", " ".join(form.errors["archivo"]))

    @override_settings(MAX_UPLOAD_SIZE=1024)
    def test_rechaza_archivo_demasiado_grande(self):
        archivo = SimpleUploadedFile(
            "grande.csv", b"x" * 2048, content_type="text/csv"
        )
        form = ArchivoUploadForm({}, {"archivo": archivo})
        self.assertFalse(form.is_valid())
        self.assertIn("límite", " ".join(form.errors["archivo"]))

    def test_acepta_las_extensiones_soportadas(self):
        for nombre in ("curva.csv", "curva.txt", "libro.xlsx", "libro.xlsm", "libro.xls"):
            with self.subTest(nombre=nombre):
                archivo = SimpleUploadedFile(nombre, b"a;b\n1;2\n")
                form = ArchivoUploadForm({}, {"archivo": archivo})
                self.assertTrue(form.is_valid(), msg=form.errors.as_json())

    def test_la_vista_de_importacion_rechaza_el_archivo_invalido(self):
        crear_usuario("ana")
        self.client.login(username="ana", password=CLAVE)
        archivo = SimpleUploadedFile("x.exe", b"MZ")
        resp = self.client.post(reverse("curvas_import_points"), {"archivo": archivo})
        self.assertEqual(resp.status_code, 400)
        self.assertIn("Extensión no soportada", resp.json()["error"])


@skipIf(
    falta_plantilla(
        "valorizador/cartera_form.html", "valorizador/contrato_form.html",
        "valorizador/curvas_form.html", "valorizador/valorizar.html",
        "valorizador/valorizacion_detail.html", "accounts/login.html",
    ),
    MOTIVO_PLANTILLA,
)
class FlujoCompletoTest(TestCase):
    """
    Recorrido de punta a punta: iniciar sesión, crear cartera, contrato y
    curvas, valorizar, guardar, ver el detalle y exportar el CSV.
    """

    @classmethod
    def setUpTestData(cls):
        cls.user = crear_usuario("ana")

    def test_flujo_completo(self):
        # 1. Login.
        resp = self.client.post(
            reverse("accounts:login"), {"username": "ana", "password": CLAVE}
        )
        self.assertEqual(resp.status_code, 302)

        # 2. Cartera.
        resp = self.client.post(
            reverse("cartera_create"),
            {"nombre": "Cordada", "descripcion": "Demo"},
        )
        self.assertEqual(resp.status_code, 302)
        cartera = Cartera.objects.get(created_by=self.user, nombre="Cordada")

        # 3. Contrato.
        resp = self.client.post(reverse("contrato_create"), {
            "cartera": cartera.pk, "counterparty": "Bice", "folio": "118039",
            "side": "Venta", "modality": "Compensacion",
            "base_ccy": "USD", "quote_ccy": "CLP",
            "notional": "2000000", "fwd_price": "893.35",
            "spot_inicio": "894.25", "maturity_date": "2026-07-13",
            "fwd_curve": "FWDUSDCLP", "disc_curve": "CLP423", "status": "Vigente",
        })
        self.assertEqual(resp.status_code, 302, msg=getattr(resp, "context", None))
        contrato = ContratoForward.objects.get(created_by=self.user, folio="118039")

        # 4. Conjunto de curvas.
        resp = self.client.post(reverse("curvas_create"), {
            "label": "Cordada 2026-05-31", "valuation_date": "2026-05-31",
            "spot_usdclp": "892.89", "source": "Libro Cordada",
            "fwd_points": json.dumps(
                [{"tenor_days": d, "value": v} for d, v in FWD_NODOS]),
            "desc_points": json.dumps(
                [{"tenor_days": d, "value": v} for d, v in DESC_NODOS]),
        })
        self.assertEqual(resp.status_code, 302)
        conjunto = ConjuntoCurvas.objects.get(created_by=self.user)
        self.assertEqual(conjunto.n_puntos, len(FWD_NODOS) + len(DESC_NODOS))

        # 5. Valorizar.
        resp = self.client.post(reverse("valorizar"), {
            "conjunto": conjunto.pk, "etiqueta": "Corrida de prueba",
            "fecha_valoracion": "2026-05-31", "spot_val": "892.89",
            "moneda": "USD", "day_count": "ACT/360", "interp_method": "Lineal",
            "extrap_method": "Lineal", "business_days": "Exacto",
            "calendar": "CL", "compounding": "Compuesta",
            "calc_greeks": "on", "shock_max": "5",
        })
        self.assertEqual(resp.status_code, 200)
        result = resp.context["result"]
        self.assertIsNotNone(result, msg="La valorización no produjo resultados.")
        self.assertEqual(result["diagnostics"]["valued"], 1)
        self.assertAlmostEqual(
            result["totals"]["total_mtm"], 2_592_812.56, places=2,
            msg="El MtM de la corrida debe cuadrar con la planilla Cordada.",
        )
        self.assertIsNotNone(resp.context["sensibilidad"])

        # 6. Guardar la valorización.
        resp = self.client.post(
            reverse("valorizar_guardar"), {"result_data": resp.context["result_json"]}
        )
        self.assertEqual(resp.status_code, 302)
        val = ValorizacionGuardada.objects.get(created_by=self.user)
        self.assertEqual(val.num_contracts, 1)
        self.assertAlmostEqual(float(val.total_mtm), 2_592_812.56, places=2)
        self.assertEqual(val.lineas.count(), 1)

        # 7. Detalle.
        resp = self.client.get(reverse("valorizacion_detail", args=[val.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.context["lineas"]), 1)

        # 8. Exportar CSV.
        resp = self.client.get(reverse("valorizacion_export_csv", args=[val.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertIn("text/csv", resp["Content-Type"])
        self.assertIn("attachment", resp["Content-Disposition"])
        contenido = resp.content.decode("utf-8")
        self.assertIn("118039", contenido)
        self.assertIn("Bice", contenido)
        self.assertIn("TOTAL", contenido)
        self.assertIn(str(contrato.maturity_date), contenido)

        # 9. Exportar Excel.
        resp = self.client.get(reverse("valorizacion_export_xlsx", args=[val.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertIn("spreadsheetml", resp["Content-Type"])
        self.assertTrue(
            resp.content.startswith(b"PK"), msg="Un .xlsx es un ZIP: debe partir con PK."
        )


@skipIf(falta_plantilla("valorizador/curvas_list.html"), MOTIVO_PLANTILLA)
class AccionesSobreCurvasTest(TestCase):
    """Duplicar y activar un conjunto de curvas."""

    @classmethod
    def setUpTestData(cls):
        cls.user = crear_usuario("ana")
        cls.datos = crear_datos(cls.user, "A")

    def setUp(self):
        self.client.login(username="ana", password=CLAVE)

    def test_duplicar_copia_el_conjunto_con_sus_puntos(self):
        original = self.datos["conjunto"]
        resp = self.client.post(reverse("curvas_duplicate", args=[original.pk]))
        self.assertEqual(resp.status_code, 302)
        copia = ConjuntoCurvas.objects.exclude(pk=original.pk).get(created_by=self.user)
        self.assertIn("copia", copia.label)
        self.assertEqual(copia.n_puntos, original.n_puntos)

    def test_activar_deja_un_solo_conjunto_activo(self):
        otro = ConjuntoCurvas.objects.create(
            label="Otro", valuation_date=date(2026, 5, 31),
            spot_usdclp=Decimal("892.89"), is_active=True, created_by=self.user,
        )
        resp = self.client.post(
            reverse("curvas_activate", args=[self.datos["conjunto"].pk])
        )
        self.assertEqual(resp.status_code, 302)
        otro.refresh_from_db()
        self.datos["conjunto"].refresh_from_db()
        self.assertFalse(otro.is_active)
        self.assertTrue(self.datos["conjunto"].is_active)
        self.assertEqual(
            ConjuntoCurvas.objects.filter(created_by=self.user, is_active=True).count(), 1
        )

    def test_activar_no_toca_los_conjuntos_de_otro_usuario(self):
        beto = crear_usuario("beto")
        suyo = ConjuntoCurvas.objects.create(
            label="De Beto", valuation_date=date(2026, 5, 31),
            spot_usdclp=Decimal("892.89"), is_active=True, created_by=beto,
        )
        self.client.post(reverse("curvas_activate", args=[self.datos["conjunto"].pk]))
        suyo.refresh_from_db()
        self.assertTrue(suyo.is_active, msg="No se puede desactivar lo de otro usuario.")


@skipIf(falta_plantilla("valorizador/contrato_import.html"), MOTIVO_PLANTILLA)
class ImportacionDeContratosTest(TestCase):
    """
    Importación por archivo: vista previa y confirmación. La mejora sobre la v1
    es que las filas rechazadas se muestran con su motivo en vez de
    desaparecer.
    """

    ENCABEZADO = "Contraparte;Folio;Operacion;Monto;Precio Fwd;TC inicio;Vencimiento\n"

    @classmethod
    def setUpTestData(cls):
        cls.user = crear_usuario("ana")
        cls.cartera = Cartera.objects.create(nombre="Cordada", created_by=cls.user)

    def setUp(self):
        self.client.login(username="ana", password=CLAVE)

    def archivo(self, texto, nombre="contratos.csv"):
        return SimpleUploadedFile(nombre, texto.encode("utf-8"), content_type="text/csv")

    def test_la_vista_previa_muestra_las_filas_validas_y_los_errores(self):
        csv = self.ENCABEZADO + (
            "Bice;118039;Venta;2000000;893,35;894,25;2026-07-13\n"
            "BTG;;Venta;1000000;886,94;887,71;\n"  # sin vencimiento
        )
        resp = self.client.post(reverse("contratos_import"), {"archivo": self.archivo(csv)})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.context["preview"]), 1)
        self.assertEqual(resp.context["preview"][0]["folio"], "118039")
        errores = resp.context["errores"]
        self.assertTrue(any("Fila 3" in e for e in errores), msg=errores)

    def test_confirmar_crea_los_contratos_del_usuario(self):
        datos = [{
            "counterparty": "Bice", "folio": "118039", "side": "Venta",
            "modality": "Compensacion", "base_ccy": "USD", "quote_ccy": "CLP",
            "notional": 2_000_000, "fwd_price": 893.35, "spot_inicio": 894.25,
            "start_date": None, "maturity_date": "2026-07-13",
        }]
        resp = self.client.post(reverse("contratos_import"), {
            "confirm": "1", "import_data": json.dumps(datos),
            "cartera_id": str(self.cartera.pk),
        })
        self.assertEqual(resp.status_code, 302)
        contrato = ContratoForward.objects.get(created_by=self.user, folio="118039")
        self.assertEqual(contrato.cartera, self.cartera)
        self.assertEqual(contrato.counterparty, "Bice")

    def test_confirmar_omite_los_folios_ya_existentes(self):
        ContratoForward.objects.create(
            counterparty="Bice", folio="118039", side="Venta",
            notional=Decimal("1"), fwd_price=Decimal("1"),
            maturity_date=date(2026, 7, 13), created_by=self.user,
        )
        datos = [{
            "counterparty": "Bice", "folio": "118039", "side": "Venta",
            "notional": 2_000_000, "fwd_price": 893.35, "spot_inicio": 894.25,
            "maturity_date": "2026-07-13",
        }]
        self.client.post(reverse("contratos_import"), {
            "confirm": "1", "import_data": json.dumps(datos),
        })
        self.assertEqual(
            ContratoForward.objects.filter(created_by=self.user, folio="118039").count(), 1
        )

    def test_confirmar_con_datos_ilegibles_no_revienta(self):
        resp = self.client.post(reverse("contratos_import"), {
            "confirm": "1", "import_data": "{esto no es json",
        })
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(ContratoForward.objects.count(), 0)

    def test_no_se_puede_importar_a_la_cartera_de_otro_usuario(self):
        beto = crear_usuario("beto")
        ajena = Cartera.objects.create(nombre="Ajena", created_by=beto)
        datos = [{
            "counterparty": "Bice", "folio": "X", "side": "Venta",
            "notional": 1_000_000, "fwd_price": 890.0, "spot_inicio": 889.0,
            "maturity_date": "2026-07-13",
        }]
        self.client.post(reverse("contratos_import"), {
            "confirm": "1", "import_data": json.dumps(datos),
            "cartera_id": str(ajena.pk),
        })
        contrato = ContratoForward.objects.get(created_by=self.user, folio="X")
        self.assertIsNone(contrato.cartera)


class ImportacionDePuntosDeCurvaTest(TestCase):
    """El endpoint que alimenta el formulario de curvas devuelve JSON."""

    @classmethod
    def setUpTestData(cls):
        crear_usuario("ana")

    def setUp(self):
        self.client.login(username="ana", password=CLAVE)

    def test_importa_una_curva_forward(self):
        archivo = SimpleUploadedFile(
            "curva.csv", "Días;Valor\n1;892,21\n62;892,03\n".encode("utf-8")
        )
        resp = self.client.post(
            reverse("curvas_import_points"), {"archivo": archivo, "type": "forward"}
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            resp.json()["points"],
            [{"tenor_days": 1, "value": 892.21}, {"tenor_days": 62, "value": 892.03}],
        )

    def test_un_archivo_sin_filas_validas_devuelve_400(self):
        archivo = SimpleUploadedFile("curva.csv", b"Dias;Valor\nx;y\n")
        resp = self.client.post(
            reverse("curvas_import_points"), {"archivo": archivo, "type": "forward"}
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("detalles", resp.json())


@skipIf(falta_plantilla("valorizador/contratos_list.html",
                        "valorizador/dashboard.html",
                        "valorizador/contrapartes_list.html"), MOTIVO_PLANTILLA)
class ListadosYFiltrosTest(TestCase):
    """Filtros de los listados y del panel: siempre dentro de lo del usuario."""

    @classmethod
    def setUpTestData(cls):
        cls.user = crear_usuario("ana")
        cls.datos = crear_datos(cls.user, "A")
        cls.otra_cartera = Cartera.objects.create(nombre="Otra", created_by=cls.user)
        cls.liquidado = ContratoForward.objects.create(
            cartera=cls.otra_cartera, counterparty="Santander", folio="LIQ",
            side="Compra", notional=Decimal("500000"), fwd_price=Decimal("880"),
            spot_inicio=Decimal("879"), maturity_date=date(2026, 9, 30),
            status="Liquidado", created_by=cls.user,
        )

    def setUp(self):
        self.client.login(username="ana", password=CLAVE)

    def test_filtro_por_estado(self):
        resp = self.client.get(reverse("contratos_list"), {"estado": "Liquidado"})
        self.assertEqual(list(resp.context["contratos"]), [self.liquidado])

    def test_filtro_por_cartera(self):
        resp = self.client.get(
            reverse("contratos_list"), {"cartera": self.datos["cartera"].pk}
        )
        self.assertEqual(list(resp.context["contratos"]), [self.datos["contrato"]])
        self.assertEqual(resp.context["cartera_obj"], self.datos["cartera"])

    def test_busqueda_por_texto(self):
        resp = self.client.get(reverse("contratos_list"), {"q": "FA"})
        self.assertEqual(list(resp.context["contratos"]), [self.datos["contrato"]])
        resp = self.client.get(reverse("contratos_list"), {"q": "inexistente"})
        self.assertEqual(list(resp.context["contratos"]), [])

    def test_el_panel_filtra_por_cartera(self):
        resp = self.client.get(
            reverse("dashboard"), {"cartera_id": self.otra_cartera.pk}
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context["num_contratos"], 0)  # el otro está liquidado

    def test_crear_contraparte_desde_el_listado(self):
        resp = self.client.post(reverse("contrapartes_list"), {
            "nombre": "Bice", "spread_bp": "75", "recovery": "0.4",
            "tiene_isda_neteo": "on",
        })
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(
            Contraparte.objects.filter(created_by=self.user, nombre="Bice").exists()
        )

    def test_la_tasa_de_recuperacion_debe_estar_entre_cero_y_uno(self):
        resp = self.client.post(reverse("contrapartes_list"), {
            "nombre": "Mala", "spread_bp": "75", "recovery": "1.5",
        })
        self.assertEqual(resp.status_code, 200)
        self.assertIn("recovery", resp.context["form"].errors)


@skipIf(falta_plantilla("valorizador/upload.html", "valorizador/dashboard.html"),
        MOTIVO_PLANTILLA)
class CargaDelLibroCordadaTest(TestCase):
    """Carga completa de un libro Cordada desde la vista de subida."""

    @classmethod
    def setUpTestData(cls):
        cls.user = crear_usuario("ana")

    def setUp(self):
        self.client.login(username="ana", password=CLAVE)

    def test_la_vista_responde_en_get(self):
        self.assertEqual(self.client.get(reverse("upload")).status_code, 200)

    def test_carga_curvas_y_contratos_del_libro(self):
        from valorizador.tests.test_cordada_excel import libro_cordada

        archivo = SimpleUploadedFile(
            "cordada.xlsx", libro_cordada().getvalue(),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        resp = self.client.post(reverse("upload"), {"archivo": archivo})
        self.assertEqual(resp.status_code, 302)

        conjunto = ConjuntoCurvas.objects.get(created_by=self.user)
        self.assertTrue(conjunto.is_active)
        self.assertEqual(conjunto.valuation_date, date(2026, 5, 31))
        self.assertAlmostEqual(float(conjunto.spot_usdclp), 892.89, places=4)
        self.assertEqual(conjunto.puntos.filter(nombre="FWDUSDCLP").count(), 4)
        self.assertEqual(conjunto.puntos.filter(nombre="CLP423").count(), 3)

        contratos = ContratoForward.objects.filter(created_by=self.user)
        self.assertEqual(contratos.count(), 2)
        c = contratos.get(folio="118039")
        self.assertAlmostEqual(
            float(c.spot_inicio), 894.25, places=4,
            msg="El spot al inicio debe salir del libro, no del spot de hoy.",
        )

    def test_un_archivo_ilegible_deja_un_mensaje_de_error(self):
        archivo = SimpleUploadedFile("roto.xlsx", b"esto no es un xlsx")
        resp = self.client.post(reverse("upload"), {"archivo": archivo})
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.context["resumen"]["ok"])


@skipIf(falta_plantilla("valorizador/valorizar.html"), MOTIVO_PLANTILLA)
class ValorizarSinDatosTest(TestCase):
    """Casos degradados de la vista de valorización."""

    @classmethod
    def setUpTestData(cls):
        cls.user = crear_usuario("ana")
        cls.conjunto = ConjuntoCurvas.objects.create(
            label="Curvas", valuation_date=date(2026, 5, 31),
            spot_usdclp=Decimal("892.8900"), created_by=cls.user,
        )
        PuntoCurva.objects.bulk_create(
            [PuntoCurva(conjunto=cls.conjunto, nombre="FWDUSDCLP", tenor_days=d,
                        value=Decimal(str(v))) for d, v in FWD_NODOS]
            + [PuntoCurva(conjunto=cls.conjunto, nombre="CLP423", tenor_days=d,
                          value=Decimal(str(v))) for d, v in DESC_NODOS]
        )

    def setUp(self):
        self.client.login(username="ana", password=CLAVE)

    def parametros(self, **extra):
        datos = {
            "conjunto": self.conjunto.pk, "fecha_valoracion": "2026-05-31",
            "moneda": "USD", "day_count": "ACT/360", "interp_method": "Lineal",
            "extrap_method": "Lineal", "business_days": "Exacto", "calendar": "CL",
            "compounding": "Compuesta", "shock_max": "5",
        }
        datos.update(extra)
        return datos

    def test_sin_contratos_avisa_y_no_produce_resultado(self):
        resp = self.client.post(reverse("valorizar"), self.parametros())
        self.assertEqual(resp.status_code, 200)
        self.assertIsNone(resp.context["result"])

    def test_un_shock_fuera_de_rango_invalida_el_formulario(self):
        resp = self.client.post(reverse("valorizar"), self.parametros(shock_max="80"))
        self.assertEqual(resp.status_code, 200)
        self.assertIn("shock_max", resp.context["form"].errors)

    def test_guardar_sin_resultados_redirige_con_error(self):
        resp = self.client.post(reverse("valorizar_guardar"), {"result_data": "{}"})
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(ValorizacionGuardada.objects.count(), 0)


class DatosDeEjemploTest(TestCase):
    """
    Carga del conjunto de ejemplo desde la interfaz.

    Antes sólo existía como `manage.py cargar_demo`: para ver la aplicación
    funcionando había que tener acceso a la consola del servidor.
    """

    def setUp(self):
        self.user = crear_usuario("ana")
        self.client.login(username="ana", password=CLAVE)

    def test_un_anonimo_no_puede_cargarlos(self):
        self.client.logout()
        resp = self.client.post(reverse("datos_ejemplo"))
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/accounts/login/", resp.url)
        self.assertEqual(ContratoForward.objects.count(), 0)

    def test_exige_post(self):
        self.assertEqual(self.client.get(reverse("datos_ejemplo")).status_code, 405)

    def test_deja_curvas_contratos_y_conjunto_activo(self):
        resp = self.client.post(reverse("datos_ejemplo"))
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(ContratoForward.objects.filter(created_by=self.user).count(), 3)
        conjunto = ConjuntoCurvas.objects.get(created_by=self.user)
        self.assertTrue(conjunto.is_active)
        self.assertEqual(conjunto.n_puntos, 14)
        self.assertEqual(Contraparte.objects.filter(created_by=self.user).count(), 2)

    def test_reproduce_el_mtm_de_referencia(self):
        """Los datos cargados desde la interfaz concilian con la planilla."""
        from core.valuation import MarketData, PricingConfig, price_portfolio

        self.client.post(reverse("datos_ejemplo"))
        conjunto = ConjuntoCurvas.objects.get(created_by=self.user)
        contratos = list(ContratoForward.objects.filter(created_by=self.user))
        res = price_portfolio(
            [c.to_core() for c in contratos],
            MarketData(valuation_date=conjunto.valuation_date,
                       spot=float(conjunto.spot_usdclp), curves=conjunto.as_curves()),
            PricingConfig(day_count="ACT/360", interp_method="Lineal",
                          extrap_method="Lineal", business_days="Exacto",
                          calendar="CL", compounding="Compuesta"),
        )
        self.assertAlmostEqual(res["totals"]["total_mtm"], -6_850_442.17, places=2)

    def test_dos_cargas_no_duplican_nada(self):
        self.client.post(reverse("datos_ejemplo"))
        self.client.post(reverse("datos_ejemplo"))
        self.assertEqual(ContratoForward.objects.filter(created_by=self.user).count(), 3)
        self.assertEqual(ConjuntoCurvas.objects.filter(created_by=self.user).count(), 1)
        self.assertEqual(Cartera.objects.filter(created_by=self.user).count(), 1)

    def test_no_toca_los_datos_de_otro_usuario(self):
        beto = crear_usuario("beto")
        crear_datos(beto, "B")
        antes = list(ContratoForward.objects.filter(created_by=beto).values_list("pk", flat=True))
        self.client.post(reverse("datos_ejemplo"))
        self.assertEqual(
            list(ContratoForward.objects.filter(created_by=beto).values_list("pk", flat=True)),
            antes,
        )

    def test_reutiliza_el_conjunto_con_la_etiqueta_anterior(self):
        """Quien ya tenía la demo cargada no termina con dos conjuntos."""
        ConjuntoCurvas.objects.create(
            label="Cordada 2026-05-31", valuation_date=date(2026, 5, 31),
            spot_usdclp=Decimal("892.8900"), created_by=self.user,
        )
        self.client.post(reverse("datos_ejemplo"))
        conjuntos = ConjuntoCurvas.objects.filter(created_by=self.user)
        self.assertEqual(conjuntos.count(), 1)
        self.assertNotIn("cordada", conjuntos.first().label.lower())
