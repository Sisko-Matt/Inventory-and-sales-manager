import csv
import datetime

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db.models import Sum, F
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render

from .decorators import admin_required, is_admin_user
from .forms import (
    CategoryForm,
    SupplierForm,
    ProductForm,
    OrderForm,
    OrderItemFormSet,
)
from .models import (
    Category,
    Supplier,
    Product,
    Order,
    OrderItem,
    PriceOverrideLog,
)


@login_required
def post_login_redirect(request):
    """Admin users land on the dashboard; Sales Staff land straight on
    the New Sale page, per the spec's authentication requirement."""
    if is_admin_user(request.user):
        return redirect("inventory:dashboard")
    return redirect("inventory:order_create")


# ------------------------------------------------------------------ Dashboard

def _parse_date(value):
    if not value:
        return None
    try:
        return datetime.date.fromisoformat(value)
    except ValueError:
        return None


@admin_required
def dashboard(request):
    from_date = _parse_date(request.GET.get("from_date", ""))
    to_date = _parse_date(request.GET.get("to_date", ""))

    orders = Order.objects.all()
    if from_date:
        orders = orders.filter(date__gte=from_date)
    if to_date:
        orders = orders.filter(date__lte=to_date)

    total_products = Product.objects.count()
    low_stock_products = Product.objects.filter(
        quantity_in_stock__lt=F("low_stock_threshold")
    ).count()

    total_orders = orders.count()
    completed_orders = orders.filter(status=Order.STATUS_COMPLETED)
    completed_orders_count = completed_orders.count()
    pending_orders_count = orders.filter(status=Order.STATUS_PENDING).count()

    total_revenue = OrderItem.objects.filter(
        order__in=completed_orders
    ).aggregate(total=Sum(F("quantity") * F("selling_price")))["total"] or 0

    top_products = (
        OrderItem.objects.filter(order__in=completed_orders)
        .values("product__name")
        .annotate(total_quantity=Sum("quantity"))
        .order_by("-total_quantity")[:5]
    )

    context = {
        "total_products": total_products,
        "low_stock_products": low_stock_products,
        "total_orders": total_orders,
        "completed_orders_count": completed_orders_count,
        "pending_orders_count": pending_orders_count,
        "total_revenue": total_revenue,
        "top_products": top_products,
        "from_date": request.GET.get("from_date", ""),
        "to_date": request.GET.get("to_date", ""),
    }
    return render(request, "inventory/dashboard.html", context)


# ------------------------------------------------------------------ Products

@login_required
def product_list(request):
    """Viewable by both roles (read-only for Sales Staff - the template
    hides Add/Edit buttons for them, but the actual create/edit views
    below are @admin_required regardless, so this is enforced, not just
    hidden)."""
    category_id = request.GET.get("category", "").strip()
    low_stock_only = request.GET.get("low_stock", "") == "1"

    products = Product.objects.select_related("category", "supplier").all()
    if category_id:
        products = products.filter(category_id=category_id)
    if low_stock_only:
        products = products.filter(quantity_in_stock__lt=F("low_stock_threshold"))

    context = {
        "products": products,
        "categories": Category.objects.all(),
        "category_id": category_id,
        "low_stock_only": low_stock_only,
    }
    return render(request, "inventory/product_list.html", context)


@admin_required
def product_create(request):
    if request.method == "POST":
        form = ProductForm(request.POST)
        if form.is_valid():
            is_override = form.is_price_override
            product = form.save()
            if is_override:
                PriceOverrideLog.objects.create(
                    product=product,
                    staff=request.user,
                    cost_price_at_override=product.cost_price,
                    selling_price_at_override=product.selling_price,
                )
                messages.warning(
                    request,
                    f"Saved '{product.name}' with a below-cost selling price. "
                    f"This override was logged.",
                )
            return redirect("inventory:product_list")
    else:
        form = ProductForm()
    return render(
        request, "inventory/product_form.html", {"form": form, "title": "Add Product"}
    )


@admin_required
def product_edit(request, pk):
    product = get_object_or_404(Product, pk=pk)
    if request.method == "POST":
        form = ProductForm(request.POST, instance=product)
        if form.is_valid():
            is_override = form.is_price_override
            product = form.save()
            if is_override:
                PriceOverrideLog.objects.create(
                    product=product,
                    staff=request.user,
                    cost_price_at_override=product.cost_price,
                    selling_price_at_override=product.selling_price,
                )
                messages.warning(
                    request,
                    f"Saved '{product.name}' with a below-cost selling price. "
                    f"This override was logged.",
                )
            return redirect("inventory:product_list")
    else:
        form = ProductForm(instance=product)
    return render(
        request,
        "inventory/product_form.html",
        {"form": form, "title": "Edit Product", "product": product},
    )


# ----------------------------------------------------------------- Categories

@admin_required
def category_list(request):
    return render(
        request, "inventory/category_list.html", {"categories": Category.objects.all()}
    )


@admin_required
def category_create(request):
    if request.method == "POST":
        form = CategoryForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect("inventory:category_list")
    else:
        form = CategoryForm()
    return render(
        request, "inventory/category_form.html", {"form": form, "title": "Add Category"}
    )


