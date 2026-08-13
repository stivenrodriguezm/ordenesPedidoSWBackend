import re
from django.conf import settings
from rest_framework import serializers
from .models import PaginawebProducto, PaginawebSetting, AsesorPerfil

CATEGORIES = [
    {"slug": "sofas", "name": "Sofás & Módulos", "icon": "sofa"},
    {"slug": "mesas", "name": "Mesas & Comedores", "icon": "table"},
    {"slug": "camas", "name": "Camas & Cabeceros", "icon": "bed"},
    {"slug": "poltronas", "name": "Poltronas & Sillas", "icon": "armchair"},
    {"slug": "accesorios", "name": "Complementos", "icon": "sparkles"},
    {"slug": "sora", "name": "Colección Sora", "icon": "star"},
]

class PaginawebProductoSerializer(serializers.ModelSerializer):
    # Opcional: PaginawebProductoAdminViewSet.perform_create genera el slug
    # automáticamente a partir del nombre cuando no se envía uno explícito —
    # si este campo fuera required=True (el default heredado del SlugField
    # del modelo, que no es blank), la validación rechazaría la creación
    # antes de que ese auto-generado pudiera ejecutarse.
    slug = serializers.SlugField(required=False, allow_blank=True)
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


WHATSAPP_RE = re.compile(r'^\d{10,15}$')


def validate_whatsapp_number(value):
    value = (value or '').strip()
    if not value:
        return value
    if not WHATSAPP_RE.match(value):
        raise serializers.ValidationError(
            "El WhatsApp debe contener solo dígitos con indicativo de país (10 a 15 dígitos), ej: 573001234567."
        )
    return value


def validate_foto_path(value):
    value = (value or '').strip()
    if not value:
        return value
    if not value.startswith('/media/asesores/'):
        raise serializers.ValidationError("La foto debe subirse mediante el cargador de asesores.")
    return value


class AsesorPublicSerializer(serializers.ModelSerializer):
    """
    Representación 100% pública de una tarjeta de asesor.
    """
    bioCorta = serializers.CharField(source='bio_corta')
    whatsappUrl = serializers.SerializerMethodField()
    profileUrl = serializers.SerializerMethodField()
    qrUrl = serializers.SerializerMethodField()

    class Meta:
        model = AsesorPerfil
        fields = ['slug', 'nombre', 'cargo', 'foto', 'bioCorta', 'whatsappUrl', 'profileUrl', 'qrUrl']

    def get_whatsappUrl(self, obj):
        if not obj.whatsapp:
            return None
        return f"https://wa.me/{obj.whatsapp}"

    def get_profileUrl(self, obj):
        return f"{settings.PUBLIC_SITE_URL}/asesor/{obj.slug}"

    def get_qrUrl(self, obj):
        return f"{settings.PUBLIC_SITE_URL}/api/asesores/{obj.slug}/qr.png"


class AsesorAdminSerializer(serializers.ModelSerializer):
    """
    Representación para "Paleta de Vendedores" (Gestión Web). Contenido
    administrado libremente por el admin, igual que los productos web —
    sin ninguna relación con el modelo de usuarios/autenticación.
    """
    bioCorta = serializers.CharField(source='bio_corta', required=False, allow_blank=True)
    profileUrl = serializers.SerializerMethodField()
    createdAt = serializers.DateTimeField(source='created_at', read_only=True)
    updatedAt = serializers.DateTimeField(source='updated_at', read_only=True)

    class Meta:
        model = AsesorPerfil
        fields = [
            'id', 'nombre', 'activo', 'slug', 'cargo', 'whatsapp', 'foto',
            'bioCorta', 'bio_corta', 'orden', 'profileUrl',
            'createdAt', 'created_at', 'updatedAt', 'updated_at',
        ]
        read_only_fields = ['id', 'slug']

    def get_profileUrl(self, obj):
        return f"{settings.PUBLIC_SITE_URL}/asesor/{obj.slug}"

    def validate_nombre(self, value):
        value = (value or '').strip()
        if not value:
            raise serializers.ValidationError("El nombre es obligatorio.")
        return value

    def validate_whatsapp(self, value):
        return validate_whatsapp_number(value)

    def validate_foto(self, value):
        return validate_foto_path(value)
