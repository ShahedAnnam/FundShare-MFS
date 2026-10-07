from django.apps import AppConfig
from django.contrib.admin import apps as admin_apps


class FundShareAdminConfig(admin_apps.AdminConfig):
    default_site = 'fundshare_app.admin_site.FundShareAdminSite'


class FundshareAppConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'fundshare_app'
    verbose_name = 'FUNDShare MFS'

    def ready(self):
        try:
            from fundshare_app.encoding import setup_console_encoding
            setup_console_encoding()
        except Exception:
            pass
