from django import forms
from django.contrib.auth import password_validation
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from fundshare_app.models import User, UserRole, Wallet
from fundshare_app.services.phone_utils import normalize_phone, is_valid_bd_phone, get_phone_variations
from fundshare_app.services.security_service import SecurityError


class RegistrationForm(forms.Form):
    full_name = forms.CharField(label='Full name', max_length=150)
    username = forms.RegexField(
        label='Username', regex=r'^[A-Za-z][A-Za-z0-9_.-]*$', min_length=3, max_length=150, strip=True,
        error_messages={'invalid': 'Start with a letter and use only letters, numbers, dots, underscores or hyphens.'},
    )
    phone = forms.CharField(label='Phone number', max_length=40)
    password1 = forms.CharField(label='Password', strip=False, max_length=128, widget=forms.PasswordInput)
    password2 = forms.CharField(label='Confirm password', strip=False, max_length=128, widget=forms.PasswordInput)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        autocomplete = {'full_name': 'name', 'username': 'username', 'phone': 'tel'}
        for name, field in self.fields.items():
            field.widget.attrs.update({
                'class': 'form-control registration-input',
                'autocomplete': autocomplete.get(name, 'new-password'),
                'aria-describedby': f'id_{name}_errors',
            })
        self.fields['full_name'].widget.attrs['autofocus'] = True
        self.fields['username'].widget.attrs['placeholder'] = 'Choose a username'
        self.fields['phone'].widget.attrs.update({'placeholder': '01XXXXXXXXX', 'inputmode': 'tel'})
        self.fields['password1'].widget.attrs['placeholder'] = 'Create a strong password'

    def clean_username(self):
        username = self.cleaned_data['username'].lower()
        if User.objects.filter(username__iexact=username).exists():
            raise ValidationError('This username is already registered. Choose another one.')
        return username

    def clean_phone(self):
        phone = normalize_phone(self.cleaned_data['phone'])
        if not is_valid_bd_phone(phone):
            raise ValidationError('Enter a valid Bangladesh mobile number, such as 01712345678.')
        if User.objects.filter(phone__in=get_phone_variations(phone)).exists():
            raise ValidationError('This phone number is already registered. Sign in instead.')
        return phone

    def clean(self):
        cleaned = super().clean()
        password = cleaned.get('password1')
        confirmation = cleaned.get('password2')
        if password and confirmation and password != confirmation:
            self.add_error('password2', 'The passwords do not match.')
        if password:
            candidate = User(username=cleaned.get('username', ''), full_name=cleaned.get('full_name', ''))
            try:
                password_validation.validate_password(password, user=candidate)
            except ValidationError as exc:
                self.add_error('password1', exc)
        return cleaned

    def save(self):
        if not self.is_valid():
            raise ValueError('Registration details must be valid before saving.')
        try:
            with transaction.atomic():
                user = User.objects.create_user(
                    username=self.cleaned_data['username'],
                    full_name=self.cleaned_data['full_name'],
                    phone=self.cleaned_data['phone'],
                    password=self.cleaned_data['password1'],
                    role=UserRole.CUSTOMER, is_staff=False, is_superuser=False,
                )
                Wallet.objects.create(owner=user)
        except IntegrityError as exc:
            # Another signup may have claimed the same identifier after validation.
            if not User.objects.filter(username__iexact=self.cleaned_data['username']).exists() and not User.objects.filter(phone__in=get_phone_variations(self.cleaned_data['phone'])).exists():
                raise
            raise SecurityError(
                'This username or phone number is already registered. Sign in or choose different details.',
                'REGISTRATION_CONFLICT', 409,
            ) from exc
        return user
