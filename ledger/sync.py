"""Réplica de un computador: nube autoritativa, envíos idempotentes y pull atómico.

No conecta SQLite directamente a PostgreSQL ni copia archivos de base de datos.
Los movimientos pendientes siempre pasan por las validaciones contables de nube.
"""
import hashlib
import hmac
import json
from datetime import date
from decimal import Decimal, InvalidOperation
from urllib.request import Request
from urllib.parse import urlparse

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core import serializers
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection, transaction
from django.http import JsonResponse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .models import (Customer, Product, PaymentMethod, ExpenseCategory, Sale,
                     SaleLine, Payment, Allocation, Expense, Sequence, Audit,
                     SyncState, SyncReceipt)
from .services import create_sale, create_payment, audit, token_value

CATALOG = (Customer, Product, PaymentMethod, ExpenseCategory)
FINANCIAL = (Sale, SaleLine, Payment, Allocation, Expense, Sequence, Audit)
PERMISSIONS = [f'ledger.view_{m._meta.model_name}' for m in
               (Customer, Product, PaymentMethod, ExpenseCategory, Sale, Payment, Expense)]


def pending():
    result = []
    for model in (Sale, Payment, Expense):
        known = SyncReceipt.objects.filter(kind=model._meta.model_name).values_list('token', flat=True)
        qs = model.objects.exclude(token__in=known)
        if model is Payment:
            qs = qs.filter(initial_sale__isnull=True)
        result.extend(qs)
    return sorted(result, key=lambda o: (o.created_at, o.pk))


def operation(obj):
    common = {'token': str(obj.token), 'kind': obj._meta.model_name}
    if isinstance(obj, Sale):
        initial = Payment.objects.filter(initial_sale=obj).first()
        common.update(customer_id=obj.customer_id, method_id=obj.method_id,
                      initial=str(obj.initial_payment),
                      cash_method_id=initial.method_id if initial else None,
                      occurred_at=obj.occurred_at.isoformat(),
                      rows=[{'product': r.product_id, 'quantity': str(r.quantity),
                             'weight': str(r.weight), 'price': str(r.price),
                             'unit': r.unit, 'by_weight': r.by_weight}
                            for r in obj.lines.all()])
    elif isinstance(obj, Payment):
        common.update(customer_id=obj.customer_id, amount=str(obj.amount),
                      method_id=obj.method_id, date=obj.date.isoformat(), notes=obj.notes)
    else:
        common.update(category_id=obj.category_id, amount=str(obj.amount),
                      method_id=obj.method_id, date=obj.date.isoformat(),
                      description=obj.description, reference=obj.reference)
    return common


