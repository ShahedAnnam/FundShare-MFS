from django.contrib.admin import AdminSite


class FundShareAdminSite(AdminSite):
    def has_permission(self, request):
        from fundshare_app.models import UserRole
        return super().has_permission(request) and (request.user.is_superuser or request.user.role == UserRole.ADMIN)
