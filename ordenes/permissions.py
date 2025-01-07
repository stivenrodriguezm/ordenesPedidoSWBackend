from rest_framework.permissions import BasePermission

class IsAdmin(BasePermission):
    """
    Permite acceso solo a los administradores (is_staff=True).
    """
    def has_permission(self, request, view):
        return request.user.is_staff

class IsVendedor(BasePermission):
    """
    Permite acceso solo a vendedores (is_staff=False).
    """
    def has_permission(self, request, view):
        return not request.user.is_staff
