from django.contrib import admin
from django.urls import path, include
from fundshare_app.views.ui_views import (
    IndexView,
    LoginPageView,
    LogoutPageView,
    RegistrationPageView,
    analyst_risk_dashboard,
    resolve_fraud_incident,
    admin_toggle_wallet_freeze,
    admin_toggle_family_pass,
    admin_toggle_purpose_fund,
)

urlpatterns = [
    # Custom Administrative Action Endpoints
    path('admin-actions/wallet/<int:wallet_id>/toggle-freeze/', admin_toggle_wallet_freeze, name='admin-action-wallet-freeze'),
    path('admin-actions/familypass/<int:pk>/action/', admin_toggle_family_pass, name='admin-action-familypass'),
    path('admin-actions/purposefund/<int:pk>/action/', admin_toggle_purpose_fund, name='admin-action-purposefund'),

    path('admin/wallet/<int:wallet_id>/toggle-freeze/', admin_toggle_wallet_freeze, name='admin-toggle-wallet-freeze'),
    path('admin/family-pass/<int:pass_id>/toggle-status/', admin_toggle_family_pass, name='admin-toggle-family-pass'),
    path('admin/purpose-funds/<int:fund_id>/toggle-status/', admin_toggle_purpose_fund, name='admin-toggle-purpose-fund'),

    path('admin/', admin.site.urls),
    path('api/', include('fundshare_app.urls')),
    path('login/', LoginPageView.as_view(), name='login'),
    path('register/', RegistrationPageView.as_view(), name='register'),
    path('logout/', LogoutPageView.as_view(), name='logout'),
    path('risk-console/', analyst_risk_dashboard, name='risk_console'),
    path('risk-console/resolve/<int:incident_id>/', resolve_fraud_incident, name='risk_console_resolve'),
    path('', IndexView.as_view(), name='index'),
]

