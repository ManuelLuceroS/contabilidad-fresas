"""Prepara una réplica aislada sin reemplazar la base ni el .env existentes."""
import argparse
import os
from pathlib import Path
import secrets
import sqlite3
import subprocess
import sys
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parent.parent
LOCAL = ROOT / '.offline'
CONFIG = LOCAL / '.env'


def environment():
    if not CONFIG.exists():
        raise RuntimeError('Primero ejecute: python scripts/local_app.py setup')
    return {**os.environ, **{k: v for k, v in dotenv_values(CONFIG).items() if v is not None}}


def manage(*args, **kwargs):
    return subprocess.run([sys.executable, str(ROOT / 'manage.py'), *args],
                          cwd=ROOT, env=environment(), check=True, **kwargs)


def setup():
    LOCAL.mkdir(mode=0o700, exist_ok=True)
    LOCAL.chmod(0o700)
    if not CONFIG.exists():
        base = dotenv_values(ROOT / '.env')
        config = {
            'DEBUG': 'true', 'SECRET_KEY': secrets.token_urlsafe(64),
            'ALLOWED_HOSTS': 'localhost,127.0.0.1', 'TRUST_PROXY': 'false',
            'CSRF_TRUSTED_ORIGINS': '', 'OFFLINE_NODE': 'true',
            'DATABASE_URL': f'sqlite:///{LOCAL / "db.sqlite3"}',
            'SYNC_URL': base.get('SYNC_URL') or 'https://contabilidad-fresas.vercel.app',
            'SYNC_TOKEN': base.get('SYNC_TOKEN') or secrets.token_urlsafe(48),
            'SYNC_BUSINESS': base.get('SYNC_BUSINESS') or 'contabilidad-fresas',
            'SYNC_USER': base.get('SYNC_USER') or 'sincronizador-local',
            'SYNC_INTERVAL': '120', 'LOCAL_PORT': '8002',
        }
        with CONFIG.open('x') as file:
            file.write(''.join(f'{key}={value}\n' for key, value in config.items()))
        CONFIG.chmod(0o600)
    manage('migrate', '--noinput')
    manage('initialize')
    # Conserva el acceso local existente, sin copiar movimientos ni contraseñas en texto.
    source = ROOT / 'db.sqlite3'
    if source.exists():
        with sqlite3.connect(f'file:{source}?mode=ro', uri=True) as conn:
            conn.row_factory = sqlite3.Row
            users = [dict(row) for row in conn.execute(
                'SELECT username,password,email,is_superuser,is_staff,is_active FROM auth_user '
                'WHERE is_active=1 AND is_superuser=1')]
        import json
        code = '''import json,sys
from django.contrib.auth import get_user_model
for data in json.load(sys.stdin):
    username=data.pop('username')
    get_user_model().objects.get_or_create(username=username, defaults=data)
print('Acceso local preparado sin modificar cuentas existentes.')
'''
        subprocess.run([sys.executable, '-c', 'import os; os.environ["DJANGO_SETTINGS_MODULE"]="config.settings"; import django; django.setup();\n' + code],
                       cwd=ROOT, env=environment(), input=json.dumps(users), text=True, check=True)
    (LOCAL / 'db.sqlite3').chmod(0o600)
    print('Instalación local preparada en .offline/. Falta la primera sincronización con la nube.')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['setup', 'open', 'sync', 'user', 'check'])
    args = parser.parse_args()
    if args.action == 'setup':
        setup()
    elif args.action == 'sync':
        manage('sync_cloud')
    elif args.action == 'user':
        manage('createsuperuser')
    elif args.action == 'check':
        manage('check')
    else:
        subprocess.run([sys.executable, str(ROOT / 'scripts/open_app.py')],
                       cwd=ROOT, env=environment(), check=True)


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, subprocess.CalledProcessError) as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
