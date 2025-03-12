from django.contrib import admin
from .models import Referencia, Proveedor, OrdenPedido, DetallePedido
from .models import CustomUser 
from django.contrib.auth.admin import UserAdmin

# Registra los modelos en el panel de administración
admin.site.register(Referencia)
admin.site.register(Proveedor)
admin.site.register(OrdenPedido)
admin.site.register(DetallePedido)


class CustomUserAdmin(UserAdmin):
    model = CustomUser
    list_display = ('username', 'email', 'first_name', 'last_name', 'role', 'is_staff', 'is_active',)
    list_filter = ('role', 'is_staff', 'is_active',)

    fieldsets = (
        (None, {'fields': ('username', 'email', 'password')}),
        ('Información Personal', {'fields': ('first_name', 'last_name')}),
        ('Roles', {'fields': ('role',)}),  
        ('Permissions', {'fields': ('is_staff', 'is_active', 'is_superuser', 'groups', 'user_permissions')}),
    )

    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('username', 'email', 'first_name', 'last_name', 'role', 'password1', 'password2', 'is_staff', 'is_active')}
        ),
    )

    search_fields = ('username', 'email', 'first_name', 'last_name')
    ordering = ('username',)

admin.site.register(CustomUser, CustomUserAdmin)