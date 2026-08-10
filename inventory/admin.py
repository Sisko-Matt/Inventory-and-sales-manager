from django.contrib import admin
from .models import Category, Supplier, Product, Order, OrderItem, PriceOverrideLog


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("name",)
    search_fields = ("name",)


@admin.register(Supplier)
class SupplierAdmin(admin.ModelAdmin):
    list_display = ("name", "phone_number", "email", "address")
    search_fields = ("name", "phone_number", "email")


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = (
        "name", "category", "supplier", "cost_price", "selling_price",
        "quantity_in_stock", "low_stock_threshold", "is_low_stock",
    )
    list_filter = ("category", "supplier")
    search_fields = ("name",)


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ("id", "customer_name", "staff", "date", "status", "total_amount")
    list_filter = ("status",)
    search_fields = ("customer_name", "customer_phone")
    inlines = [OrderItemInline]


@admin.register(PriceOverrideLog)
class PriceOverrideLogAdmin(admin.ModelAdmin):
    list_display = ("product", "staff", "cost_price_at_override", "selling_price_at_override", "timestamp")
    list_filter = ("staff",)
