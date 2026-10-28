"""Cola durable de documentos privados y envío mediante WhatsApp Cloud API."""
import json
import re
import uuid
from urllib.error import HTTPError, URLError
from urllib.request import Request, HTTPRedirectHandler, build_opener
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from .models import WhatsAppMessage, Worker
from .services import audit, retry_locked
from .templatetags.money import cop


class MetaError(Exception):
    def __init__(self, code='connection', ambiguous=False):
        self.code = str(code)[:40]
        self.ambiguous = ambiguous


def normalize_phone(raw):
    raw = (raw or '').strip()
    if re.search(r'[^+0-9\s().-]', raw) or '+' in raw[1:]:
        return ''
    digits = re.sub(r'\D', '', raw)
    if raw.startswith('00'):
        digits = digits[2:]
    elif not raw.startswith('+') and len(digits) == 10:
        digits = settings.WHATSAPP_COUNTRY_CODE + digits
    if not digits.isascii() or not digits.isdigit() or not 8 <= len(digits) <= 15 or digits.startswith('0'):
        return ''
    return digits


def configuration_problem(kind=None):
    if settings.OFFLINE_NODE:
        return 'El envío automático se realiza desde la instalación principal.'
    if not settings.WHATSAPP_ENABLED:
        return 'Falta activar WhatsApp Business Platform para enviar desde el número de la empresa.'
    if not settings.WHATSAPP_ACCESS_TOKEN or not settings.WHATSAPP_PHONE_NUMBER_ID:
        return 'Faltan las credenciales de WhatsApp Business Platform.'
    if not re.fullmatch(r'[0-9]+', settings.WHATSAPP_PHONE_NUMBER_ID) or not re.fullmatch(r'v[0-9]+\.[0-9]+', settings.WHATSAPP_API_VERSION):
        return 'Revise el identificador del teléfono y la versión de la API.'
    template = settings.WHATSAPP_SALE_TEMPLATE if kind == 'sale' else settings.WHATSAPP_PAYROLL_TEMPLATE
    if kind and not template:
        return 'Falta configurar la plantilla aprobada para este comprobante.'
    return ''


def individual_payroll_pdf(payroll, worker_id):
    from .exports import export_table
    from .farm_services import payroll_summary
    worker = next((w for w in payroll_summary(payroll) if w['worker_id'] == worker_id), None)
    if not worker:
        raise ValueError('El trabajador no está incluido en esta nómina.')
    days = [d.snapshot for d in payroll.days.all() if d.snapshot['worker_id'] == worker_id]
    status = 'Pago confirmado' if payroll.status == 'paid' else ('Anulada' if payroll.status == 'cancelled' else 'Liquidación generada; pago pendiente')
    return export_table('pdf', f'{settings.BUSINESS_NAME} · Nómina #{payroll.pk} · {worker["name"]}',
        ['Fecha', 'Trabajó', 'Extras (min)', 'Pago días', 'Pago extras', 'Total día'],
        [[d['date'], 'Sí' if d['worked'] else 'No', d['minutes'], cop(d['base']), cop(d['extra']), cop(d['total'])] for d in days],
        f'Período: {payroll.start} a {payroll.end} | {status} | Días: {worker["days"]} | '
        f'Extras: {worker["hours"]} h {worker["remaining_minutes"]} min | Total: {cop(worker["total"])}',
        totals=['TOTAL', worker['days'], worker['minutes'], cop(worker['base']), cop(worker['extra']), cop(worker['total'])])


def enqueue_sale(sale, user):
    if settings.OFFLINE_NODE or not sale.customer.whatsapp_opt_in:
        return None
    from .receipt import sale_receipt
    return WhatsAppMessage.objects.get_or_create(key=f'sale:{sale.token}', defaults=dict(
        kind='sale', sale=sale, recipient=normalize_phone(sale.customer.phone), recipient_name=sale.customer_name,
        reference=str(sale), summary=cop(sale.total), document=sale_receipt(sale).content,
        filename=f'{sale}.pdf', created_by=user))[0]


def enqueue_payroll(payroll, user):
    from .farm_services import payroll_summary
    for row in payroll_summary(payroll):
        if row['total'] <= 0:
            continue
        worker = Worker.objects.get(pk=row['worker_id'])
        phase = 'paid' if payroll.status == 'paid' else 'generated'
        summary = (f'{"Pago confirmado" if phase == "paid" else "Pago pendiente"}; '
                   f'{row["days"]} días; extras {row["hours"]} h {row["remaining_minutes"]} min; '
                   f'días {cop(row["base"])}; extras {cop(row["extra"])}; total {cop(row["total"])}')
        WhatsAppMessage.objects.get_or_create(key=f'payroll:{payroll.token}:{worker.pk}:{phase}', defaults=dict(
            kind='payroll', payroll=payroll, worker=worker, phase=phase, recipient=normalize_phone(worker.phone),
            recipient_name=row['name'], reference=f'{payroll.start} a {payroll.end}', summary=summary,
            document=individual_payroll_pdf(payroll, worker.pk).content,
            filename=f'nomina-{payroll.pk}-trabajador-{worker.pk}.pdf', created_by=user))


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def meta_request(path, payload=None, data=None, content_type=None, sending=False):
    if payload is not None:
        data = json.dumps(payload).encode()
        content_type = 'application/json'
    request = Request(f'https://graph.facebook.com/{settings.WHATSAPP_API_VERSION}/{path}', data=data,
                      headers={'Authorization': 'Bearer ' + settings.WHATSAPP_ACCESS_TOKEN,
                               'Content-Type': content_type or 'application/json'})
    try:
        with build_opener(NoRedirect).open(request, timeout=8) as response:
            result = json.load(response)
            if not isinstance(result, dict):
                raise MetaError('invalid_response', ambiguous=sending)
            return result
    except HTTPError as exc:
        # No se guarda ni muestra el cuerpo remoto: puede contener datos sensibles.
        raise MetaError(exc.code, ambiguous=sending and exc.code >= 500) from None
    except (URLError, TimeoutError, OSError, ValueError):
        raise MetaError('connection', ambiguous=sending) from None


