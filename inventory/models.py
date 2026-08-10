from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models import F


class Category(models.Model):
    name = models.CharField(max_length=100, unique=True)

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "Categories"

    def __str__(self):
        return self.name

    def clean(self):
        if not self.name or not self.name.strip():
            raise ValidationError({"name": "Category name should not be empty."})

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)


class Supplier(models.Model):
    name = models.CharField(max_length=150)
    phone_number = models.CharField(max_length=20)
    email = models.EmailField(blank=True)
    address = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    def clean(self):
        if not self.phone_number or not self.phone_number.strip():
            raise ValidationError({"phone_number": "Phone number should not be empty."})

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)


class Product(models.Model):
    name = models.CharField(max_length=150)
    category = models.ForeignKey(
        Category, on_delete=models.PROTECT, related_name="products"
    )
    supplier = models.ForeignKey(
        Supplier, on_delete=models.PROTECT, related_name="products"
    )
    cost_price = models.DecimalField(max_digits=10, decimal_places=2)
    selling_price = models.DecimalField(max_digits=10, decimal_places=2)
    quantity_in_stock = models.PositiveIntegerField(default=0)
    low_stock_threshold = models.PositiveIntegerField(default=5)
    date_added = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    def clean(self):
        # These are the "hard invariant" checks - things that should never
        # be true regardless of who's saving the record or how. They run
        # on every save() (see below), not just through a form.
        #
        # Deliberately NOT included here: "selling_price should not be
        # below cost_price." That rule is overridable by a human decision
        # (a staff member may legitimately price something as a loss
        # leader, or to clear old stock), which doesn't fit an
        # unconditional model-level invariant. It's enforced instead in
        # ProductForm, where a "confirm override" checkbox lets someone
        # explicitly acknowledge it - and the view logs that override to
        # PriceOverrideLog. See README for the fuller reasoning.
        errors = {}
        if self.cost_price is not None and self.cost_price < 0:
            errors["cost_price"] = "Cost price cannot be negative."
        if self.selling_price is not None and self.selling_price < 0:
            errors["selling_price"] = "Selling price cannot be negative."
        if self.quantity_in_stock is not None and self.quantity_in_stock < 0:
            errors["quantity_in_stock"] = "Stock quantity cannot be negative."
        if self.low_stock_threshold is not None and self.low_stock_threshold < 0:
            errors["low_stock_threshold"] = "Low stock threshold cannot be negative."
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    @property
    def is_low_stock(self):
        return self.quantity_in_stock < self.low_stock_threshold


class PriceOverrideLog(models.Model):
    """Audit trail: created whenever an admin saves a Product whose
    selling_price is below its cost_price and explicitly confirms the
    override checkbox in ProductForm."""

    product = models.ForeignKey(
        Product, on_delete=models.CASCADE, related_name="override_logs"
    )
    staff = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True
    )
    cost_price_at_override = models.DecimalField(max_digits=10, decimal_places=2)
    selling_price_at_override = models.DecimalField(max_digits=10, decimal_places=2)
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-timestamp"]

    def __str__(self):
        return f"Override on {self.product.name} at {self.timestamp:%Y-%m-%d %H:%M}"


class Order(models.Model):
    STATUS_PENDING = "pending"
    STATUS_COMPLETED = "completed"
    STATUS_CANCELLED = "cancelled"

    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_COMPLETED, "Completed"),
        (STATUS_CANCELLED, "Cancelled"),
    ]

    customer_name = models.CharField(max_length=150)
    customer_phone = models.CharField(max_length=20, blank=True)
    staff = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="orders"
    )
    date = models.DateField(auto_now_add=True)
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING
    )

    class Meta:
        ordering = ["-date", "-id"]

    def __str__(self):
        return f"Order #{self.pk} - {self.customer_name}"

    @property
    def total_amount(self):
        return sum(
            (item.subtotal for item in self.items.all()), Decimal("0.00")
        )

    def complete(self):
        """
        Marks the order Completed and deducts stock for every item, in one
        atomic transaction - either every item's stock is deducted and the
        order becomes Completed, or nothing changes at all.

        Raises ValidationError (without changing anything) if:
          - the order has no items, or
          - any single item's quantity exceeds that product's current
            stock.
        """
        if self.status == self.STATUS_COMPLETED:
            return  # already completed - nothing to do, safe to call again

        items = list(self.items.select_related("product"))
        if not items:
            raise ValidationError("Cannot complete an order with no items.")

        insufficient = [
            item for item in items if item.quantity > item.product.quantity_in_stock
        ]
        if insufficient:
            details = ", ".join(
                f"{item.product.name} (have {item.product.quantity_in_stock}, "
                f"need {item.quantity})"
                for item in insufficient
            )
            raise ValidationError(f"Insufficient stock for: {details}")

        with transaction.atomic():
            for item in items:
                # F() expressions push the arithmetic down to the database
                # itself (an UPDATE ... SET quantity_in_stock = quantity_in_stock - X),
                # rather than reading a Python value and writing it back -
                # this avoids a race condition if two sales were somehow
                # being completed for the same product at the same instant.
                Product.objects.filter(pk=item.product_id).update(
                    quantity_in_stock=F("quantity_in_stock") - item.quantity
                )
            self.status = self.STATUS_COMPLETED
            self.save(update_fields=["status"])

    def cancel(self):
        """
        Cancels the order. If it was Completed, restores the stock that
        was deducted. If it was still Pending, no stock was ever deducted,
        so nothing needs restoring - just the status changes.
        """
        if self.status == self.STATUS_CANCELLED:
            return  # already cancelled - safe to call again

        with transaction.atomic():
            if self.status == self.STATUS_COMPLETED:
                for item in self.items.select_related("product"):
                    Product.objects.filter(pk=item.product_id).update(
                        quantity_in_stock=F("quantity_in_stock") + item.quantity
                    )
            self.status = self.STATUS_CANCELLED
            self.save(update_fields=["status"])


class OrderItem(models.Model):
    """The through model implementing the Product <-> Order many-to-many
    relationship: one row per product within one order, carrying the
    quantity and a price snapshot."""

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey(
        Product, on_delete=models.PROTECT, related_name="order_items"
    )
    quantity = models.PositiveIntegerField()

    # Snapshotted from product.selling_price at the moment the OrderItem is
    # created (see views.order_create) - NOT re-read from the product on
    # every access. This protects historical accuracy: if the catalog
    # price changes later, past orders still show what the customer was
    # actually charged at the time.
    selling_price = models.DecimalField(max_digits=10, decimal_places=2)

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return f"{self.quantity} x {self.product.name}"

    @property
    def subtotal(self):
        return self.quantity * self.selling_price

    def clean(self):
        if self.quantity is not None and self.quantity <= 0:
            raise ValidationError({"quantity": "Quantity must be greater than zero."})

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)
