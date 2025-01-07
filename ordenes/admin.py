from django.contrib import admin
from .models import Referencia, Proveedor, OrdenPedido, DetallePedido

# Registra los modelos en el panel de administración
admin.site.register(Referencia)
admin.site.register(Proveedor)
admin.site.register(OrdenPedido)
admin.site.register(DetallePedido)