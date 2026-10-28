"""Vistas y filtros de las pantallas de ventas, cartera y gastos."""

import hashlib
import json
import uuid
from datetime import date, timedelta
from decimal import Decimal
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required, permission_required
from django.core.exceptions import ValidationError, PermissionDenied
from django.core.serializers.json import DjangoJSONEncoder
from django.db import transaction, IntegrityError
from django.db.models import Q, Sum, F
from django.forms.models import model_to_dict
from django.http import HttpResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.views.decorators.http import require_POST
from .models import (
    Audit,
    Customer,
    Expense,
    ExpenseCategory,
    LoginAttempt,
    Payment,
    PaymentMethod,
    Product,
    Sale,
)
from .forms import CategoryForm, CustomerForm, ExpenseForm, MethodForm, ProductForm
from .services import create_sale, create_payment, statement, audit, token_value
from .exports import export_table, export_sales_pdf
from .reporting import sales_summary, line_totals
from .templatetags.money import cop, plain_number

ZERO = Decimal("0")


def error(request, exc):
    messages.error(
        request,
        " ".join(exc.messages) if isinstance(exc, ValidationError) else str(exc),
    )


def period(request, default=False):
    today = timezone.localdate()
    try:
        start = (
            date.fromisoformat(request.GET["start"])
            if request.GET.get("start")
            else today.replace(day=1) if default else None
        )
        end = (
            date.fromisoformat(request.GET["end"])
            if request.GET.get("end")
            else today if default else None
        )
        if start and end and start > end:
            raise ValueError()
        return start, end
    except ValueError:
        messages.error(request, "Rango de fechas inválido. Se muestra el mes actual.")
        return today.replace(day=1), today


def display_date(value, fallback="Hoy"):
    return value.strftime("%d/%m/%Y") if value else fallback


def date_filter(qs, field, start, end):
    if start:
        qs = qs.filter(**{field + "__gte": start})
    if end:
        qs = qs.filter(**{field + "__lte": end})
    return qs


def login_view(request):
    from django.utils.http import url_has_allowed_host_and_scheme
    target = request.POST.get('next') or request.GET.get('next') or '/'
    if not url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        target = '/'
    if request.user.is_authenticated:
        return redirect(target)
    if request.method == "POST":
        username = request.POST.get("username", "").strip()
        key = hashlib.sha256(username.casefold().encode()).hexdigest()
        attempt, _ = LoginAttempt.objects.get_or_create(key=key)
        blocked = (
            attempt.failures >= 5
            and timezone.now() - attempt.last_attempt < timedelta(minutes=15)
        )
        user = (
            None
            if blocked
            else authenticate(
                request, username=username, password=request.POST.get("password", "")
            )
        )
        if user:
            LoginAttempt.objects.filter(pk=attempt.pk).update(failures=0)
            login(request, user)
            return redirect(target)
        if not blocked:
            count = (
                attempt.failures + 1
                if timezone.now() - attempt.last_attempt < timedelta(minutes=15)
                else 1
            )
            LoginAttempt.objects.filter(pk=attempt.pk).update(
                failures=count, last_attempt=timezone.now()
            )
        messages.error(
            request,
            (
                "Demasiados intentos. Espere 15 minutos."
                if blocked
                else "Usuario, correo o contraseña incorrectos."
            ),
        )
    return render(request, "ledger/login.html")


@require_POST
@login_required
def logout_view(request):
    logout(request)
    return redirect("login")


