import hashlib
import hmac
import json
import time
from datetime import timedelta
from urllib.parse import urlencode
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import F
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST, require_GET
from .models import WhatsAppMessage, Payroll
from .whatsapp import (configuration_problem, dispatch_message, normalize_phone,
                       individual_payroll_pdf, message_audit)


def queue_context(jobs):
    jobs = list(jobs)
    for job in jobs:
        contact = job.sale.customer if job.sale_id else job.worker
        phone = normalize_phone(contact.phone)
        job.manual_url = ('https://wa.me/' + phone + '?' + urlencode({'text': f'Hola {job.recipient_name}. Nómina {job.reference}: {job.summary}. Adjunto el comprobante.'})) if phone else ''
    return dict(wa_jobs=jobs, wa_sender=settings.WHATSAPP_SENDER_NUMBER,
                wa_problem=configuration_problem(), wa_enabled=not bool(configuration_problem()))


def require_source(user, job, sending=False):
    permissions = ['ledger.view_sale', 'ledger.view_payment'] if job.sale_id else ['ledger.view_payroll', 'ledger.view_worker']
    if sending:
        permissions.append('ledger.send_whatsappmessage')
    if not user.has_perms(permissions):
        raise PermissionDenied


@login_required
@require_POST
def process(request, pk):
    job = get_object_or_404(WhatsAppMessage, pk=pk)
    require_source(request.user, job, sending=True)
    job = dispatch_message(pk)
    return JsonResponse({'status': job.status, 'label': job.get_status_display(), 'detail': job.detail})


@login_required
@require_POST
def retry(request, pk):
    from .farm_services import lock_farm
    with transaction.atomic():
        lock_farm()
        job = get_object_or_404(WhatsAppMessage.objects.select_for_update(), pk=pk)
        require_source(request.user, job, sending=True)
        if job.status == 'processing' and job.attempted_at and job.attempted_at < timezone.now() - timedelta(minutes=2):
            job.status = 'uncertain'
            job.detail = 'El proceso anterior no confirmó el resultado. Revise WhatsApp.'
            job.save()
        if job.payroll_id and job.payroll.status == 'cancelled':
            messages.error(request, 'No se puede enviar una nómina anulada.')
        elif request.POST.get('action') == 'review':
            messages.info(request, 'Estado actualizado. Revise WhatsApp antes de autorizar un nuevo intento.')
        elif job.status == 'uncertain' and request.POST.get('confirm_uncertain') != 'yes':
            messages.error(request, 'Revise primero si el documento llegó al destinatario; un reenvío podría duplicarlo.')
        elif job.status in ('pending', 'blocked', 'failed', 'uncertain'):
            job.status, job.detail = 'pending', ''
            job.save()
            message_audit(job, 'Reintento WhatsApp autorizado')
        else:
            messages.info(request, 'El mensaje ya fue aceptado o está en proceso; no se enviará de nuevo.')
    return redirect('sale_detail', pk=job.sale_id) if job.sale_id else redirect('payroll_detail', pk=job.payroll_id)


@login_required
@permission_required('ledger.view_payroll', raise_exception=True)
@require_GET
def payroll_document(request, pk, worker_id):
    payroll = get_object_or_404(Payroll, pk=pk)
    if not payroll.days.filter(snapshot__worker_id=worker_id).exists():
        from django.http import Http404
        raise Http404
    response = individual_payroll_pdf(payroll, worker_id)
    response['Content-Disposition'] = f'attachment; filename="nomina-{pk}-trabajador-{worker_id}.pdf"'
    return response


@require_GET
def cron(request):
    if (not settings.CRON_SECRET or len(settings.CRON_SECRET) < 32
            or not hmac.compare_digest(request.headers.get('Authorization', '').encode(), ('Bearer ' + settings.CRON_SECRET).encode())):
        return JsonResponse({'error': 'Acceso denegado.'}, status=403)
    if configuration_problem():
        return JsonResponse({'pending_configuration': True})
    started = time.monotonic()
    jobs = list(WhatsAppMessage.objects.filter(status__in=['pending', 'blocked']).order_by(F('attempted_at').asc(nulls_first=True), 'created_at').values_list('pk', flat=True)[:40])
    processed = 0
    for pk in jobs:
        if time.monotonic() - started > 40:
            break
        dispatch_message(pk)
        processed += 1
    return JsonResponse({'processed': processed})


