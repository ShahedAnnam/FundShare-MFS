from django.shortcuts import render, redirect
from django.views.generic import TemplateView
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.mixins import LoginRequiredMixin
from django.views import View
from django.contrib import messages


class IndexView(LoginRequiredMixin, TemplateView):
    """Main SPA dashboard — requires login."""
    template_name = "index.html"
    login_url = '/login/'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['user'] = self.request.user
        ctx['user_role'] = self.request.user.role
        return ctx


class LoginPageView(View):
    """Standalone login page with beautiful MFS UI."""
    def get(self, request):
        if request.user.is_authenticated:
            return redirect('/')
        return render(request, 'login.html', {'error': None})

    def post(self, request):
        username = request.POST.get('username', '').strip()
        password = request.POST.get('password', '').strip()

        if not username or not password:
            return render(request, 'login.html', {'error': 'Please enter your phone number/username and PIN.'})

        # Try username first, then phone
        from django.contrib.auth import get_user_model
        User = get_user_model()

        from fundshare_app.services.phone_utils import find_user_by_phone_or_username
        user_obj = find_user_by_phone_or_username(username)
        if user_obj:
            user = authenticate(request, username=user_obj.username, password=password)
        else:
            user = authenticate(request, username=username, password=password)

        if user is not None:
            login(request, user)
            next_url = request.GET.get('next', '/')
            return redirect(next_url)
        else:
            return render(request, 'login.html', {
                'error': 'Invalid phone number or PIN. Please try again.',
                'username': username
            })


class LogoutPageView(View):
    def post(self, request):
        logout(request)
        return redirect('/login/')

    def get(self, request):
        logout(request)
        return redirect('/login/')