def upload_document(message):
    boundary = 'fresas' + uuid.uuid4().hex
    chunks = []
    for name, value in [('messaging_product', 'whatsapp'), ('type', 'application/pdf')]:
        chunks.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
    chunks.append(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{message.filename}"\r\nContent-Type: application/pdf\r\n\r\n'.encode())
    chunks.extend([bytes(message.document), f'\r\n--{boundary}--\r\n'.encode()])
    result = meta_request(settings.WHATSAPP_PHONE_NUMBER_ID + '/media', data=b''.join(chunks), content_type='multipart/form-data; boundary=' + boundary)
    if not result.get('id'):
        raise MetaError('missing_media_id')
    return result['id']


def message_audit(message, action):
    source = message.sale if message.sale_id else message.payroll
    audit(message.created_by, source, action, after={'whatsapp_id': str(message.pk), 'estado': message.status,
                                                   'provider_id': message.provider_id, 'detalle': message.detail})


@retry_locked
@transaction.atomic
def claim_message(pk):
    from .farm_services import lock_farm
    lock_farm()
    message = WhatsAppMessage.objects.select_for_update().select_related('sale__customer', 'payroll', 'worker').get(pk=pk)
    if message.status not in ('pending', 'blocked'):
        return None
    if message.payroll_id and message.payroll.status == 'cancelled':
        message.status, message.detail = 'cancelled', 'Nómina anulada.'
        message.save()
        return None
    contact = message.sale.customer if message.sale_id else message.worker
    problem = configuration_problem(message.kind)
    recipient = normalize_phone(contact.phone)
    if not recipient:
        problem = 'Registre un WhatsApp válido en los datos del destinatario.'
    elif not contact.whatsapp_opt_in:
        problem = 'Registre la autorización del destinatario para recibir estos comprobantes.'
    if problem:
        message.status, message.detail = 'blocked', problem
        message.attempted_at = timezone.now()
        message.save()
        return None
    message.recipient = recipient
    message.status, message.detail = 'processing', ''
    message.provider_id = ''
    message.attempts += 1
    message.attempted_at = timezone.now()
    message.save()
    message_audit(message, 'Intentar envío WhatsApp')
    return message


def dispatch_message(pk):
    message = claim_message(pk)
    if message is None:
        return WhatsAppMessage.objects.get(pk=pk)
    try:
        identity = meta_request(settings.WHATSAPP_PHONE_NUMBER_ID + '?fields=display_phone_number')
        if normalize_phone(identity.get('display_phone_number')) != normalize_phone(settings.WHATSAPP_SENDER_NUMBER):
            raise MetaError('sender_mismatch')
        media_id = upload_document(message)
        template = settings.WHATSAPP_SALE_TEMPLATE if message.kind == 'sale' else settings.WHATSAPP_PAYROLL_TEMPLATE
        result = meta_request(settings.WHATSAPP_PHONE_NUMBER_ID + '/messages', sending=True, payload={
            'messaging_product': 'whatsapp', 'to': message.recipient, 'type': 'template',
            'biz_opaque_callback_data': f'{message.pk}:{message.attempts}',
            'template': {'name': template, 'language': {'code': settings.WHATSAPP_TEMPLATE_LANGUAGE}, 'components': [
                {'type': 'header', 'parameters': [{'type': 'document', 'document': {'id': media_id, 'filename': message.filename}}]},
                {'type': 'body', 'parameters': [{'type': 'text', 'text': ' '.join(value.split())}
                    for value in (message.recipient_name, message.reference, message.summary)]}
            ]}})
        replies = result.get('messages')
        provider_id = replies[0].get('id') if isinstance(replies, list) and replies and isinstance(replies[0], dict) else None
        if not isinstance(provider_id, str) or not provider_id or len(provider_id) > 200:
            raise MetaError('missing_message_id', ambiguous=True)
        outcome = ('accepted', 'WhatsApp aceptó la solicitud. La entrega se confirma por webhook.', provider_id)
    except MetaError as exc:
        outcome = ('uncertain' if exc.ambiguous else 'failed',
                   'No se pudo confirmar el envío; revise WhatsApp antes de reintentar.' if exc.ambiguous else f'WhatsApp no aceptó la operación (código {exc.code}). Revise la configuración.', '')
    # Un webhook puede haber confirmado la entrega antes de que vuelva la respuesta HTTP.
    with transaction.atomic():
        current = WhatsAppMessage.objects.select_for_update().get(pk=pk)
        if current.status == 'processing':
            current.status, current.detail, current.provider_id = outcome
            current.save()
            message_audit(current, 'Resultado WhatsApp')
    return WhatsAppMessage.objects.get(pk=pk)