@login_required
@permission_required(
    (
        "ledger.view_sale",
        "ledger.view_payment",
        "ledger.view_expense",
        "ledger.view_customer",
        "ledger.view_product",
    ),
    raise_exception=True,
)
def dashboard(request):
    start, end = period(request, True)
    today = timezone.localdate()
    sales = Sale.objects.prefetch_related("allocations")
    from .reporting import accounting_expenses
    expenses = accounting_expenses()
    selected = list(date_filter(sales, "occurred_at__date", start, end))
    selected_expenses = list(date_filter(expenses, "date", start, end))
    payments = date_filter(Payment.objects.all(), "date", start, end)

    def sales_total(q):
        return sum((s.total for s in q), ZERO)

    def expenses_total(q):
        return sum((e.amount for e in q), ZERO)

    metrics = [
        ("Ventas de hoy", sales_total(sales.filter(occurred_at__date=today))),
        (
            "Ventas del mes",
            sales_total(
                sales.filter(
                    occurred_at__date__gte=today.replace(day=1),
                    occurred_at__date__lte=today,
                )
            ),
        ),
        ("Gastos de hoy", expenses_total(expenses.filter(date=today))),
        (
            "Gastos del mes",
            expenses_total(
                expenses.filter(date__gte=today.replace(day=1), date__lte=today)
            ),
        ),
        ("Cuentas por cobrar", sum((s.balance for s in sales), ZERO)),
        ("Abonos del periodo", sum((p.amount for p in payments), ZERO)),
    ]
    customers = list(Customer.objects.prefetch_related("sales__allocations"))
    top = sorted(
        [c for c in customers if c.balance > 0], key=lambda c: c.balance, reverse=True
    )[:5]
    # Agrupa por día hasta 62 días; usa meses para periodos más largos.
    buckets = {}
    monthly = (end - start).days > 62
    for s in selected:
        d = timezone.localtime(s.occurred_at).date()
        k = d.strftime("%Y-%m" if monthly else "%Y-%m-%d")
        buckets.setdefault(k, [ZERO, ZERO])[0] += s.total
    for e in selected_expenses:
        k = e.date.strftime("%Y-%m" if monthly else "%Y-%m-%d")
        buckets.setdefault(k, [ZERO, ZERO])[1] += e.amount
    peak = max([max(v) for v in buckets.values()] + [Decimal("1")])
    chart = [
        {
            "label": date.fromisoformat(k + "-01" if monthly else k).strftime(
                "%m/%Y" if monthly else "%d/%m/%Y"
            ),
            "sales": v[0],
            "expenses": v[1],
            "sw": float(v[0] / peak * 100),
            "ew": float(v[1] / peak * 100),
        }
        for k, v in sorted(buckets.items())
    ]
    return render(
        request,
        "ledger/dashboard.html",
        dict(
            title="Resumen del negocio",
            metrics=metrics,
            start=start,
            end=end,
            top=top,
            chart=chart,
            active_customers=Customer.objects.filter(active=True).count(),
            active_products=Product.objects.filter(active=True).count(),
            period_sales=sales_total(selected),
            period_expenses=expenses_total(selected_expenses),
        ),
    )


CATALOGS = {
    "clientes": (Customer, CustomerForm, "Clientes", "customer"),
    "productos": (Product, ProductForm, "Productos", "product"),
    "categorias": (
        ExpenseCategory,
        CategoryForm,
        "Categorías de gastos",
        "expensecategory",
    ),
    "medios": (PaymentMethod, MethodForm, "Medios de pago", "paymentmethod"),
}


@login_required
def catalog(request, kind):
    if kind not in CATALOGS:
        return HttpResponse(status=404)
    model, form, title, perm = CATALOGS[kind]
    if not request.user.has_perm("ledger.view_" + perm):
        raise PermissionDenied
    if kind == "clientes" and not request.user.has_perms(
        ["ledger.view_sale", "ledger.view_payment"]
    ):
        raise PermissionDenied
    q = request.GET.get("q", "")
    objects = model.objects.all()
    if kind == "clientes":
        objects = objects.prefetch_related("sales__allocations")
    if q:
        condition = Q(name__icontains=q)
        if kind == "clientes":
            condition |= Q(identification__icontains=q)
        if kind == "productos":
            condition |= Q(code__icontains=q)
        objects = objects.filter(condition)
    balance_total = (
        sum((o.balance for o in objects), ZERO) if kind == "clientes" else ZERO
    )
    return render(
        request,
        "ledger/catalog.html",
        dict(title=title, objects=objects, kind=kind, q=q, balance_total=balance_total),
    )


@login_required
def catalog_edit(request, kind, pk=None):
    if kind not in CATALOGS:
        return HttpResponse(status=404)
    model, form_class, title, perm = CATALOGS[kind]
    if not request.user.has_perm("ledger." + ("change_" if pk else "add_") + perm):
        raise PermissionDenied
    instance = get_object_or_404(model, pk=pk) if pk else None
    form = form_class(request.POST or None, instance=instance)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            before = (
                json.loads(
                    json.dumps(
                        model_to_dict(model.objects.select_for_update().get(pk=pk)),
                        cls=DjangoJSONEncoder,
                    )
                )
                if pk
                else {}
            )
            obj = form.save()
            audit(
                request.user,
                obj,
                "Actualización" if pk else "Creación",
                before,
                json.loads(json.dumps(model_to_dict(obj), cls=DjangoJSONEncoder)),
            )
        messages.success(request, "Información guardada correctamente.")
        return redirect("catalog", kind=kind)
    return render(
        request,
        "ledger/form.html",
        dict(
            title=("Editar " if pk else "Crear ") + title.lower(),
            form=form,
            back="/" + kind + "/",
        ),
    )


