"""
Django settings for inventory_sales_manager project.

For more information on this file, see
https://docs.djangoproject.com/en/4.2/topics/settings/

For the full list of settings and their values, see
https://docs.djangoproject.com/en/4.2/ref/settings/
"""

import os
from pathlib import Path

# PyMySQL is a pure-Python MySQL driver. We register it here to act as a
# drop-in replacement for mysqlclient, so Django's 'django.db.backends.mysql'
# engine works without needing to compile any C extensions.
import pymysql

pymysql.install_as_MySQLdb()

BASE_DIR = Path(__file__).resolve().parent.parent


# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = os.environ.get(
    'SECRET_KEY', 'django-insecure-change-me-in-production-1a2b3c4d5e6f7g8h9i0j'
)

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = os.environ.get('DEBUG', 'True') == 'True'

ALLOWED_HOSTS = ['.onrender.com', 'localhost', '127.0.0.1']
extra_hosts = os.environ.get('ALLOWED_HOSTS', '')
if extra_hosts:
    ALLOWED_HOSTS += [h.strip() for h in extra_hosts.split(',') if h.strip()]

CSRF_TRUSTED_ORIGINS = ['https://*.onrender.com']
extra_csrf_origins = os.environ.get('CSRF_TRUSTED_ORIGINS', '')
if extra_csrf_origins:
    CSRF_TRUSTED_ORIGINS += [o.strip() for o in extra_csrf_origins.split(',') if o.strip()]


INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'inventory',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'inventory_sales_manager.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'inventory.context_processors.role_context',
            ],
        },
    },
]

WSGI_APPLICATION = 'inventory_sales_manager.wsgi.application'


# Database
# https://docs.djangoproject.com/en/4.2/ref/settings/#databases

db_options = {
    'charset': 'utf8mb4',
    'init_command': "SET sql_mode='STRICT_TRANS_TABLES'",
}
db_ssl_ca = os.environ.get('DB_SSL_CA', '')
if db_ssl_ca:
    ca_path = Path(db_ssl_ca)
    if not ca_path.is_absolute():
        ca_path = BASE_DIR / ca_path
    if not ca_path.exists():
        raise FileNotFoundError(
            f"DB_SSL_CA is set to '{db_ssl_ca}' but no file was found at "
            f"'{ca_path}'. Make sure the certificate file is committed to "
            f"the repo at that path relative to the project root (where "
            f"manage.py lives)."
        )
    db_options = {
    'charset': 'utf8mb4',
    }

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.mysql',
        'NAME': os.environ.get('DB_NAME', 'inventory_sales_db'),
        'USER': os.environ.get('DB_USER', 'root'),
        'PASSWORD': os.environ.get('DB_PASSWORD', ''),
        'HOST': os.environ.get('DB_HOST', 'localhost'),
        'PORT': os.environ.get('DB_PORT', '3306'),
        'OPTIONS': db_options,
    }
}


AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]


LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True


STATIC_URL = 'static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Auth redirects - post_login_redirect inspects the user's group and sends
# Admins to the dashboard, Sales Staff to the New Sale page.
LOGIN_URL = 'inventory:login'
LOGIN_REDIRECT_URL = 'inventory:post_login_redirect'
LOGOUT_REDIRECT_URL = 'inventory:login'
