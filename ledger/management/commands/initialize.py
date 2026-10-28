from django.core.management.base import BaseCommand
from django.contrib.auth.models import Group, Permission
from ledger.models import PaymentMethod, ExpenseCategory, Sequence


class Command(BaseCommand):
    help = (
        "Configura medios y categorías editables; no crea ventas ni clientes ficticios."
    )

    def handle(self, *args, **options):
        for name, credit in [
            ("Efectivo", False),
            ("Transferencia", False),
            ("Crédito", True),
        ]:
            PaymentMethod.objects.get_or_create(
                name=name, defaults={"is_credit": credit}
            )
        for name in [
            "Transporte",
            "Arriendo",
            "Servicios públicos",
            "Nómina",
            "Compra de materiales",
            "Mantenimiento",
            "Otros gastos",
        ]:
            ExpenseCategory.objects.get_or_create(name=name)
        Sequence.objects.get_or_create(name="sales")
        group, _ = Group.objects.get_or_create(name="Operadores")
        group.permissions.set(
            Permission.objects.filter(content_type__app_label="ledger")
            .exclude(codename__startswith="delete_")
            .exclude(
                content_type__model__in=[
                    "audit",
                    "sequence",
                    "loginattempt",
                    "allocation",
                    "saleline",
                    "payrollday",
                    "payrollsettings",
                ]
            )
        )
        self.stdout.write(
            self.style.SUCCESS(
                "Configuración inicial lista. Cree el administrador con createsuperuser."
            )
        )
