from .settings import *
GEMINI_API_KEY = ''  # Tests must never call the external AI service.

# Fast fixture hashing; production continues to use Django's strong default hashers.
PASSWORD_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']
CACHES = {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}}
LOGGING = {'version': 1, 'disable_existing_loggers': False, 'handlers': {'null': {'class': 'logging.NullHandler'}}, 'loggers': {'django.request': {'handlers': ['null'], 'propagate': False}}}
