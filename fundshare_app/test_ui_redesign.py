from collections import Counter
from html.parser import HTMLParser

from django.conf import settings
from django.test import TestCase

from fundshare_app.models import User, Wallet


class PageElements(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.ids = []
        self.buttons = []
        self.current_button = None
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if 'id' in attributes:
            self.ids.append(attributes['id'])
        if tag == 'button':
            self.current_button = {'attrs': attributes, 'text': ''}

    def handle_data(self, data):
        if self.current_button is not None:
            self.current_button['text'] += data

    def handle_endtag(self, tag):
        if tag == 'button' and self.current_button is not None:
            self.buttons.append(self.current_button)
            self.current_button = None


class RedesignedUITests(TestCase):
    def setUp(self):
        self.customer = User.objects.create_user(username='ui-customer', phone='01740000001', password='QuietRiver!53927')
        Wallet.objects.create(owner=self.customer)
        self.client.force_login(self.customer)

    def test_dashboard_preserves_transaction_and_security_dom_contracts(self):
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        elements = PageElements(response.content.decode())
        expected = ['sendReceiver', 'sendAmount', 'fundRecipient', 'editFundRecipient', 'fpRecipient', 'payAmount', 'billAmount', 'rechargeAmount', 'cashOutAmount', 'transactionPinDialog', 'transactionPinInput', 'changePasswordModal', 'contactBookModal', 'notifPanel']
        for identifier in expected:
            self.assertIn(identifier, elements.ids)

    def test_composed_views_do_not_duplicate_identifiers(self):
        elements = PageElements(self.client.get('/').content.decode())
        duplicates = [identifier for identifier, count in Counter(elements.ids).items() if count > 1]
        self.assertEqual(duplicates, [])
        for view in ['home', 'account', 'funds', 'payments', 'familypass', 'history', 'ai', 'more']:
            self.assertIn(f'tab-{view}', elements.ids)
            self.assertIn(f'nav-{view}', elements.ids)

    def test_future_features_are_disabled_and_have_no_transaction_handlers(self):
        elements = PageElements(self.client.get('/').content.decode())
        future = [button for button in elements.buttons if 'Coming Soon' in button['text']]
        self.assertEqual(len(future), 6)
        for button in future:
            self.assertIn('disabled', button['attrs'])
            self.assertNotIn('onclick', button['attrs'])
        self.assertTrue(any('Request Money' in button['text'] for button in future))

    def test_family_pass_remains_a_primary_navigation_item_and_service(self):
        response = self.client.get('/')
        self.assertContains(response, 'id="nav-familypass"')
        self.assertContains(response, 'family-service customer-only')
        self.assertContains(response, 'id="fpOwnerView"')
        self.assertContains(response, 'id="fpRecipientView"')

    def test_icon_library_brand_asset_and_ui_styles_are_local(self):
        response = self.client.get('/')
        for asset in ['ui.css', 'ui.js', 'brand-mark.png', 'vendor/lucide-0.468.0.min.js']:
            self.assertContains(response, '/static/' + asset)
            self.assertTrue((settings.BASE_DIR / 'static' / asset).is_file())
        self.assertNotContains(response, 'unpkg.com')

    def test_login_keeps_password_and_csrf_contract_and_links_registration(self):
        self.client.logout()
        response = self.client.get('/login/')
        self.assertContains(response, 'name="username"')
        self.assertContains(response, 'name="password"')
        self.assertContains(response, 'name="csrfmiddlewaretoken"')
        self.assertContains(response, 'href="/register/"')
        self.assertContains(response, '/static/auth.css')
        self.assertNotContains(response, 'Instant QR payments')

    def test_registration_inherits_the_authentication_theme(self):
        self.client.logout()
        response = self.client.get('/register/')
        self.assertContains(response, 'Create your account')
        self.assertContains(response, '/static/auth.css')
        self.assertContains(response, 'name="phone"')
        self.assertContains(response, 'name="password1"')
        self.assertContains(response, 'href="/login/"')
