from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models import F, Q


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
        # Defense-in-depth: full_clean() (called from save()) already
        # blocks negative values through normal application code, but
        # anything that writes to this table without going through
        # save() - a raw QuerySet.update(), a bulk operation, a direct
        # SQL statement, a future dev forgetting the override exists -
        # would bypass that check entirely. A CHECK constraint enforces
        # the same rule at the database level, so it holds no matter
        # what wrote the row. Requested by Evans specifically for
        # quantity_in_stock; added the same protection to the other
        # numeric fields for consistency, since they're just as capable
        # of being written around full_clean().
        constraints = [
            models.CheckConstraint(
                check=Q(quantity_in_stock__gte=0),
                name="product_quantity_in_stock_gte_0",
            ),
            models.CheckConstraint(
                check=Q(cost_price__gte=0),
                name="product_cost_price_gte_0",
            ),
            models.CheckConstraint(
                check=Q(selling_price__gte=0),
                name="product_selling_price_gte_0",
            ),
            models.CheckConstraint(
                check=Q(low_stock_threshold__gte=0),
                name="product_low_stock_threshold_gte_0",
            ),
        ]

    def __str__(self):
        return self.name

    def clean(self):
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

    def _quantity_needed_by_product(self):
        """
        Groups this order's items by product and sums their quantities.

        This matters because the same product can legitimately appear as
        more than one OrderItem on a single order (e.g. added twice from
        the sale form, or two different discount lines for the same
        item). Checking/deducting stock per-item independently would let
        two 6-unit lines both individually "pass" against 10 units in
        stock, while together actually requiring 13 - so the check and
        the deduction both need to work against the combined total per
        product, not each line in isolation.
        """
        needed = {}
        for item in self.items.all():
            needed[item.product_id] = needed.get(item.product_id, 0) + item.quantity
        return needed

    def complete(self):
        """
        Marks the order Completed and deducts stock for every item, in one
        atomic transaction - either every item's stock is deducted and the
        order becomes Completed, or nothing changes at all.

        Raises ValidationError (without changing anything) if:
          - the order has no items,
          - the same product appears across multiple items and their
            combined quantity exceeds stock (even if no single item
            alone would), or
          - any single product's needed quantity exceeds current stock.
        """
        if self.status == self.STATUS_COMPLETED:
            return  # already completed - nothing to do, safe to call again

        needed_by_product = self._quantity_needed_by_product()
        if not needed_by_product:
            raise ValidationError("Cannot complete an order with no items.")

        with transaction.atomic():
            # select_for_update() locks these specific Product rows for
            # the rest of this transaction. If a second order for the
            # same product is being completed at (almost) the same
            # moment, that second call blocks here until this
            # transaction commits or rolls back, instead of both reading
            # the same starting stock value and both passing the check.
            # This closes the gap between "check stock" and "deduct
            # stock" that a plain read-then-update leaves open, even
            # when the deduction itself uses an F() expression.
            locked_products = {
                p.pk: p
                for p in Product.objects.select_for_update().filter(
                    pk__in=needed_by_product.keys()
                )
            }

            insufficient = [
                (locked_products[product_id], needed)
                for product_id, needed in needed_by_product.items()
                if needed > locked_products[product_id].quantity_in_stock
            ]
            if insufficient:
                details = ", ".join(
                    f"{product.name} (have {product.quantity_in_stock}, need {needed})"
                    for product, needed in insufficient
                )
                raise ValidationError(f"Insufficient stock for: {details}")

            for product_id, needed in needed_by_product.items():
                Product.objects.filter(pk=product_id).update(
                    quantity_in_stock=F("quantity_in_stock") - needed
                )

            self.status = self.STATUS_COMPLETED
            self.save(update_fields=["status"])

    def cancel(self):
        """
        Cancels the order. If it was Completed, restores stock (grouped
        by product, same reasoning as complete() - see
        _quantity_needed_by_product()). If it was still Pending, no
        stock was ever deducted, so nothing needs restoring.
        """
        if self.status == self.STATUS_CANCELLED:
            return  # already cancelled - safe to call again

        with transaction.atomic():
            if self.status == self.STATUS_COMPLETED:
                needed_by_product = self._quantity_needed_by_product()
                # Locking here too, for the same reason as complete():
                # keeps a concurrent complete()/cancel() on an
                # overlapping product from interleaving with this
                # restoration.
                list(
                    Product.objects.select_for_update().filter(
                        pk__in=needed_by_product.keys()
                    )
                )
                for product_id, needed in needed_by_product.items():
                    Product.objects.filter(pk=product_id).update(
                        quantity_in_stock=F("quantity_in_stock") + needed
                    )
            self.status = self.STATUS_CANCELLED
            self.save(update_fields=["status"])


class OrderItem(models.Model):
    """The through model implementing the Product <-> Order many-to-many
    relationship: one row per product within one order, carrying the
    quantity and a price snapshot. The same product may appear in more
    than one row on the same order - see Order._quantity_needed_by_product()
    for how that's handled correctly during stock checks/updates."""

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey(
        Product, on_delete=models.PROTECT, related_name="order_items"
    )
    quantity = models.PositiveIntegerField()
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