import django_filters
from .models import Caja

class CajaFilter(django_filters.FilterSet):
    fecha_inicio = django_filters.DateFilter(field_name="fecha", lookup_expr='gte', label="Fecha Inicio")
    fecha_fin = django_filters.DateFilter(field_name="fecha", lookup_expr='lte', label="Fecha Fin")

    class Meta:
        model = Caja
        fields = ['tipo', 'fecha_inicio', 'fecha_fin']
