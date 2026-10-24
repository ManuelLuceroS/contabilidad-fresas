from django.contrib import admin
from django.urls import path
from ledger import views as v

urlpatterns = [
    path("admin/", admin.site.urls),
    path("ingresar/", v.login_view, name="login"),
    path("salir/", v.logout_view, name="logout"),
    path("", v.dashboard, name="dashboard"),
    path("ventas/", v.sales_report, name="sales"),
    path("reportes/", v.sales_report, name="reports"),
    path("ventas/nueva/", v.sale_new, name="sale_new"),
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
