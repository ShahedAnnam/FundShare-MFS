import hashlib
import json
import re
from functools import wraps
from decimal import InvalidOperation

from django.db import DatabaseError, transaction
from rest_framework.exceptions import NotAuthenticated
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.renderers import JSONRenderer
from rest_framework.response import Response
from rest_framework.views import APIView

from fundshare_app.models import FinancialRequest, Transaction, UserRole
from fundshare_app.services.security_service import SecurityError, verify_pin


class AuthenticatedAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def handle_exception(self, exc):
        if isinstance(exc, DatabaseError):
            return Response({'error': 'The request could not be confirmed. Please retry using the same transaction key.', 'code': 'TRANSACTION_BUSY'}, status=503)
        response = super().handle_exception(exc)
        if isinstance(exc, NotAuthenticated):
            response.status_code = 401
        if isinstance(response.data, dict) and 'detail' in response.data:
            response.data['error'] = str(response.data['detail'])
        return response


class AdministratorPermission(BasePermission):
    message = 'Administrator access is required.'

    def has_permission(self, request, view):
        user = request.user
        return user.is_authenticated and user.is_active and (user.is_superuser or user.role == UserRole.ADMIN)


class WalletUserPermission(BasePermission):
    message = 'This action requires a customer wallet or administrator account.'

    def has_permission(self, request, view):
        user = request.user
        return user.is_authenticated and user.is_active and (user.is_superuser or user.role in (UserRole.CUSTOMER, UserRole.ADMIN))


class CustomerPermission(BasePermission):
    message = 'FamilyPass is available between active customer accounts only.'

    def has_permission(self, request, view):
        user = request.user
        return user.is_authenticated and user.is_active and user.effective_role == UserRole.CUSTOMER


class AdminAPIView(AuthenticatedAPIView):
    permission_classes = [IsAuthenticated, AdministratorPermission]


class FinancialAPIView(AuthenticatedAPIView):
    permission_classes = [IsAuthenticated, WalletUserPermission]

    def financial_action(self, request, handler, *args, **kwargs):
        try:
            if not isinstance(request.data, dict):
                return Response({'error': 'Transaction details must be a JSON object.', 'code': 'INVALID_TRANSACTION'}, status=400)
            key = request.headers.get('Idempotency-Key', '')
            if not re.fullmatch(r'[A-Za-z0-9_.:-]{8,128}', key):
                return Response({'error': 'A valid Idempotency-Key is required.', 'code': 'IDEMPOTENCY_KEY_REQUIRED'}, status=400)
            verify_pin(request.user, request.data.get('pin'))
            payload = {k: v for k, v in request.data.items() if k != 'pin'}
            operation = request.resolver_match.func.view_class.__name__
            encoded = json.dumps([operation, request.method, kwargs, payload], sort_keys=True, separators=(',', ':'))
            fingerprint = hashlib.sha256(encoded.encode()).hexdigest()
            with transaction.atomic():
                # The unique constraint serializes concurrent inserts of the same key.
                record, created = FinancialRequest.objects.get_or_create(
                    user=request.user, key=key, defaults={'fingerprint': fingerprint},
                )
                record = FinancialRequest.objects.select_for_update().get(pk=record.pk)
                if not created:
                    if record.fingerprint != fingerprint:
                        return Response({'error': 'This request key was already used for a different transaction.', 'code': 'IDEMPOTENCY_CONFLICT'}, status=409)
                    response = Response(record.response, status=record.response_status)
                    response['Idempotency-Replayed'] = 'true'
                    return response
                with transaction.atomic():
                    response = handler(request, *args, **kwargs)
                    if response.status_code >= 400:
                        transaction.set_rollback(True)
                if getattr(request, 'rejected_transaction', None):
                    Transaction.objects.create(**request.rejected_transaction)
                record.response = json.loads(JSONRenderer().render(response.data))
                record.response_status = response.status_code
                record.save(update_fields=['response', 'response_status'])
                return response
        except SecurityError as exc:
            return Response({'error': exc.message, 'code': exc.code}, status=exc.status)
        except (InvalidOperation, ValueError, TypeError, OverflowError):
            return Response({'error': 'Invalid transaction details. Check the amount and selected accounts.', 'code': 'INVALID_TRANSACTION'}, status=400)
        except DatabaseError:
            return Response({'error': 'The transaction could not be confirmed. Retry with the same request key.', 'code': 'TRANSACTION_BUSY'}, status=503)

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        for method in ('post', 'delete'):
            handler = cls.__dict__.get(method)
            if handler:
                @wraps(handler)
                def wrapped(self, request, *args, _handler=handler, **kw):
                    return self.financial_action(request, _handler.__get__(self, type(self)), *args, **kw)

                setattr(cls, method, wrapped)
