"""Entidades contables, saldos calculados y restricciones de integridad."""

import uuid
from decimal import Decimal
from django.db import models
from django.db.models import Q
from django.conf import settings
from django.core.validators import MinValueValidator
from django.utils import timezone


class Timestamp(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class Customer(Timestamp):
    name = models.CharField("Nombre o razón social", max_length=180)
    identification = models.CharField("Identificación", max_length=40, blank=True)
    phone = models.CharField("Teléfono", max_length=40, blank=True)
    address = models.CharField("Dirección", max_length=240, blank=True)
    email = models.EmailField("Correo electrónico", blank=True)
    notes = models.TextField("Observaciones", blank=True)
    active = models.BooleanField("Activo", default=True)
    revision = models.PositiveIntegerField(default=0)

    def __str__(self):
        return self.name

    @property
    def balance(self):
        return sum((s.balance for s in self.sales.all()), Decimal("0"))

    class Meta:
        ordering = ["name"]


class Product(Timestamp):
    name = models.CharField("Nombre", max_length=180)
    code = models.CharField("Código o referencia", max_length=40, blank=True)
    price = models.DecimalField(
        "Precio (COP por unidad o libra)",
        max_digits=14,
        decimal_places=2,
        validators=[MinValueValidator(0)],
    )
    unit = models.CharField("Unidad o presentación", max_length=40, default="unidad")
    by_weight = models.BooleanField("¿Se vende por peso?", default=False)
    variable_weight = models.BooleanField(
        "Ingresar peso por presentación en cada venta", default=False
    )
    weight = models.DecimalField(
        "Peso fijo por presentación (lb)",
        max_digits=12,
        decimal_places=3,
        default=0,
        validators=[MinValueValidator(0)],
    )
    active = models.BooleanField("Activo", default=True)

    def __str__(self):
        return self.name

    class Meta:
        ordering = ["name"]
        constraints = [
            models.CheckConstraint(
                condition=Q(price__gte=0, price__lte=Decimal("999999999999.99"))
                & Q(weight__gte=0, weight__lte=Decimal("999999999.999")),
                name="product_nonnegative",
            )
        ]


class PaymentMethod(Timestamp):
    name = models.CharField("Nombre", max_length=60, unique=True)
    active = models.BooleanField("Activo", default=True)
    is_credit = models.BooleanField("Es crédito (solo ventas)", default=False)

    def __str__(self):
        return self.name


class Sequence(models.Model):
    name = models.CharField(max_length=30, unique=True)
    value = models.PositiveIntegerField(default=0)


class Sale(Timestamp):
    number = models.PositiveIntegerField(unique=True)
    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    customer = models.ForeignKey(
        Customer, on_delete=models.PROTECT, related_name="sales"
    )
    customer_name = models.CharField(max_length=180)
    customer_identification = models.CharField(max_length=40, blank=True)
    occurred_at = models.DateTimeField(default=timezone.now)
    method = models.ForeignKey(PaymentMethod, on_delete=models.PROTECT)
    method_name = models.CharField(max_length=60)
    total = models.DecimalField(max_digits=14, decimal_places=2)
    initial_payment = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)

    @property
    def paid(self):
        return sum((a.amount for a in self.allocations.all()), Decimal("0"))

    @property
    def balance(self):
        return self.total - self.paid

    def __str__(self):
        return f"VE-{self.number:06d}"

    class Meta:
        ordering = ["-occurred_at", "-id"]
        constraints = [
            models.CheckConstraint(
                condition=Q(total__gte=0, total__lte=Decimal("999999999999.99"))
                & Q(initial_payment__gte=0)
                & Q(initial_payment__lte=models.F("total")),
                name="sale_valid_amounts",
            )
        ]


class SaleLine(models.Model):
    sale = models.ForeignKey(Sale, on_delete=models.PROTECT, related_name="lines")
    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    name = models.CharField(max_length=180)
    unit = models.CharField(max_length=40)
    by_weight = models.BooleanField()
    price = models.DecimalField(max_digits=14, decimal_places=2)
    quantity = models.DecimalField(max_digits=12, decimal_places=3)
    weight = models.DecimalField(max_digits=12, decimal_places=3, default=0)
    total_weight = models.DecimalField(max_digits=15, decimal_places=6, default=0)
    subtotal = models.DecimalField(max_digits=14, decimal_places=2)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(quantity__gt=0, quantity__lte=Decimal("999999999.999"))
                & Q(price__gte=0, price__lte=Decimal("999999999999.99"))
                & Q(weight__gte=0, weight__lte=Decimal("999999999.999"))
                & Q(total_weight__gte=0, total_weight__lte=Decimal("999999999.999999"))
                & Q(subtotal__gte=0, subtotal__lte=Decimal("999999999999.99")),
                name="line_valid_amounts",
            )
        ]


