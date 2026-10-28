class PrivatePagesMiddleware:
    """Evita almacenar pantallas financieras o formularios de acceso en cachés."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if not request.path.startswith("/static/"):
            response["Cache-Control"] = "private, no-store, max-age=0"
            response["Pragma"] = "no-cache"
        return response


class OfflineReplicaMiddleware:
    """El catálogo local es una copia; se modifica exclusivamente en la nube."""
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        from django.conf import settings
        from django.http import HttpResponseForbidden
        from .models import SyncState
        if settings.OFFLINE_NODE and request.path.startswith(("/nomina/", "/fumigacion/", "/whatsapp/", "/api/whatsapp/")):
            return HttpResponseForbidden("Nómina y fumigación se administran en la instalación principal. La sincronización actual solo incluye ventas, abonos, gastos y sus catálogos.")
        if settings.OFFLINE_NODE and request.method not in ("GET", "HEAD", "OPTIONS"):
            path = request.path
            if path not in ("/ingresar/", "/salir/", "/sincronizacion/", "/api/mobile/push/"):
                if (path.startswith(("/nomina/", "/fumigacion/", "/admin/", "/clientes/", "/productos/", "/categorias/", "/medios/"))
                        or (path.startswith("/gastos/") and path != "/gastos/nuevo/")):
                    return HttpResponseForbidden("Este cambio se realiza en la nube. El equipo local recibe el catálogo y los gastos actualizados al sincronizar.")
                if not SyncState.objects.filter(pk=1, initialized=True).exists():
                    return HttpResponseForbidden("Realice la primera sincronización con internet antes de registrar movimientos.")
        return self.get_response(request)
