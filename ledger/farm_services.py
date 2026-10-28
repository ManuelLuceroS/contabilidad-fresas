"""Operaciones serializadas y auditadas de nómina y fumigación."""
import json
from uuid import uuid5
from collections import OrderedDict
from decimal import Decimal, ROUND_HALF_UP
from django.core.exceptions import ValidationError
from django.core.serializers.json import DjangoJSONEncoder
from django.db import transaction
from django.db.models import F
from django.forms.models import model_to_dict
from django.utils import timezone
from .models import (Sequence, Worker, PayrollSettings, Attendance, Payroll, PayrollDay,
                     SprayApplication, SprayLine, PayrollExpense, Expense, ExpenseCategory, PaymentMethod)
from .services import audit, retry_locked


def snapshot(obj):
    return json.loads(json.dumps(model_to_dict(obj), cls=DjangoJSONEncoder))


def lock_farm():
    # Una fila común también protege rangos solapados y asistencia aún inexistente.
    seq, _ = Sequence.objects.get_or_create(name='farm_operations')
    Sequence.objects.filter(pk=seq.pk).update(value=F('value') + 1)
    Sequence.objects.select_for_update().get(pk=seq.pk)


def cents(value):
    return value.quantize(Decimal('.01'), rounding=ROUND_HALF_UP)


@retry_locked
@transaction.atomic
def save_catalog(form, user):
    lock_farm()
    obj = form.save(commit=False)
    before = {}
    if obj.pk and type(obj).objects.filter(pk=obj.pk).exists():
        current = type(obj).objects.get(pk=obj.pk)
        if current.revision != form.cleaned_data['revision']:
            raise ValidationError('Otra persona cambió este registro. Recargue antes de editar.')
        before = snapshot(current)
        obj.revision = current.revision + 1
    else:
        obj.revision = 1
    obj.full_clean()
    obj.save()
    audit(user, obj, 'Actualizar' if before else 'Crear', before, snapshot(obj))
    return obj


@retry_locked
@transaction.atomic
def save_attendance(date, rows, user):
    lock_farm()
    if date > timezone.localdate():
        raise ValidationError('No se permite registrar asistencia futura.')
    if len({r['worker'] for r in rows}) != len(rows):
        raise ValidationError('Hay trabajadores repetidos en el formulario.')
    config = PayrollSettings.objects.filter(pk=1).first()
    for row in rows:
        worker = Worker.objects.get(pk=row['worker'])
        record = Attendance.objects.filter(worker=worker, date=date).first()
        if not worker.active and record is None:
            raise ValidationError('Solo se registra asistencia nueva para trabajadores activos.')
        if date < worker.joined_on:
            if row['worked']:
                raise ValidationError(f'{worker}: la fecha es anterior al ingreso.')
            continue
        if record and record.payroll_days.exclude(payroll__status='cancelled').exists():
            if (record.worked == row['worked'] and record.extra_minutes == row['hours'] * 60 + row['minutes']
                    and record.notes == row['notes'] and record.revision == row['revision']):
                continue
            raise ValidationError(f'{worker}: asistencia liquidada. Anule la nómina antes de corregir.')
        if (record.revision if record else 0) != row['revision']:
            raise ValidationError('La asistencia cambió en otra sesión. Recargue la fecha.')
        before = snapshot(record) if record else {}
        if record is None:
            if config is None or not config.mode:
                raise ValidationError('Configure las tarifas de horas extras antes de guardar asistencia.')
            rule = snapshot(config)
            hourly = (config.hourly_rate if config.mode == 'hourly' else
                      worker.daily_rate / config.ordinary_hours * config.multiplier)
            record = Attendance(worker=worker, date=date, daily_rate=worker.daily_rate,
                                hourly_rate=hourly.quantize(Decimal('.00000001'), rounding=ROUND_HALF_UP),
                                rate_rule=rule, created_by=user)
        record.worked = row['worked']
        record.extra_minutes = row['hours'] * 60 + row['minutes']
        record.notes = row['notes']
        record.revision += 1
        record.full_clean()
        record.save()
        audit(user, record, 'Guardar asistencia', before, snapshot(record))