class Payment(Timestamp):
    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    customer = models.ForeignKey(
        Customer, on_delete=models.PROTECT, related_name="payments"
    )
    date = models.DateField(default=timezone.localdate)
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    method = models.ForeignKey(PaymentMethod, on_delete=models.PROTECT)
    method_name = models.CharField(max_length=60)
    notes = models.TextField(blank=True)
    initial_sale = models.OneToOneField(
        Sale, null=True, blank=True, on_delete=models.PROTECT
    )
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)

    def __str__(self):
        return f"AB-{self.pk:06d}"

    class Meta:
        ordering = ["date", "id"]
        constraints = [
            models.CheckConstraint(
                condition=Q(amount__gt=0, amount__lte=Decimal("999999999999.99")),
                name="payment_positive",
            )
        ]


class Allocation(models.Model):
    payment = models.ForeignKey(
        Payment, on_delete=models.PROTECT, related_name="allocations"
    )
    sale = models.ForeignKey(Sale, on_delete=models.PROTECT, related_name="allocations")
    amount = models.DecimalField(max_digits=14, decimal_places=2)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["payment", "sale"], name="unique_payment_sale"
            ),
            models.CheckConstraint(
                condition=Q(amount__gt=0, amount__lte=Decimal("999999999999.99")),
                name="allocation_positive",
            ),
        ]


class ExpenseCategory(Timestamp):
    name = models.CharField("Nombre", max_length=100, unique=True)
    description = models.TextField("Descripción", blank=True)
    active = models.BooleanField("Activo", default=True)

    def __str__(self):
        return self.name


class Expense(Timestamp):
    date = models.DateField("Fecha", default=timezone.localdate)
    category = models.ForeignKey(
        ExpenseCategory, verbose_name="Categoría", on_delete=models.PROTECT
    )
    description = models.TextField("Descripción", blank=True)
    amount = models.DecimalField(
        "Valor (COP)",
        max_digits=14,
        decimal_places=2,
        validators=[MinValueValidator(Decimal(".01"))],
    )
    method = models.ForeignKey(
        PaymentMethod, verbose_name="Medio de pago", on_delete=models.PROTECT
    )
    reference = models.CharField("Comprobante o referencia", max_length=100, blank=True)
    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    revision = models.PositiveIntegerField(default=0)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)

    class Meta:
        ordering = ["-date", "-id"]
        constraints = [
            models.CheckConstraint(
                condition=Q(amount__gt=0, amount__lte=Decimal("999999999999.99")),
                name="expense_positive",
            )
        ]


class Audit(models.Model):
    date = models.DateTimeField(auto_now_add=True)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    action = models.CharField(max_length=100)
    entity = models.CharField(max_length=60)
    object_id = models.PositiveBigIntegerField()
    before = models.JSONField(default=dict)
    after = models.JSONField(default=dict)


class LoginAttempt(models.Model):
    key = models.CharField(max_length=64, unique=True)
    failures = models.PositiveIntegerField(default=0)
    last_attempt = models.DateTimeField(default=timezone.now)


class SyncState(models.Model):
    """Estado de la réplica local; no contiene las credenciales de conexión."""
    initialized = models.BooleanField(default=False)
    business = models.CharField(max_length=100, blank=True)
    last_success = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True)


class SyncReceipt(models.Model):
    token = models.UUIDField()
    kind = models.CharField(max_length=20)
    digest = models.CharField(max_length=64, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['kind', 'token'], name='sync_kind_token_unique')]

# Django registra también los modelos agrícolas dentro de la aplicación existente.
from .farm_models import (Worker, PayrollSettings, Attendance, Payroll, PayrollDay,
                          SprayProduct, SprayApplication, SprayLine)  # noqa: E402,F401
