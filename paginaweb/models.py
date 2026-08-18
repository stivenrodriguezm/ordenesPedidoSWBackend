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


class AsesorPerfil(models.Model):
    """
    Tarjeta digital de un asesor comercial LOTTUS, gestionada desde "Gestión
    Web" (Paleta de Vendedores). Es contenido independiente del sistema de
    usuarios/autenticación (CustomUser) — el admin crea, edita y elimina
    tantas tarjetas como quiera, igual que con los productos web.
    """
    id = models.CharField(max_length=255, primary_key=True, default=uuid.uuid4)
    nombre = models.CharField(max_length=150, verbose_name="Nombre")
    activo = models.BooleanField(default=False, verbose_name="Visible en la página web")
    slug = models.SlugField(max_length=160, unique=True, verbose_name="Slug")
    cargo = models.CharField(max_length=120, blank=True, default="Asesor Comercial", verbose_name="Cargo")
    whatsapp = models.CharField(max_length=20, blank=True, default="", verbose_name="WhatsApp")
    foto = models.CharField(max_length=500, blank=True, default="", verbose_name="Foto")
    bio_corta = models.CharField(max_length=280, blank=True, default="", verbose_name="Bio corta")
    orden = models.PositiveIntegerField(default=0, verbose_name="Orden")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Fecha de Creación")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Última Actualización")

    class Meta:
        db_table = 'paginaweb_asesor_perfil'
        verbose_name = 'Perfil de Asesor'
        verbose_name_plural = 'Perfiles de Asesores'
        ordering = ['orden', 'nombre']

    def __str__(self):
        return f"{self.nombre} ({self.slug})"


class PqrsTicket(models.Model):
    """
    Ticket de PQRS (Petición, Queja, Reclamo, Sugerencia) enviado desde el
    formulario público de "Contacto". Se gestiona desde "Gestión Web" en el
    ERP: el admin puede cambiar el estado libremente y responder — cada
    respuesta queda registrada en `respuestas` y se envía por correo al
    cliente.
    """
    TIPO_CHOICES = [
        ('peticion', 'Petición'),
        ('queja', 'Queja'),
        ('reclamo', 'Reclamo'),
        ('sugerencia', 'Sugerencia'),
    ]
    ESTADO_CHOICES = [
        ('recibido', 'Recibido'),
        ('en_proceso', 'En proceso'),
        ('respondido', 'Respondido'),
        ('cerrado', 'Cerrado'),
    ]

    id = models.CharField(max_length=255, primary_key=True, default=uuid.uuid4)
    tipo = models.CharField(max_length=20, choices=TIPO_CHOICES, default='peticion', verbose_name="Tipo de PQRS")
    asunto = models.CharField(max_length=150, blank=True, default="", verbose_name="Asunto")
    nombre = models.CharField(max_length=150, verbose_name="Nombre")
    email = models.EmailField(verbose_name="Correo electrónico")
    telefono = models.CharField(max_length=30, blank=True, default="", verbose_name="Teléfono")
    mensaje = models.TextField(verbose_name="Mensaje")
    estado = models.CharField(max_length=20, choices=ESTADO_CHOICES, default='recibido', verbose_name="Estado")
    # Lista de respuestas: [{"mensaje": str, "fecha": iso str, "autor": str}, ...]
    respuestas = models.JSONField(default=list, blank=True, verbose_name="Respuestas")
    respondido_por = models.CharField(max_length=150, blank=True, default="", verbose_name="Respondido por")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Fecha de Creación")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Última Actualización")

    class Meta:
        db_table = 'paginaweb_pqrs_ticket'
        verbose_name = 'Ticket PQRS'
        verbose_name_plural = 'Tickets PQRS'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.radicado} — {self.nombre} ({self.get_tipo_display()})"

    @property
    def radicado(self):
        # Referencia corta y legible para el cliente (no expone el UUID completo).
        return f"PQRS-{str(self.id)[:8].upper()}"
