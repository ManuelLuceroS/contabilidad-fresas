"""Entidades agrícolas adicionales; el historial contable existente no se altera."""
import uuid
from datetime import timedelta
from decimal import Decimal
from django.db import models
from django.db.models import Q
from django.conf import settings
from django.core.validators import MinValueValidator
from django.utils import timezone
from .models import Timestamp


def money(label):
    return models.DecimalField(label, max_digits=14, decimal_places=2, validators=[MinValueValidator(0)])


class Worker(Timestamp):
    name = models.CharField('Nombre completo', max_length=180)
    identification = models.CharField('Identificación', max_length=40, blank=True)
    occupation = models.CharField('Cargo u ocupación', max_length=100, blank=True)
    joined_on = models.DateField('Fecha de ingreso', default=timezone.localdate)
    daily_rate = money('Valor del día (COP)')
    active = models.BooleanField('Activo', default=True)
    notes = models.TextField('Observaciones', blank=True)
    revision = models.PositiveIntegerField(default=0)

    def __str__(self):
        return self.name

    class Meta:
        ordering = ['name', 'pk']
        constraints = [models.CheckConstraint(condition=Q(daily_rate__gte=0), name='worker_rate_nonnegative')]


class PayrollSettings(Timestamp):
    mode = models.CharField('Regla para extras', max_length=12, choices=[('hourly', 'Tarifa por hora explícita'), ('derived', 'Valor día / horas ordinarias × factor')])
    hourly_rate = models.DecimalField('Tarifa extra por hora (COP)', max_digits=14, decimal_places=2, null=True, blank=True, validators=[MinValueValidator(0)])
    ordinary_hours = models.DecimalField('Horas ordinarias por día', max_digits=5, decimal_places=2, null=True, blank=True, validators=[MinValueValidator(Decimal('.01'))])
    multiplier = models.DecimalField('Factor definido por el administrador', max_digits=6, decimal_places=3, null=True, blank=True, validators=[MinValueValidator(0)])
    revision = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=Q(pk=1), name='payroll_settings_singleton'),
            models.CheckConstraint(condition=(Q(mode='hourly', hourly_rate__gte=0, hourly_rate__isnull=False)
                | Q(mode='derived', ordinary_hours__gt=0, ordinary_hours__isnull=False,
                    multiplier__gte=0, multiplier__isnull=False)), name='payroll_settings_valid_rule'),
        ]


class Attendance(Timestamp):
    worker = models.ForeignKey(Worker, on_delete=models.PROTECT, related_name='attendance')
    date = models.DateField('Fecha')
    worked = models.BooleanField('Trabajó', default=False)
    extra_minutes = models.PositiveIntegerField(default=0)
    daily_rate = money('Tarifa diaria histórica')
    hourly_rate = models.DecimalField(max_digits=20, decimal_places=8)
    rate_rule = models.JSONField(default=dict)
    notes = models.TextField(blank=True)
    revision = models.PositiveIntegerField(default=0)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)

    class Meta:
        ordering = ['date', 'worker__name']
        constraints = [
            models.UniqueConstraint(fields=['worker', 'date'], name='attendance_worker_date_unique'),
            models.CheckConstraint(condition=Q(worked=True) | Q(extra_minutes=0), name='attendance_no_absent_extras'),
            models.CheckConstraint(condition=Q(daily_rate__gte=0, hourly_rate__gte=0, extra_minutes__lte=1440), name='attendance_valid_rates'),
        ]


class Payroll(Timestamp):
    token = models.UUIDField(default=uuid.uuid4, unique=True)
    start = models.DateField('Fecha inicial')
    end = models.DateField('Fecha final')
    status = models.CharField(max_length=12, choices=[('generated', 'Generada'), ('paid', 'Pagada'), ('cancelled', 'Anulada')], default='generated')
    total = models.DecimalField(max_digits=14, decimal_places=2)
    paid_at = models.DateTimeField(null=True, blank=True)
    cancellation_reason = models.TextField(blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)

    class Meta:
        ordering = ['-created_at']
        constraints = [models.CheckConstraint(condition=Q(start__lte=models.F('end'), total__gte=0), name='payroll_valid_period')]


class PayrollDay(models.Model):
    payroll = models.ForeignKey(Payroll, on_delete=models.PROTECT, related_name='days')
    attendance = models.ForeignKey(Attendance, on_delete=models.PROTECT, related_name='payroll_days')
    snapshot = models.JSONField()

    class Meta:
        constraints = [models.UniqueConstraint(fields=['payroll', 'attendance'], name='payroll_attendance_unique')]


class SprayProduct(Timestamp):
    name = models.CharField('Nombre comercial', max_length=180)
    ingredient = models.CharField('Ingrediente activo', max_length=180, blank=True)
    category = models.CharField('Tipo o categoría', max_length=100, blank=True)
    unit = models.CharField('Presentación o unidad', max_length=60)
    interval_days = models.PositiveIntegerField('Intervalo autorizado (días)', null=True, blank=True, validators=[MinValueValidator(1)])
    interval_source = models.CharField('Etiqueta o responsable que define el intervalo', max_length=240, blank=True)
    notes = models.TextField('Observaciones y restricciones de uso', blank=True)
    active = models.BooleanField('Activo', default=True)
    revision = models.PositiveIntegerField(default=0)

    def __str__(self):
        return self.name

    class Meta:
        ordering = ['name']
        constraints = [models.CheckConstraint(condition=Q(interval_days__isnull=True) | Q(interval_days__gt=0), name='spray_interval_positive')]


class SprayApplication(Timestamp):
    token = models.UUIDField(default=uuid.uuid4, unique=True)
    scheduled_at = models.DateTimeField('Fecha y hora')
    completed_at = models.DateTimeField('Aplicación confirmada', null=True, blank=True)
    area = models.CharField('Lote, finca o área', max_length=180)
    responsible = models.CharField('Responsable', max_length=180)
    status = models.CharField('Estado', max_length=12, choices=[('scheduled', 'Programada'), ('completed', 'Realizada'), ('cancelled', 'Anulada')])
    notes = models.TextField('Observaciones', blank=True)
    source = models.ForeignKey('self', on_delete=models.PROTECT, null=True, blank=True, related_name='followups')
    revision = models.PositiveIntegerField(default=0)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)

    class Meta:
        ordering = ['-scheduled_at']
        constraints = [models.CheckConstraint(condition=Q(status='completed', completed_at__isnull=False) | Q(status__in=['scheduled', 'cancelled'], completed_at__isnull=True), name='spray_confirmation_required')]

    @property
    def overdue(self):
        return self.status == 'scheduled' and self.scheduled_at < timezone.now()

    @property
    def due_soon(self):
        now = timezone.now()
        return self.status == 'scheduled' and now <= self.scheduled_at <= now + timedelta(days=3)


class SprayLine(models.Model):
    application = models.ForeignKey(SprayApplication, on_delete=models.PROTECT, related_name='lines')
    product = models.ForeignKey(SprayProduct, on_delete=models.PROTECT, related_name='applications')
    name = models.CharField(max_length=180)
    quantity = models.DecimalField('Cantidad', max_digits=14, decimal_places=3, validators=[MinValueValidator(Decimal('.001'))])
    unit = models.CharField('Unidad', max_length=60)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['application', 'product'], name='spray_product_unique'),
            models.CheckConstraint(condition=Q(quantity__gt=0), name='spray_quantity_positive'),
        ]
