from django.db import models
from django.utils import timezone
import uuid
from ordenes.models import Proveedor, CustomUser, Venta, OrdenPedido, Referencia

class Categoria(models.Model):
    nombre = models.CharField(max_length=100, unique=True)

    def __str__(self):
        return self.nombre

class Subcategoria(models.Model):
    categoria = models.ForeignKey(Categoria, on_delete=models.CASCADE, related_name='subcategorias')
    nombre = models.CharField(max_length=100)

    def __str__(self):
        return f"{self.nombre} ({self.categoria.nombre})"


class GrupoInventario(models.Model):
    nombre = models.CharField(max_length=150)  # "Comedor 6 puestos"
    descripcion = models.TextField(blank=True)
    activo = models.BooleanField(default=True)
    categoria = models.ForeignKey(Categoria, on_delete=models.SET_NULL, null=True, blank=True)
    subcategoria = models.ForeignKey(Subcategoria, on_delete=models.SET_NULL, null=True, blank=True)
    observacion = models.TextField(blank=True)
    venta = models.ForeignKey(Venta, on_delete=models.SET_NULL, null=True, blank=True, related_name='grupos_inventario')

    def __str__(self):
        return self.nombre


class GrupoInventarioComponente(models.Model):
    grupo = models.ForeignKey(GrupoInventario, on_delete=models.CASCADE, related_name='componentes')
    referencia = models.ForeignKey(Referencia, on_delete=models.CASCADE)
    categoria = models.ForeignKey(Categoria, on_delete=models.SET_NULL, null=True, blank=True)
    subcategoria = models.ForeignKey(Subcategoria, on_delete=models.SET_NULL, null=True, blank=True)
    variacion = models.CharField(max_length=255, blank=True)
    cantidad = models.PositiveIntegerField(default=1)

    def __str__(self):
        return f"{self.cantidad}x {self.referencia.nombre} en {self.grupo.nombre}"


class Sede(models.Model):
    nombre = models.CharField(max_length=100, unique=True)
    descripcion = models.TextField(blank=True, null=True)

    def __str__(self):
        return self.nombre

class Zona(models.Model):
    sede = models.ForeignKey(Sede, on_delete=models.CASCADE, related_name='zonas')
    nombre = models.CharField(max_length=100) # e.g., 'Piso 1', 'Bodega 1'
    descripcion = models.TextField(blank=True, null=True)

    def __str__(self):
        return f"{self.nombre} ({self.sede.nombre})"

class Inventario(models.Model):
    DISPONIBILIDAD_CHOICES = [
        ('exhibicion', 'Exhibición'),
        ('cliente', 'Cliente'),
        ('por_despachar', 'Por Despachar'),
        ('despachado', 'Despachado'),
        ('entregado', 'Entregado'),
        ('por_reparar', 'Por Reparar'),
        ('consignacion', 'Consignación'),
        ('no_venta', 'No a la venta'),
    ]
    ESTADO_FISICO_CHOICES = [
        ('buen_estado', 'Buen estado'),
        ('por_reparar', 'Por reparar'),
        ('por_modificar', 'Por modificar'),
    ]
    id_referencia = models.CharField(max_length=50, primary_key=True)
    referencia = models.ForeignKey(Referencia, on_delete=models.CASCADE, related_name='items_inventario_sum', null=True)
    categoria = models.ForeignKey(Categoria, on_delete=models.SET_NULL, null=True, blank=True)
    subcategoria = models.ForeignKey(Subcategoria, on_delete=models.SET_NULL, null=True, blank=True)
    variacion = models.CharField(max_length=255, blank=True)
    costo_especifico = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    observacion = models.TextField(blank=True, null=True)
    disponibilidad = models.CharField(max_length=50, choices=DISPONIBILIDAD_CHOICES, default='cliente')
    estado_fisico = models.CharField(max_length=50, choices=ESTADO_FISICO_CHOICES, default='buen_estado')
    zona = models.ForeignKey(Zona, on_delete=models.SET_NULL, null=True, blank=True, related_name='items_inventario')
    qr_uuid = models.UUIDField(default=uuid.uuid4, editable=False, unique=True, null=True)
    
    venta = models.ForeignKey(Venta, on_delete=models.SET_NULL, null=True, blank=True, related_name='items_inventario')
    pedido = models.ForeignKey(OrdenPedido, on_delete=models.SET_NULL, null=True, blank=True, related_name='items_inventario')
    factura = models.ForeignKey('FacturaProveedor', on_delete=models.SET_NULL, null=True, blank=True, related_name='items_inventario')
    detalle_factura = models.ForeignKey('DetalleFactura', on_delete=models.SET_NULL, null=True, blank=True, related_name='items_inventario')
    factura_manual = models.CharField(max_length=50, blank=True, null=True)
    grupo = models.ForeignKey('GrupoInventario', on_delete=models.SET_NULL, null=True, blank=True, related_name='items_inventario')
    
    fecha_ingreso = models.DateField(default=timezone.localdate)
    imagen = models.URLField(max_length=500, blank=True, null=True)

    # Tracking de tela (legacy)
    lleva_tela = models.BooleanField(default=False)
    tela_referencia = models.CharField(max_length=100, blank=True, null=True)
    tela_color = models.CharField(max_length=50, blank=True, null=True)
    tela_costo_metro = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    tela_cantidad_metros = models.DecimalField(max_digits=8, decimal_places=2, default=0)

    def __str__(self):
        if self.referencia:
            return f"{self.id_referencia} - {self.referencia.nombre}"
        return self.id_referencia


