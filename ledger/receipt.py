"""Comprobante privado y opciones de compartir sin publicar datos del cliente."""
from urllib.parse import urlencode
from django.conf import settings
from django.utils import timezone
from .exports import export_table
from .reporting import line_totals
from .templatetags.money import cop, plain_number


def whatsapp_url(sale):
    from .whatsapp import normalize_phone
    digits = normalize_phone(sale.customer.phone)
    if not digits:
        return ''
    message = f'Hola {sale.customer_name}, te comparto el comprobante {sale} de {settings.BUSINESS_NAME} por {cop(sale.total)}. Adjunto el PDF en esta conversación.'
    return f'https://wa.me/{digits}?' + urlencode({'text': message})


def sale_receipt(sale, inline=False):
    totals = line_totals(sale.lines.all())
    response = export_table('pdf', f'{settings.BUSINESS_NAME} · {sale} · Comprobante de venta interno',
        ['Producto', 'Cantidad', 'Unidad', 'lb / presentación', 'Peso total lb', 'Precio', 'Subtotal'],
        [[l.name, plain_number(l.quantity), l.unit, plain_number(l.weight) if l.by_weight else '—',
          plain_number(l.total_weight) if l.by_weight else '—', cop(l.price), cop(l.subtotal)] for l in sale.lines.all()],
        f'Cliente: {sale.customer_name} · Identificación: {sale.customer_identification or "Sin registrar"} · '
        f'{timezone.localtime(sale.occurred_at):%d/%m/%Y %H:%M} · {sale.method_name} | Total: {cop(sale.total)} | '
        f'Pago inicial: {cop(sale.initial_payment)} | Total abonado: {cop(sale.paid)} | Saldo actual: {cop(sale.balance)}',
        totals=['Total vendido', plain_number(totals['quantity']), '', '', plain_number(totals['weight']), '', cop(sale.total)])
    disposition = 'inline' if inline else 'attachment'
    response['Content-Disposition'] = f'{disposition}; filename="{sale}.pdf"'
    return response
