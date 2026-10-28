"""Registro transaccional de ventas, abonos y movimientos del cliente."""

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from uuid import UUID, uuid5, NAMESPACE_URL
from django.db import transaction, OperationalError, connection
from functools import wraps
import time
from django.db.models import F
from django.core.exceptions import ValidationError
from django.utils import timezone
from .models import (
    Customer,
    Product,
    Sale,
    SaleLine,
    Payment,
    Allocation,
    Sequence,
    Audit,
)

ZERO = Decimal("0")


def retry_locked(fn):
    """Reintenta bloqueos temporales de SQLite; propaga los demás errores."""

    @wraps(fn)
    def wrapped(*args, **kwargs):
        for attempt in range(8):
            try:
                return fn(*args, **kwargs)
            except OperationalError as exc:
                if connection.vendor != "sqlite" or "locked" not in str(exc).lower():
                    raise
                if attempt == 7:
                    raise ValidationError(
                        "La base de datos está ocupada. Reintente el envío; la operación está protegida contra duplicados."
                    )
                time.sleep(0.025 * (attempt + 1))

    return wrapped


def number(value, places=2, positive=False):
    """Valida rango y precisión decimal sin redondear la entrada."""
    try:
        n = Decimal(str(value))
        if (
            not n.is_finite()
            or n < 0
            or n > Decimal("999999999999.99")
            or (positive and n <= 0)
        ):
            raise ValueError()
        if n != n.quantize(Decimal(10) ** -places):
            raise ValueError()
        return n
    except (ValueError, InvalidOperation, TypeError):
        raise ValidationError(
            f'Ingrese un número válido, {"mayor que cero" if positive else "no negativo"}, con máximo {places} decimales.'
        )


def token_value(value):
    try:
        return UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        raise ValidationError(
            "Identificador de operación inválido. Recargue el formulario."
        )


def audit(user, obj, action, before=None, after=None):
    Audit.objects.create(
        actor=user,
        entity=obj._meta.label,
        object_id=obj.pk,
        action=action,
        before=before or {},
        after=after or {},
    )


def lock_customer(pk):
    """Serializa los cambios de cartera del cliente dentro de la transacción."""
    Customer.objects.filter(pk=pk).update(revision=F("revision") + 1)
    return Customer.objects.select_for_update().get(pk=pk)


def next_number():
    seq, _ = Sequence.objects.get_or_create(name="sales")
    Sequence.objects.filter(pk=seq.pk).update(value=F("value") + 1)
    seq.refresh_from_db()
    return seq.value


@retry_locked
@transaction.atomic
def create_sale(*, user, customer_id, rows, method, initial, cash_method, token, occurred_at=None):
    """Registra la venta y su pago inicial una sola vez por token."""
    token = token_value(token)
    customer = lock_customer(customer_id)
    existing = Sale.objects.filter(token=token).first()
    if existing:
        return existing
    if not customer.active or not method.active:
        raise ValidationError("Cliente o medio de pago inactivo.")
    if not isinstance(rows, list) or not rows or len(rows) > 100:
        raise ValidationError("Agregue entre 1 y 100 productos.")
    details = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValidationError("El detalle de productos es inválido.")
        try:
            p = Product.objects.get(pk=row["product"], active=True)
        except (Product.DoesNotExist, ValueError, KeyError):
            raise ValidationError("Seleccione un producto activo.")
        quantity = number(row.get("quantity"), 0, True)
        if quantity > Decimal("999999999.999"):
            raise ValidationError("La cantidad supera el límite permitido.")
        weight = (
            number(row.get("weight"), 3, True)
            if p.by_weight and p.variable_weight
            else p.weight if p.by_weight else ZERO
        )
        if p.by_weight and weight <= 0:
            raise ValidationError("El peso debe ser mayor que cero.")
        total_weight = weight * quantity if p.by_weight else ZERO
        if total_weight > Decimal("999999999.999999"):
            raise ValidationError("El peso total supera el límite permitido.")
        subtotal = ((total_weight if p.by_weight else quantity) * p.price).quantize(
            Decimal(".01"), rounding=ROUND_HALF_UP
        )
        details.append(
            dict(
                product=p,
                name=p.name,
                unit=p.unit,
                by_weight=p.by_weight,
                price=p.price,
                quantity=quantity,
                weight=weight,
                total_weight=total_weight,
                subtotal=subtotal,
            )
        )
    total = sum((r["subtotal"] for r in details), ZERO)
    if total > Decimal("999999999999.99"):
        raise ValidationError("El total supera el límite permitido.")
    initial = number(initial)
    if initial > total:
        raise ValidationError("El pago inicial supera el total de la venta.")
    if initial and (not cash_method or not cash_method.active or cash_method.is_credit):
        raise ValidationError("Seleccione un medio real para el pago recibido.")
    sale = Sale.objects.create(
        number=next_number(),
        token=token,
        customer=customer,
        customer_name=customer.name,
        customer_identification=customer.identification,
        method=method,
        method_name=method.name,
        occurred_at=occurred_at or timezone.now(),
        total=total,
        initial_payment=initial,
        created_by=user,
    )
    for detail in details:
        SaleLine.objects.create(sale=sale, **detail)
    if initial:
        payment = Payment.objects.create(
            token=uuid5(NAMESPACE_URL, f"fresas:initial:{token}"),
            customer=customer,
            amount=initial,
            method=cash_method,
            method_name=cash_method.name,
            initial_sale=sale,
            date=timezone.localtime(sale.occurred_at).date(),
            created_by=user,
        )
        Allocation.objects.create(payment=payment, sale=sale, amount=initial)
        audit(user, payment, "Pago inicial", after={"valor": str(initial)})
    audit(user, sale, "Venta registrada", after={"total": str(total)})
    from .whatsapp import enqueue_sale
    enqueue_sale(sale, user)
    return sale