@retry_locked
@transaction.atomic
def generate_payroll(start, end, token, user, paid=False, payment_method=None):
    lock_farm()
    existing = Payroll.objects.filter(token=token).first()
    if existing:
        return existing
    if start > end or end > timezone.localdate():
        raise ValidationError('Seleccione un período válido, sin fechas futuras.')
    records = list(Attendance.objects.filter(date__range=(start, end)).select_related('worker'))
    if not records:
        raise ValidationError('No hay registros de asistencia en este período.')
    if PayrollDay.objects.filter(attendance__in=records).exclude(payroll__status='cancelled').exists():
        raise ValidationError('El período incluye asistencias ya liquidadas. Consulte el historial o anule la nómina anterior.')
    payroll = Payroll.objects.create(start=start, end=end, token=token, total=0, created_by=user)
    total = Decimal(0)
    for record in records:
        base = record.daily_rate if record.worked else Decimal(0)
        if record.rate_rule.get('mode') == 'derived':
            # Redondear solo el importe final: la tarifa mostrada tiene 8 decimales.
            rule = record.rate_rule
            extra = cents(record.daily_rate * Decimal(rule['multiplier']) * record.extra_minutes
                          / Decimal(rule['ordinary_hours']) / 60)
        else:
            extra = cents(record.hourly_rate * record.extra_minutes / 60)
        data = {'worker_id': record.worker_id, 'worker': record.worker.name,
                'identification': record.worker.identification, 'date': record.date.isoformat(),
                'worked': record.worked, 'minutes': record.extra_minutes,
                'daily_rate': str(record.daily_rate), 'hourly_rate': str(record.hourly_rate),
                'base': str(base), 'extra': str(extra), 'total': str(base + extra),
                'notes': record.notes, 'rule': record.rate_rule}
        PayrollDay.objects.create(payroll=payroll, attendance=record, snapshot=data)
        total += base + extra
    payroll.total = total
    payroll.full_clean()
    payroll.save()
    if paid and not payment_method:
        raise ValidationError('Seleccione el medio de pago real.')
    if paid:
        payment_method = real_payment_method(payment_method.pk)
        payroll.status = 'paid'
        payroll.paid_at = timezone.now()
        payroll.save()
    create_payroll_expense(payroll, user, payment_method if paid else None)
    from .whatsapp import enqueue_payroll
    enqueue_payroll(payroll, user)
    audit(user, payroll, 'Generar nómina', after={'start': str(start), 'end': str(end), 'total': str(total)})
    return payroll


def payroll_summary(payroll):
    workers = OrderedDict()
    for day in payroll.days.order_by('pk'):
        d = day.snapshot
        w = workers.setdefault(d['worker_id'], dict(worker_id=d['worker_id'], name=d['worker'], days=0, minutes=0,
                              base=Decimal(0), extra=Decimal(0), total=Decimal(0)))
        w['days'] += int(d['worked'])
        w['minutes'] += d['minutes']
        for key in ['base', 'extra', 'total']:
            w[key] += Decimal(d[key])
    for w in workers.values():
        w['hours'], w['remaining_minutes'] = divmod(w['minutes'], 60)
    return list(workers.values())


@retry_locked
@transaction.atomic
def payroll_transition(pk, action, reason, user, method_id=None):
    lock_farm()
    payroll = Payroll.objects.get(pk=pk)
    before = snapshot(payroll)
    if action == 'pay' and payroll.status == 'generated':
        method = real_payment_method(method_id)
        payroll.status = 'paid'
        payroll.paid_at = timezone.now()
    elif action == 'cancel' and payroll.status in ('generated', 'paid'):
        if payroll.whatsapp_messages.filter(status='processing').exists():
            raise ValidationError('Hay un envío de WhatsApp en proceso. Espere su resultado antes de anular.')
        if payroll.status == 'paid' and not user.is_superuser:
            raise ValidationError('Solo un administrador puede anular una nómina pagada.')
        if not reason.strip():
            raise ValidationError('Explique el motivo de anulación. La copia original se conserva.')
        payroll.status = 'cancelled'
        payroll.cancellation_reason = reason.strip()
    else:
        raise ValidationError('El estado de esta nómina ya cambió. Recargue el detalle.')
    payroll.save()
    entry = PayrollExpense.objects.filter(payroll=payroll).select_related('expense').first()
    if entry and action == 'pay':
        expense = entry.expense
        old_expense = snapshot(expense)
        expense.method = method
        expense.revision += 1
        expense.save()
        audit(user, expense, 'Pago de gasto de nómina', old_expense, snapshot(expense))
    if action == 'cancel':
        if entry:
            entry.active = False
            entry.cancelled_at = timezone.now()
            entry.save()
            audit(user, entry.expense, 'Anular gasto de nómina', after={'motivo': reason, 'nomina': pk})
        payroll.whatsapp_messages.filter(status__in=['pending', 'blocked', 'failed']).update(status='cancelled', detail='Nómina anulada.')
    elif action == 'pay':
        payroll.whatsapp_messages.filter(phase='generated', status__in=['pending', 'blocked', 'failed']).update(status='cancelled', detail='Sustituido por el resumen de pago confirmado.')
        from .whatsapp import enqueue_payroll
        enqueue_payroll(payroll, user)
    audit(user, payroll, 'Estado de nómina', before, snapshot(payroll))
    return payroll