@login_required
@permission_required(
    ("ledger.view_customer", "ledger.view_sale", "ledger.view_payment"),
    raise_exception=True,
)
def customer_detail(request, pk):
    c = get_object_or_404(Customer, pk=pk)
    start, end = period(request)
    opening, events, closing = statement(c, start, end)
    headers = [
        "Fecha",
        "Referencia",
        "Descripción",
        "Ventas (COP)",
        "Abonos (COP)",
        "Saldo (COP)",
    ]
    period_sales = sum((e["debit"] for e in events), ZERO)
    period_payments = sum((e["credit"] for e in events), ZERO)
    rows = [
        [
            e["date"].strftime("%d/%m/%Y"),
            e["reference"],
            e["description"],
            cop(e["debit"]),
            cop(e["credit"]),
            cop(e["balance"]),
        ]
        for e in events
    ]
    if request.GET.get("export") in ["csv", "pdf"]:
        return export_table(
            request.GET["export"],
            "Estado de cuenta · " + c.name,
            headers,
            rows,
            f'Identificación: {c.identification or "Sin registrar"} | Generado: {timezone.localtime():%d/%m/%Y %H:%M} | Periodo: {display_date(start,"Inicio")} a {display_date(end)} | Saldo inicial: {cop(opening)} | Saldo final: {cop(closing)}',
            totals=[
                "Totales del periodo",
                "",
                "",
                cop(period_sales),
                cop(period_payments),
                cop(closing),
            ],
        )
    history_sales = list(c.sales.prefetch_related("allocations"))
    history_payments = list(c.payments.select_related("created_by"))
    history_sold = sum((s.total for s in history_sales), ZERO)
    history_received = sum((p.amount for p in history_payments), ZERO)
    return render(
        request,
        "ledger/customer.html",
        dict(
            title=c.name,
            customer=c,
            start=start,
            end=end,
            opening=opening,
            events=events,
            closing=closing,
            period_sales=period_sales,
            period_payments=period_payments,
            sales=history_sales,
            payments=history_payments,
            history_sold=history_sold,
            history_received=history_received,
            history_balance=history_sold - history_received,
        ),
    )


@login_required
@permission_required("ledger.add_sale", raise_exception=True)
def sale_new(request):
    if request.method == "POST":
        try:
            method = get_object_or_404(PaymentMethod, pk=request.POST.get("method"))
            cash = (
                PaymentMethod.objects.filter(
                    pk=request.POST.get("cash_method") or None
                ).first()
                if method.is_credit
                else method
            )
            sale = create_sale(
                user=request.user,
                customer_id=request.POST.get("customer"),
                rows=json.loads(request.POST.get("rows", "[]")),
                method=method,
                initial=request.POST.get("initial", "0"),
                cash_method=cash,
                token=request.POST.get("token"),
            )
            messages.success(
                request, "Venta registrada. El comprobante ya está disponible."
            )
            return redirect("sale_operation", token=sale.token)
        except (ValidationError, ValueError, TypeError, Customer.DoesNotExist) as exc:
            error(request, exc)
    products = list(
        Product.objects.filter(active=True).values(
            "id",
            "name",
            "price",
            "unit",
            "by_weight",
            "variable_weight",
            "weight",
            "code",
        )
    )
    return render(
        request,
        "ledger/sale_new.html",
        dict(
            title="Nueva venta",
            customers=Customer.objects.filter(active=True),
            products=products,
            methods=PaymentMethod.objects.filter(active=True),
            cash_methods=PaymentMethod.objects.filter(active=True, is_credit=False),
            token=request.POST.get("token") or uuid.uuid4(),
            submitted=request.POST.dict(),
        ),
    )


