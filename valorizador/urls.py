from django.urls import path

from . import views

urlpatterns = [
    path('', views.dashboard, name='dashboard'),

    # Datos de ejemplo
    path('datos-ejemplo/', views.datos_ejemplo, name='datos_ejemplo'),

    # Curvas
    path('curvas/', views.curvas_list, name='curvas_list'),
    path('curvas/crear/', views.curvas_create, name='curvas_create'),
    path('curvas/<int:pk>/', views.curvas_detail, name='curvas_detail'),
    path('curvas/<int:pk>/editar/', views.curvas_edit, name='curvas_edit'),
    path('curvas/<int:pk>/eliminar/', views.curvas_delete, name='curvas_delete'),
    path('curvas/<int:pk>/duplicar/', views.curvas_duplicate, name='curvas_duplicate'),
    path('curvas/<int:pk>/activar/', views.curvas_activate, name='curvas_activate'),
    path('curvas/importar-puntos/', views.curvas_import_points, name='curvas_import_points'),

    # Carteras y contrapartes
    path('carteras/', views.carteras_list, name='carteras_list'),
    path('carteras/crear/', views.cartera_create, name='cartera_create'),
    path('carteras/<int:pk>/eliminar/', views.cartera_delete, name='cartera_delete'),
    path('contrapartes/', views.contrapartes_list, name='contrapartes_list'),

    # Contratos
    path('contratos/', views.contratos_list, name='contratos_list'),
    path('contratos/crear/', views.contrato_create, name='contrato_create'),
    path('contratos/<int:pk>/editar/', views.contrato_edit, name='contrato_edit'),
    path('contratos/<int:pk>/eliminar/', views.contrato_delete, name='contrato_delete'),
    path('contratos/importar/', views.contratos_import, name='contratos_import'),
    path('contratos/exportar/', views.contratos_export_csv, name='contratos_export_csv'),

    # Valorizar
    path('valorizar/', views.valorizar, name='valorizar'),
    path('valorizar/guardar/', views.valorizar_guardar, name='valorizar_guardar'),

    # Valorizaciones guardadas
    path('valorizaciones/', views.valorizaciones_list, name='valorizaciones_list'),
    path('valorizaciones/<int:pk>/', views.valorizacion_detail, name='valorizacion_detail'),
    path('valorizaciones/<int:pk>/csv/', views.valorizacion_export_csv, name='valorizacion_export_csv'),
    path('valorizaciones/<int:pk>/xlsx/', views.valorizacion_export_xlsx, name='valorizacion_export_xlsx'),
    path('valorizaciones/<int:pk>/eliminar/', views.valorizacion_delete, name='valorizacion_delete'),

    # Carga del libro Cordada
    path('cargar-libro/', views.upload_excel, name='upload'),

    # Asistente
    path('api/chat/', views.api_chat, name='api_chat'),
]