@transaction.atomic
def accept(data, user):
    """El recibo y el movimiento se confirman juntos, incluso ante reintentos."""
    token = token_value(data['token'])
    kind = data['kind']
    if kind not in ('sale', 'payment', 'expense') or not user.has_perm(f'ledger.add_{kind}'):
        raise PermissionDenied
    # Serializa todos los envíos del único nodo autorizado.
    state, _ = SyncState.objects.get_or_create(pk=1)
    SyncState.objects.select_for_update().get(pk=state.pk)
    digest = hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()
    receipt = SyncReceipt.objects.filter(token=token).first()
    if receipt:
        if receipt.digest != digest:
            raise ValidationError('El identificador ya pertenece a otra operación.')
        return
    if any(m.objects.filter(token=token).exists() for m in (Sale, Payment, Expense)):
        raise ValidationError('Identificador existente sin recibo de sincronización.')
    method = PaymentMethod.objects.get(pk=data['method_id'])
    if kind == 'sale':
        # No se modifica silenciosamente una venta si cambió el catálogo.
        for row in data['rows']:
            product = Product.objects.get(pk=row['product'], active=True)
            expected_weight = str(product.weight) if product.by_weight else '0'
            if (Decimal(row['price']) != product.price or row['unit'] != product.unit
                    or row['by_weight'] != product.by_weight
                    or (not product.variable_weight and Decimal(row['weight']) != Decimal(expected_weight))):
                raise ValidationError('Cambió el catálogo. Revise la venta pendiente antes de sincronizar.')
        occurred = parse_datetime(data['occurred_at'])
        if occurred is None or timezone.is_naive(occurred) or occurred > timezone.now():
            raise ValidationError('Fecha de venta inválida o futura.')
        customer = Customer.objects.get(pk=data['customer_id'])
        if occurred < customer.created_at:
            raise ValidationError('La venta es anterior al cliente.')
        create_sale(user=user, customer_id=customer.pk,
                           rows=data['rows'], method=method, initial=data['initial'],
                           cash_method=PaymentMethod.objects.get(pk=data['cash_method_id'])
                           if data['cash_method_id'] else None, token=token,
                           occurred_at=occurred)
    elif kind == 'payment':
        create_payment(user=user, customer_id=data['customer_id'], amount=data['amount'],
                       method=method, date=date.fromisoformat(data['date']),
                       notes=data['notes'], token=token)
    else:
        category = ExpenseCategory.objects.get(pk=data['category_id'], active=True)
        if not method.active or method.is_credit:
            raise ValidationError('Medio de pago inválido para el gasto.')
        expense = Expense(token=token, date=date.fromisoformat(data['date']),
                          category=category, amount=data['amount'], method=method,
                          description=data['description'], reference=data['reference'],
                          created_by=user, revision=1)
        expense.full_clean()
        if expense.date > timezone.localdate():
            raise ValidationError('Fecha de gasto futura.')
        expense.save()
        audit(user, expense, 'Gasto recibido del equipo local', after={'valor': str(expense.amount)})
    SyncReceipt.objects.create(token=token, kind=kind, digest=digest)


@transaction.atomic
def snapshot():
    # Todas las tablas deben representar el mismo instante en PostgreSQL.
    if connection.vendor == 'postgresql':
        with connection.cursor() as cursor:
            cursor.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
    objects = [obj for model in (*CATALOG, *FINANCIAL) for obj in model.objects.all()]
    return {'business': settings.SYNC_BUSINESS,
            'objects': json.loads(serializers.serialize('json', objects)),
            'users': dict(get_user_model().objects.values_list('id', 'username'))}


@csrf_exempt
@require_POST
def endpoint(request):
    """API privada: token de alta entropía, HTTPS y usuario dedicado con permisos."""
    if (settings.OFFLINE_NODE or len(settings.SYNC_TOKEN) < 32
            or not settings.SYNC_BUSINESS
            or not hmac.compare_digest(request.headers.get('Authorization', ''),
                                       'Bearer ' + settings.SYNC_TOKEN)):
        return JsonResponse({'error': 'Acceso denegado.'}, status=403)
    user = get_user_model().objects.filter(username=settings.SYNC_USER, is_active=True).first()
    if not user or not user.has_perms(PERMISSIONS):
        return JsonResponse({'error': 'Usuario de sincronización sin permisos.'}, status=403)
    try:
        data = json.loads(request.body)
        if data.get('business') != settings.SYNC_BUSINESS:
            raise ValidationError('La configuración corresponde a otro negocio.')
        if data['action'] == 'push':
            accept(data['operation'], user)
            return JsonResponse({'ok': True})
        if data['action'] == 'pull':
            return JsonResponse(snapshot())
        raise ValidationError('Acción desconocida.')
    except PermissionDenied:
        return JsonResponse({'error': 'Operación no autorizada.'}, status=403)
    except (ValidationError, ValueError, KeyError, TypeError, AttributeError, InvalidOperation,
            Customer.DoesNotExist, Product.DoesNotExist,
            PaymentMethod.DoesNotExist, ExpenseCategory.DoesNotExist) as exc:
        message = ' '.join(exc.messages) if isinstance(exc, ValidationError) else 'Datos de sincronización inválidos.'
        return JsonResponse({'error': message}, status=409)