@login_required
@permission_required(("ledger.view_sale", "ledger.view_payment"), raise_exception=True)
def sale_detail(request, pk=None, token=None):
    sale = get_object_or_404(
        Sale.objects.prefetch_related("lines", "allocations__payment"),
        **({"token": token} if token else {"pk": pk})
    )
    totals = line_totals(sale.lines.all())
    from .receipt import sale_receipt, whatsapp_url, sale_whatsapp_text
    from .whatsapp_views import queue_context
    if request.GET.get("export") == "pdf":
        return sale_receipt(sale, inline=request.GET.get("view") == "1")
    return render(
        request,
        "ledger/sale_detail.html",
        dict(title=str(sale), sale=sale, totals=totals, whatsapp_url=whatsapp_url(sale), sale_share_message=sale_whatsapp_text(sale),
             **queue_context(sale.whatsapp_messages.select_related('sale__customer'))),
    )


@login_required
@permission_required("ledger.view_sale", raise_exception=True)
def sales_report(request):
    start, end = period(request)
    qs = date_filter(
        Sale.objects.select_related("customer").prefetch_related("lines"),
        "occurred_at__date",
        start,
        end,
    )
    if request.GET.get("customer"):
        cid = request.GET["customer"]
        selected_customer = get_object_or_404(
            Customer, pk=int(cid) if cid.isdigit() and len(cid) < 16 else 0
        )
        qs = qs.filter(customer=selected_customer)
    q = request.GET.get("q", "")[:180]
    if q:
        cond = Q(customer_name__icontains=q)
        raw = q.upper().removeprefix("VE-")
        if raw.isdigit():
            cond |= Q(number=int(raw))
        qs = qs.filter(cond)
    order = request.GET.get("sort", "-occurred_at")
    if order in ["occurred_at", "-occurred_at", "total", "-total", "customer_name"]:
        qs = qs.order_by(order)
    sales = list(qs)
    total = sum((s.total for s in sales), ZERO)
    report = sales_summary(sales)
    quantity = report["quantity"]
    groups = {}
    for s in sales:
        group = groups.setdefault(
            s.customer_id,
            {
                "name": s.customer.name,
                "identification": s.customer.identification,
                "total": ZERO,
            },
        )
        group["total"] += s.total
    if request.GET.get("export") in ["csv", "pdf"]:
        summary = f'Periodo: {display_date(start,"Inicio")} a {display_date(end)} | Ventas: {len(sales)} | Total vendido: {cop(total)}'
        if request.GET["export"] == "pdf":
            return export_sales_pdf(sales, summary, report)
        rows = []
        for sale in sales:
            for line in sale.lines.all():
                rows.append(
                    [
                        timezone.localtime(sale.occurred_at).strftime("%d/%m/%Y"),
                        str(sale),
                        sale.customer_name,
                        line.name,
                        plain_number(line.quantity),
                        plain_number(line.total_weight) if line.by_weight else "",
                        cop(line.price),
                        cop(line.subtotal),
                    ]
                )
            rows.append(
                [
                    "",
                    str(sale),
                    "",
                    "TOTAL VENTA",
                    plain_number(sale.report_totals["quantity"]),
                    plain_number(sale.report_totals["weight"]),
                    "",
                    cop(sale.total),
                ]
            )
        rows.append(
            [
                "",
                "",
                "",
                "TOTAL VENDIDO",
                plain_number(report["quantity"]),
                plain_number(report["weight"]),
                "",
                cop(total),
            ]
        )
        rows.append([])
        rows.append(["RESUMEN GENERAL POR PRODUCTO"])
        rows.append(["Producto", "Cantidad", "Libras totales", "Total vendido"])
        rows.extend(
            [
                [
                    r["name"],
                    plain_number(r["quantity"]),
                    plain_number(r["weight"]) if r["by_weight"] else "",
                    cop(r["total"]),
                ]
                for r in report["products"]
            ]
        )
        rows.append(
            [
                "TOTAL GENERAL",
                plain_number(report["quantity"]),
                plain_number(report["weight"]),
                cop(total),
            ]
        )
        return export_table(
            "csv",
            "Reporte de ventas",
            [
                "Fecha",
                "Venta",
                "Cliente",
                "Producto",
                "Cantidad",
                "Libras totales",
                "Precio unidad / lb",
                "Subtotal",
            ],
            rows,
            summary,
        )
    return render(
        request,
        "ledger/sales.html",
        dict(
            title="Ventas y reportes",
            sales=sales,
            start=start,
            end=end,
            customers=Customer.objects.all(),
            quantity=quantity,
            groups=groups,
            q=q,
            report=report,
            total=total,
        ),
    )


