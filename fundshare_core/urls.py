from django.contrib import admin
from django.urls import path, include
from fundshare_app.views.ui_views import IndexView

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/', include('fundshare_app.urls')),
    path('', IndexView.as_view(), name='index'),
]
