import calendar
import uuid
from datetime import date, timedelta
from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django import forms
from .models import Worker, PayrollSettings, Attendance, Payroll, SprayProduct, SprayApplication, Audit
from .farm_forms import (WorkerForm, SettingsForm, SprayProductForm, AttendanceRows, PeriodForm, SprayForm, SprayRows)
from .farm_services import (save_catalog, save_attendance, generate_payroll, payroll_summary,
                            payroll_transition, save_spray, cancel_spray)
from .farm_exports import payroll_xlsx


def require(user, *permissions):
    if not user.has_perms(permissions):
        raise PermissionDenied


def notify_error(request, exc):
    messages.error(request, ' '.join(exc.messages))


@login_required
def farm_catalog(request, kind, pk=None, edit=False):
    model, formclass, title, base = {
        'workers': (Worker, WorkerForm, 'Trabajadores', '/nomina/trabajadores/'),
        'spray_products': (SprayProduct, SprayProductForm, 'Productos para fumigación', '/fumigacion/productos/'),
        'settings': (PayrollSettings, SettingsForm, 'Configuración de tarifas', '/nomina/')
    }[kind]
    require(request.user, f'ledger.view_{model._meta.model_name}')
    if edit or kind == 'settings':
        require(request.user, f'ledger.{"change" if pk or kind == "settings" else "add"}_{model._meta.model_name}')
        obj = (model.objects.filter(pk=1).first() or model(pk=1)) if kind == 'settings' else (get_object_or_404(model, pk=pk) if pk else None)
        form = formclass(request.POST or None, instance=obj)
        if request.method == 'POST' and form.is_valid():
            try:
                save_catalog(form, request.user)
                messages.success(request, 'Información guardada; las tarifas históricas se conservan.')
                return redirect(base)
            except ValidationError as exc:
                form.add_error(None, exc)
        history = Audit.objects.filter(entity=model._meta.label, object_id=obj.pk).order_by('-date')[:30] if obj and obj.pk else []
        return render(request, 'ledger/form.html', dict(title=title, form=form, back=base, history=history))
    records = model.objects.all()
    q = request.GET.get('q', '').strip()
    if q:
        records = records.filter(name__icontains=q)
    state = request.GET.get('active', '')
    if state in ('1', '0'):
        records = records.filter(active=state == '1')
    return render(request, 'ledger/farm_catalog.html', dict(title=title, records=records, base=base, kind=kind, q=q, active=state))


@login_required
@permission_required(('ledger.view_worker', 'ledger.view_attendance', 'ledger.view_payroll'), raise_exception=True)
def worker_history(request, pk):
    worker = get_object_or_404(Worker, pk=pk)
    attendance = worker.attendance.all()
    payrolls = Payroll.objects.filter(days__attendance__worker=worker).distinct()
    return render(request, 'ledger/worker_history.html', dict(title=worker.name, worker=worker, attendance=attendance, payrolls=payrolls))


def selected_date(request):
    field = forms.DateField()
    try:
        return field.clean(request.GET.get('date') or timezone.localdate().isoformat())
    except ValidationError:
        messages.error(request, 'Fecha inválida. Se muestra hoy.')
        return timezone.localdate()


