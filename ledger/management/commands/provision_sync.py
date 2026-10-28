from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.management.base import BaseCommand, CommandError
from ledger.sync import PERMISSIONS


class Command(BaseCommand):
    help = 'Prepara el usuario técnico de nube para un único computador offline.'

    def handle(self, *args, **options):
        if settings.OFFLINE_NODE or not settings.SYNC_USER or len(settings.SYNC_TOKEN) < 32 or not settings.SYNC_BUSINESS:
            raise CommandError('Configure SYNC_USER, SYNC_TOKEN y SYNC_BUSINESS en la nube, con OFFLINE_NODE=false.')
        user, created = get_user_model().objects.get_or_create(username=settings.SYNC_USER)
        if not created and (user.is_staff or user.is_superuser or user.has_usable_password()):
            raise CommandError('El nombre corresponde a una cuenta interactiva. Use un nombre técnico nuevo.')
        if created:
            user.set_unusable_password()
            user.save()
        codes = [p.split('.')[1] for p in PERMISSIONS] + ['add_sale', 'add_payment', 'add_expense']
        user.user_permissions.add(*Permission.objects.filter(content_type__app_label='ledger', codename__in=codes))
        self.stdout.write('Usuario técnico preparado. No se modificaron contraseñas ni movimientos.')
