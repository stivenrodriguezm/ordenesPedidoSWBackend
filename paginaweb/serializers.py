from rest_framework import serializers
from .models import PaginawebProducto, PaginawebSetting

CATEGORIES = [
    {"slug": "sofas", "name": "Sofás & Módulos", "icon": "sofa"},
    {"slug": "mesas", "name": "Mesas & Comedores", "icon": "table"},
    {"slug": "camas", "name": "Camas & Cabeceros", "icon": "bed"},
    {"slug": "poltronas", "name": "Poltronas & Sillas", "icon": "armchair"},
    {"slug": "accesorios", "name": "Complementos", "icon": "sparkles"},
    {"slug": "sora", "name": "Colección Sora", "icon": "star"},
]

class PaginawebProductoSerializer(serializers.ModelSerializer):
    oldPrice = serializers.DecimalField(source='old_price', max_digits=12, decimal_places=2, required=False, allow_null=True)
    priceRange = serializers.JSONField(source='price_range', required=False, allow_null=True)
    shortDescription = serializers.CharField(source='short_description', required=False, allow_blank=True)
    createdAt = serializers.DateTimeField(source='created_at', read_only=True)
    updatedAt = serializers.DateTimeField(source='updated_at', read_only=True)

    class Meta:
        model = PaginawebProducto
        fields = [
            'id', 'name', 'slug', 'category', 'price', 'oldPrice', 'old_price',
            'priceRange', 'price_range', 'variants', 'badge', 'shortDescription',
            'short_description', 'description', 'materials', 'dimensions',
            'features', 'images', 'featured', 'active', 'createdAt', 'created_at',
            'updatedAt', 'updated_at'
        ]

    def to_representation(self, instance):
        ret = super().to_representation(instance)
        # Asegurar tipos adecuados
        ret['price'] = float(instance.price) if instance.price is not None else 0.0
        ret['oldPrice'] = float(instance.old_price) if instance.old_price is not None else None
        ret['old_price'] = ret['oldPrice']
        return ret


class PaginawebSettingSerializer(serializers.ModelSerializer):
    class Meta:
        model = PaginawebSetting
        fields = ['key', 'value']
