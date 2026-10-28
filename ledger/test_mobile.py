import json
from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings
from .models import Customer, Product, PaymentMethod, ExpenseCategory, Sale, Payment, Expense
from .mobile_views import mobile_identity
from .sync import snapshot


@override_settings(SYNC_BUSINESS='test-fresas')
class MobileTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser('movil', '', 'Mobile-test-927!')
        self.customer = Customer.objects.create(name='Cliente móvil')
        self.product = Product.objects.create(name='Fresas', price=2000)
        self.method = PaymentMethod.objects.create(name='Efectivo')
        self.category = ExpenseCategory.objects.create(name='Transporte')
        self.client.force_login(self.user)

    def post(self, operation, identity=None, client=None):
        return (client or self.client).post('/api/mobile/push/',
            data=json.dumps({'identity': identity or {'user': self.user.pk, 'username': 'movil',
                             'business': 'test-fresas'}, 'operation': operation}),
            content_type='application/json')

    def test_public_shell_contains_no_customer_or_secret(self):
        self.client.logout()
        response = self.client.get('/movil/')
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, self.customer.name)
        self.assertNotContains(response, 'SYNC_TOKEN')
        self.assertEqual(self.client.get('/api/mobile/bootstrap/').status_code, 401)

    def test_bootstrap_contains_catalog_and_no_passwords(self):
        response = self.client.get('/api/mobile/bootstrap/')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['identity']['user'], self.user.pk)
        self.assertEqual(data['products'][0]['price'], '2000.00')
        self.assertNotIn('password', response.content.decode())
        self.assertIn('no-store', response['Cache-Control'])

    def test_idempotent_expense_sync(self):
        import uuid
        from django.utils import timezone
        operation = {'kind': 'expense', 'token': str(uuid.uuid4()), 'amount': '500',
                     'date': timezone.localdate().isoformat(), 'category_id': self.category.pk,
                     'method_id': self.method.pk, 'description': 'Transporte', 'reference': ''}
        self.assertEqual(self.post(operation).status_code, 200)
        self.assertEqual(self.post(operation).status_code, 200)
        self.assertEqual(Expense.objects.count(), 1)
        self.assertEqual(Expense.objects.get().created_by, self.user)

    def test_user_without_read_permissions_cannot_download(self):
        user = get_user_model().objects.create_user('sin-permisos', password='test')
        self.client.force_login(user)
        self.assertEqual(self.client.get('/api/mobile/bootstrap/').status_code, 403)

    def test_identity_mismatch_rejected(self):
        self.assertEqual(self.post({}, identity={'user': 999, 'username': 'otro',
                                               'business': 'test-fresas'}).status_code, 403)
        self.assertFalse(Expense.objects.exists())

    def test_push_requires_csrf_even_with_valid_session(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        self.assertEqual(self.post({}, client=client).status_code, 403)

    def test_manifest_and_worker_have_scoped_offline_shell(self):
        manifest = self.client.get('/movil/manifest.webmanifest').json()
        self.assertEqual(manifest['start_url'], '/movil/')
        self.assertEqual(manifest['display'], 'standalone')
        worker = self.client.get('/movil/sw.js')
        self.assertEqual(worker.status_code, 200)
        self.assertEqual(worker['Service-Worker-Allowed'], '/movil/')
        self.assertNotContains(worker, '__VERSION__')
        self.assertNotContains(worker, '__ASSETS__')
        self.assertNotContains(worker, '/api/mobile/bootstrap/')

    @override_settings(OFFLINE_NODE=True)
    def test_mobile_does_not_sync_into_desktop_replica(self):
        self.assertEqual(self.client.get('/api/mobile/bootstrap/').status_code, 409)
        self.assertEqual(self.post({}).status_code, 409)

    def test_login_returns_to_mobile_and_rejects_external_redirect(self):
        self.client.logout()
        response = self.client.post('/ingresar/?next=/movil/',
                                    {'username': 'movil', 'password': 'Mobile-test-927!'})
        self.assertEqual(response['Location'], '/movil/')
        self.client.logout()
        response = self.client.post('/ingresar/?next=https://evil.example/',
                                    {'username': 'movil', 'password': 'Mobile-test-927!'})
        self.assertEqual(response['Location'], '/')