class ItemInventarioTelaCuero(models.Model):
    """Soporta múltiples telas y/o cueros por ítem de inventario con metraje (m) o decimetraje (dm)."""
    TIPO_CHOICES = [
        ('tela', 'Tela'),
        ('cuero', 'Cuero'),
    ]
    UNIDAD_CHOICES = [
        ('metro', 'Metro (m)'),
        ('decimetro', 'Decímetro (dm)'),
    ]
    inventario = models.ForeignKey(
        Inventario, on_delete=models.CASCADE, related_name='telas_cueros'
    )
    tipo = models.CharField(max_length=20, choices=TIPO_CHOICES, default='tela')
    referencia = models.CharField(max_length=100, blank=True, null=True)
    color = models.CharField(max_length=50, blank=True, null=True)
    unidad_medida = models.CharField(max_length=20, choices=UNIDAD_CHOICES, default='metro')
    costo_unidad = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    cantidad = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    class Meta:
        ordering = ['id']

    @property
    def costo_total(self):
        return float(self.costo_unidad or 0) * float(self.cantidad or 0)

    def __str__(self):
        return f"[{self.get_tipo_display()}] {self.referencia or 'Sin ref'} ({self.color or 'Sin color'}) — {self.cantidad}{self.unidad_medida}"


def _ensure_telas_cueros_table():
    from django.db import connection
    try:
        with connection.cursor() as cursor:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS `suministros_iteminventariotelacuero` (
                  `id` bigint NOT NULL AUTO_INCREMENT,
                  `tipo` varchar(20) NOT NULL DEFAULT 'tela',
                  `referencia` varchar(100) DEFAULT NULL,
                  `color` varchar(50) DEFAULT NULL,
                  `unidad_medida` varchar(20) NOT NULL DEFAULT 'metro',
                  `costo_unidad` decimal(12,2) NOT NULL DEFAULT '0.00',
                  `cantidad` decimal(10,2) NOT NULL DEFAULT '0.00',
                  `inventario_id` varchar(255) NOT NULL,
                  PRIMARY KEY (`id`),
                  KEY `suministros_iteminve_inventario_id_idx` (`inventario_id`),
                  CONSTRAINT `fk_suministros_iteminve_inventario` FOREIGN KEY (`inventario_id`) REFERENCES `suministros_inventario` (`id_referencia`) ON DELETE CASCADE
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
            """)
    except Exception as e:
        pass

try:
    _ensure_telas_cueros_table()
except Exception:
    pass

class CostoAdicionalInventario(models.Model):
    """Costos adicionales por ítem (tela, mano de obra, herrajes, etc.)
    No altera el costo_especifico original proveniente de la factura del proveedor."""
    inventario = models.ForeignKey(
        Inventario, on_delete=models.CASCADE, related_name='costos_adicionales'
    )
    descripcion = models.CharField(max_length=200)  # Ej: "Tela microfibra", "Mano de obra tapizado"
    valor = models.DecimalField(max_digits=12, decimal_places=2)
    fecha = models.DateField(default=timezone.localdate)

    class Meta:
        ordering = ['fecha', 'id']

    def __str__(self):
        return f"{self.descripcion} (${self.valor}) — {self.inventario.id_referencia}"


class FacturaProveedor(models.Model):
    ESTADO_CHOICES = [
        ('pagada', 'Pagada'),
        ('pendiente', 'Pendiente'),
        ('atrasada', 'Atrasada'),
    ]
    id_manual = models.CharField(max_length=50, unique=True)
    valor = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    fecha_factura = models.DateTimeField(default=timezone.now)
    fecha_pago = models.DateField(null=True, blank=True)
    estado = models.CharField(max_length=50, choices=ESTADO_CHOICES, default='pendiente')
    proveedor = models.ForeignKey(Proveedor, on_delete=models.CASCADE, related_name='facturas_suministros', null=True, blank=True)
    observaciones = models.TextField(blank=True, null=True)

    def __str__(self):
        return f"Factura {self.id_manual}"

class DetalleFactura(models.Model):
    factura = models.ForeignKey(FacturaProveedor, on_delete=models.CASCADE, related_name='productos')
    referencia = models.ForeignKey(Referencia, on_delete=models.CASCADE, null=True)
    categoria = models.ForeignKey(Categoria, on_delete=models.SET_NULL, null=True, blank=True)
    subcategoria = models.ForeignKey(Subcategoria, on_delete=models.SET_NULL, null=True, blank=True)
    variacion = models.CharField(max_length=255, blank=True)
    costo = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    observacion = models.TextField(blank=True, null=True)
    disponibilidad = models.CharField(max_length=50, blank=True, null=True)
    estado_fisico = models.CharField(max_length=50, blank=True, null=True, default='nuevo')
    zona = models.ForeignKey(Zona, on_delete=models.SET_NULL, null=True, blank=True)
    venta_id = models.CharField(max_length=50, blank=True, null=True)
    imagen = models.URLField(max_length=500, blank=True, null=True)

    # Tracking de tela
    lleva_tela = models.BooleanField(default=False)
    tela_referencia = models.CharField(max_length=100, blank=True, null=True)
    tela_color = models.CharField(max_length=50, blank=True, null=True)
    tela_costo_metro = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    tela_cantidad_metros = models.DecimalField(max_digits=8, decimal_places=2, default=0)

    def __str__(self):
        return f"Detalle de Factura {self.factura.id_manual}"

class HistorialTraslado(models.Model):
    item_inventario = models.ForeignKey(Inventario, on_delete=models.CASCADE, related_name='historial_traslados')
    zona_origen = models.ForeignKey(Zona, on_delete=models.SET_NULL, null=True, blank=True, related_name='traslados_origen')
    zona_destino = models.ForeignKey(Zona, on_delete=models.SET_NULL, null=True, blank=True, related_name='traslados_destino')
    usuario = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True, blank=True)
    fecha = models.DateTimeField(default=timezone.now)
    observacion = models.TextField(blank=True, null=True)

    def __str__(self):
        return f"Traslado de {self.item_inventario.id_referencia} a {self.zona_destino}"

class RemisionSuministro(models.Model):
    ESTADO_CHOICES = [
        ('creada', 'Creada'),
        ('despachada', 'Despachada'),
        ('finalizada', 'Finalizada'),
        ('anulada', 'Anulada'),
        ('devuelta', 'Devuelta'),
    ]
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    fecha_entrega = models.DateField(null=True, blank=True)
    hora_desde = models.TimeField(null=True, blank=True)
    hora_hasta = models.TimeField(null=True, blank=True)
    direccion_entrega = models.CharField(max_length=255, blank=True)
    ciudad = models.CharField(max_length=100, blank=True)
    barrio = models.CharField(max_length=100, blank=True)
    
    orden_asociada = models.ForeignKey(Venta, on_delete=models.SET_NULL, null=True, blank=True, related_name='remisiones_suministros')
    estado = models.CharField(max_length=50, choices=ESTADO_CHOICES, default='creada')
    
    sin_saldo = models.BooleanField(default=False)
    saldo = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    metodo_pago = models.CharField(max_length=100, blank=True)
    transportador_usuario = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True, blank=True, related_name='remisiones_transportadas')
    transportador = models.CharField(max_length=100, blank=True) # Fallback para "Otro" o nombres externos
    vendedor = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True, blank=True, related_name='remisiones_suministros')
    observacion = models.TextField(blank=True, null=True)
    
    inventario_items = models.ManyToManyField(Inventario, related_name='remisiones_suministros', blank=True)
    nota_transportador = models.TextField(blank=True, null=True)
    costo_entrega = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    def __str__(self):
        return f"Remisión Suministro {self.id}"