@login_required
@permission_required(('ledger.view_worker', 'ledger.view_attendance'), raise_exception=True)
def attendance(request):
    day = selected_date(request)
    workers = list(Worker.objects.filter(Q(active=True, joined_on__lte=day) | Q(attendance__date=day)).distinct())
    existing = {a.worker_id: a for a in Attendance.objects.filter(date=day)}
    initial = []
    for worker in workers:
        a = existing.get(worker.pk)
        hours, minutes = divmod(a.extra_minutes if a else 0, 60)
        initial.append(dict(worker=worker.pk, revision=a.revision if a else 0,
                            worked=a.worked if a else False, hours=hours, minutes=minutes, notes=a.notes if a else ''))
    rows = AttendanceRows(request.POST if request.method == 'POST' else None, initial=initial)
    for row, worker in zip(rows, workers):
        record = existing.get(worker.pk)
        row.locked = bool(record and record.payroll_days.exclude(payroll__status='cancelled').exists())
        if row.locked:
            for name in ('worked', 'hours', 'minutes', 'notes'):
                row.fields[name].disabled = True
    if request.method == 'POST':
        require(request.user, 'ledger.add_attendance', 'ledger.change_attendance')
        if rows.is_valid():
            try:
                if {r['worker'] for r in rows.cleaned_data} != {w.pk for w in workers}:
                    raise ValidationError('Cambió el listado de trabajadores. Recargue la fecha.')
                save_attendance(day, rows.cleaned_data, request.user)
                messages.success(request, 'Asistencia guardada sin duplicados.')
                return redirect(request.get_full_path())
            except ValidationError as exc:
                notify_error(request, exc)
    for row in rows:
        try:
            row.worker_name = next(w.name for w in workers if str(w.pk) == str(row['worker'].value()))
        except StopIteration:
            row.worker_name = 'Trabajador inválido'
    return render(request, 'ledger/attendance.html', dict(title='Registro diario de asistencia', day=day, rows=rows))


@login_required
@permission_required('ledger.view_payroll', raise_exception=True)
def payroll_list(request):
    records = Payroll.objects.all()
    if request.GET.get('status') in ('generated', 'paid', 'cancelled'):
        records = records.filter(status=request.GET['status'])
    for param, lookup in [('start', 'end__gte'), ('end', 'start__lte')]:
        if request.GET.get(param):
            try:
                records = records.filter(**{lookup: forms.DateField().clean(request.GET[param])})
            except ValidationError as exc:
                notify_error(request, exc)
    return render(request, 'ledger/payroll_list.html', dict(title='Historial de nóminas', records=records))


@login_required
@permission_required(('ledger.add_payroll', 'ledger.view_attendance', 'ledger.view_worker', 'ledger.view_payroll'), raise_exception=True)
def payroll_new(request):
    today = timezone.localdate()
    form = PeriodForm(request.POST or None, initial={'start': today - timedelta(days=today.weekday()), 'end': today, 'token': uuid.uuid4()})
    if request.method == 'POST' and form.is_valid():
        try:
            p = generate_payroll(user=request.user, **form.cleaned_data)
            messages.success(request, 'Nómina generada y guardada. Revise el detalle antes de confirmar el pago.')
            return redirect('payroll_detail', pk=p.pk)
        except ValidationError as exc:
            form.add_error(None, exc)
    return render(request, 'ledger/payroll_new.html', dict(title='Generar nómina', form=form))


@login_required
@permission_required('ledger.view_payroll', raise_exception=True)
def payroll_detail(request, pk):
    p = get_object_or_404(Payroll, pk=pk)
    if request.method == 'POST':
        require(request.user, 'ledger.change_payroll')
        try:
            payroll_transition(pk, request.POST.get('action'), request.POST.get('reason', ''), request.user)
            messages.success(request, 'Estado actualizado. La operación quedó auditada.')
            return redirect('payroll_detail', pk=pk)
        except ValidationError as exc:
            notify_error(request, exc)
    if request.GET.get('export') == 'xlsx':
        return payroll_xlsx(p)
    return render(request, 'ledger/payroll_detail.html', dict(title=f'Nómina #{p.pk}', payroll=p, summary=payroll_summary(p),
        history=Audit.objects.filter(entity=Payroll._meta.label, object_id=pk).order_by('-date')))


