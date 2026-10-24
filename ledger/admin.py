from django.contrib import admin
from .models import Audit


@admin.register(Audit)
class AuditAdmin(admin.ModelAdmin):
    list_display = ["date", "actor", "action", "entity", "object_id"]
    list_filter = ["entity", "action"]
    readonly_fields = [
        "date",
        "actor",
        "action",
        "entity",
        "object_id",
        "before",
        "after",
    ]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


admin.site.site_header = "Mi Contabilidad · Administración de acceso"
admin.site.site_title = "Mi Contabilidad"
