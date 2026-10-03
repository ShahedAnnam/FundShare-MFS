from django.apps import AppConfig


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