@login_required
@permission_required(('ledger.view_sprayapplication', 'ledger.view_sprayproduct'), raise_exception=True)
def spray_list(request, mode='history'):
    records = SprayApplication.objects.prefetch_related('lines').all()
    area = request.GET.get('area', '').strip()
    product = request.GET.get('product', '')
    if area:
        records = records.filter(area__icontains=area)
    if product.isdecimal():
        records = records.filter(lines__product_id=product)
    if mode == 'upcoming':
        records = records.filter(status='scheduled').order_by('scheduled_at')
    for param in ('start', 'end'):
        if request.GET.get(param):
            try:
                value = forms.DateField().clean(request.GET[param])
                records = records.filter(**{f'scheduled_at__date__{"gte" if param == "start" else "lte"}': value})
            except ValidationError as exc:
                notify_error(request, exc)
    weeks = []
    month = selected_date(request).replace(day=1)
    if mode == 'calendar':
        last = date(month.year, month.month, calendar.monthrange(month.year, month.month)[1])
        events = list(records.filter(scheduled_at__date__range=(month, last)).order_by('scheduled_at'))
        weeks = [[{'date': d, 'events': [e for e in events if timezone.localtime(e.scheduled_at).date() == d], 'in_month': d.month == month.month}
                 for d in week] for week in calendar.Calendar().monthdatescalendar(month.year, month.month)]
    return render(request, 'ledger/spray_list.html', dict(title={'history': 'Historial de aplicaciones', 'upcoming': 'Próximas aplicaciones', 'calendar': 'Calendario de fumigaciones'}[mode],
        records=records, mode=mode, weeks=weeks, month=month, previous=(month-timedelta(days=1)).replace(day=1),
        following=(month+timedelta(days=32)).replace(day=1), products=SprayProduct.objects.all(), area=area, product=product))


@login_required
@permission_required(('ledger.view_sprayapplication', 'ledger.view_sprayproduct'), raise_exception=True)
def spray_edit(request, pk=None):
    obj = get_object_or_404(SprayApplication, pk=pk) if pk else None
    require(request.user, 'ledger.change_sprayapplication' if obj else 'ledger.add_sprayapplication')
    if obj and obj.status != 'scheduled':
        return redirect('spray_detail', pk=pk)
    initial = [dict(product=l.product_id, quantity=l.quantity, unit=l.unit) for l in obj.lines.all()] if obj else []
    form = SprayForm(request.POST or None, instance=obj, initial={'token': obj.token if obj else uuid.uuid4(),
        'scheduled_at': obj.scheduled_at if obj else timezone.localtime().replace(second=0, microsecond=0), 'status': obj.status if obj else 'completed'})
    rows = SprayRows(request.POST if request.method == 'POST' else None, initial=initial)
    # Los productos inactivos ya programados siguen siendo consultables y editables.
    for row in rows:
        row.fields['product'].queryset = SprayProduct.objects.filter(Q(active=True) | Q(applications__application=obj)).distinct() if obj else SprayProduct.objects.filter(active=True)
    if request.method == 'POST' and form.is_valid() and rows.is_valid():
        try:
            saved = save_spray(form, [r for r in rows.cleaned_data if r and not r.get('DELETE')], request.user)
            messages.success(request, 'Aplicación guardada. Las programaciones requieren confirmación para pasar a realizadas.')
            return redirect('spray_detail', pk=saved.pk)
        except ValidationError as exc:
            form.add_error(None, exc)
    product_rules = list(SprayProduct.objects.filter(active=True).values('id', 'name', 'unit', 'interval_days', 'interval_source'))
    return render(request, 'ledger/spray_form.html', dict(title='Editar programación' if obj else 'Registrar fumigación', form=form, rows=rows, product_rules=product_rules))


@login_required
@permission_required(('ledger.view_sprayapplication', 'ledger.view_sprayproduct'), raise_exception=True)
def spray_detail(request, pk):
    obj = get_object_or_404(SprayApplication.objects.prefetch_related('lines'), pk=pk)
    if request.method == 'POST':
        require(request.user, 'ledger.change_sprayapplication')
        try:
            cancel_spray(pk, request.POST.get('reason', ''), request.user)
            messages.success(request, 'Programación anulada; se conserva el historial.')
            return redirect('spray_detail', pk=pk)
        except ValidationError as exc:
            notify_error(request, exc)
    return render(request, 'ledger/spray_detail.html', dict(title=f'Fumigación #{pk}', application=obj,
        history=Audit.objects.filter(entity=SprayApplication._meta.label, object_id=pk).order_by('-date')))
