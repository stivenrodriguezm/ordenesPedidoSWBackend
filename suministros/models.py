from django.db import models
from django.utils import timezone
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


class Inventario(models.Model):
    DISPONIBILIDAD_CHOICES = [
        ('cliente', 'Cliente'),
        ('exhibicion', 'Exhibición'),
        ('consignacion', 'Consignación'),
        ('por_despachar', 'Por Despachar'),
        ('no_venta', 'No Venta'),
        ('venta', 'Venta'),
    ]
    id_referencia = models.CharField(max_length=50, primary_key=True)
    referencia = models.ForeignKey(Referencia, on_delete=models.CASCADE, related_name='items_inventario_sum', null=True)
    categoria = models.ForeignKey(Categoria, on_delete=models.SET_NULL, null=True, blank=True)
    subcategoria = models.ForeignKey(Subcategoria, on_delete=models.SET_NULL, null=True, blank=True)
    variacion = models.CharField(max_length=255, blank=True)
    costo_especifico = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    observacion = models.TextField(blank=True, null=True)
    disponibilidad = models.CharField(max_length=50, choices=DISPONIBILIDAD_CHOICES, default='cliente')
    
    venta = models.ForeignKey(Venta, on_delete=models.SET_NULL, null=True, blank=True, related_name='items_inventario')
    pedido = models.ForeignKey(OrdenPedido, on_delete=models.SET_NULL, null=True, blank=True, related_name='items_inventario')
    factura = models.ForeignKey('FacturaProveedor', on_delete=models.SET_NULL, null=True, blank=True, related_name='items_inventario')
    detalle_factura = models.ForeignKey('DetalleFactura', on_delete=models.SET_NULL, null=True, blank=True, related_name='items_inventario')
    factura_manual = models.CharField(max_length=50, blank=True, null=True)
    grupo = models.ForeignKey('GrupoInventario', on_delete=models.SET_NULL, null=True, blank=True, related_name='items_inventario')
    
    fecha_ingreso = models.DateField(default=timezone.localdate)
    imagen = models.URLField(max_length=500, blank=True, null=True)

    def __str__(self):
        if self.referencia:
            return f"{self.id_referencia} - {self.referencia.nombre}"
        return self.id_referencia

class FacturaProveedor(models.Model):
    ESTADO_CHOICES = [
        ('pagada', 'Pagada'),
        ('pendiente', 'Pendiente'),
        ('atrasada', 'Atrasada'),
    ]
    id_manual = models.CharField(max_length=50, unique=True)
    valor = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    fecha_factura = models.DateField(default=timezone.localdate)
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
    venta_id = models.CharField(max_length=50, blank=True, null=True)
    imagen = models.URLField(max_length=500, blank=True, null=True)

    def __str__(self):
        return f"Detalle de Factura {self.factura.id_manual}"

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