@transaction.atomic
def install_snapshot(data):
    state, _ = SyncState.objects.get_or_create(pk=1)
    SyncState.objects.select_for_update().get(pk=1)
    if data['business'] != settings.SYNC_BUSINESS or (state.business and state.business != data['business']):
        raise ValidationError('La réplica pertenece a otro negocio.')
    if pending():
        raise ValidationError('Hay movimientos nuevos pendientes. Se conservaron para el próximo intento.')
    users = {}
    for pk, username in data['users'].items():
        user = get_user_model().objects.filter(username=username).first()
        if user is None:
            user = get_user_model()(username=username)
            user.set_unusable_password()
            user.save()
        users[int(pk)] = user.pk
    allowed = {m._meta.label_lower for m in (*CATALOG, *FINANCIAL)}
    objects = data['objects']
    if any(item['model'] not in allowed for item in objects):
        raise ValidationError('Modelo de réplica no autorizado.')
    # La nube reemplaza la réplica únicamente cuando no queda nada por enviar.
    # Orden inverso de dependencias; el borrado es interno y transaccional.
    for model in (Allocation, SaleLine, Payment, Sale, Expense, Audit, Sequence):
        model.objects.all()._raw_delete(using='default')
    for item in objects:
        for field in ('created_by', 'actor'):
            if field in item['fields']:
                item['fields'][field] = users[item['fields'][field]]
    for obj in serializers.deserialize('json', json.dumps(objects)):
        obj.save()
    for model in CATALOG:
        ids = [o['pk'] for o in objects if o['model'] == model._meta.label_lower]
        model.objects.exclude(pk__in=ids).delete()
    SyncReceipt.objects.all().delete()
    for model in (Sale, Payment, Expense):
        SyncReceipt.objects.bulk_create([SyncReceipt(token=t, kind=model._meta.model_name) for t in model.objects.values_list('token', flat=True)])
    state.initialized = True
    state.business = data['business']
    state.last_success = timezone.now()
    state.last_error = ''
    state.save()


def exchange(action, **extra):
    parsed = urlparse(settings.SYNC_URL)
    if parsed.scheme != 'https' or not parsed.netloc or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValidationError('SYNC_URL debe ser un origen HTTPS sin credenciales ni parámetros.')
    if len(settings.SYNC_TOKEN) < 32 or not settings.SYNC_BUSINESS:
        raise ValidationError('Configure SYNC_TOKEN (mínimo 32 caracteres) y SYNC_BUSINESS.')
    body = json.dumps({'action': action, 'business': settings.SYNC_BUSINESS, **extra}).encode()
    request = Request(settings.SYNC_URL + '/api/sync/', data=body,
                      headers={'Authorization': 'Bearer ' + settings.SYNC_TOKEN,
                               'Content-Type': 'application/json'})
    # Evita reenviar el token secreto a otro host mediante una redirección.
    from urllib.request import HTTPRedirectHandler, build_opener
    class NoRedirect(HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None
    with build_opener(NoRedirect).open(request, timeout=30) as response:
        return json.load(response)


def synchronize():
    if not settings.OFFLINE_NODE:
        raise ValidationError('La sincronización se ejecuta únicamente en el equipo local.')
    state, _ = SyncState.objects.get_or_create(pk=1)
    if not state.initialized:
        if any(m.objects.exists() for m in (Sale, Payment, Expense, Customer, Product)):
            raise ValidationError('La primera sincronización requiere una base local vacía de datos del negocio. Respalde los datos existentes y prepare otra instalación.')
    else:
        for obj in pending():
            exchange('push', operation=operation(obj))
            SyncReceipt.objects.get_or_create(token=obj.token, kind=obj._meta.model_name)
    install_snapshot(exchange('pull'))
