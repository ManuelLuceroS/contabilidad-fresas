import hashlib
import hmac
import json
import uuid
from datetime import timedelta
from decimal import Decimal
from io import BytesIO
from unittest.mock import patch
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.test import TestCase, Client, override_settings
from django.utils import timezone
from pypdf import PdfReader
from .models import (Worker, PayrollSettings, Payroll, PayrollExpense, Expense, ExpenseCategory,
                     PaymentMethod, Customer, Product, WhatsAppMessage, Audit)
from .farm_services import save_attendance, generate_payroll, payroll_transition
from .reporting import accounting_expenses
from .services import create_sale
from .whatsapp import dispatch_message, MetaError, individual_payroll_pdf

API_CONFIG = dict(WHATSAPP_ENABLED=True, WHATSAPP_ACCESS_TOKEN='test-only-token',
                  WHATSAPP_PHONE_NUMBER_ID='123456', WHATSAPP_SENDER_NUMBER='573115893850',
                  WHATSAPP_SALE_TEMPLATE='comprobante_venta', WHATSAPP_PAYROLL_TEMPLATE='resumen_nomina',
                  WHATSAPP_TEMPLATE_LANGUAGE='es_CO')


class PayrollExpenseWhatsAppTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command('initialize', verbosity=0)
        cls.user = get_user_model().objects.create_superuser('message-admin')
        cls.day = timezone.localdate() - timedelta(days=2)
        cls.cash = PaymentMethod.objects.get(name='Efectivo')
        PayrollSettings.objects.create(pk=1, mode='hourly', hourly_rate=10000)
        cls.a = Worker.objects.create(name='Trabajadora Uno', joined_on=cls.day, daily_rate=50000,
                                      phone='3001234567', whatsapp_opt_in=True)
        cls.b = Worker.objects.create(name='Trabajador Dos', joined_on=cls.day, daily_rate=90000,
                                      phone='3007654321', whatsapp_opt_in=True)
        cls.customer = Customer.objects.create(name='Cliente WhatsApp', phone='3011234567', whatsapp_opt_in=True)
        cls.product = Product.objects.create(name='Fresa prueba', unit='canasta', price=25000)

    def setUp(self):
        self.client.force_login(self.user)

    def payroll(self, both=True, paid=False):
        workers = [self.a, self.b] if both else [self.a]
        save_attendance(self.day, [dict(worker=w.pk, worked=True, hours=1, minutes=30, revision=0, notes='') for w in workers], self.user)
        return generate_payroll(self.day, self.day, uuid.uuid4(), self.user, paid=paid, payment_method=self.cash if paid else None)

    def sale(self):
        return create_sale(user=self.user, customer_id=self.customer.pk, rows=[dict(product=self.product.pk, quantity=2)],
                           method=self.cash, initial=50000, cash_method=self.cash, token=uuid.uuid4())

    def text(self, pdf):
        return ' '.join(p.extract_text() for p in PdfReader(BytesIO(bytes(pdf))).pages)

    def webhook(self, job, status='delivered', **overrides):
        event = {'id': job.provider_id or 'wamid.callback', 'recipient_id': job.recipient, 'status': status,
                 'biz_opaque_callback_data': f'{job.pk}:{job.attempts}'}
        event.update(overrides)
        body = json.dumps({'entry': [{'changes': [{'value': {'metadata': {'phone_number_id': '123456'}, 'statuses': [event]}}]}]}).encode()
        signature = 'sha256=' + hmac.new(b'test-app-secret', body, hashlib.sha256).hexdigest()
        return self.client.post('/api/whatsapp/webhook/', body, content_type='application/json', HTTP_X_HUB_SIGNATURE_256=signature)

    def test_generated_payroll_creates_exactly_one_accounted_expense(self):
        p = self.payroll()
        entry = p.expense_entry
        self.assertEqual(entry.expense.amount, p.total)
        self.assertEqual(entry.expense.category.name, 'Nómina')
        self.assertEqual(entry.expense.date, p.end)
        self.assertFalse(entry.expense.method.active)
        self.assertIn('Pendiente', entry.expense.method.name)
        self.assertEqual(generate_payroll(p.start, p.end, p.token, self.user).pk, p.pk)
        self.assertEqual(Expense.objects.count(), 1)
        self.assertEqual(sum(e.amount for e in accounting_expenses()), p.total)
        self.assertTrue(Audit.objects.filter(action='Gasto automático de nómina').exists())
        response = self.client.get('/gastos/', {'start': p.start, 'end': p.end})
        self.assertEqual(response.context['total'], p.total)

    def test_confirm_payment_updates_same_expense_and_individual_phase(self):
        p = self.payroll()
        expense_id = p.expense_entry.expense_id
        with self.assertRaises(ValidationError):
            payroll_transition(p.pk, 'pay', '', self.user)
        payroll_transition(p.pk, 'pay', '', self.user, method_id=self.cash.pk)
        p.refresh_from_db()
        self.assertEqual(p.status, 'paid')
        self.assertIsNotNone(p.paid_at)
        self.assertEqual(p.expense_entry.expense_id, expense_id)
        self.assertEqual(Expense.objects.get(pk=expense_id).method_id, self.cash.pk)
        self.assertEqual(Expense.objects.count(), 1)
        self.assertEqual(p.whatsapp_messages.filter(phase='generated', status='cancelled').count(), 2)
        self.assertEqual(p.whatsapp_messages.filter(phase='paid').count(), 2)
        for job in p.whatsapp_messages.filter(phase='paid'):
            self.assertIn('Pago confirmado', job.summary)
            self.assertIn('Pago confirmado', self.text(job.document))

    def test_generate_already_paid_uses_real_payment_method(self):
        p = self.payroll(paid=True)
        self.assertEqual(p.status, 'paid')
        self.assertEqual(p.expense_entry.expense.method_id, self.cash.pk)
        self.assertFalse(p.whatsapp_messages.exclude(phase='paid').exists())

    def test_cancellation_keeps_history_excludes_cost_and_sync(self):
        p = self.payroll(paid=True)
        old_id = p.expense_entry.expense_id
        payroll_transition(p.pk, 'cancel', 'Revisión de asistencia', self.user)
        self.assertTrue(Expense.objects.filter(pk=old_id).exists())
        self.assertFalse(accounting_expenses().exists())
        self.assertFalse(PayrollExpense.objects.get(payroll=p).active)
        self.assertFalse(p.whatsapp_messages.exclude(status='cancelled').exists())
        from .sync import snapshot
        data = snapshot()
        self.assertFalse([r for r in data['objects'] if r['model'] == 'ledger.expense'])
        for item in data['objects']:
            if item['model'] == 'ledger.customer':
                self.assertNotIn('whatsapp_opt_in', item['fields'])
        new = generate_payroll(p.start, p.end, uuid.uuid4(), self.user)
        self.assertNotEqual(new.expense_entry.expense_id, old_id)
        self.assertEqual(accounting_expenses().count(), 1)
        self.assertEqual(Expense.objects.count(), 2)

    def test_linked_expense_cannot_be_manually_changed(self):
        p = self.payroll()
        expense = p.expense_entry.expense
        response = self.client.post(f'/gastos/{expense.pk}/editar/', {'amount': 1, 'revision': 1})
        self.assertRedirects(response, f'/nomina/{p.pk}/')
        expense.refresh_from_db()
        self.assertEqual(expense.amount, p.total)

    def test_inactive_expense_category_rolls_back_payroll_and_queue(self):
        ExpenseCategory.objects.filter(name='Nómina').update(active=False)
        with self.assertRaises(ValidationError):
            self.payroll()
        self.assertFalse(Payroll.objects.exists())
        self.assertFalse(WhatsAppMessage.objects.exists())
        self.assertFalse(Expense.objects.exists())

    def test_zero_payroll_creates_no_zero_cost_or_notifications(self):
        save_attendance(self.day, [dict(worker=self.a.pk, worked=False, hours=0, minutes=0, revision=0, notes='')], self.user)
        p = generate_payroll(self.day, self.day, uuid.uuid4(), self.user)
        self.assertEqual(p.total, 0)
        self.assertFalse(Expense.objects.exists())
        self.assertFalse(p.whatsapp_messages.exists())

    def test_individual_pdf_never_contains_other_worker(self):
        p = self.payroll()
        job = p.whatsapp_messages.get(worker=self.a)
        text = self.text(job.document)
        self.assertIn(self.a.name, text)
        self.assertNotIn(self.b.name, text)
        self.assertIn('$ 65.000,00', text)
        self.assertNotIn('$ 105.000,00', text)
        self.assertIn('pago pendiente', text)
        pdf = self.client.get(f'/nomina/{p.pk}/trabajador/{self.a.pk}/pdf/')
        self.assertEqual(pdf.status_code, 200)
        self.assertNotIn(self.b.name, self.text(pdf.content))
        self.assertEqual(self.client.get(f'/nomina/{p.pk}/trabajador/9999/pdf/').status_code, 404)

    def test_sale_queues_pdf_and_replay_does_not_duplicate(self):
        sale = self.sale()
        job = sale.whatsapp_messages.get()
        self.assertEqual(job.recipient, '573011234567')
        self.assertIn(str(sale), self.text(job.document))
        self.client.post(f'/ventas/{sale.pk}/whatsapp/')
        self.assertEqual(sale.whatsapp_messages.count(), 1)
        self.customer.whatsapp_opt_in = False
        self.customer.save()
        self.assertFalse(self.sale().whatsapp_messages.exists())

    @override_settings(**API_CONFIG)
    @patch('ledger.whatsapp.meta_request')
    def test_official_sender_and_template_document_payload(self, meta):
        job = self.sale().whatsapp_messages.get()
        meta.side_effect = [{'display_phone_number': '+57 3115893850'}, {'id': 'media-test'}, {'messages': [{'id': 'wamid.test'}]}]
        job = dispatch_message(job.pk)
        self.assertEqual(job.status, 'accepted')
        payload = meta.call_args.kwargs['payload']
        self.assertEqual(payload['to'], '573011234567')
        self.assertEqual(payload['template']['name'], 'comprobante_venta')
        self.assertEqual(payload['template']['components'][0]['parameters'][0]['document']['id'], 'media-test')
        self.assertEqual(payload['biz_opaque_callback_data'], f'{job.pk}:1')
        self.assertEqual(dispatch_message(job.pk).status, 'accepted')
        self.assertEqual(meta.call_count, 3)

    @override_settings(**API_CONFIG)
    @patch('ledger.whatsapp.meta_request', return_value={'display_phone_number': '+57 3000000000'})
    def test_wrong_sender_blocks_before_upload_and_send(self, meta):
        job = dispatch_message(self.sale().whatsapp_messages.get().pk)
        self.assertEqual(job.status, 'failed')
        self.assertIn('sender_mismatch', job.detail)
        self.assertEqual(meta.call_count, 1)

    @override_settings(WHATSAPP_ENABLED=False)
    @patch('ledger.whatsapp.meta_request')
    def test_unconfigured_api_never_claims_or_sends(self, meta):
        job = dispatch_message(self.sale().whatsapp_messages.get().pk)
        self.assertEqual(job.status, 'blocked')
        self.assertEqual(job.attempts, 0)
        meta.assert_not_called()

    @override_settings(**API_CONFIG)
    @patch('ledger.whatsapp.meta_request')
    def test_recipient_consent_required_at_dispatch(self, meta):
        sale = self.sale()
        self.customer.whatsapp_opt_in = False
        self.customer.save()
        job = dispatch_message(sale.whatsapp_messages.get().pk)
        self.assertEqual(job.status, 'blocked')
        self.assertIn('autorización', job.detail)
        meta.assert_not_called()

    @override_settings(**API_CONFIG)
    @patch('ledger.whatsapp.meta_request')
    def test_ambiguous_timeout_not_retried_automatically(self, meta):
        job = self.sale().whatsapp_messages.get()
        meta.side_effect = [{'display_phone_number': '573115893850'}, {'id': 'media'}, MetaError(ambiguous=True)]
        job = dispatch_message(job.pk)
        self.assertEqual(job.status, 'uncertain')
        dispatch_message(job.pk)
        self.assertEqual(meta.call_count, 3)
        self.client.post(f'/whatsapp/envios/{job.pk}/reintentar/')
        job.refresh_from_db()
        self.assertEqual(job.status, 'uncertain')
        self.client.post(f'/whatsapp/envios/{job.pk}/reintentar/', {'confirm_uncertain': 'yes'})
        job.refresh_from_db()
        self.assertEqual(job.status, 'pending')

    @override_settings(WHATSAPP_APP_SECRET='test-app-secret', WHATSAPP_PHONE_NUMBER_ID='123456')
    def test_webhook_authenticated_monotonic_and_private_recipient(self):
        job = self.sale().whatsapp_messages.get()
        job.status, job.provider_id = 'accepted', 'wamid.test'
        job.save()
        self.assertEqual(self.client.post('/api/whatsapp/webhook/', '{}', content_type='application/json').status_code, 403)
        self.webhook(job, recipient_id='573000000000')
        job.refresh_from_db()
        self.assertEqual(job.status, 'accepted')
        self.assertEqual(self.webhook(job).status_code, 200)
        job.refresh_from_db()
        self.assertEqual(job.status, 'delivered')
        self.webhook(job, status='sent')
        self.webhook(job, status='failed')
        job.refresh_from_db()
        self.assertEqual(job.status, 'delivered')
        self.webhook(job, status='read')
        job.refresh_from_db()
        self.assertEqual(job.status, 'read')
        count = Audit.objects.filter(action='Confirmación WhatsApp').count()
        self.webhook(job, status='read')
        self.assertEqual(Audit.objects.filter(action='Confirmación WhatsApp').count(), count)

    @override_settings(WHATSAPP_APP_SECRET='test-app-secret', WHATSAPP_PHONE_NUMBER_ID='123456')
    def test_webhook_reconciles_lost_http_response_using_job_id(self):
        job = self.sale().whatsapp_messages.get()
        job.status = 'uncertain'
        job.save()
        self.webhook(job)
        job.refresh_from_db()
        self.assertEqual(job.status, 'delivered')
        self.assertEqual(job.provider_id, 'wamid.callback')

    @override_settings(WHATSAPP_APP_SECRET='test-app-secret', WHATSAPP_PHONE_NUMBER_ID='123456')
    def test_old_attempt_callback_does_not_overwrite_new_attempt(self):
        job = self.sale().whatsapp_messages.get()
        job.status, job.attempts = 'processing', 2
        job.save()
        self.webhook(job, biz_opaque_callback_data=f'{job.pk}:1')
        job.refresh_from_db()
        self.assertEqual(job.status, 'processing')

    def test_cannot_cancel_payroll_during_active_send(self):
        p = self.payroll()
        p.whatsapp_messages.update(status='processing')
        with self.assertRaises(ValidationError):
            payroll_transition(p.pk, 'cancel', 'Error', self.user)
        self.assertTrue(p.expense_entry.active)

    def test_access_csrf_and_no_cross_financial_permissions(self):
        sale = self.sale()
        job = sale.whatsapp_messages.get()
        viewer = get_user_model().objects.create_user('limited-viewer')
        viewer.user_permissions.add(Permission.objects.get(codename='send_whatsappmessage', content_type__app_label='ledger'))
        self.client.force_login(viewer)
        self.assertEqual(self.client.post(f'/whatsapp/envios/{job.pk}/procesar/').status_code, 403)
        secure = Client(enforce_csrf_checks=True)
        secure.force_login(self.user)
        self.assertEqual(secure.post(f'/whatsapp/envios/{job.pk}/procesar/').status_code, 403)
        self.assertEqual(self.client.get('/api/whatsapp/cola/').status_code, 403)

    @override_settings(CRON_SECRET='cron-test-'*8, WHATSAPP_ENABLED=False)
    def test_cron_authorization_and_disabled_state(self):
        self.assertEqual(self.client.get('/api/whatsapp/cola/').status_code, 403)
        response = self.client.get('/api/whatsapp/cola/', HTTP_AUTHORIZATION='Bearer '+settings.CRON_SECRET)
        self.assertEqual(response.json(), {'pending_configuration': True})

    def test_paid_generate_form_and_queue_pages_render(self):
        save_attendance(self.day, [dict(worker=self.a.pk, worked=True, hours=0, minutes=0, revision=0, notes='')], self.user)
        data = {'start': self.day, 'end': self.day, 'token': uuid.uuid4(), 'paid': 'on'}
        self.assertContains(self.client.post('/nomina/generar/', data), 'Seleccione cómo se pagó')
        data['payment_method'] = self.cash.pk
        response = self.client.post('/nomina/generar/', data)
        self.assertEqual(response.status_code, 302)
        p = Payroll.objects.get()
        page = self.client.get(f'/nomina/{p.pk}/')
        self.assertContains(page, 'Compartir PDF y total')
        self.assertContains(page, 'Descargar PDF individual')
        self.assertContains(page, 'Gasto NO-')
        self.assertEqual(self.client.get(f'/ventas/{self.sale().pk}/').status_code, 200)


    @override_settings(WHATSAPP_ENABLED=False)
    def test_manual_sale_sharing_needs_no_api_or_opt_in(self):
        self.customer.whatsapp_opt_in = False
        self.customer.save()
        sale = self.sale()
        page = self.client.get(f'/ventas/{sale.pk}/')
        self.assertContains(page, 'WhatsApp normal')
        self.assertContains(page, 'PDF y total')
        self.assertNotContains(page, 'Falta activar WhatsApp Business Platform')
        message = page.context['sale_share_message']
        self.assertIn('Total de la venta: $ 50.000,00', message)
        self.assertIn(str(sale), message)
        self.assertContains(page, 'data-share-text=')
        from urllib.parse import urlparse, parse_qs
        chat_message = parse_qs(urlparse(page.context['whatsapp_url']).query)['text'][0]
        self.assertEqual(message, chat_message)
        self.assertFalse(sale.whatsapp_messages.exists())

    @override_settings(WHATSAPP_ENABLED=False)
    def test_historical_payroll_can_share_each_total_without_jobs_or_api(self):
        p = self.payroll(paid=True)
        p.whatsapp_messages.all().delete()
        page = self.client.get(f'/nomina/{p.pk}/')
        rows = page.context['wa_manual_workers']
        self.assertEqual(len(rows), 2)
        first = next(w for w in rows if w['worker_id'] == self.a.pk)
        self.assertIn(self.a.name, first['message'])
        self.assertNotIn(self.b.name, first['message'])
        self.assertIn('Total pagado: $ 65.000,00', first['message'])
        self.assertNotIn('105.000', first['message'])
        self.assertIn(f'/trabajador/{self.a.pk}/pdf/', first['pdf_url'])
        self.assertIn('573001234567', first['chat_url'])
        self.assertNotContains(page, 'Falta activar WhatsApp Business Platform')
        self.assertNotContains(page, 'Revisar / reintentar envío automático')

    def test_manual_unpaid_payroll_does_not_claim_paid_total(self):
        p = self.payroll()
        page = self.client.get(f'/nomina/{p.pk}/')
        for row in page.context['wa_manual_workers']:
            self.assertIn('pago pendiente', row['message'])
            self.assertNotIn('Total pagado', row['message'])
