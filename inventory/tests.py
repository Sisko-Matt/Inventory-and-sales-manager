import datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.test import TestCase, Client
from django.urls import reverse

from .decorators import ADMIN_GROUP_NAME, SALES_STAFF_GROUP_NAME
from .models import Category, Supplier, Product, Order, OrderItem

User = get_user_model()


def make_product(name="Widget", stock=10, cost=Decimal("5.00"), price=Decimal("10.00")):
    category = Category.objects.create(name=f"Category for {name}")
    supplier = Supplier.objects.create(name=f"Supplier for {name}", phone_number="0700000000")
    return Product.objects.create(
        name=name,
        category=category,
        supplier=supplier,
        cost_price=cost,
        selling_price=price,
        quantity_in_stock=stock,
        low_stock_threshold=3,
    )


class StockManagementTest(TestCase):
    """Completing and cancelling orders must move stock correctly."""

    def setUp(self):
        self.staff_user = User.objects.create_user(username="staffuser", password="testpass123")
        self.product = make_product(stock=10)

    def _make_order(self, quantity):
        order = Order.objects.create(
            customer_name="Test Customer", customer_phone="0711111111", staff=self.staff_user
        )
        OrderItem.objects.create(
            order=order,
            product=self.product,
            quantity=quantity,
            selling_price=self.product.selling_price,
        )
        return order

    def test_completing_order_reduces_stock_correctly(self):
        order = self._make_order(quantity=4)
        order.complete()

        self.product.refresh_from_db()
        order.refresh_from_db()
        self.assertEqual(self.product.quantity_in_stock, 6)  # 10 - 4
        self.assertEqual(order.status, Order.STATUS_COMPLETED)

    def test_completing_order_fails_when_stock_insufficient(self):
        order = self._make_order(quantity=999)  # far more than the 10 in stock

        with self.assertRaises(ValidationError):
            order.complete()

        # Nothing should have changed - order still pending, stock untouched.
        self.product.refresh_from_db()
        order.refresh_from_db()
        self.assertEqual(self.product.quantity_in_stock, 10)
        self.assertEqual(order.status, Order.STATUS_PENDING)

    def test_cancelling_completed_order_restores_stock(self):
        order = self._make_order(quantity=4)
        order.complete()
        self.product.refresh_from_db()
        self.assertEqual(self.product.quantity_in_stock, 6)

        order.cancel()

        self.product.refresh_from_db()
        order.refresh_from_db()
        self.assertEqual(self.product.quantity_in_stock, 10)  # restored
        self.assertEqual(order.status, Order.STATUS_CANCELLED)

    def test_cancelling_pending_order_does_not_touch_stock(self):
        order = self._make_order(quantity=4)
        # Never completed - stock was never deducted.
        order.cancel()

        self.product.refresh_from_db()
        self.assertEqual(self.product.quantity_in_stock, 10)
        self.assertEqual(order.status, Order.STATUS_CANCELLED)


class PermissionsTest(TestCase):
    """Sales Staff must be blocked from product/category/supplier
    management at the view level, not just hidden from the navbar."""

    def setUp(self):
        self.client = Client()
        sales_group, _ = Group.objects.get_or_create(name=SALES_STAFF_GROUP_NAME)
        self.sales_user = User.objects.create_user(username="salesperson", password="testpass123")
        self.sales_user.groups.add(sales_group)

        admin_group, _ = Group.objects.get_or_create(name=ADMIN_GROUP_NAME)
        self.admin_user = User.objects.create_user(username="adminperson", password="testpass123")
        self.admin_user.groups.add(admin_group)

    def test_sales_staff_cannot_access_product_management(self):
        self.client.login(username="salesperson", password="testpass123")
        response = self.client.get(reverse("inventory:product_create"))
        self.assertEqual(response.status_code, 403)

    def test_sales_staff_can_view_product_list(self):
        self.client.login(username="salesperson", password="testpass123")
        response = self.client.get(reverse("inventory:product_list"))
        self.assertEqual(response.status_code, 200)

    def test_admin_can_access_product_management(self):
        self.client.login(username="adminperson", password="testpass123")
        response = self.client.get(reverse("inventory:product_create"))
        self.assertEqual(response.status_code, 200)

    def test_sales_staff_cannot_access_dashboard(self):
        self.client.login(username="salesperson", password="testpass123")
        response = self.client.get(reverse("inventory:dashboard"))
        self.assertEqual(response.status_code, 403)


class DashboardRevenueDateRangeTest(TestCase):
    """Dashboard revenue and order counts must respect the from/to date
    filter, only counting completed orders within that range."""

    def setUp(self):
        admin_group, _ = Group.objects.get_or_create(name=ADMIN_GROUP_NAME)
        self.admin_user = User.objects.create_user(username="adminperson", password="testpass123")
        self.admin_user.groups.add(admin_group)
        self.product = make_product(stock=100, price=Decimal("20.00"))
        self.client = Client()
        self.client.login(username="adminperson", password="testpass123")

    def _completed_order_on(self, date, quantity=1):
        order = Order.objects.create(
            customer_name="Customer", staff=self.admin_user
        )
        # date has auto_now_add=True, so we set it explicitly afterward
        # via update() to backdate it for the test - .save() would just
        # reset it to today because of auto_now_add.
        Order.objects.filter(pk=order.pk).update(date=date)
        order.refresh_from_db()
        OrderItem.objects.create(
            order=order, product=self.product, quantity=quantity,
            selling_price=self.product.selling_price,
        )
        order.complete()
        return order

    def test_revenue_only_counts_orders_within_selected_range(self):
        self._completed_order_on(datetime.date(2026, 1, 5), quantity=2)   # inside range
        self._completed_order_on(datetime.date(2026, 1, 10), quantity=3)  # inside range
        self._completed_order_on(datetime.date(2026, 2, 1), quantity=5)   # outside range

        response = self.client.get(
            reverse("inventory:dashboard"),
            {"from_date": "2026-01-01", "to_date": "2026-01-31"},
        )

        self.assertEqual(response.status_code, 200)
        # Only the two January orders should count: (2 + 3) * 20.00 = 100.00
        self.assertEqual(response.context["total_revenue"], Decimal("100.00"))
        self.assertEqual(response.context["completed_orders_count"], 2)

    def test_revenue_with_no_range_counts_everything(self):
        self._completed_order_on(datetime.date(2026, 1, 5), quantity=2)
        self._completed_order_on(datetime.date(2026, 2, 1), quantity=5)

        response = self.client.get(reverse("inventory:dashboard"))

        self.assertEqual(response.status_code, 200)
        # (2 + 5) * 20.00 = 140.00
        self.assertEqual(response.context["total_revenue"], Decimal("140.00"))
        self.assertEqual(response.context["completed_orders_count"], 2)
