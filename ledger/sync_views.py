from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from .models import SyncState
from .sync import pending


@login_required
def sync_status(request):
    state = SyncState.objects.filter(pk=1).first() if settings.OFFLINE_NODE else None
    operations = pending() if settings.OFFLINE_NODE else []
    return render(request, 'ledger/sync_status.html', {
        'title': 'Sincronización', 'offline_node': settings.OFFLINE_NODE,
        'state': state, 'pending_count': len(operations), 'pending_operations': operations[:100],
    })


def replica_context(request):
    return {'offline_replica': settings.OFFLINE_NODE}