@login_required
@permission_required(
    ("ledger.view_payment", "ledger.view_sale", "ledger.view_customer"),
    raise_exception=True,
)
def receivables(request):
    q = request.GET.get("q", "")
    customers = Customer.objects.filter(
        Q(name__icontains=q) | Q(identification__icontains=q)
    ).prefetch_related("sales__allocations", "payments")
    rows = []
    for c in customers:
        sales = list(c.sales.all())
        payments = list(c.payments.all())
        credit = sum((s.total - s.initial_payment for s in sales), ZERO)
        abonos = sum((p.amount for p in payments if not p.initial_sale_id), ZERO)
        last = max(
            [timezone.localtime(s.occurred_at).date() for s in sales]
            + [p.date for p in payments],
            default=None,
        )
        rows.append(
            dict(
                customer=c,
                credit=credit,
                abonos=abonos,
                sold=sum((s.total for s in sales), ZERO),
                received=sum((p.amount for p in payments), ZERO),
                balance=c.balance,
                last=last,
            )
        )
    return render(
        request,
        "ledger/receivables.html",
        dict(
            title="Cuentas por cobrar",
            rows=rows,
            q=q,
            total=sum((r["balance"] for r in rows), ZERO),
            sold_total=sum((r["sold"] for r in rows), ZERO),
            received_total=sum((r["received"] for r in rows), ZERO),
        ),
    )


@login_required
@permission_required(
    ("ledger.add_payment", "ledger.view_sale", "ledger.view_customer"),
    raise_exception=True,
)
def payment_new(request):
    cid = request.POST.get("customer") or request.GET.get("customer")
    customer = (
        get_object_or_404(
            Customer, pk=int(cid) if cid.isdigit() and len(cid) < 16 else 0
        )
        if cid
        else None
    )
    debts = (
        [
            s
            for s in customer.sales.prefetch_related("allocations").order_by(
                "occurred_at", "id"
            )
            if s.balance > 0
        ]
        if customer
        else []
    )
    if request.method == "POST":
        try:
            payment = create_payment(
                user=request.user,
                customer_id=cid,
                amount=request.POST.get("amount"),
                method=get_object_or_404(PaymentMethod, pk=request.POST.get("method")),
                date=date.fromisoformat(request.POST.get("date", "")),
                notes=request.POST.get("notes", ""),
                token=request.POST.get("token"),
            )
            messages.success(request, "Abono registrado y aplicado a la cartera.")
            return redirect("payment_operation", token=payment.token)
        except (ValidationError, ValueError, TypeError, Customer.DoesNotExist) as exc:
            error(request, exc)
    return render(
        request,
        "ledger/payment_new.html",
        dict(
            title="Registrar abono",
            customers=Customer.objects.all(),
            customer=customer,
            debts=debts,
            methods=PaymentMethod.objects.filter(active=True, is_credit=False),
            today=timezone.localdate(),
            token=request.POST.get("token") or uuid.uuid4(),
            submitted=request.POST,
            debt_total=sum((s.balance for s in debts), ZERO),
        ),
    )


@login_required
@permission_required(
    ("ledger.view_payment", "ledger.view_sale", "ledger.view_customer"),
    raise_exception=True,
)
def payment_detail(request, pk=None, token=None):
    payment = get_object_or_404(
        Payment.objects.select_related("customer", "created_by").prefetch_related(
            "allocations__sale"
        ),
        **({"token": token} if token else {"pk": pk}),
    )
    if request.GET.get("export") == "pdf":
        return export_table(
            "pdf",
            str(payment) + " · Comprobante de abono",
            ["Venta", "Valor aplicado"],
            [[str(a.sale), cop(a.amount)] for a in payment.allocations.all()],
            f"{payment.customer.name} | Fecha: {payment.date:%d/%m/%Y} | Recibido: {cop(payment.amount)} | Medio: {payment.method_name} | Registró: {payment.created_by.get_username()} | {payment.notes}",
            totals=["Total aplicado", cop(payment.amount)],
        )
    return render(
        request, "ledger/payment_detail.html", dict(title=str(payment), payment=payment)
    )


