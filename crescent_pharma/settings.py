import os
import sys
from pathlib import Path
from datetime import timedelta
import environ

BASE_DIR = Path(__file__).resolve().parent.parent

# Initialize environ
env = environ.Env()
# Read .env file
environ.Env.read_env(os.path.join(BASE_DIR, '.env'))

SECRET_KEY = env('SECRET_KEY', default='django-insecure-^-e1qi5-o+z6l!vdc3g^xoe3x4-8wqxrfo=58ck1^4%xzpg00s')
DEBUG = env.bool('DEBUG', default=True)
ALLOWED_HOSTS = env.list('ALLOWED_HOSTS', default=['*'])

INSTALLED_APPS = [
    'daphne',
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'rest_framework',
    'rest_framework_simplejwt',
    'django_filters',
    'corsheaders',
    'drf_spectacular',
    'channels',
    'users',
    'core',
    'hr',
    'inventory',
    'sales',
    'marketing',
    'accounting',
    'purchases',
    'production',
    'api',
]

MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'crescent_pharma.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'crescent_pharma.wsgi.application'
ASGI_APPLICATION = 'crescent_pharma.asgi.application'

DATABASES = {
    'default': env.db('DATABASE_URL')
}

# The database is remote, so opening a connection costs a full network
# round trip plus auth (~1.3s measured). Without CONN_MAX_AGE Django opens a
# fresh one for every request and throws it away, so that cost is paid on each
# call. Holding the connection open for 10 minutes per worker removes it from
# all but the first request. CONN_HEALTH_CHECKS makes Django verify a pooled
# connection is still alive before reusing it, so a server-side timeout
# surfaces as a reconnect rather than an InterfaceError.
DATABASES['default']['CONN_MAX_AGE'] = env.int('DB_CONN_MAX_AGE', 600)
DATABASES['default']['CONN_HEALTH_CHECKS'] = True

# CONN_MAX_AGE alone is not enough here. `runserver` calls
# connections.close_all() after every request (see Django's
# ThreadedWSGIServer.close_request), and any per-thread connection dies with
# its thread, so in practice each request paid a fresh handshake - measured at
# ~1.2s against this host (~220ms TCP plus ~900ms Postgres auth round trips).
#
# A psycopg3 pool lives above the request/thread cycle, so connections are
# borrowed and returned instead of reopened. Enabled only when psycopg3 and
# psycopg_pool are both importable, so an environment still on psycopg2 keeps
# working on CONN_MAX_AGE alone rather than failing at startup.
def _pooling_available():
    try:
        import psycopg  # noqa: F401
        import psycopg_pool  # noqa: F401
    except ImportError:
        return False
    return psycopg.__version__ >= '3'


if env.bool('DB_USE_POOL', True) and _pooling_available():
    DATABASES['default'].setdefault('OPTIONS', {})
    DATABASES['default']['OPTIONS']['pool'] = {
        'min_size': env.int('DB_POOL_MIN', 2),
        'max_size': env.int('DB_POOL_MAX', 10),
        'timeout': env.int('DB_POOL_TIMEOUT', 30),
    }
    # A pooled connection is owned by the pool, not by the request; Django
    # requires CONN_MAX_AGE to be 0 so it hands the connection back each time.
    DATABASES['default']['CONN_MAX_AGE'] = 0
    # The pool already validates a connection before handing it out, so
    # Django's own health-check ping would just add a round trip.
    DATABASES['default']['CONN_HEALTH_CHECKS'] = False

# The default hasher runs 1.5M PBKDF2 iterations, about 2.5 seconds per
# password. The test suite creates users in setUp, which runs once per test
# method, so that alone accounted for most of the suite's runtime. Production
# keeps the strong hasher; only the test runner gets the fast one.
if 'test' in sys.argv:
    PASSWORD_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']

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

STORAGES = {
    'default': {
        'BACKEND': 'django.core.files.storage.FileSystemStorage',
    },
    'staticfiles': {
        # WhiteNoise's manifest storage requires collectstatic to have run, so
        # keep the plain backend in development where it usually has not.
        'BACKEND': (
            'django.contrib.staticfiles.storage.StaticFilesStorage'
            if DEBUG
            else 'whitenoise.storage.CompressedManifestStaticFilesStorage'
        ),
    },
}

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

from corsheaders.defaults import default_headers

AUTH_USER_MODEL = 'users.CustomUser'
CORS_ALLOW_ALL_ORIGINS = True
CORS_ALLOW_CREDENTIALS = True
CORS_ALLOW_HEADERS = list(default_headers) + [
    'x-client-type',
    'x-csrftoken',
]

REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': ('rest_framework_simplejwt.authentication.JWTAuthentication',),
    'DEFAULT_PERMISSION_CLASSES': ('rest_framework.permissions.IsAuthenticated',),
    'DEFAULT_FILTER_BACKENDS': (
        'django_filters.rest_framework.DjangoFilterBackend',
        'rest_framework.filters.SearchFilter',
        'rest_framework.filters.OrderingFilter',
    ),
    'DEFAULT_PAGINATION_CLASS': 'api.pagination.CustomPageNumberPagination',
    'PAGE_SIZE': 10,
    'DEFAULT_RENDERER_CLASSES': (
        'djangorestframework_camel_case.render.CamelCaseJSONRenderer',
        'djangorestframework_camel_case.render.CamelCaseBrowsableAPIRenderer',
    ),
    'DEFAULT_PARSER_CLASSES': (
        'djangorestframework_camel_case.parser.CamelCaseJSONParser',
        'rest_framework.parsers.FormParser',
        'rest_framework.parsers.MultiPartParser',
    ),
    'DEFAULT_SCHEMA_CLASS': 'drf_spectacular.openapi.AutoSchema',
}

SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(days=7),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=30),
    'AUTH_HEADER_TYPES': ('Bearer',),
}

SPECTACULAR_SETTINGS = {
    'TITLE': 'Crescent Pharma Backend API',
    'DESCRIPTION': 'API documentation for Crescent Pharma ERP system',
    'VERSION': '1.0.0',
    'SERVE_INCLUDE_SCHEMA': False,
    'CAMELIZE_NAMES': True,
    'SCHEMA_PATH_PREFIX': r'/api',
    'TAGS': [
        {'name': 'Authentication', 'description': 'User authentication and JWT token management'},
        {'name': 'Users / Employees', 'description': 'Employee records and user profile management'},
        {'name': 'Core / Lookups', 'description': 'System lookups and configurations'},
        {'name': 'Core / Roles & Permissions', 'description': 'Custom roles and system micropermissions management'},
        {'name': 'HR - Attendance', 'description': 'Attendance tracking and check-in operations'},
        {'name': 'HR - Live GPS Tracking', 'description': 'Real-time GPS field tracking, background ping, offline batch sync, mock location detection, and historical route playback'},
        {'name': 'HR - Leave Management', 'description': 'Employee leave requests, approvals, and balance management'},
        {'name': 'HR - Payroll', 'description': 'Payroll calculations, approvals, and salary management'},
        {'name': 'HR - Loans', 'description': 'Employee loans and EMI management'},
        {'name': 'HR - Tour Allowance', 'description': 'Tour expenses and allowance tracking'},
        {'name': 'HR - Holidays & Weekends', 'description': 'Public holidays and weekly off-day configurations'},
        {'name': 'Products & Categories', 'description': 'Product catalog, categories, and attributes management'},
        {'name': 'Inventory & Stock Management', 'description': 'Warehouses, stock levels, batch/expiry tracking, and stock movements'},
        {'name': 'Customers & Sales Orders', 'description': 'Customer directory, client orders, and order history'},
        {'name': 'Marketing & Sales Targets', 'description': 'Smart sales targets allocation, auto-pricing, real-time achievement scorecards, and team analytics'},
        {'name': 'Accounting / Chart of Accounts', 'description': '5-tier Chart of Accounts (COA) and hierarchical GL tree'},
        {'name': 'Accounting / Fiscal Calendar', 'description': 'Fiscal Years, Accounting Periods, and anti-tampering period locking'},
        {'name': 'Accounting / Vouchers', 'description': 'Double-entry Journal, Contra, Payment, Receipt, and Sales/Payroll vouchers with reversal workflows'},
        {'name': 'Accounting / Payments & Collections', 'description': 'Customer money receipts, vendor disbursements, and invoice payment reconciliation'},
        {'name': 'Accounting / Bank Reconciliation', 'description': 'Bank Statement matching, unpresented cheques, and BRS audit generation'},
        {'name': 'Accounting / Financial Reports', 'description': 'Real-time General Ledger, Cash/Bank Book, Trial Balance, P&L, Balance Sheet, and VAT reports'},
        {'name': 'Production / Bill of Materials (BOM)', 'description': 'Master recipes, formulas, raw and packaging material specifications, and batch material scaling'},
        {'name': 'Production / Manufacturing Batches & WIP', 'description': 'Production lines, master scheduling, batch execution, material issue slips, in-process IPQC logs, and finished goods transfers'},
    ],
}

CELERY_BROKER_URL = env('CELERY_BROKER_URL', default='redis://localhost:6379/0')
CELERY_RESULT_BACKEND = env('CELERY_RESULT_BACKEND', default='redis://localhost:6379/0')
CELERY_ACCEPT_CONTENT = ['application/json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_TIMEZONE = TIME_ZONE

USE_REDIS_CHANNEL = env.bool('USE_REDIS_CHANNEL', default=False)
if USE_REDIS_CHANNEL:
    CHANNEL_LAYERS = {
        'default': {
            'BACKEND': 'channels_redis.core.RedisChannelLayer',
            'CONFIG': {'hosts': [(env('REDIS_HOST', default='127.0.0.1'), env.int('REDIS_PORT', default=6379))]},
        },
    }
else:
    CHANNEL_LAYERS = {
        'default': {
            'BACKEND': 'channels.layers.InMemoryChannelLayer',
        },
    }

CSRF_TRUSTED_ORIGINS = [
    "https://server-crescentpharmabackend-l4ajai-5ed25b-62-84-177-235.sslip.io",
]