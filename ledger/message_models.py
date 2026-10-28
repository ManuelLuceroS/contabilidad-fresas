import uuid
from django.conf import settings
from django.db import models
from .models import Timestamp


class WhatsAppMessage(Timestamp):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    key = models.CharField(max_length=150, unique=True)
    kind = models.CharField(max_length=12, choices=[('sale', 'Venta'), ('payroll', 'Nómina')])
    phase = models.CharField(max_length=12, default='generated')
    sale = models.ForeignKey('ledger.Sale', on_delete=models.PROTECT, null=True, blank=True, related_name='whatsapp_messages')
    payroll = models.ForeignKey('ledger.Payroll', on_delete=models.PROTECT, null=True, blank=True, related_name='whatsapp_messages')
    worker = models.ForeignKey('ledger.Worker', on_delete=models.PROTECT, null=True, blank=True)
    recipient = models.CharField(max_length=20, blank=True)
    recipient_name = models.CharField(max_length=180)
    reference = models.CharField(max_length=100)
    summary = models.CharField(max_length=1000)
    document = models.BinaryField(editable=False)
    filename = models.CharField(max_length=100)
    status = models.CharField(max_length=15, default='pending', choices=[
        ('pending', 'Pendiente'), ('blocked', 'Pendiente de configuración o contacto'),
        ('processing', 'En proceso'), ('accepted', 'Aceptado por WhatsApp'), ('sent', 'Enviado'),
        ('delivered', 'Entregado'), ('read', 'Leído'), ('failed', 'Rechazado'),
        ('uncertain', 'Envío por verificar'), ('cancelled', 'Cancelado')])
    detail = models.CharField(max_length=250, blank=True)
    provider_id = models.CharField(max_length=200, blank=True, db_index=True)
    attempts = models.PositiveIntegerField(default=0)
    attempted_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)

    class Meta:
        ordering = ['created_at']
        permissions = [('send_whatsappmessage', 'Puede enviar comprobantes por WhatsApp')]
        constraints = [models.CheckConstraint(condition=(
            models.Q(kind='sale', sale__isnull=False, payroll__isnull=True, worker__isnull=True)
            | models.Q(kind='payroll', sale__isnull=True, payroll__isnull=False, worker__isnull=False)
        ), name='whatsapp_recipient_source')]
