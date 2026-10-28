from django.contrib import admin
from django.urls import path
from ledger import views as v
from ledger.sync import endpoint
from ledger.sync_views import sync_status
from ledger import mobile_views as mobile
from ledger import farm_views as farm
from ledger import whatsapp_views as wa

urlpatterns = [
    path('ventas/<int:pk>/whatsapp/', wa.prepare_sale, name='whatsapp_prepare_sale'),
    path('whatsapp/envios/<uuid:pk>/procesar/', wa.process, name='whatsapp_process'),
    path('whatsapp/envios/<uuid:pk>/reintentar/', wa.retry, name='whatsapp_retry'),
    path('api/whatsapp/cola/', wa.cron, name='whatsapp_cron'),
    path('api/whatsapp/webhook/', wa.webhook, name='whatsapp_webhook'),
    path('nomina/<int:pk>/trabajador/<int:worker_id>/pdf/', wa.payroll_document, name='payroll_document'),
    path("nomina/", farm.payroll_list, name="payroll_list"),
    path("nomina/generar/", farm.payroll_new, name="payroll_new"),
    path("nomina/asistencia/", farm.attendance, name="attendance"),
    path("nomina/tarifas/", farm.farm_catalog, {"kind": "settings"}, name="payroll_settings"),
    path("nomina/trabajadores/", farm.farm_catalog, {"kind": "workers"}, name="workers"),
    path("nomina/trabajadores/nuevo/", farm.farm_catalog, {"kind": "workers", "edit": True}, name="worker_new"),
    path("nomina/trabajadores/<int:pk>/editar/", farm.farm_catalog, {"kind": "workers", "edit": True}, name="worker_edit"),
    path("nomina/trabajadores/<int:pk>/", farm.worker_history, name="worker_history"),
    path("nomina/<int:pk>/", farm.payroll_detail, name="payroll_detail"),
    path("fumigacion/", farm.spray_list, name="spray_history"),
    path("fumigacion/calendario/", farm.spray_list, {"mode": "calendar"}, name="spray_calendar"),
    path("fumigacion/proximas/", farm.spray_list, {"mode": "upcoming"}, name="spray_upcoming"),
    path("fumigacion/productos/", farm.farm_catalog, {"kind": "spray_products"}, name="spray_products"),
    path("fumigacion/productos/nuevo/", farm.farm_catalog, {"kind": "spray_products", "edit": True}, name="spray_product_new"),
    path("fumigacion/productos/<int:pk>/editar/", farm.farm_catalog, {"kind": "spray_products", "edit": True}, name="spray_product_edit"),
    path("fumigacion/nueva/", farm.spray_edit, name="spray_new"),
    path("fumigacion/<int:pk>/", farm.spray_detail, name="spray_detail"),
    path("fumigacion/<int:pk>/editar/", farm.spray_edit, name="spray_edit"),

    path("movil/", mobile.shell, name="mobile"),
    path("movil/sw.js", mobile.service_worker),
    path("movil/manifest.webmanifest", mobile.manifest),
    path("api/mobile/bootstrap/", mobile.bootstrap),
    path("api/mobile/push/", mobile.push),
    path("api/sync/", endpoint, name="sync_api"),
    path("sincronizacion/", sync_status, name="sync_status"),
    path("admin/", admin.site.urls),
    path("ingresar/", v.login_view, name="login"),
    path("salir/", v.logout_view, name="logout"),
    path("", v.dashboard, name="dashboard"),
    path("ventas/", v.sales_report, name="sales"),
    path("reportes/", v.sales_report, name="reports"),
    path("ventas/nueva/", v.sale_new, name="sale_new"),
    path("ventas/operacion/<uuid:token>/", v.sale_detail, name="sale_operation"),
    path("abonos/operacion/<uuid:token>/", v.payment_detail, name="payment_operation"),
    path("ventas/<int:pk>/", v.sale_detail, name="sale_detail"),
    path("clientes/<int:pk>/estado/", v.customer_detail, name="customer_detail"),
    path("cartera/", v.receivables, name="receivables"),
    path("abonos/nuevo/", v.payment_new, name="payment_new"),
    path("abonos/<int:pk>/", v.payment_detail, name="payment_detail"),
    path("gastos/", v.expenses, name="expenses"),
    path("gastos/nuevo/", v.expense_edit, name="expense_new"),
    path("gastos/<int:pk>/editar/", v.expense_edit, name="expense_edit"),
    path("<str:kind>/nuevo/", v.catalog_edit, name="catalog_new"),
    path("<str:kind>/<int:pk>/editar/", v.catalog_edit, name="catalog_edit"),
    path("<str:kind>/", v.catalog, name="catalog"),
]
