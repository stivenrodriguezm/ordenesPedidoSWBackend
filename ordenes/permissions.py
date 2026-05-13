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

class IsAdministradorRole(BasePermission):
    """
    Permite acceso solo a usuarios designados explícitamente con el rol administrador.
    """
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.role == 'administrador')

def check_feature_permission(feature_code):
    """
    Generates a DRF BasePermission class dynamically to strictly check if the 
    authenticated user has the specific feature permission in their RolePermission rules.
    """
    from rest_framework.permissions import BasePermission
    class DynamicFeaturePermission(BasePermission):
        def has_permission(self, request, view):
            if not request.user or not request.user.is_authenticated:
                return False
                
            # Admins bypass role checks
            if request.user.role == 'administrador':
                return True
                
            # For other roles (e.g. vendedor, auxiliar, etc.), look up their dynamic permissions
            from .models import RolePermission
            rp = RolePermission.objects.filter(role=request.user.role).first()
            if rp and feature_code in rp.permissions:
                return True
                
            return False
            
    return DynamicFeaturePermission
