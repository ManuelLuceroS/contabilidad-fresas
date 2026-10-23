"""Production settings regression checks; no database connection is opened."""
import os
from pathlib import Path
import subprocess
import sys
import unittest

class ProductionSettingsTests(unittest.TestCase):
    def run_settings(self, **overrides):
        env = dict(os.environ, VERCEL='1', DEBUG='false', SECRET_KEY='test-only-' * 8,
                   DATABASE_URL='postgresql://test:test@localhost/test?sslmode=require',
                   ALLOWED_HOSTS=' contabilidad-fresas.vercel.app, ',
                   CSRF_TRUSTED_ORIGINS=' https://contabilidad-fresas.vercel.app, ',
                   TRUST_PROXY='true')
        env.update(overrides)
        return subprocess.run([sys.executable, '-c',
            'from config import settings as s; '
            'assert not s.DEBUG; '
            'assert s.ALLOWED_HOSTS == ["contabilidad-fresas.vercel.app"]; '
            'assert s.CSRF_TRUSTED_ORIGINS == ["https://contabilidad-fresas.vercel.app"]; '
            'assert s.SECURE_PROXY_SSL_HEADER == ("HTTP_X_FORWARDED_PROTO", "https"); '
            'assert s.DATABASES["default"]["CONN_MAX_AGE"] == 0; '
            'assert s.DATABASES["default"]["OPTIONS"]["sslmode"] == "require"; '
            'assert s.SESSION_COOKIE_SECURE and s.CSRF_COOKIE_SECURE'],
            cwd=Path(__file__).resolve().parent.parent, env=env, capture_output=True, text=True)

    def test_production_configuration(self):
        result = self.run_settings()
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_unsafe_configuration_fails_early(self):
        for overrides, message in [
            ({'SECRET_KEY': ''}, 'Configure SECRET_KEY'),
            ({'DATABASE_URL': ''}, 'Configure DATABASE_URL'),
            ({'DATABASE_URL': 'sqlite:////tmp/accounting.sqlite3'}, 'debe usar PostgreSQL'),
            ({'DEBUG': 'true'}, 'DEBUG debe ser false'),
            ({'ALLOWED_HOSTS': '*'}, 'dominios explícitos'),
            ({'ALLOWED_HOSTS': ''}, 'dominios explícitos'),
            ({'CSRF_TRUSTED_ORIGINS': ''}, 'Configure CSRF_TRUSTED_ORIGINS'),
            ({'CSRF_TRUSTED_ORIGINS': 'http://example.com'}, 'debe usar HTTPS'),
            ({'TRUST_PROXY': 'false'}, 'TRUST_PROXY debe ser true'),
        ]:
            with self.subTest(overrides=overrides):
                result = self.run_settings(**overrides)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(message, result.stderr)
