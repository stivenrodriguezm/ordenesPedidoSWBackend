from django.contrib import admin

from .models import (
    CategoriaLista, GrupoTela,
    LineaProducto, VarianteProducto, CargoVariante, PrecioVariante,
)

admin.site.register(CategoriaLista)
admin.site.register(GrupoTela)
admin.site.register(LineaProducto)
admin.site.register(VarianteProducto)
admin.site.register(CargoVariante)
admin.site.register(PrecioVariante)
