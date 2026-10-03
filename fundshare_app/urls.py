from django.urls import path
from fundshare_app.views import api_views

urlpatterns = [
    # Auth
    path('auth/login/', api_views.LoginView.as_view(), name='api-login'),
    path('auth/logout/', api_views.LogoutView.as_view(), name='api-logout'),
    path('auth/me/', api_views.MeView.as_view(), name='api-me'),
    path('auth/switch-role/', api_views.SwitchRoleView.as_view(), name='api-switch-role'),

    # Wallet
    path('wallet/summary/', api_views.WalletSummaryView.as_view(), name='api-wallet-summary'),
    path('wallet/cash-in/', api_views.CashInView.as_view(), name='api-cash-in'),
    path('wallet/send/', api_views.SendMoneyView.as_view(), name='api-send-money'),       # JS uses /api/wallet/send/
    path('wallet/send-money/', api_views.SendMoneyView.as_view(), name='api-send-money2'),
    path('wallet/utility/', api_views.UtilityServicesView.as_view(), name='api-utility'),

    # Purpose Funds
    path('funds/', api_views.PurposeFundsListView.as_view(), name='api-funds-list'),
    path('funds/<int:pk>/', api_views.PurposeFundManageView.as_view(), name='api-fund-manage'),
    path('funds/<int:pk>/allocate/', api_views.PurposeFundAllocateView.as_view(), name='api-fund-allocate'),
    path('funds/transfer/', api_views.PurposeFundTransferView.as_view(), name='api-fund-transfer'),
    path('funds/<int:pk>/details/', api_views.PurposeFundDetailView.as_view(), name='api-fund-details'),

    # Contact Book
    path('contacts/', api_views.ContactsListView.as_view(), name='api-contacts-list'),
    path('contacts/search/', api_views.ContactSearchView.as_view(), name='api-contacts-search'),
    path('contacts/resolve/', api_views.ContactResolveView.as_view(), name='api-contacts-resolve'),
    path('contacts/<int:pk>/', api_views.ContactDetailView.as_view(), name='api-contact-detail'),


    # Merchants & Payments
    path('merchants/', api_views.MerchantsListView.as_view(), name='api-merchants'),
    path('pay/', api_views.PayMerchantView.as_view(), name='api-pay'),                    # JS uses /api/pay/
    path('payments/merchant/', api_views.PayMerchantView.as_view(), name='api-pay-merchant'),
    path('merchant/dashboard/', api_views.MerchantDashboardView.as_view(), name='api-merchant-dashboard'),

    # FamilyPass
    path('family-pass/', api_views.FamilyPassListView.as_view(), name='api-familypass-list'),   # JS uses /api/family-pass/
    path('familypass/', api_views.FamilyPassListView.as_view(), name='api-familypass-list2'),
    path('familypass/members-list/', api_views.AvailableMembersView.as_view(), name='api-familypass-members'),
    path('family-pass/<int:pk>/', api_views.FamilyPassDetailView.as_view(), name='api-fp-detail'),
    path('familypass/<int:pk>/', api_views.FamilyPassDetailView.as_view(), name='api-familypass-detail'),
    path('family-pass/<int:pk>/edit/', api_views.FamilyPassDetailView.as_view(), name='api-fp-edit'),
    path('familypass/<int:pk>/edit/', api_views.FamilyPassDetailView.as_view(), name='api-familypass-edit'),
    path('family-pass/<int:pk>/revoke/', api_views.FamilyPassRevokeView.as_view(), name='api-fp-revoke'),
    path('familypass/<int:pk>/revoke/', api_views.FamilyPassRevokeView.as_view(), name='api-familypass-revoke'),
    path('family-pass/<int:pk>/activity/', api_views.FamilyPassActivityView.as_view(), name='api-fp-activity'),
    path('familypass/<int:pk>/activity/', api_views.FamilyPassActivityView.as_view(), name='api-familypass-activity'),

    # Transactions & Notifications
    path('transactions/', api_views.TransactionHistoryView.as_view(), name='api-transactions'),
    path('notifications/', api_views.NotificationsListView.as_view(), name='api-notifications'),
    path('notifications/<int:pk>/read/', api_views.MarkNotificationReadView.as_view(), name='api-notification-read'),

    # AI & Intelligence
    path('intelligence/dashboard/', api_views.IntelligenceDashboardView.as_view(), name='api-intelligence-dashboard'),
    path('ai/query/', api_views.AICoachQueryView.as_view(), name='api-ai-coach'),         # JS uses /api/ai/query/
    path('ai/set-key/', api_views.AISetKeyView.as_view(), name='api-ai-set-key'),
    path('intelligence/coach/', api_views.AICoachQueryView.as_view(), name='api-ai-coach2'),
    path('reports/', api_views.ReportsView.as_view(), name='api-reports'),

    # Evaluations & Experiments (Admin / Judges)
    path('evaluation/metrics/', api_views.EvaluationMetricsView.as_view(), name='api-evaluation-metrics'),
    path('evaluation/experiments/', api_views.ExperimentRecordsView.as_view(), name='api-evaluation-experiments'),
    path('seed/', api_views.SeedDemoDataView.as_view(), name='api-seed-data'),             # JS uses /api/seed/
    path('admin/seed-data/', api_views.SeedDemoDataView.as_view(), name='api-seed-data2'),
]
