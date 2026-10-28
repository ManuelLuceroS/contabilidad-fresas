import json
import time
from urllib.error import HTTPError
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import close_old_connections
from ledger.models import SyncState
from ledger.sync import synchronize


class Command(BaseCommand):
    help = 'Envía pendientes y actualiza la réplica local desde la nube.'

    def add_arguments(self, parser):
        parser.add_argument('--watch', action='store_true')

    def handle(self, *args, **options):
        if not settings.OFFLINE_NODE:
            raise CommandError('Configure OFFLINE_NODE=true únicamente en la instalación local.')
        # Un solo worker por instalación; el SO libera el bloqueo al salir.
        import fcntl
        lock = open(settings.BASE_DIR / '.sync.lock', 'a')
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise CommandError('Ya hay un sincronizador activo en este computador.')
        while True:
            try:
                synchronize()
                self.stdout.write('Sincronización completa.')
            except Exception as exc:
                message = 'No se pudo conectar con la nube. Se reintentará; los datos permanecen en este equipo.'
                if isinstance(exc, HTTPError):
                    try:
                        message = json.loads(exc.read()).get('error', message)
                    except (ValueError, OSError):
                        pass
                else:
                    from django.core.exceptions import ValidationError
                    if isinstance(exc, ValidationError):
                        message = ' '.join(exc.messages)
                SyncState.objects.update_or_create(pk=1, defaults={'last_error': message})
                if not options['watch']:
                    raise CommandError(message) from None
                self.stderr.write(message)
            finally:
                close_old_connections()
            if not options['watch']:
                break
            time.sleep(settings.SYNC_INTERVAL)