@admin_required
def category_edit(request, pk):
    category = get_object_or_404(Category, pk=pk)
    if request.method == "POST":
        form = CategoryForm(request.POST, instance=category)
        if form.is_valid():
            form.save()
            return redirect("inventory:category_list")
    else:
        form = CategoryForm(instance=category)
    return render(
        request,
        "inventory/category_form.html",
        {"form": form, "title": "Edit Category", "category": category},
    )


# ------------------------------------------------------------------ Suppliers

@admin_required
def supplier_list(request):
    return render(
        request, "inventory/supplier_list.html", {"suppliers": Supplier.objects.all()}
    )


@admin_required
def supplier_create(request):
    if request.method == "POST":
        form = SupplierForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect("inventory:supplier_list")
    else:
        form = SupplierForm()
    return render(
        request, "inventory/supplier_form.html", {"form": form, "title": "Add Supplier"}
    )


@admin_required
def supplier_edit(request, pk):
    supplier = get_object_or_404(Supplier, pk=pk)
    if request.method == "POST":
        form = SupplierForm(request.POST, instance=supplier)
        if form.is_valid():
            form.save()
            return redirect("inventory:supplier_list")
    else:
        form = SupplierForm(instance=supplier)
    return render(
        request,
        "inventory/supplier_form.html",
        {"form": form, "title": "Edit Supplier", "supplier": supplier},
    )


@admin_required
def supplier_products(request, pk):
    supplier = get_object_or_404(Supplier, pk=pk)
    products = supplier.products.all()
    return render(
        request,
        "inventory/supplier_products.html",
        {"supplier": supplier, "products": products},
    )


# ---------------------------------------------------------------------- Sales

@login_required
def order_list(request):
    """Viewable by both roles - Sales Staff need to see orders to
    complete/cancel the sales they process."""
    status = request.GET.get("status", "").strip()
    orders = Order.objects.select_related("staff").prefetch_related("items__product")
    if status:
        orders = orders.filter(status=status)
    context = {
        "orders": orders,
        "status": status,
        "status_choices": Order.STATUS_CHOICES,
    }
    return render(request, "inventory/order_list.html", context)


@login_required
def order_create(request):
    """New Sale page - available to both Sales Staff and Admin. Creating
    an order does NOT touch stock at all; stock is only affected when the
    order is later completed (see order_complete)."""
    if request.method == "POST":
        order_form = OrderForm(request.POST)
        formset = OrderItemFormSet(request.POST)
        if order_form.is_valid() and formset.is_valid():
            has_at_least_one_item = any(
                form.cleaned_data and not form.cleaned_data.get("DELETE", False)
                for form in formset.forms
                if form.cleaned_data
            )
            if not has_at_least_one_item:
                messages.error(request, "An order must have at least one item.")
            else:
                order = order_form.save(commit=False)
                order.staff = request.user
                order.save()

                for item_form in formset.forms:
                    if not item_form.cleaned_data or item_form.cleaned_data.get("DELETE", False):
                        continue
                    product = item_form.cleaned_data.get("product")
                    quantity = item_form.cleaned_data.get("quantity")
                    if not product or not quantity:
                        continue
                    OrderItem.objects.create(
                        order=order,
                        product=product,
                        quantity=quantity,
                        # Snapshotted at creation time - see model docstring.
                        selling_price=product.selling_price,
                    )
                messages.success(request, f"Order #{order.pk} created as Pending.")
                return redirect("inventory:order_list")
    else:
        order_form = OrderForm()
        formset = OrderItemFormSet()

    return render(
        request,
        "inventory/order_form.html",
        {"order_form": order_form, "formset": formset},
    )


@login_required
def order_detail(request, pk):
    order = get_object_or_404(
        Order.objects.prefetch_related("items__product"), pk=pk
    )
    return render(request, "inventory/order_detail.html", {"order": order})


@login_required
def order_complete(request, pk):
    if request.method != "POST":
        return redirect("inventory:order_detail", pk=pk)
    order = get_object_or_404(Order, pk=pk)
    try:
        order.complete()
        messages.success(request, f"Order #{order.pk} completed. Stock updated.")
    except ValidationError as e:
        messages.error(request, f"Could not complete order #{order.pk}: {e.message if hasattr(e, 'message') else e}")
    return redirect("inventory:order_detail", pk=pk)


@login_required
def order_cancel(request, pk):
    if request.method != "POST":
        return redirect("inventory:order_detail", pk=pk)
    order = get_object_or_404(Order, pk=pk)
    order.cancel()
    messages.success(request, f"Order #{order.pk} cancelled.")
    return redirect("inventory:order_detail", pk=pk)


# ------------------------------------------------------------------ Exports

@admin_required
def export_orders_csv(request):
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = 'attachment; filename="completed_orders.csv"'

    writer = csv.writer(response)
    writer.writerow(
        ["Order ID", "Customer Name", "Staff Member", "Date", "Products", "Total Amount"]
    )

    orders = (
        Order.objects.filter(status=Order.STATUS_COMPLETED)
        .select_related("staff")
        .prefetch_related("items__product")
    )
    for order in orders:
        products_str = "; ".join(
            f"{item.product.name} x{item.quantity}" for item in order.items.all()
        )
        writer.writerow(
            [
                order.pk,
                order.customer_name,
                order.staff.username,
                order.date,
                products_str,
                order.total_amount,
            ]
        )

    return response
