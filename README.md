# Inventory & Sales Manager

A Django + MySQL application for a small retail shop to manage products,
inventory, suppliers, and sales - with role-based access control, atomic
stock management, price-override auditing, and revenue reporting.

## Project Overview

Two kinds of users work with this system:

- **Admin** - manages products, categories, suppliers, and views the
  dashboard/reports.
- **Sales Staff** - views products (read-only) and creates sales. Cannot
  touch product/category/supplier management or the dashboard.

A sale (`Order`) can contain multiple products (`OrderItem`, the
many-to-many through model). Completing an order deducts stock
automatically; cancelling a completed order restores it. Nothing about
stock changes until an order is explicitly completed - creating an order
just records intent to sell.

## Features

- **Role-based access control** using Django's built-in Groups
  (`Admin`, `Sales Staff`), enforced server-side by a decorator that
  raises a real 403 - not just a hidden navbar link.
- **Category, Supplier, Product management** (Admin only) - with a
  low-stock flag and filter, and a price-override warning + audit log
  when selling price is set below cost price.
- **Sales / Orders** - a dynamic multi-item sale form (Django formset,
  no external frontend framework), Pending → Completed/Cancelled status
  flow, and atomic stock updates.
- **Dashboard** (Admin only) - totals, low-stock count, completed/pending
  order counts, revenue, top-5 best sellers, all recalculated for an
  optional From/To date range.
- **CSV export** of completed orders.
- **10 automated tests** (5 required minimum) covering stock management,
  permissions, and dashboard date-range revenue.

## Technology Stack

- **Backend:** Django 4.2 LTS (see the repair-tracker project's README
  for the fuller MariaDB/Python version-compatibility reasoning behind
  choosing 4.2 - same applies here).
- **Database:** MySQL, via **PyMySQL** (pure-Python driver, registered as
  a drop-in replacement for `mysqlclient` via
  `pymysql.install_as_MySQLdb()` in `settings.py`).
- **Frontend:** Django templates + Bootstrap 5 (CDN) + a small amount of
  vanilla JavaScript for the dynamic order-item formset (no React, Vue,
  or DRF anywhere in this project).
- **Production server:** gunicorn + whitenoise.

## Project Structure

```
inventory_sales_manager/
├── manage.py
├── requirements.txt
├── README.md
├── inventory_sales_manager/     # project settings, urls, wsgi
├── templates/inventory/         # all HTML templates
└── inventory/                   # the app
    ├── models.py                 # Category, Supplier, Product, Order, OrderItem, PriceOverrideLog
    ├── forms.py                  # incl. the OrderItem formset and price-override form
    ├── views.py
    ├── decorators.py             # admin_required - the actual permission enforcement
    ├── context_processors.py     # is_admin flag for templates (UX only, not security)
    ├── tests.py
    └── management/commands/
        ├── setup_groups.py
        └── create_default_superuser.py
```

## Model Relationships

```
Category  (1) ──── (many) Product
Supplier  (1) ──── (many) Product
Product  (many) ──── (many) Order      [through OrderItem]
User → Group ("Admin" or "Sales Staff")
```

## MySQL Database Setup

```sql
CREATE DATABASE inventory_sales_db CHARACTER SET utf8mb4;
```

Configuration is read from environment variables in `settings.py`:

| Variable      | Default                |
|---------------|-------------------------|
| `DB_NAME`     | `inventory_sales_db`   |
| `DB_USER`     | `root`                 |
| `DB_PASSWORD` | *(empty)*               |
| `DB_HOST`     | `localhost`             |
| `DB_PORT`     | `3306`                  |
| `DB_SSL_CA`   | *(unset - set for hosts requiring SSL, e.g. Aiven)* |

## Installation Steps

```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

## Database Migrations

```bash
python manage.py makemigrations
python manage.py migrate
```

## Superuser Creation

```bash
python manage.py createsuperuser
python manage.py setup_groups
```

`setup_groups` creates the `Admin` and `Sales Staff` groups (safe to run
repeatedly). Add your superuser to `Admin` via the Django admin's User
page (`/admin/auth/user/`), or in the shell:

```python
python manage.py shell
>>> from django.contrib.auth.models import User, Group
>>> u = User.objects.get(username="your_username")
>>> u.groups.add(Group.objects.get(name="Admin"))
```

To create a Sales Staff test user:
```python
>>> staff = User.objects.create_user("salesperson", password="a-strong-password")
>>> staff.groups.add(Group.objects.get(name="Sales Staff"))
```

(On hosts without shell access, like Render's free tier, use
`python manage.py create_default_superuser` instead - see Deployment.)

## Running the Application

```bash
python manage.py runserver
```

Admin users land on the dashboard after login; Sales Staff land on the
New Sale page.

## Running the Test Suite

```bash
python manage.py test inventory
```

10 tests: stock reduction on completion, blocked completion on
insufficient stock (with an all-or-nothing check), stock restoration on
cancelling a completed order, cancelling a pending order leaves stock
untouched, Sales Staff blocked from product management and the
dashboard (403), Sales Staff can still view products, Admin can access
product management, and dashboard revenue is correctly scoped to a
selected date range (and to all-time with none given).

