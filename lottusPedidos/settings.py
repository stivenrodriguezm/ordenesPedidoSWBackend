from pathlib import Path
from datetime import timedelta

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/5.1/howto/deployment/checklist/

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = 'django-insecure-9k362@l)2sf4x1pstt7f=js1!y5u8*+ck*z77x=3x#k24j%r)-'

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = True # Cambiar a False en producción

AUTH_USER_MODEL = 'ordenes.CustomUser'

ALLOWED_HOSTS = [
    # "your_production_domain.com", # Reemplazar con tu dominio de producción
    # "your_production_ip",
    "*", # ¡ADVERTENCIA! No usar en producción. Solo para desarrollo.
]

# CORS configuration
CORS_ALLOW_ALL_ORIGINS = False  # Cambiar a False en producción y especificar CORS_ALLOWED_ORIGINS

CORS_ALLOWED_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]

CORS_ALLOW_CREDENTIALS = True  # Permitir el envío de cookies y credenciales

CORS_ALLOW_METHODS = [
    'GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS',
]

CORS_ALLOW_HEADERS = [
    "accept",
    "accept-encoding",
    "authorization",  # Permitir el encabezado de autorización
    "content-type",
    "dnt",
    "origin",
    "user-agent",
    "x-csrftoken",
    "x-requested-with",
]

CSRF_TRUSTED_ORIGINS = [
    "http://localhost:5173",  # Tu frontend en localhost:5173
    "http://127.0.0.1:5173", 
    "http://127.0.0.1", 
    "http://localhost",
]

# **Importante: Para entorno de desarrollo local**
CSRF_COOKIE_SECURE = False  # Desactiva en desarrollo, cuando no usas HTTPS
SESSION_COOKIE_SECURE = False  # Desactiva en desarrollo, cuando no usas HTTPS

# Application definition
INSTALLED_APPS = [
    'corsheaders',  # Asegúrate de que corsheaders esté instalado
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'rest_framework',
    'ordenes',
    'django_extensions',
    'django_filters',
]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",  # Debe ir primero
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'lottusPedidos.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'lottusPedidos.wsgi.application'

# Database configuration
# ADVERTENCIA: No usar credenciales hardcodeadas en producción.
# Usar variables de entorno o un sistema de gestión de secretos.
# Ejemplo:
# import os
# 'NAME': os.environ.get('DB_NAME', 'u756180748_pruebasv3'),
# 'USER': os.environ.get('DB_USER', 'u756180748_root'),
# 'PASSWORD': os.environ.get('DB_PASSWORD', 'Lottus123'),
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.mysql',
        'NAME': 'u756180748_pruebasv3',
        'USER': 'u756180748_root',
        'PASSWORD': 'Lottus123',
        'HOST': '31.170.167.52',
        'PORT': '3306',
        'OPTIONS': {
            'init_command': "SET sql_mode='STRICT_TRANS_TABLES'",
            'connect_timeout': 10,
            'autocommit': True,
        },
    }
}

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]

# Internationalization
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'America/Bogota'
USE_I18N = True
USE_TZ = True

# Static files (CSS, JavaScript, Images)
STATIC_URL = 'static/'

# Default primary key field type
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# REST Framework configuration
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'rest_framework_simplejwt.authentication.JWTAuthentication',
    ),
    'DEFAULT_PERMISSION_CLASSES': (
        'rest_framework.permissions.IsAuthenticated',
    ),
    'DEFAULT_THROTTLE_CLASSES': [
        'rest_framework.throttling.AnonRateThrottle',
        'rest_framework.throttling.UserRateThrottle'
    ],
    'DEFAULT_THROTTLE_RATES': {
        'anon': '100/day',
        'user': '1000/day'
    }
}

SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(hours=8),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=1),
    'AUTH_HEADER_TYPES': ('Bearer',),
}

