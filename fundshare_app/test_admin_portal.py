from decimal import Decimal
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone
from datetime import timedelta
from fundshare_app.models import (
    User, UserRole, Wallet, PurposeFund, BusinessCategory,
    FamilyPass, FamilyPassStatus, FamilyPassPurpose,
    Transaction, TransactionType, PaymentSource, TransactionStatus
)


class AdminPortalIntegrationTests(TestCase):
    def setUp(self):
        self.client = Client()
        # Create admin user
        self.admin_user = User.objects.create_user(
            username='admin_tester',
            phone='01711999999',
            password='Password123!',
            role=UserRole.ADMIN,
            is_staff=True,
            is_superuser=True
        )
        self.admin_wallet = Wallet.objects.create(owner=self.admin_user, balance=Decimal('1000.00'))

        # Create regular customer
        self.customer_user = User.objects.create_user(
            username='customer_tester',
            phone='01711888888',
            password='Password123!',
            role=UserRole.CUSTOMER
        )
        self.customer_wallet = Wallet.objects.create(owner=self.customer_user, balance=Decimal('5000.00'))

        # Create second customer
        self.dependent_user = User.objects.create_user(
            username='dependent_tester',
            phone='01711777777',
            password='Password123!',
            role=UserRole.CUSTOMER
        )
        self.dependent_wallet = Wallet.objects.create(owner=self.dependent_user, balance=Decimal('200.00'), is_frozen=True)

        # Create a FamilyPass circle
        self.family_pass = FamilyPass.objects.create(
            owner=self.customer_user,
            member=self.dependent_user,
            limit_amount=Decimal('3000.00'),
            used_amount=Decimal('500.00'),
            expiry_date=timezone.now().date() + timedelta(days=30),
            purpose=FamilyPassPurpose.GROCERY,
            allowed_categories=['Grocery'],
            status=FamilyPassStatus.ACTIVE
        )

        # Create a PurposeFund
        self.purpose_fund = PurposeFund.objects.create(
            owner=self.customer_user,
            name='Groceries & Nutrition',
            category=BusinessCategory.GROCERY,
            allocated_amount=Decimal('8000.00'),
            current_balance=Decimal('4500.00'),
            monthly_budget=Decimal('6000.00')
        )

        # Create a completed transaction in past 24h
        self.txn = Transaction.objects.create(
            sender=self.customer_user,
            receiver=self.dependent_user,
            amount=Decimal('500.00'),
            transaction_type=TransactionType.SEND_MONEY,
            payment_source=PaymentSource.FAMILY_PASS,
            category='Grocery',
            status=TransactionStatus.COMPLETED
        )

    def test_admin_portal_view_for_staff(self):
        """Staff user receives system-wide aggregates and Admin Operations Command Center."""
        self.client.force_login(self.admin_user)
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)

        # Check context variables
        self.assertTrue(response.context['is_admin_portal'])
        platform = response.context['platform_aggregates']
        self.assertGreater(platform['total_float'], Decimal('0.00'))
        self.assertEqual(platform['total_wallets'], 3)
        self.assertEqual(platform['active_wallets'], 2)
        self.assertEqual(platform['frozen_wallets'], 1)
        self.assertEqual(platform['volume_24h'], Decimal('500.00'))

        fp_platform = response.context['familypass_platform']
        self.assertEqual(fp_platform['total_circles'], 1)
        self.assertEqual(fp_platform['active_circles'], 1)
        self.assertEqual(fp_platform['total_dependents'], 1)

        funds_platform = response.context['purpose_funds_platform']
        self.assertEqual(funds_platform['total_funds'], 1)
        self.assertEqual(funds_platform['total_locked'], Decimal('4500.00'))

        # Check HTML content
        content = response.content.decode('utf-8')
        self.assertIn('FundShare Operations Platform', content)
        self.assertIn('Platform Aggregates &amp; Liquidity', content)
        self.assertIn('System-Wide FamilyPass Intelligence', content)
        self.assertIn('Purpose Funds &amp; Locked Savings Intelligence', content)
        self.assertIn('Master User &amp; Wallet Registry (CRUD)', content)
        self.assertIn('admin-nav-btn', content)
        self.assertIn('bg-cyan-500/10 text-cyan-400 border-l-4 border-cyan-400 font-semibold', content)
        self.assertIn('LIVE TELEMETRY ACTIVE', content)
        self.assertIn('ISO_FOREST_V2.0 + NETWORKX GRAPH MULE DETECTOR', content)
        self.assertIn('Export CSV Audit Log', content)
        self.assertIn('chartFloatVelocity', content)
        self.assertIn('chartCapitalAllocation', content)
        self.assertIn('admin-tab-pane', content)
        self.assertIn('switchAdminTab', content)
        self.assertIn('toggleAdminTheme', content)
        self.assertIn('btn-theme-toggle', content)
        # Exactly one centralized theme toggle button exists in the interface
        self.assertEqual(content.count('onclick="toggleAdminTheme()"'), 1)
        # Redundant Trust & Risk Console button removed from hero banner
        banner_actions = content.split('admin-banner-actions')[1].split('</section>')[0]
        self.assertNotIn('Trust &amp; Risk Console', banner_actions)
        self.assertIn('Refresh Telemetry', banner_actions)
        # Profile header does not contain static "Loading..." placeholder
        header_profile = content.split('avatar-btn')[1].split('</button>')[0]
        self.assertNotIn('Loading...', header_profile)
        # CSS Theme Token Architecture verified
        self.assertIn('--admin-bg: #030712', content)
        self.assertIn('--admin-bg: #f8fafc', content)
        self.assertIn('--admin-surface: #0f172a', content)
        self.assertIn('--admin-surface: #ffffff', content)
        # Hero Banner Light Mode Theme verification
        self.assertIn('--admin-banner-bg: linear-gradient(135deg, #ffffff 0%, #f8fafc 100%)', content)
        self.assertNotIn('linear-gradient(135deg, #064E3B', content)
        self.assertIn('btn-refresh-telemetry', content)
        self.assertIn('btn-export-csv', content)
        self.assertNotIn('class="risk-console-header-btn"', content)
        self.assertIn('initAdminSidebarNav', content)
        self.assertIn('sectionConsole', content)
        self.assertIn('Section 5: Trust &amp; Risk Intelligence Console', content)
        self.assertIn('NetworkX 2-Hop Graph Topological Engine &amp; Mule Funnel Canvas', content)
        self.assertIn('Section 2: System-Wide FamilyPass Intelligence &amp; Circles CRUD', content)
        self.assertIn('[data-admin-theme="light"] #sectionFamilyPass .admin-section-title', content)
        self.assertIn('[data-admin-theme="light"] #sectionFamilyPass .admin-section-desc', content)
        self.assertIn('class="limit-bar-wrap" style="display: block; margin-top: 6px;"', content)
        self.assertIn('href="#sectionConsole"', content)
        self.assertIn('href="/admin/" target="_blank"', content)
        self.assertIn('resolveConsoleIncident', content)

    def test_admin_unified_console_tab_view(self):
        """Admin can access unified Trust & Risk Console inside the dashboard."""
        self.client.force_login(self.admin_user)
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        content = response.content.decode('utf-8')
        # Sidebar Console nav button links to internal SPA tab #sectionConsole
        self.assertIn('href="#sectionConsole" data-section="sectionConsole"', content)
        # Sidebar has clean Django Admin link
        self.assertIn('href="/admin/" target="_blank" rel="noopener"', content)
        # Contains the 2-hop NetworkX topology visualizer
        self.assertIn('graph-triage-svg', content)
        # Context contains risk KPIs
        self.assertIn('risk_kpis', response.context)
        self.assertIn('recent_resolved', response.context)

    def test_customer_portal_view_unchanged(self):
        """Regular customer sees consumer dashboard without admin operations."""
        self.client.force_login(self.customer_user)
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context.get('is_admin_portal', False))
        content = response.content.decode('utf-8')
        self.assertIn('Services', content)
        self.assertNotIn('FundShare Operations Platform', content)

    def test_admin_toggle_wallet_freeze(self):
        """Admin can freeze and unfreeze customer wallets."""
        self.client.force_login(self.admin_user)

        # Freeze customer wallet
        res = self.client.post(
            f'/admin/wallet/{self.customer_wallet.id}/toggle-freeze/',
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data['success'])
        self.assertTrue(data['is_frozen'])
        self.customer_wallet.refresh_from_db()
        self.assertTrue(self.customer_wallet.is_frozen)

        # Unfreeze customer wallet
        res2 = self.client.post(
            f'/admin/wallet/{self.customer_wallet.id}/toggle-freeze/',
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )
        self.assertEqual(res2.status_code, 200)
        data2 = res2.json()
        self.assertTrue(data2['success'])
        self.assertFalse(data2['is_frozen'])
        self.customer_wallet.refresh_from_db()
        self.assertFalse(self.customer_wallet.is_frozen)

    def test_admin_toggle_family_pass(self):
        """Admin can revoke or activate a FamilyPass circle."""
        self.client.force_login(self.admin_user)
        res = self.client.post(
            f'/admin/family-pass/{self.family_pass.id}/toggle-status/',
            {'action': 'toggle'},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data['success'])
        self.assertEqual(data['status'], 'REVOKED')
        self.family_pass.refresh_from_db()
        self.assertEqual(self.family_pass.status, FamilyPassStatus.REVOKED)

    def test_admin_toggle_purpose_fund(self):
        """Admin can archive or activate a Purpose Fund."""
        self.client.force_login(self.admin_user)
        res = self.client.post(
            f'/admin/purpose-funds/{self.purpose_fund.id}/toggle-status/',
            {'action': 'toggle'},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data['success'])
        self.assertEqual(data['status'], 'ARCHIVED')
        self.purpose_fund.refresh_from_db()
        self.assertEqual(self.purpose_fund.status, 'ARCHIVED')

    def test_customer_denied_admin_actions(self):
        """Standard customers cannot call administrative endpoints."""
        self.client.force_login(self.customer_user)
        res = self.client.post(
            f'/admin/wallet/{self.customer_wallet.id}/toggle-freeze/',
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )
        # user_passes_test redirects to login URL
        self.assertEqual(res.status_code, 302)