@retry_locked
@transaction.atomic
def create_payment(
    *, user, customer_id, amount, method, date, notes, token, allocation=None
):
    """Aplica el abono a las deudas más antiguas, una sola vez por token."""
    token = token_value(token)
    customer = lock_customer(customer_id)
    existing = Payment.objects.filter(token=token).first()
    if existing:
        return existing
    amount = number(amount, positive=True)
    if not method.active or method.is_credit:
        raise ValidationError("El abono requiere un medio de pago real y activo.")
    if (
        date > timezone.localdate()
        or date < customer.created_at.astimezone(timezone.get_current_timezone()).date()
    ):
        raise ValidationError(
            "La fecha debe estar entre la creación del cliente y hoy."
        )
    debts = list(
        customer.sales.order_by("occurred_at", "id").prefetch_related("allocations")
    )
    available = {
        s.pk: s
        for s in debts
        if s.balance > 0 and timezone.localtime(s.occurred_at).date() <= date
    }
    if amount > sum((s.balance for s in available.values()), ZERO):
        raise ValidationError("El abono supera la deuda disponible en esa fecha.")
    distribution = []
    if allocation is not None:
        raise ValidationError(
            "Los abonos se aplican automáticamente de la venta más antigua a la más nueva."
        )
    remaining = amount
    for sale in available.values():
        value = min(remaining, sale.balance)
        if value:
            distribution.append((sale, value))
        remaining -= value
        if remaining == 0:
            break
    payment = Payment.objects.create(
        token=token,
        customer=customer,
        amount=amount,
        method=method,
        method_name=method.name,
        date=date,
        notes=notes,
        created_by=user,
    )
    for sale, value in distribution:
        Allocation.objects.create(payment=payment, sale=sale, amount=value)
    audit(
        user,
        payment,
        "Abono registrado",
        after={
            "valor": str(amount),
            "distribución": {str(s): str(v) for s, v in distribution},
        },
    )
    return payment


def statement(customer, start=None, end=None):
    """Devuelve saldo inicial, movimientos del periodo y saldo final."""
    events = []
    for s in customer.sales.all():
        events.append(
            {
                "date": timezone.localtime(s.occurred_at).date(),
                "order": (s.created_at, 0, s.pk),
                "reference": str(s),
                "description": "Venta interna",
                "debit": s.total,
                "credit": ZERO,
            }
        )
    for p in customer.payments.all():
        events.append(
            {
                "date": p.date,
                "order": (p.created_at, 1, p.pk),
                "reference": str(p),
                "description": (
                    f"Pago inicial · {p.initial_sale}"
                    if p.initial_sale_id
                    else "Abono recibido"
                ),
                "debit": ZERO,
                "credit": p.amount,
            }
        )
    events.sort(key=lambda e: (e["date"], e["order"]))
    balance = ZERO
    opening = ZERO
    result = []
    for e in events:
        if end and e["date"] > end:
            continue
        balance += e["debit"] - e["credit"]
        e["balance"] = balance
        if start and e["date"] < start:
            opening = balance
        else:
            result.append(e)
    return opening, result, balance
