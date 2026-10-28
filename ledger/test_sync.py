import json
import uuid
from unittest.mock import patch
from django.test import TestCase, override_settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.utils import timezone
from .models import (Customer, Product, PaymentMethod, Sale, Payment, SyncReceipt,
                     SyncState)
from .services import create_sale
from .sync import accept, operation, snapshot, install_snapshot, synchronize, pending


@override_settings(SYNC_BUSINESS='fresas-test', SYNC_TOKEN='x' * 40, SYNC_USER='sync')
class SyncTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser('sync', '', 'test-password')
        self.customer = Customer.objects.create(name='Cliente')
        self.product = Product.objects.create(name='Fresas', price=2000)
        self.cash = PaymentMethod.objects.create(name='Efectivo')
        self.credit = PaymentMethod.objects.create(name='Crédito', is_credit=True)

    def payload(self):
        return {'kind': 'sale', 'token': str(uuid.uuid4()),
                'customer_id': self.customer.pk, 'method_id': self.credit.pk,
                'initial': '1000', 'cash_method_id': self.cash.pk,
                'occurred_at': timezone.now().isoformat(),
                'rows': [{'product': self.product.pk, 'quantity': '2', 'weight': '0',
                          'price': '2000', 'unit': 'unidad', 'by_weight': False}]}

    def test_retry_does_not_duplicate_sale_or_initial_payment(self):
        payload = self.payload()
        accept(payload, self.user)
        accept(payload, self.user)
        self.assertEqual(Sale.objects.count(), 1)
        self.assertEqual(Payment.objects.count(), 1)
        self.assertEqual(Sale.objects.get().total, 4000)
        self.assertEqual(Sale.objects.get().occurred_at.isoformat(), payload['occurred_at'])
        payload['initial'] = '999'
        with self.assertRaises(ValidationError):
            accept(payload, self.user)

    def test_changed_price_stays_unaccepted(self):
        payload = self.payload()
        Product.objects.update(price=3000)
        with self.assertRaises(ValidationError):
            accept(payload, self.user)
        self.assertFalse(Sale.objects.exists())
        self.assertFalse(SyncReceipt.objects.exists())

    def test_cloud_snapshot_restores_balances_and_receipts(self):
        accept(self.payload(), self.user)
        data = snapshot()
        install_snapshot(data)
        self.assertEqual(Sale.objects.get().balance, 3000)
        self.assertEqual(pending(), [])
        self.assertTrue(SyncState.objects.get().initialized)
        install_snapshot(data)
        self.assertEqual(Sale.objects.count(), 1)

    def test_pull_never_overwrites_pending_sale(self):
        data = snapshot()
        create_sale(user=self.user, customer_id=self.customer.pk,
                    rows=[{'product': self.product.pk, 'quantity': 1}],
                    method=self.credit, initial=0, cash_method=None, token=uuid.uuid4())
        with self.assertRaises(ValidationError):
            install_snapshot(data)
        self.assertEqual(Sale.objects.count(), 1)

    @override_settings(OFFLINE_NODE=True)
    def test_initial_sync_refuses_existing_business_data(self):
        with patch('ledger.sync.exchange') as exchange:
            with self.assertRaises(ValidationError):
                synchronize()
            exchange.assert_not_called()

    def test_endpoint_requires_authentication_and_business(self):
        response = self.client.post('/api/sync/', data=json.dumps({'action': 'pull'}),
                                    content_type='application/json')
        self.assertEqual(response.status_code, 403)
        response = self.client.post('/api/sync/',
                                    data=json.dumps({'action': 'pull', 'business': 'otro'}),
                                    content_type='application/json',
                                    HTTP_AUTHORIZATION='Bearer ' + 'x' * 40)
        self.assertEqual(response.status_code, 409)

    @override_settings(OFFLINE_NODE=True)
    def test_local_catalog_and_admin_are_read_only(self):
        self.client.force_login(self.user)
        for path in ('/productos/nuevo/', '/clientes/nuevo/', '/admin/ledger/product/add/',
                     '/gastos/1/editar/'):
            self.assertEqual(self.client.post(path).status_code, 403)

    @override_settings(OFFLINE_NODE=True)
    def test_offline_api_cannot_receive_replication(self):
        response = self.client.post('/api/sync/', data='{}', content_type='application/json',
                                    HTTP_AUTHORIZATION='Bearer ' + 'x' * 40)
        self.assertEqual(response.status_code, 403)

    def test_receipt_for_sale_does_not_hide_payment_with_same_uuid(self):
        payload = self.payload()
        accept(payload, self.user)
        from .services import create_payment
        payment = create_payment(user=self.user, customer_id=self.customer.pk,
                                 amount=100, method=self.cash, date=timezone.localdate(),
                                 notes='', token=payload['token'])
        self.assertIn(payment, pending())

    def test_bad_numeric_payload_is_rejected_without_partial_sale(self):
        payload = self.payload()
        payload['rows'][0]['price'] = 'not-a-number'
        response = self.client.post('/api/sync/',
                                    data=json.dumps({'action': 'push', 'business': 'fresas-test',
                                                     'operation': payload}),
                                    content_type='application/json',
                                    HTTP_AUTHORIZATION='Bearer ' + 'x' * 40)
        self.assertEqual(response.status_code, 409)
        self.assertFalse(Sale.objects.exists())

    def test_initial_payment_has_stable_identity_and_uuid_routes_work(self):
        payload = self.payload()
        accept(payload, self.user)
        from uuid import uuid5, NAMESPACE_URL
        payment = Payment.objects.get()
        self.assertEqual(payment.token, uuid5(NAMESPACE_URL, f"fresas:initial:{payload['token']}"))
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(f'/ventas/operacion/{payload["token"]}/').status_code, 200)
        self.assertEqual(self.client.get(f'/abonos/operacion/{payment.token}/').status_code, 200)
        self.assertEqual(self.client.get('/sincronizacion/').status_code, 200)