@csrf_exempt
@transaction.atomic
def webhook(request):
    if request.method == 'GET':
        if (settings.WHATSAPP_VERIFY_TOKEN and request.GET.get('hub.mode') == 'subscribe'
                and hmac.compare_digest(request.GET.get('hub.verify_token', '').encode(), settings.WHATSAPP_VERIFY_TOKEN.encode())):
            return HttpResponse(request.GET.get('hub.challenge', ''), content_type='text/plain')
        return HttpResponse(status=403)
    if request.method != 'POST':
        return HttpResponse(status=405)
    if not settings.WHATSAPP_APP_SECRET:
        return HttpResponse(status=503)
    if len(request.body) > 1000000:
        return HttpResponse(status=413)
    signature = 'sha256=' + hmac.new(settings.WHATSAPP_APP_SECRET.encode(), request.body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(request.headers.get('X-Hub-Signature-256', '').encode(), signature.encode()):
        return HttpResponse(status=403)
    try:
        payload = json.loads(request.body)
        if not isinstance(payload, dict):
            raise ValueError
        for entry in payload.get('entry', []):
            for change in entry.get('changes', []):
                value = change.get('value', {})
                if value.get('metadata', {}).get('phone_number_id') != settings.WHATSAPP_PHONE_NUMBER_ID:
                    continue
                for event in value.get('statuses', []):
                    status = event.get('status')
                    if status not in ('sent', 'delivered', 'read', 'failed') or not event.get('id'):
                        continue
                    jobs = WhatsAppMessage.objects.select_for_update().filter(provider_id=event['id'])
                    callback = event.get('biz_opaque_callback_data')
                    if callback:
                        import uuid
                        try:
                            callback_id, callback_attempt = callback.rsplit(':', 1)
                            jobs = WhatsAppMessage.objects.select_for_update().filter(pk=uuid.UUID(callback_id), attempts=int(callback_attempt))
                        except (ValueError, TypeError):
                            continue
                    job = jobs.first()
                    if not job or job.status not in ('processing', 'uncertain', 'accepted', 'sent', 'delivered', 'read', 'failed'):
                        continue
                    if job.provider_id and job.provider_id != event['id']:
                        continue
                    if normalize_phone(event.get('recipient_id')) != job.recipient:
                        continue
                    rank = {'processing': 0, 'uncertain': 0, 'failed': 0, 'accepted': 1, 'sent': 2, 'delivered': 3, 'read': 4}
                    if status == 'failed' and job.status in ('delivered', 'read'):
                        continue
                    if status != 'failed' and rank[status] < rank[job.status]:
                        continue
                    if job.status == status and job.provider_id == event['id']:
                        continue
                    job.status, job.provider_id = status, event['id']
                    job.detail = 'WhatsApp informó este estado mediante webhook verificado.'
                    job.save()
                    message_audit(job, 'Confirmación WhatsApp')
    except (ValueError, TypeError, AttributeError, KeyError):
        return HttpResponse(status=400)
    return HttpResponse(status=200)


@login_required
@permission_required(('ledger.view_sale', 'ledger.view_payment', 'ledger.send_whatsappmessage'), raise_exception=True)
@require_POST
def prepare_sale(request, pk):
    from .models import Sale
    from .whatsapp import enqueue_sale
    from .services import retry_locked
    sale = get_object_or_404(Sale, pk=pk)
    if not sale.customer.whatsapp_opt_in:
        messages.error(request, 'Registre primero en Clientes la autorización para recibir comprobantes por WhatsApp.')
    else:
        retry_locked(enqueue_sale)(sale, request.user)
        messages.success(request, 'Comprobante preparado. Consulte el estado de envío debajo.')
    return redirect('sale_detail', pk=pk)
