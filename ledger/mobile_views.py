"""API móvil por sesión: jamás entrega el secreto del sincronizador de escritorio."""
import json
from decimal import InvalidOperation
from pathlib import Path
from django.conf import settings
from django.contrib.staticfiles.storage import staticfiles_storage
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import HttpResponse, JsonResponse
from django.middleware.csrf import get_token
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_POST
from .models import Customer, Product, PaymentMethod, ExpenseCategory, Sale
from .sync import PERMISSIONS, accept


def mobile_identity(request):
    return {'user': request.user.pk, 'username': request.user.username,
            'business': settings.SYNC_BUSINESS or request.get_host()}


def denied(request):
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Inicia sesión con internet para sincronizar.'}, status=401)
    if not request.user.has_perms(PERMISSIONS):
        return JsonResponse({'error': 'No tienes permisos para descargar la contabilidad.'}, status=403)
    return None


@require_GET
def shell(request):
    return render(request, 'ledger/mobile.html')


@require_GET
@ensure_csrf_cookie
def bootstrap(request):
    rejection = denied(request)
    if rejection is not None:
        return rejection
    if settings.OFFLINE_NODE:
        return JsonResponse({'error': 'Instala la app móvil desde el dominio HTTPS de la nube.'}, status=409)
    sales = Sale.objects.prefetch_related('allocations').all()
    debts = [{'id': s.pk, 'token': str(s.token), 'customer': s.customer_id,
              'date': timezone.localtime(s.occurred_at).date().isoformat(),
              'balance': str(s.balance)} for s in sales if s.balance > 0]
    return JsonResponse({
        'identity': mobile_identity(request), 'csrf': get_token(request),
        'updated': timezone.now().isoformat(),
        'customers': list(Customer.objects.values('id', 'name', 'active', 'created_at')),
        'products': list(Product.objects.values('id', 'name', 'active', 'price', 'unit',
                                                'by_weight', 'variable_weight', 'weight')),
        'methods': list(PaymentMethod.objects.values('id', 'name', 'active', 'is_credit')),
        'categories': list(ExpenseCategory.objects.values('id', 'name', 'active')),
        'debts': debts,
        'permissions': {kind: request.user.has_perm(f'ledger.add_{kind}')
                        for kind in ('sale', 'payment', 'expense')},
    })


@require_POST
def push(request):
    rejection = denied(request)
    if rejection is not None:
        return rejection
    if settings.OFFLINE_NODE:
        return JsonResponse({'error': 'Sincroniza el celular con la nube.'}, status=409)
    try:
        data = json.loads(request.body)
        if data['identity'] != mobile_identity(request):
            raise PermissionDenied
        accept(data['operation'], request.user)
        return JsonResponse({'ok': True})
    except PermissionDenied:
        return JsonResponse({'error': 'La cuenta cambió o no tiene permiso para registrar este movimiento.'}, status=403)
    except (ValidationError, ValueError, KeyError, TypeError, AttributeError,
            InvalidOperation, Customer.DoesNotExist, Product.DoesNotExist,
            PaymentMethod.DoesNotExist, ExpenseCategory.DoesNotExist) as exc:
        message = ' '.join(exc.messages) if isinstance(exc, ValidationError) else 'Movimiento inválido.'
        return JsonResponse({'error': message}, status=409)


@require_GET
def service_worker(request):
    import hashlib
    files = ['ledger/mobile.js', 'ledger/mobile.css', 'ledger/mobile-icon-192.png',
             'ledger/mobile-icon-512.png']
    assets = ['/movil/', '/movil/manifest.webmanifest'] + [staticfiles_storage.url(f) for f in files]
    source_dir = Path(settings.BASE_DIR) / 'ledger'
    version = hashlib.sha256(b''.join((source_dir / 'static' / f).read_bytes() for f in files)
                             + (source_dir / 'templates/ledger/mobile.html').read_bytes()
                             + (source_dir / 'static/ledger/mobile-sw.js').read_bytes()).hexdigest()[:16]
    source = (source_dir / 'static/ledger/mobile-sw.js').read_text()
    source = source.replace('__ASSETS__', json.dumps(assets)).replace('__VERSION__', version)
    response = HttpResponse(source, content_type='application/javascript')
    response['Service-Worker-Allowed'] = '/movil/'
    response['Cache-Control'] = 'no-cache'
    return response


@require_GET
def manifest(request):
    return JsonResponse({'id': '/movil/', 'name': 'Contabilidad de Fresas',
                         'short_name': 'Fresas', 'lang': 'es-CO', 'start_url': '/movil/',
                         'scope': '/movil/', 'display': 'standalone',
                         'background_color': '#f6f5ef', 'theme_color': '#14301f',
                         'icons': [{'src': staticfiles_storage.url(f'ledger/mobile-icon-{size}.png'),
                                    'sizes': f'{size}x{size}', 'type': 'image/png',
                                    'purpose': 'any maskable'} for size in (192, 512)]},
                        content_type='application/manifest+json')
