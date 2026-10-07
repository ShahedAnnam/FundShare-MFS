from django.shortcuts import render, redirect
from django.views.generic import TemplateView
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.mixins import LoginRequiredMixin
from django.views import View
from django.contrib import messages
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.csrf import ensure_csrf_cookie
from django.utils.decorators import method_decorator
from fundshare_app.forms import RegistrationForm
from fundshare_app.ml.demo_qa import DEMO_QA
from fundshare_app.services.security_service import check_login_rate, record_login_failure, clear_login_failures, check_registration_rate, SecurityError


@method_decorator(ensure_csrf_cookie, name='dispatch')
class IndexView(LoginRequiredMixin, TemplateView):
    """Main SPA dashboard — requires login."""
    template_name = "index.html"
    login_url = '/login/'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['demo_qa'] = DEMO_QA
        if self.request.user.is_authenticated:
            ctx['user'] = self.request.user
            ctx['user_role'] = self.request.user.effective_role
            ctx['user_role_display'] = self.request.user.get_effective_role_display()
        return ctx


class LoginPageView(View):
    """Standalone login page with beautiful MFS UI."""
    def get(self, request):
        if request.user.is_authenticated:
            return redirect('/')
        return render(request, 'login.html', {'error': None})

    def post(self, request):
        username = request.POST.get('username', '').strip()
        password = request.POST.get('password', '')

        if not username or not password:
            return render(request, 'login.html', {'error': 'Please enter your phone number/username and password.'})

        # Try username first, then phone
        from django.contrib.auth import get_user_model
        User = get_user_model()

        from fundshare_app.services.phone_utils import find_user_by_phone_or_username
        user_obj = find_user_by_phone_or_username(username)
        try:
            check_login_rate(request, user_obj.username if user_obj else username)
        except SecurityError as exc:
            return render(request, 'login.html', {'error': exc.message, 'username': username}, status=429)
        if user_obj:
            user = authenticate(request, username=user_obj.username, password=password)
        else:
            user = authenticate(request, username=username, password=password)

        if user is not None:
            clear_login_failures(request, user.username)
            login(request, user)
            next_url = request.GET.get('next', '/')
            if not url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
                next_url = '/'
            return redirect(next_url)
        else:
            record_login_failure(request, user_obj.username if user_obj else username)
            return render(request, 'login.html', {
                'error': 'Invalid phone number or password. Please try again.',
                'username': username
            })


class RegistrationPageView(View):
    def get(self, request):
        if request.user.is_authenticated:
            return redirect('/')
        return render(request, 'register.html', {'form': RegistrationForm()})

    def post(self, request):
        if request.user.is_authenticated:
            return redirect('/')
        form = RegistrationForm(request.POST)
        try:
            check_registration_rate(request)
            if form.is_valid():
                user = form.save()
                login(request, user, backend='django.contrib.auth.backends.ModelBackend')
                return redirect('/')
        except SecurityError as exc:
            return render(request, 'register.html', {'form': form, 'error': exc.message}, status=exc.status)
        return render(request, 'register.html', {'form': form}, status=400)


class LogoutPageView(View):
    def post(self, request):
        logout(request)
        return redirect('/login/')
