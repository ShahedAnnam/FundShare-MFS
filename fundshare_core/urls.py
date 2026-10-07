from django.contrib import admin
from django.urls import path, include
from fundshare_app.views.ui_views import IndexView, LoginPageView, LogoutPageView, RegistrationPageView

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/', include('fundshare_app.urls')),
    path('login/', LoginPageView.as_view(), name='login'),
    path('register/', RegistrationPageView.as_view(), name='register'),
    path('logout/', LogoutPageView.as_view(), name='logout'),
    path('', IndexView.as_view(), name='index'),
]
