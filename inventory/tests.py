import datetime
import threading
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.db import DataError, IntegrityError, connection
from django.test import TestCase, TransactionTestCase, Client
from django.urls import reverse

from .decorators import ADMIN_GROUP_NAME, SALES_STAFF_GROUP_NAME
from .models import Category, Supplier, Product, Order, OrderItem

User = get_user_model()


def make_product(name="Widget", stock=10, cost=Decimal("5.00"), price=Decimal("10.00")):
    category = Category.objects.create(name=f"Category for {name}")
    supplier = Supplier.objects.create(name=f"Supplier for {name}", phone_number="0700000000")
    return Product.objects.create(
        name=name, category=category, supplier=supplier,
        cost_price=cost, selling_price=price,
        quantity_in_stock=stock, low_stock_threshold=3,
    )


class StockManagementTest(TestCase):
    def setUp(self):
        self.staff_user = User.objects.create_user(username="staffuser", password="testpass123")
        self.product = make_product(stock=10)

    def _make_order(self, quantity):
        order = Order.objects.create(customer_name="Test Customer", staff=self.staff_user)
        OrderItem.objects.create(
            order=order, product=self.product, quantity=quantity,
            selling_price=self.product.selling_price,
        )
        return order

    def test_completing_order_reduces_stock_correctly(self):
        order = self._make_order(quantity=4)
        order.complete()
        self.product.refresh_from_db()
        order.refresh_from_db()
        self.assertEqual(self.product.quantity_in_stock, 6)
        self.assertEqual(order.status, Order.STATUS_COMPLETED)

    def test_completing_order_fails_when_stock_insufficient(self):
        order = self._make_order(quantity=999)
        with self.assertRaises(ValidationError):
            order.complete()
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
        self.assertEqual(self.product.quantity_in_stock, 10)
        self.assertEqual(order.status, Order.STATUS_CANCELLED)

    def test_cancelling_pending_order_does_not_touch_stock(self):
        order = self._make_order(quantity=4)
        order.cancel()
        self.product.refresh_from_db()
        self.assertEqual(self.product.quantity_in_stock, 10)
        self.assertEqual(order.status, Order.STATUS_CANCELLED)


class DuplicateProductInOrderTest(TestCase):
    """Same product added as two separate line items on one order must
    have its quantities combined - both for the stock check and the
    deduction/restoration - not checked/deducted per line independently."""

    def setUp(self):
        self.staff_user = User.objects.create_user(username="staffuser2", password="testpass123")
        self.product = make_product(name="Cable", stock=10)

    def _make_order_with_duplicate_lines(self, qty1, qty2):
        order = Order.objects.create(customer_name="Dup Customer", staff=self.staff_user)
        OrderItem.objects.create(
            order=order, product=self.product, quantity=qty1,
            selling_price=self.product.selling_price,
        )
        OrderItem.objects.create(
            order=order, product=self.product, quantity=qty2,
            selling_price=self.product.selling_price,
        )
        return order

    def test_duplicate_lines_combined_quantity_deducted_correctly(self):
        # 4 + 3 = 7 needed, 10 in stock - should succeed and deduct 7 total.
        order = self._make_order_with_duplicate_lines(4, 3)
        order.complete()
        self.product.refresh_from_db()
        self.assertEqual(self.product.quantity_in_stock, 3)  # 10 - 7
        self.assertEqual(order.status, Order.STATUS_COMPLETED)

    def test_duplicate_lines_each_individually_ok_but_combined_exceeds_stock(self):
        # 6 + 7 = 13 needed, only 10 in stock. Each line ALONE (6 or 7) is
        # individually <= 10, so a per-line check would incorrectly pass
        # this. The combined-quantity check must catch it.
        order = self._make_order_with_duplicate_lines(6, 7)
        with self.assertRaises(ValidationError):
            order.complete()
        self.product.refresh_from_db()
        order.refresh_from_db()
        self.assertEqual(self.product.quantity_in_stock, 10)  # untouched
        self.assertEqual(order.status, Order.STATUS_PENDING)

    def test_duplicate_lines_stock_restored_correctly_on_cancel(self):
        order = self._make_order_with_duplicate_lines(4, 3)
        order.complete()
        self.product.refresh_from_db()
        self.assertEqual(self.product.quantity_in_stock, 3)
        order.cancel()
        self.product.refresh_from_db()
        self.assertEqual(self.product.quantity_in_stock, 10)  # fully restored


