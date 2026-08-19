import os
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
    'api',
]

MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.security.SecurityMiddleware',
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
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

AUTH_USER_MODEL = 'users.CustomUser'
CORS_ALLOW_ALL_ORIGINS = True
CORS_ALLOW_CREDENTIALS = True

REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': ('rest_framework_simplejwt.authentication.JWTAuthentication',),
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
        {'name': 'HR - Leave Management', 'description': 'Employee leave requests, approvals, and balance management'},
        {'name': 'HR - Payroll', 'description': 'Payroll calculations, approvals, and salary management'},
        {'name': 'HR - Loans', 'description': 'Employee loans and EMI management'},
        {'name': 'HR - Tour Allowance', 'description': 'Tour expenses and allowance tracking'},
        {'name': 'HR - Holidays & Weekends', 'description': 'Public holidays and weekly off-day configurations'},
        {'name': 'Products & Categories', 'description': 'Product catalog, categories, and attributes management'},
        {'name': 'Inventory & Stock Management', 'description': 'Warehouses, stock levels, batch/expiry tracking, and stock movements'},
        {'name': 'Customers & Sales Orders', 'description': 'Customer directory, client orders, and order history'},
        {'name': 'Marketing & Sales Targets', 'description': 'Smart sales targets allocation, auto-pricing, real-time achievement scorecards, and team analytics'},
    ],
}

CELERY_BROKER_URL = env('CELERY_BROKER_URL', default='redis://localhost:6379/0')
CELERY_RESULT_BACKEND = env('CELERY_RESULT_BACKEND', default='redis://localhost:6379/0')
CELERY_ACCEPT_CONTENT = ['application/json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_TIMEZONE = TIME_ZONE

CHANNEL_LAYERS = {
    'default': {
        'BACKEND': 'channels_redis.core.RedisChannelLayer',
        'CONFIG': {'hosts': [('127.0.0.1', 6379)]},
    },
}
