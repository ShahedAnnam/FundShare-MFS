from django.urls import path
from fundshare_app.views import api_views

urlpatterns = [
    # Auth & Demo Switcher
    path('auth/login/', api_views.LoginView.as_view(), name='api-login'),
    path('auth/logout/', api_views.LogoutView.as_view(), name='api-logout'),
    path('auth/me/', api_views.MeView.as_view(), name='api-me'),
    path('auth/switch-role/', api_views.SwitchRoleView.as_view(), name='api-switch-role'),

    # Wallet
    path('wallet/summary/', api_views.WalletSummaryView.as_view(), name='api-wallet-summary'),
    path('wallet/cash-in/', api_views.CashInView.as_view(), name='api-cash-in'),
    path('wallet/send-money/', api_views.SendMoneyView.as_view(), name='api-send-money'),
    path('wallet/utility/', api_views.UtilityServicesView.as_view(), name='api-utility'),

    # Purpose Funds
    path('funds/', api_views.PurposeFundsListView.as_view(), name='api-funds-list'),
    path('funds/<int:pk>/allocate/', api_views.PurposeFundAllocateView.as_view(), name='api-fund-allocate'),
    path('funds/transfer/', api_views.PurposeFundTransferView.as_view(), name='api-fund-transfer'),
    path('funds/<int:pk>/details/', api_views.PurposeFundDetailView.as_view(), name='api-fund-details'),

    # Merchants & Payments
    path('merchants/', api_views.MerchantsListView.as_view(), name='api-merchants'),
    path('payments/merchant/', api_views.PayMerchantView.as_view(), name='api-pay-merchant'),
    path('merchant/dashboard/', api_views.MerchantDashboardView.as_view(), name='api-merchant-dashboard'),

    # FamilyPass
    path('familypass/', api_views.FamilyPassListView.as_view(), name='api-familypass-list'),
    path('familypass/members-list/', api_views.AvailableMembersView.as_view(), name='api-familypass-members'),
    path('familypass/<int:pk>/revoke/', api_views.FamilyPassRevokeView.as_view(), name='api-familypass-revoke'),
    path('familypass/<int:pk>/activity/', api_views.FamilyPassActivityView.as_view(), name='api-familypass-activity'),

    # Transactions & Notifications
    path('transactions/', api_views.TransactionHistoryView.as_view(), name='api-transactions'),
    path('notifications/', api_views.NotificationsListView.as_view(), name='api-notifications'),
    path('notifications/<int:pk>/read/', api_views.MarkNotificationReadView.as_view(), name='api-notification-read'),

    # AI & Intelligence
    path('intelligence/dashboard/', api_views.IntelligenceDashboardView.as_view(), name='api-intelligence-dashboard'),
    path('intelligence/coach/', api_views.AICoachQueryView.as_view(), name='api-ai-coach'),
    path('reports/', api_views.ReportsView.as_view(), name='api-reports'),

    # Evaluations & Experiments (Admin / Judges)
    path('evaluation/metrics/', api_views.EvaluationMetricsView.as_view(), name='api-evaluation-metrics'),
    path('evaluation/experiments/', api_views.ExperimentRecordsView.as_view(), name='api-evaluation-experiments'),
    path('admin/seed-data/', api_views.SeedDemoDataView.as_view(), name='api-seed-data'),
]
