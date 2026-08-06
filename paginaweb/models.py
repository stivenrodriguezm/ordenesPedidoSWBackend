from django.db import models
import uuid

class PaginawebProducto(models.Model):
    id = models.CharField(max_length=255, primary_key=True, default=uuid.uuid4)
    name = models.CharField(max_length=255, verbose_name="Nombre")
    slug = models.SlugField(max_length=255, unique=True, verbose_name="Slug")
    category = models.CharField(max_length=100, blank=True, default="", verbose_name="Categoría")
    price = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name="Precio")
    old_price = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True, verbose_name="Precio Anterior")
    price_range = models.JSONField(null=True, blank=True, verbose_name="Rango de Precios")
    variants = models.JSONField(default=list, blank=True, verbose_name="Variaciones")
    badge = models.CharField(max_length=100, null=True, blank=True, verbose_name="Etiqueta / Badge")
    short_description = models.TextField(blank=True, default="", verbose_name="Descripción Corta")
    description = models.TextField(blank=True, default="", verbose_name="Descripción Larga")
    materials = models.TextField(blank=True, default="", verbose_name="Materiales")
    dimensions = models.TextField(blank=True, default="", verbose_name="Dimensiones")
    features = models.JSONField(default=list, blank=True, verbose_name="Características")
    images = models.JSONField(default=list, blank=True, verbose_name="Imágenes")
    featured = models.BooleanField(default=False, verbose_name="Destacado")
    active = models.BooleanField(default=True, verbose_name="Activo")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Fecha de Creación")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Última Actualización")

    class Meta:
        db_table = 'paginaweb_producto'
        verbose_name = 'Producto Web'
        verbose_name_plural = 'Productos Web'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.name} ({self.category})"


class PaginawebSetting(models.Model):
    key = models.CharField(max_length=100, primary_key=True, verbose_name="Clave")
    value = models.JSONField(null=True, blank=True, verbose_name="Valor")

    class Meta:
        db_table = 'paginaweb_setting'
        verbose_name = 'Configuración Web'
        verbose_name_plural = 'Configuraciones Web'

    def __str__(self):
        return self.key
