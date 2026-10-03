#!/usr/bin/env python
"""Django's command-line utility for administrative tasks."""
import os
import sys


def main():
    """Run administrative tasks."""
    # Ensure standard streams handle UTF-8 and Unicode characters like ৳ without charmap encoding errors
    try:
        from fundshare_app.encoding import setup_console_encoding
        setup_console_encoding()
    except Exception:
        # Fallback if fundshare_app is not yet on pythonpath
        os.environ.setdefault('PYTHONUTF8', '1')
        os.environ.setdefault('PYTHONIOENCODING', 'utf-8')
        for s in (sys.stdout, sys.stderr):
            if s and hasattr(s, 'reconfigure'):
                try:
                    s.reconfigure(encoding='utf-8', errors='replace')
                except Exception:
                    pass

    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'fundshare_core.settings')
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?"
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == '__main__':
    main()