@login_required
@permission_required("ledger.view_expense", raise_exception=True)
def expenses(request):
    start, end = period(request, True)
    from .reporting import accounting_expenses
    qs = date_filter(
        accounting_expenses().select_related("category", "method"), "date", start, end
    )
    if request.GET.get("category"):
        category = request.GET["category"]
        selected_category = get_object_or_404(
            ExpenseCategory,
            pk=int(category) if category.isdigit() and len(category) < 16 else 0,
        )
        qs = qs.filter(category=selected_category)
    if request.GET.get("q"):
        qs = qs.filter(
            Q(description__icontains=request.GET["q"])
            | Q(reference__icontains=request.GET["q"])
        )
    items = list(qs)
    total = sum((e.amount for e in items), ZERO)
    groups = {}
    for e in items:
        groups[e.category.name] = groups.get(e.category.name, ZERO) + e.amount
    if request.GET.get("export") in ["csv", "pdf"]:
        return export_table(
            request.GET["export"],
            "Reporte de gastos",
            ["Fecha", "Categoría", "Descripción", "Valor", "Medio", "Referencia"],
            [
                [
                    e.date.strftime("%d/%m/%Y"),
                    e.category.name,
                    e.description,
                    cop(e.amount),
                    e.method.name,
                    e.reference,
                ]
                for e in items
            ],
            f'Periodo: {display_date(start,"Inicio")} a {display_date(end)} | Total: {cop(total)} | '
            + " · ".join(f"{k}: {cop(v)}" for k, v in groups.items()),
            totals=["TOTAL GASTOS", "", "", cop(total), "", ""],
        )
    return render(
        request,
        "ledger/expenses.html",
        dict(
            title="Gastos del negocio",
            expenses=items,
            total=total,
            groups=groups,
            start=start,
            end=end,
            categories=ExpenseCategory.objects.all(),
        ),
    )


@login_required
def expense_edit(request, pk=None):
    if not request.user.has_perm(
        "ledger." + ("change_expense" if pk else "add_expense")
    ):
        raise PermissionDenied
    instance = get_object_or_404(Expense, pk=pk) if pk else None
    if instance and hasattr(instance, 'payroll_entry'):
        if request.method == 'POST':
            messages.error(request, 'Este gasto se administra desde su nómina para conservar los totales.')
        return redirect('payroll_detail', pk=instance.payroll_entry.payroll_id)
    form = ExpenseForm(request.POST or None, instance=instance)
    token = request.POST.get("token") or str(uuid.uuid4())
    if request.method == "POST" and form.is_valid():
        try:
            with transaction.atomic():
                if pk:
                    locked = Expense.objects.select_for_update().get(pk=pk)
                    if locked.revision != form.cleaned_data["revision"]:
                        raise ValidationError(
                            "Otro usuario modificó este gasto. Recargue antes de guardar."
                        )
                    before = json.loads(
                        json.dumps(model_to_dict(locked), cls=DjangoJSONEncoder)
                    )
                else:
                    token = token_value(token)
                    if Expense.objects.filter(token=token).exists():
                        return redirect("expenses")
                    before = {}
                obj = form.save(commit=False)
                if not pk:
                    obj.created_by = request.user
                    obj.token = token
                obj.revision += 1
                obj.save()
                audit(
                    request.user,
                    obj,
                    "Gasto editado" if pk else "Gasto registrado",
                    before,
                    json.loads(json.dumps(model_to_dict(obj), cls=DjangoJSONEncoder)),
                )
            messages.success(request, "Gasto guardado correctamente.")
            return redirect("expenses")
        except IntegrityError:
            if not pk and Expense.objects.filter(token=token).exists():
                messages.success(
                    request, "Este gasto ya estaba registrado. No se creó un duplicado."
                )
                return redirect("expenses")
            messages.error(
                request,
                "No se pudo guardar el gasto. Revise los datos y vuelva a intentar.",
            )
        except ValidationError as exc:
            error(request, exc)
    history = (
        Audit.objects.filter(entity="ledger.Expense", object_id=pk)
        .select_related("actor")
        .order_by("-date")
        if pk
        else []
    )
    return render(
        request,
        "ledger/form.html",
        dict(
            title="Editar gasto" if pk else "Registrar gasto",
            form=form,
            token=token,
            back="/gastos/",
            history=history,
        ),
    )
