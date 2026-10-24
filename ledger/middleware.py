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
