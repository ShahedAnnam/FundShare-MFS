from .settings import *
import tempfile
import uuid

# Fast fixture hashing; production continues to use Django's strong default hashers.
PASSWORD_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']
CACHES = {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}}
LOGGING = {'version': 1, 'disable_existing_loggers': False, 'handlers': {'null': {'class': 'logging.NullHandler'}}, 'loggers': {'django.request': {'handlers': ['null'], 'propagate': False}}}
if DATABASES['default']['ENGINE'] == 'django.db.backends.sqlite3':
    DATABASES['default']['TEST'] = {'NAME': str(Path(tempfile.gettempdir()) / f'fundshare-test-{uuid.uuid4().hex}.sqlite3')}
