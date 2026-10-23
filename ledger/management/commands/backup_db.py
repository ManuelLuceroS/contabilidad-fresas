import os, sqlite3, subprocess
from pathlib import Path
from datetime import datetime
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
class Command(BaseCommand):
    help='Crea un respaldo consistente de SQLite o PostgreSQL. No elimina ni reemplaza datos.'
    def add_arguments(self,parser): parser.add_argument('--directory',default='backups')
    def handle(self,*args,**options):
        directory=Path(options['directory']); directory.mkdir(parents=True,exist_ok=True)
        stamp=datetime.now().strftime('%Y%m%d-%H%M%S-%f')
        db=settings.DATABASES['default']
        if db['ENGINE'].endswith('sqlite3'):
            destination=directory/f'nexo-{stamp}.sqlite3'
            with sqlite3.connect(db['NAME']) as source,sqlite3.connect(destination) as target:
                source.backup(target)
                if target.execute('PRAGMA integrity_check').fetchone()[0]!='ok': raise CommandError('Respaldo inválido')
        else:
            destination=directory/f'nexo-{stamp}.dump'
            env={**os.environ,'PGPASSWORD':str(db.get('PASSWORD',''))}
            try:
                subprocess.run(['pg_dump','--format=custom','--file',str(destination),'--host',str(db.get('HOST') or 'localhost'),'--port',str(db.get('PORT') or 5432),'--username',str(db.get('USER','')),str(db['NAME'])],env=env,check=True,capture_output=True)
            except (FileNotFoundError,subprocess.CalledProcessError): raise CommandError('No se pudo ejecutar pg_dump. Verifique el cliente PostgreSQL y la conexión.')
        destination.chmod(0o600)
        self.stdout.write(self.style.SUCCESS(f'Respaldo creado: {destination}'))