@retry_locked
@transaction.atomic
def save_spray(form, rows, user):
    lock_farm()
    data = form.cleaned_data
    existing = SprayApplication.objects.filter(token=data['token']).first()
    obj = form.save(commit=False)
    if existing and not obj.pk:
        return existing
    before = {}
    if obj.pk:
        old = SprayApplication.objects.get(pk=obj.pk)
        if old.status != 'scheduled' or old.revision != data['revision']:
            raise ValidationError('El registro cambió o ya fue realizado/anulado. Recargue el historial.')
        before = snapshot(old)
        before['lines'] = list(old.lines.values('product_id', 'name', 'quantity', 'unit'))
        before = json.loads(json.dumps(before, cls=DjangoJSONEncoder))
    products = [r['product'].pk for r in rows]
    if not products or len(products) != len(set(products)):
        raise ValidationError('Agregue productos sin repetirlos dentro de una misma aplicación.')
    obj.token = data['token']
    obj.created_by = obj.created_by if obj.pk else user
    obj.completed_at = obj.scheduled_at if obj.status == 'completed' else None
    obj.revision += 1
    obj.full_clean()
    obj.save()
    obj.lines.all().delete()  # Solo se permite cambiar el detalle aún programado; se audita antes/después.
    for row in rows:
        line = SprayLine(application=obj, product=row['product'], name=row['product'].name,
                         quantity=row['quantity'], unit=row['unit'])
        line.full_clean()
        line.save()
    if data.get('next_at'):
        followup = SprayApplication.objects.create(scheduled_at=data['next_at'], area=obj.area,
            responsible=obj.responsible, status='scheduled', source=obj, created_by=user,
            notes='Programación revisada al registrar la aplicación anterior.')
        for line in obj.lines.all():
            SprayLine.objects.create(application=followup, product=line.product, name=line.name,
                                     quantity=line.quantity, unit=line.unit)
        audit(user, followup, 'Programar próxima aplicación', after=snapshot(followup))
    after = snapshot(obj)
    after['lines'] = json.loads(json.dumps(list(obj.lines.values('product_id', 'name', 'quantity', 'unit')), cls=DjangoJSONEncoder))
    audit(user, obj, 'Guardar fumigación', before, after)
    return obj


@retry_locked
@transaction.atomic
def cancel_spray(pk, reason, user):
    lock_farm()
    obj = SprayApplication.objects.get(pk=pk)
    if obj.status != 'scheduled' or not reason.strip():
        raise ValidationError('Solo se anulan programaciones pendientes, indicando el motivo.')
    before = snapshot(obj)
    obj.status = 'cancelled'
    obj.notes += '\nAnulación: ' + reason.strip()
    obj.revision += 1
    obj.save()
    audit(user, obj, 'Anular programación', before, snapshot(obj))


def real_payment_method(pk):
    method = PaymentMethod.objects.filter(pk=pk, active=True, is_credit=False).first()
    if not method:
        raise ValidationError('Seleccione un medio de pago real y activo para confirmar el pago.')
    return method


def create_payroll_expense(payroll, user, method=None):
    if payroll.total == 0:
        return None
    category, _ = ExpenseCategory.objects.get_or_create(name='Nómina')
    if not category.active:
        raise ValidationError('Active la categoría de gastos Nómina antes de generar la liquidación.')
    if method is None:
        method, _ = PaymentMethod.objects.get_or_create(name='Pendiente de pago de nómina', defaults={'active': False, 'is_credit': False})
    expense = Expense(date=payroll.end, category=category, description=f'Nómina #{payroll.pk}: {payroll.start} a {payroll.end}',
                      amount=payroll.total, method=method, reference=f'NO-{payroll.pk}',
                      token=uuid5(payroll.token, 'expense'), created_by=user, revision=1)
    expense.full_clean()
    expense.save()
    PayrollExpense.objects.create(payroll=payroll, expense=expense)
    audit(user, expense, 'Gasto automático de nómina', after=snapshot(expense))
    return expense
