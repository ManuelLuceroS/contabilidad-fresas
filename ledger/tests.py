import uuid
from datetime import timedelta
from decimal import Decimal
from concurrent.futures import ThreadPoolExecutor
from django.test import TestCase, Client, TransactionTestCase
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db import IntegrityError, transaction, close_old_connections, connections
from django.db.models.deletion import ProtectedError
from django.utils import timezone
from .models import (
    Audit,
    Customer,
    Expense,
    ExpenseCategory,
    Payment,
    PaymentMethod,
    Product,
    Sale,
    SaleLine,
)
from .services import create_sale, create_payment, statement, number
from .forms import ProductForm, ExpenseForm


class AccountingTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("initialize", verbosity=0)
        cls.user = get_user_model().objects.create_superuser(
            "admin", "admin@example.com", "Safe-test-927!"
        )
        cls.customer = Customer.objects.create(name="Cliente de prueba")
        cls.berries = Product.objects.create(
            name="Canasta de fresa primera",
            price=2000,
            unit="canasta",
            by_weight=True,
            weight=16,
        )
        cls.box = Product.objects.create(
            name="Caja de producto", price=15000, unit="caja"
        )
        cls.cash = PaymentMethod.objects.get(name="Efectivo")
        cls.credit = PaymentMethod.objects.get(name="Crédito")

    def sale(self, product=None, quantity=10, initial=100000, token=None, weight=None):
        return create_sale(
            user=self.user,
            customer_id=self.customer.pk,
            rows=[
                {
                    "product": (product or self.berries).pk,
                    "quantity": quantity,
                    "weight": weight,
                }
            ],
            method=self.credit,
            initial=initial,
            cash_method=self.cash,
            token=token or uuid.uuid4(),
        )

    def payment(self, amount=70000, token=None, allocation=None, day=None):
        return create_payment(
            user=self.user,
            customer_id=self.customer.pk,
            amount=amount,
            method=self.cash,
            date=day or timezone.localdate(),
            notes="",
            token=token or uuid.uuid4(),
            allocation=allocation,
        )

    def test_A_weight(self):
        s = self.sale(initial=0)
        l = s.lines.get()
        self.assertEqual(l.total_weight, 160)
        self.assertEqual(s.total, 320000)
        self.assertEqual(l.quantity, 10)
        self.assertEqual(l.weight, 16)

    def test_fractional_weight_preserves_exact_product(self):
        self.berries.variable_weight = True
        self.berries.price = 10000
        self.berries.save()
        sale = self.sale(quantity=3, initial=0, weight=".333")
        self.assertEqual(sale.lines.get().total_weight, Decimal(".999"))
        self.assertEqual(sale.total, Decimal("9990.00"))

    def test_B_units(self):
        self.assertEqual(self.sale(self.box, 3, 0).total, 45000)

    def test_C_credit(self):
        s = self.sale()
        self.assertEqual(s.total, 320000)
        self.assertEqual(s.initial_payment, 100000)
        self.assertEqual(s.balance, 220000)

    def test_D_payment(self):
        s = self.sale()
        self.payment()
        self.assertEqual(s.balance, 150000)

    def test_E_statement(self):
        self.sale()
        self.payment()
        opening, events, closing = statement(self.customer)
        self.assertEqual(opening, 0)
        self.assertEqual(closing, 150000)
        self.assertEqual([e["debit"] for e in events], [320000, 0, 0])
        self.assertEqual([e["credit"] for e in events], [0, 100000, 70000])
        self.assertEqual([e["balance"] for e in events], [320000, 220000, 150000])

    def test_F_period_opening_and_reports(self):
        s = self.sale()
        yesterday = timezone.localdate() - timedelta(days=1)
        Sale.objects.filter(pk=s.pk).update(
            occurred_at=timezone.now() - timedelta(days=1)
        )
        Payment.objects.filter(initial_sale=s).update(date=yesterday)
        self.payment()
        opening, events, closing = statement(
            self.customer, timezone.localdate(), timezone.localdate()
        )
        self.assertEqual(opening, 220000)
        self.assertEqual(len(events), 1)
        self.assertEqual(closing, 150000)
        self.client.force_login(self.user)
        today = timezone.localdate().isoformat()
        response = self.client.get("/reportes/", {"start": today, "end": today})
        self.assertEqual(len(response.context["sales"]), 0)
        account = self.client.get(
            f"/clientes/{self.customer.pk}/estado/", {"start": today, "end": today}
        )
        self.assertEqual(account.context["period_payments"], 70000)
        self.assertEqual(response.context["report"]["total"], 0)

    def test_G_expenses(self):
        self.client.force_login(self.user)
        for amount in [50000, 30000]:
            r = self.client.post(
                "/gastos/nuevo/",
                {
                    "date": timezone.localdate(),
                    "category": ExpenseCategory.objects.first().pk,
                    "amount": amount,
                    "method": self.cash.pk,
                    "token": uuid.uuid4(),
                    "revision": 0,
                },
            )
            self.assertEqual(r.status_code, 302)
        r = self.client.get("/gastos/")
        self.assertEqual(r.context["total"], 80000)
        self.assertEqual(len(r.context["expenses"]), 2)

    def test_duplicate_sale(self):
        token = uuid.uuid4()
        a = self.sale(token=token)
        b = self.sale(token=token)
        self.assertEqual(a.pk, b.pk)
        self.assertEqual(Sale.objects.count(), 1)
        self.assertEqual(Payment.objects.count(), 1)

    def test_duplicate_payment(self):
        s = self.sale()
        token = uuid.uuid4()
        a = self.payment(token=token)
        b = self.payment(token=token)
        self.assertEqual(a.pk, b.pk)
        self.assertEqual(s.balance, 150000)

    def test_negative_and_nonfinite_inputs(self):
        for value in [-1, "NaN", "Infinity", "-Infinity", "hello", "1.001"]:
            with self.subTest(value=value), self.assertRaises(ValidationError):
                number(value)
        self.assertEqual(number(0), 0)

    def test_zero_and_negative_quantity_rejected(self):
        for qty in [0, -1, "NaN"]:
            with self.subTest(qty=qty), self.assertRaises(ValidationError):
                self.sale(quantity=qty)
        self.assertEqual(Sale.objects.count(), 0)

    def test_overpayment_rollback(self):
        s = self.sale()
        for amount in [220001, 0, -1]:
            with self.subTest(amount=amount), self.assertRaises(ValidationError):
                self.payment(amount)
        self.assertEqual(s.balance, 220000)
        self.assertEqual(Payment.objects.count(), 1)

    def test_initial_overpayment(self):
        with self.assertRaises(ValidationError):
            self.sale(initial=400000)
        self.assertFalse(Sale.objects.exists())
        self.assertFalse(Payment.objects.exists())

    def test_product_snapshot(self):
        s = self.sale()
        self.berries.price = 9000
        self.berries.weight = 8
        self.berries.name = "Otro nombre"
        self.berries.save()
        line = s.lines.get()
        self.assertEqual(line.name, "Canasta de fresa primera")
        self.assertEqual(line.price, 2000)
        self.assertEqual(line.weight, 16)
        self.assertEqual(s.total, 320000)

    def test_variable_weight(self):
        self.berries.variable_weight = True
        self.berries.save()
        self.assertEqual(self.sale(initial=0, weight=17).total, 340000)
        with self.assertRaises(ValidationError):
            self.sale(weight=0)

    def test_manual_distribution_rejected(self):
        a = self.sale()
        b = self.sale(self.box, 3, 0)
        with self.assertRaises(ValidationError):
            self.payment(50000, allocation={str(a.pk): 30000, str(b.pk): 20000})
        self.assertEqual(a.balance, 220000)
        self.assertEqual(b.balance, 45000)

    def test_invalid_distribution(self):
        a = self.sale()
        other = Customer.objects.create(name="Otro")
        b = create_sale(
            user=self.user,
            customer_id=other.pk,
            rows=[{"product": self.box.pk, "quantity": 1}],
            method=self.credit,
            initial=0,
            cash_method=None,
            token=uuid.uuid4(),
        )
        for allocation in [{str(a.pk): 1}, {str(b.pk): 70000}, {str(a.pk): 300000}]:
            with self.subTest(allocation=allocation), self.assertRaises(
                ValidationError
            ):
                self.payment(allocation=allocation)
        self.assertEqual(a.balance, 220000)

    def test_fifo(self):
        a = self.sale()
        b = self.sale(self.box, 3, 0)
        p = self.payment(240000)
        self.assertEqual(a.balance, 0)
        self.assertEqual(b.balance, 25000)
        self.assertEqual(sum(x.amount for x in p.allocations.all()), 240000)

    def test_inactive_customer_and_product(self):
        self.customer.active = False
        self.customer.save()
        with self.assertRaises(ValidationError):
            self.sale()
        self.customer.active = True
        self.customer.save()
        self.berries.active = False
        self.berries.save()
        with self.assertRaises(ValidationError):
            self.sale()

    def test_protected_history(self):
        self.sale()
        with self.assertRaises(ProtectedError):
            self.customer.delete()
        with self.assertRaises(ProtectedError):
            self.berries.delete()
        with self.assertRaises(ProtectedError):
            self.cash.delete()

    def test_future_and_precreation_payment(self):
        self.sale()
        for day in [
            timezone.localdate() + timedelta(days=1),
            timezone.localdate() - timedelta(days=2),
        ]:
            with self.assertRaises(ValidationError):
                self.payment(day=day)

    def test_backdated_payment_not_before_sale(self):
        self.sale()
        Customer.objects.filter(pk=self.customer.pk).update(
            created_at=timezone.now() - timedelta(days=10)
        )
        with self.assertRaises(ValidationError):
            self.payment(day=timezone.localdate() - timedelta(days=1))

    def test_unique_consecutive(self):
        a = self.sale()
        b = self.sale()
        self.assertEqual(b.number, a.number + 1)

    def test_complete_transaction_rollback(self):
        with self.assertRaises(ValidationError):
            create_sale(
                user=self.user,
                customer_id=self.customer.pk,
                rows=[
                    {"product": self.box.pk, "quantity": 3},
                    {"product": self.berries.pk, "quantity": -1},
                ],
                method=self.credit,
                initial=0,
                cash_method=None,
                token=uuid.uuid4(),
            )
        self.assertEqual(Sale.objects.count(), 0)
        self.assertEqual(SaleLine.objects.count(), 0)

    def test_product_form_fixed_weight(self):
        f = ProductForm(
            {
                "name": "Prueba",
                "price": 2000,
                "unit": "canasta",
                "by_weight": True,
                "weight": 0,
                "active": True,
            }
        )
        self.assertFalse(f.is_valid())
        self.assertIn("weight", f.errors)

    def test_expense_validation_and_audit(self):
        self.client.force_login(self.user)
        data = {
            "date": timezone.localdate(),
            "category": ExpenseCategory.objects.first().pk,
            "amount": 0,
            "method": self.cash.pk,
            "token": uuid.uuid4(),
            "revision": 0,
        }
        self.assertFalse(ExpenseForm(data).is_valid())
        data["amount"] = 50000
        self.client.post("/gastos/nuevo/", data)
        self.client.post("/gastos/nuevo/", data)
        self.assertEqual(Expense.objects.count(), 1)
        expense = Expense.objects.get()
        data["amount"] = 30000
        data["revision"] = expense.revision
        self.client.post(f"/gastos/{expense.pk}/editar/", data)
        expense.refresh_from_db()
        self.assertEqual(expense.amount, 30000)
        self.assertEqual(Audit.objects.filter(entity="ledger.Expense").count(), 2)
        data["amount"] = 99999
        r = self.client.post(f"/gastos/{expense.pk}/editar/", data)
        self.assertEqual(r.status_code, 200)
        expense.refresh_from_db()
        self.assertEqual(expense.amount, 30000)

    def test_auth_username_email_logout(self):
        self.assertTrue(
            self.client.login(username="ADMIN@EXAMPLE.COM", password="Safe-test-927!")
        )
        self.assertEqual(self.client.get("/").status_code, 200)
        self.assertEqual(self.client.get("/salir/").status_code, 405)
        self.assertEqual(self.client.post("/salir/").status_code, 302)
        self.assertEqual(self.client.get("/").status_code, 302)

    def test_permissions(self):
        u = get_user_model().objects.create_user("limited", password="Safe-test-927!")
        self.client.force_login(u)
        for path in [
            "/",
            "/ventas/",
            "/cartera/",
            "/clientes/",
            "/gastos/",
            "/ventas/nueva/",
        ]:
            self.assertEqual(self.client.get(path).status_code, 403, path)

    def test_csrf(self):
        c = Client(enforce_csrf_checks=True)
        c.force_login(self.user)
        self.assertEqual(
            c.post("/clientes/nuevo/", {"name": "Sin csrf"}).status_code, 403
        )

    def test_throttle(self):
        for _ in range(6):
            self.client.post(
                "/ingresar/", {"username": "admin", "password": "incorrecta"}
            )
        r = self.client.post(
            "/ingresar/", {"username": "admin", "password": "Safe-test-927!"}
        )
        self.assertContains(r, "Demasiados intentos")

    def test_all_pages_and_exports(self):
        s = self.sale()
        p = self.payment()
        self.client.force_login(self.user)
        for path in [
            "/",
            "/clientes/",
            "/productos/",
            "/categorias/",
            "/medios/",
            "/clientes/nuevo/",
            "/productos/nuevo/",
            "/categorias/nuevo/",
            "/medios/nuevo/",
            "/gastos/",
            "/gastos/nuevo/",
            "/ventas/",
            "/reportes/",
            "/ventas/nueva/",
            "/cartera/",
            f"/abonos/nuevo/?customer={self.customer.pk}",
            f"/clientes/{self.customer.pk}/estado/",
            f"/ventas/{s.pk}/",
            f"/abonos/{p.pk}/",
        ]:
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 200)
        for path in [
            "/ventas/",
            "/gastos/",
            f"/clientes/{self.customer.pk}/estado/",
            f"/ventas/{s.pk}/",
            f"/abonos/{p.pk}/",
        ]:
            response = self.client.get(path, {"export": "pdf"})
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.content.startswith(b"%PDF"))
        self.assertIn(
            "text/csv", self.client.get("/ventas/", {"export": "csv"})["Content-Type"]
        )

    def test_invalid_filters_return_404(self):
        self.client.force_login(self.user)
        for url in [
            "/reportes/?customer=abc",
            "/gastos/?category=abc",
            "/abonos/nuevo/?customer=abc",
        ]:
            self.assertEqual(self.client.get(url).status_code, 404)

    def test_manual_empty_distribution_rejected(self):
        self.sale()
        with self.assertRaises(ValidationError):
            self.payment(allocation={})

    def test_same_name_customers_not_merged(self):
        self.sale()
        other = Customer.objects.create(name=self.customer.name)
        create_sale(
            user=self.user,
            customer_id=other.pk,
            rows=[{"product": self.box.pk, "quantity": 1}],
            method=self.credit,
            initial=0,
            cash_method=None,
            token=uuid.uuid4(),
        )
        self.client.force_login(self.user)
        self.assertEqual(len(self.client.get("/reportes/").context["groups"]), 2)

    def test_expense_category_cannot_delete_and_backup(self):
        category = ExpenseCategory.objects.first()
        Expense.objects.create(
            category=category, amount=1, method=self.cash, created_by=self.user
        )
        with self.assertRaises(ProtectedError):
            category.delete()

    def test_fractional_quantities_rejected(self):
        for product in [self.berries, self.box]:
            for quantity in ["1.5", ".333"]:
                with self.subTest(
                    product=product.name, quantity=quantity
                ), self.assertRaises(ValidationError):
                    self.sale(product, quantity, 0)
        self.assertFalse(Sale.objects.exists())

    def test_statement_interleaves_sales_and_payments(self):
        first = self.sale()
        initial = Payment.objects.get(initial_sale=first)
        second = self.sale(self.box, 3, 0)
        payment = self.payment(10000)
        third = self.sale(self.box, 1, 0)
        _, events, closing = statement(self.customer)
        self.assertEqual(
            [e["reference"] for e in events],
            [str(first), str(initial), str(second), str(payment), str(third)],
        )
        self.assertEqual(
            [e["balance"] for e in events], [320000, 220000, 265000, 255000, 270000]
        )
        self.assertEqual(closing, self.customer.balance)

    def test_forged_manual_post_still_applies_oldest_first(self):
        first = self.sale()
        second = self.sale(self.box, 3, 0)
        self.client.force_login(self.user)
        response = self.client.post(
            "/abonos/nuevo/",
            {
                "customer": self.customer.pk,
                "amount": 30000,
                "method": self.cash.pk,
                "date": timezone.localdate(),
                "token": uuid.uuid4(),
                "distribution": "manual",
                f"apply_{second.pk}": 30000,
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(first.balance, 190000)
        self.assertEqual(second.balance, 45000)

    def test_product_weight_optional_for_units_and_variable(self):
        for values in [{}, {"by_weight": True, "variable_weight": True}]:
            form = ProductForm(
                {
                    "name": "Nuevo",
                    "price": 1000,
                    "unit": "caja",
                    "active": True,
                    **values,
                }
            )
            self.assertTrue(form.is_valid(), form.errors)
            self.assertEqual(form.save().weight, 0)

    def test_expense_reference_hidden_and_history_retained(self):
        expense = Expense.objects.create(
            category=ExpenseCategory.objects.first(),
            amount=50000,
            method=self.cash,
            reference="Anterior",
            created_by=self.user,
        )
        form = ExpenseForm(
            {
                "date": timezone.localdate(),
                "category": expense.category_id,
                "amount": 30000,
                "method": self.cash.pk,
                "revision": 0,
            },
            instance=expense,
        )
        self.assertNotIn("reference", form.fields)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.save().reference, "Anterior")

    def test_sales_pdf_grouped_details_and_compact_numbers(self):
        from io import BytesIO
        from pypdf import PdfReader

        self.sale()
        self.sale(self.box, 3, 0)
        self.client.force_login(self.user)
        response = self.client.get("/reportes/", {"export": "pdf"})
        text = " ".join(
            page.extract_text() for page in PdfReader(BytesIO(response.content)).pages
        )
        for expected in [
            "Cantidad",
            "Libras totales",
            "Canasta de fresa primera",
            "Caja de producto",
            "160",
            "10",
            "3",
            "VE-000001",
            "VE-000002",
        ]:
            self.assertIn(expected, text)
        self.assertNotIn("10.000", text)
        self.assertNotIn("160.000000", text)
        csv = self.client.get("/reportes/", {"export": "csv"}).content.decode(
            "utf-8-sig"
        )
        self.assertIn("Libras totales", csv)
        self.assertIn(";10;160;", csv)
        self.assertIn(";3;;", csv)

    def test_product_summary_multiple_sales_filters_and_snapshots(self):
        first = self.sale(initial=0)
        self.sale(quantity=2, initial=0)
        self.sale(self.box, 3, 0)
        self.berries.price = 3000
        self.berries.weight = 20
        self.berries.name = "Fresa actualizada"
        self.berries.save()
        self.sale(quantity=1, initial=0)
        old = self.sale(self.box, 7, 0)
        Sale.objects.filter(pk=old.pk).update(
            occurred_at=timezone.now() - timedelta(days=3)
        )
        other = Customer.objects.create(name="Otro cliente")
        create_sale(
            user=self.user,
            customer_id=other.pk,
            rows=[{"product": self.box.pk, "quantity": 99}],
            method=self.credit,
            initial=0,
            cash_method=None,
            token=uuid.uuid4(),
        )
        self.client.force_login(self.user)
        today = timezone.localdate().isoformat()
        response = self.client.get(
            "/reportes/", {"start": today, "end": today, "customer": self.customer.pk}
        )
        report = response.context["report"]
        self.assertEqual(report["count"], 4)
        self.assertEqual(report["quantity"], 16)
        self.assertEqual(report["weight"], 212)
        self.assertEqual(report["total"], 489000)
        self.assertEqual(sum(r["total"] for r in report["products"]), report["total"])
        berry = next(
            r for r in report["products"] if r["product_id"] == self.berries.pk
        )
        self.assertEqual(
            (berry["quantity"], berry["weight"], berry["total"]), (13, 212, 444000)
        )
        self.assertEqual(first.lines.get().name, "Canasta de fresa primera")

    def test_sales_only_exports_with_final_summary(self):
        from io import BytesIO
        from pypdf import PdfReader

        self.sale()
        self.payment()
        self.sale(self.box, 3, 0)
        self.client.force_login(self.user)
        response = self.client.get("/reportes/")
        self.assertContains(response, "Resumen general por producto")
        self.assertNotContains(response, "Saldo actual")
        self.assertNotContains(response, "Recaudos por fecha")
        self.assertContains(response, "TOTAL GENERAL VENDIDO")
        pdf = self.client.get("/reportes/", {"export": "pdf"})
        text = " ".join(p.extract_text() for p in PdfReader(BytesIO(pdf.content)).pages)
        for phrase in [
            "Resumen general por producto",
            "TOTAL DE LA VENTA",
            "TOTAL GENERAL VENDIDO",
            "$ 365.000,00",
        ]:
            self.assertIn(phrase, text)
        for phrase in [
            "Saldo",
            "abonado",
            "Abonos",
            "Recaudos",
            "Presentación",
            "Pago inicial",
        ]:
            self.assertNotIn(phrase, text)
        csv = self.client.get("/reportes/", {"export": "csv"}).content.decode(
            "utf-8-sig"
        )
        for phrase in [
            "TOTAL VENTA",
            "RESUMEN GENERAL POR PRODUCTO",
            "TOTAL GENERAL",
            "365.000,00",
        ]:
            self.assertIn(phrase, csv)
        for phrase in ["Saldo", "Abonos", "Presentación"]:
            self.assertNotIn(phrase, csv)

    def test_account_footers_use_closing_balance_not_sum_of_balances(self):
        self.sale()
        self.payment()
        self.sale(self.box, 3, 0)
        self.client.force_login(self.user)
        response = self.client.get(f"/clientes/{self.customer.pk}/estado/")
        self.assertEqual(response.context["period_sales"], 365000)
        self.assertEqual(response.context["period_payments"], 170000)
        self.assertEqual(response.context["closing"], 195000)
        self.assertEqual(response.context["history_sold"], 365000)
        self.assertEqual(response.context["history_received"], 170000)
        csv = self.client.get(
            f"/clientes/{self.customer.pk}/estado/", {"export": "csv"}
        ).content.decode("utf-8-sig")
        self.assertEqual(
            csv.strip().splitlines()[-1],
            "Totales del periodo;;;$ 365.000,00;$ 170.000,00;$ 195.000,00",
        )

    def test_receivable_and_receipt_footers_reconcile(self):
        sale = self.sale()
        p = self.payment()
        self.client.force_login(self.user)
        r = self.client.get("/cartera/")
        self.assertEqual(r.context["sold_total"], 320000)
        self.assertEqual(r.context["received_total"], 170000)
        self.assertEqual(r.context["total"], 150000)
        self.assertContains(r, "TOTALES DE LA CONSULTA")
        self.assertContains(self.client.get(f"/ventas/{sale.pk}/"), "TOTAL ABONADO")
        self.assertContains(self.client.get(f"/abonos/{p.pk}/"), "TOTAL APLICADO")

    def test_multi_page_sales_pdf_preserves_all_sales_and_final_totals(self):
        from io import BytesIO
        from pypdf import PdfReader

        for _ in range(35):
            self.sale(self.box, 1, 0)
        self.client.force_login(self.user)
        response = self.client.get("/reportes/", {"export": "pdf"})
        pages = PdfReader(BytesIO(response.content)).pages
        text = " ".join(p.extract_text() for p in pages)
        self.assertGreater(len(pages), 1)
        self.assertEqual(text.count("TOTAL DE LA VENTA"), 35)
        self.assertIn("TOTAL GENERAL VENDIDO", pages[-1].extract_text())
        self.assertIn("Caja de producto", pages[-1].extract_text())
        self.assertIn("$ 525.000,00", pages[-1].extract_text())

    def test_empty_report_totals_and_no_price_sums(self):
        self.client.force_login(self.user)
        r = self.client.get("/reportes/")
        self.assertEqual(r.context["report"]["quantity"], 0)
        self.assertEqual(r.context["report"]["weight"], 0)
        self.assertEqual(r.context["report"]["products"], [])
        self.assertContains(r, "TOTAL GENERAL VENDIDO")
        self.assertTrue(
            self.client.get("/reportes/", {"export": "pdf"}).content.startswith(b"%PDF")
        )

    def test_single_user_navigation(self):
        self.client.force_login(self.user)
        self.assertNotContains(self.client.get("/"), "Usuarios y acceso")

    def test_private_cache_headers(self):
        self.client.force_login(self.user)
        self.assertIn("no-store", self.client.get("/")["Cache-Control"])

    def test_db_negative_constraint(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Product.objects.create(name="Invalido", price=-1, weight=0)


class ConcurrentPaymentsTests(TransactionTestCase):
    def test_duplicate_concurrent_payments(self):
        call_command("initialize", verbosity=0)
        user = get_user_model().objects.create_user("race")
        customer = Customer.objects.create(name="Concurrente")
        product = Product.objects.create(name="Producto", price=100000)
        cash = PaymentMethod.objects.get(name="Efectivo")
        credit = PaymentMethod.objects.get(name="Crédito")
        sale = create_sale(
            user=user,
            customer_id=customer.pk,
            rows=[{"product": product.pk, "quantity": 1}],
            method=credit,
            initial=0,
            cash_method=None,
            token=uuid.uuid4(),
        )
        token = uuid.uuid4()

        def pay(_):
            close_old_connections()
            try:
                return create_payment(
                    user=user,
                    customer_id=customer.pk,
                    amount=70000,
                    method=cash,
                    date=timezone.localdate(),
                    notes="",
                    token=token,
                ).pk
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(pay, range(2)))
        self.assertEqual(results[0], results[1])
        self.assertEqual(sale.balance, 30000)

    def test_distinct_concurrent_overpayments(self):
        call_command("initialize", verbosity=0)
        user = get_user_model().objects.create_user("parallel")
        customer = Customer.objects.create(name="Paralelo")
        product = Product.objects.create(name="Producto", price=100000)
        cash = PaymentMethod.objects.get(name="Efectivo")
        credit = PaymentMethod.objects.get(name="Crédito")
        sale = create_sale(
            user=user,
            customer_id=customer.pk,
            rows=[{"product": product.pk, "quantity": 1}],
            method=credit,
            initial=0,
            cash_method=None,
            token=uuid.uuid4(),
        )

        def pay(_):
            close_old_connections()
            try:
                create_payment(
                    user=user,
                    customer_id=customer.pk,
                    amount=70000,
                    method=cash,
                    date=timezone.localdate(),
                    notes="",
                    token=uuid.uuid4(),
                )
                return "ok"
            except ValidationError:
                return "rejected"
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(pay, range(2)))
        self.assertEqual(sorted(results), ["ok", "rejected"])
        self.assertEqual(sale.balance, 30000)
