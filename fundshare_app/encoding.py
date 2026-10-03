"""
Unicode and Console Encoding Utilities for FUNDShare.
Ensures safe console output, logging, and terminal operations across Windows, Linux, and macOS
without altering stored database values or UI-facing currency symbols (৳).
"""

import sys
import os
import codecs
import logging


def _bdt_encode_error_handler(error):
    """
    Custom error handler for Python codecs.
    When a character cannot be encoded into the active terminal encoding (e.g., cp1252 on Windows),
    converts the Bangladeshi Taka symbol '৳' (\\u09f3) to 'BDT ' in console output,
    and replaces other unencodable characters with '?' to prevent UnicodeEncodeError crashes.
    """
    if isinstance(error, UnicodeEncodeError):
        bad_chars = error.object[error.start:error.end]
        replacements = []
        for ch in bad_chars:
            if ch == '\u09f3':
                replacements.append('BDT ')
            else:
                replacements.append('?')
        return (''.join(replacements), error.end)
    raise error


# Register custom codec error handler once
try:
    codecs.register_error('bdt_replace', _bdt_encode_error_handler)
except Exception:
    pass


def setup_console_encoding():
    """
    Configures standard input/output/error streams to UTF-8 on Windows and systems
    with non-UTF-8 console codepages. Attaches 'bdt_replace' as the error fallback
    so terminal output never crashes with UnicodeEncodeError.
    """
    # Set environment variables for any child processes
    os.environ.setdefault('PYTHONUTF8', '1')
    os.environ.setdefault('PYTHONIOENCODING', 'utf-8')

    for stream_name in ('stdout', 'stderr'):
        stream = getattr(sys, stream_name, None)
        if stream and hasattr(stream, 'reconfigure'):
            try:
                # First attempt full UTF-8 with bdt_replace safety fallback
                stream.reconfigure(encoding='utf-8', errors='bdt_replace')
            except Exception:
                try:
                    # If encoding change is disallowed by terminal wrapper, set safe error handler
                    stream.reconfigure(errors='bdt_replace')
                except Exception:
                    pass


def safe_console_text(text: str, stream=None) -> str:
    """
    Helper to convert '৳' to 'BDT ' only if the target stream cannot encode '৳'.
    If the target stream supports UTF-8, preserves '৳' intact.
    Does NOT alter UI or database values.
    """
    if not isinstance(text, str):
        return text

    target_stream = stream or sys.stdout
    encoding = getattr(target_stream, 'encoding', 'utf-8') or 'utf-8'

    try:
        text.encode(encoding)
        return text
    except (UnicodeEncodeError, LookupError):
        # Fallback for display in non-Unicode terminal: convert ৳ to BDT first
        converted = text.replace('\u09f3', 'BDT ')
        try:
            return converted.encode(encoding, errors='replace').decode(encoding)
        except Exception:
            return converted.encode('ascii', errors='replace').decode('ascii')


class SafeConsoleFormatter(logging.Formatter):
    """
    Logging formatter that ensures log messages never throw UnicodeEncodeError
    when written to terminal consoles with non-UTF-8 encodings.
    Preserves all error messages, tracebacks, line numbers, and timestamps.
    """
    def format(self, record):
        msg = super().format(record)
        try:
            stream_enc = getattr(sys.stderr, 'encoding', 'utf-8') or 'utf-8'
            msg.encode(stream_enc)
            return msg
        except (UnicodeEncodeError, LookupError):
            converted = msg.replace('\u09f3', 'BDT ')
            try:
                return converted.encode(stream_enc, errors='replace').decode(stream_enc)
            except Exception:
                return converted.encode('ascii', errors='replace').decode('ascii')