class PermissionsTest(TestCase):
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
    def setUp(self):
        admin_group, _ = Group.objects.get_or_create(name=ADMIN_GROUP_NAME)
        self.admin_user = User.objects.create_user(username="adminperson", password="testpass123")
        self.admin_user.groups.add(admin_group)
        self.product = make_product(stock=100, price=Decimal("20.00"))
        self.client = Client()
        self.client.login(username="adminperson", password="testpass123")

    def _completed_order_on(self, date, quantity=1):
        order = Order.objects.create(customer_name="Customer", staff=self.admin_user)
        Order.objects.filter(pk=order.pk).update(date=date)
        order.refresh_from_db()
        OrderItem.objects.create(
            order=order, product=self.product, quantity=quantity,
            selling_price=self.product.selling_price,
        )
        order.complete()
        return order

    def test_revenue_only_counts_orders_within_selected_range(self):
        self._completed_order_on(datetime.date(2026, 1, 5), quantity=2)
        self._completed_order_on(datetime.date(2026, 1, 10), quantity=3)
        self._completed_order_on(datetime.date(2026, 2, 1), quantity=5)
        response = self.client.get(
            reverse("inventory:dashboard"),
            {"from_date": "2026-01-01", "to_date": "2026-01-31"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["total_revenue"], Decimal("100.00"))
        self.assertEqual(response.context["completed_orders_count"], 2)

    def test_revenue_with_no_range_counts_everything(self):
        self._completed_order_on(datetime.date(2026, 1, 5), quantity=2)
        self._completed_order_on(datetime.date(2026, 2, 1), quantity=5)
        response = self.client.get(reverse("inventory:dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["total_revenue"], Decimal("140.00"))
        self.assertEqual(response.context["completed_orders_count"], 2)


class StockCheckConstraintTest(TestCase):
    """The DB-level CHECK constraint is the backstop for anything that
    writes stock without going through save()/full_clean() - e.g. a raw
    QuerySet.update(), which Django never routes through a model's
    clean()/save() override."""

    def setUp(self):
        self.product = make_product(stock=5)
        
    def test_bulk_update_bypasses_full_clean_but_db_still_rejects_negative_stock(self):
        # MariaDB can reject this write in one of two ways depending on the
        # exact column type: as a type-level range violation (DataError,
        # since quantity_in_stock is an unsigned int and -1 is out of range
        # for the type itself) or as an explicit CHECK constraint violation
        # (IntegrityError). Both are the database correctly refusing the bad
        # write with strict mode on - which is the actual thing being tested
        # here, not which specific exception class it happens to raise.
        with self.assertRaises((IntegrityError, DataError)):
            Product.objects.filter(pk=self.product.pk).update(quantity_in_stock=-1)


    def test_valid_bulk_update_still_works(self):
        # Sanity check: the constraint only blocks negative values, not
        # legitimate updates.
        Product.objects.filter(pk=self.product.pk).update(quantity_in_stock=3)
        self.product.refresh_from_db()
        self.assertEqual(self.product.quantity_in_stock, 3)


class ConcurrentOrderCompletionTest(TransactionTestCase):
    """
    Verifies the select_for_update() locking in Order.complete() actually
    prevents two orders from both passing the stock check against the
    same starting value and jointly overselling.

    Uses TransactionTestCase (not TestCase) because this needs real,
    separate database transactions running on separate threads - a
    plain TestCase wraps each test in one outer transaction that never
    really commits, which would prevent genuine cross-thread locking
    from being exercised at all.
    """

    def setUp(self):
        self.staff_user = User.objects.create_user(username="staffuser3", password="testpass123")
        self.product = make_product(name="Contested Item", stock=10)

    def test_two_orders_racing_for_the_same_limited_stock(self):
        # Two orders, each wanting 6 units, but only 10 in stock. At most
        # one can succeed; the other must be blocked - and the two
        # together must never both succeed (which would drive stock to
        # -2, the exact scenario select_for_update() exists to prevent).
        order_a = Order.objects.create(customer_name="Customer A", staff=self.staff_user)
        OrderItem.objects.create(order=order_a, product=self.product, quantity=6, selling_price=self.product.selling_price)

        order_b = Order.objects.create(customer_name="Customer B", staff=self.staff_user)
        OrderItem.objects.create(order=order_b, product=self.product, quantity=6, selling_price=self.product.selling_price)

        results = {}
        start_barrier = threading.Barrier(2)

        def attempt_complete(order, key):
            try:
                start_barrier.wait(timeout=5)
                order.complete()
                results[key] = "success"
            except ValidationError:
                # The clean outcome: this thread's transaction blocked on
                # select_for_update() until the other committed, then
                # re-read the now-updated stock and correctly found it
                # insufficient. This is what happens on the real target
                # database (MySQL/MariaDB via InnoDB row-level locking).
                results[key] = "blocked_insufficient_stock"
            except Exception as e:
                # SQLite (used only for this test run, not production)
                # doesn't support true row-level locking the way InnoDB
                # does - under concurrent writers it sometimes raises
                # "database table is locked" instead of cleanly blocking
                # and letting the second transaction re-check stock. That
                # OperationalError is SQLite's cruder way of enforcing the
                # same guarantee (only one writer proceeds at a time), so
                # it counts as "correctly prevented", same as the
                # ValidationError case above - the one thing it must NOT
                # do is silently succeed and oversell.
                results[key] = f"blocked_db_error: {e}"
            finally:
                connection.close()

        thread_a = threading.Thread(target=attempt_complete, args=(order_a, "a"))
        thread_b = threading.Thread(target=attempt_complete, args=(order_b, "b"))
        thread_a.start()
        thread_b.start()
        thread_a.join(timeout=10)
        thread_b.join(timeout=10)

        outcomes = list(results.values())
        successes = sum(1 for o in outcomes if o == "success")
        blocked = sum(1 for o in outcomes if o.startswith("blocked"))

        # The one invariant that actually matters: exactly one of the two
        # succeeded, never both (which is the oversell scenario) and
        # never neither (which would mean the lock never released).
        self.assertEqual(successes, 1, f"outcomes were: {results}")
        self.assertEqual(blocked, 1, f"outcomes were: {results}")

        self.product.refresh_from_db()
        # Whichever order succeeded, exactly one order's worth (6) should
        # have been deducted - never both (-2), never neither (10).
        self.assertEqual(self.product.quantity_in_stock, 4)  # 10 - 6
        self.assertGreaterEqual(self.product.quantity_in_stock, 0)