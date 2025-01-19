from django.db import models
from django.contrib.auth.models import User

# Modelo para referencias asociadas a proveedores
class Referencia(models.Model):
    nombre = models.CharField(max_length=255)
    proveedor = models.ForeignKey('Proveedor', on_delete=models.CASCADE, related_name='referencias')

    def __str__(self):
        return f"{self.nombre} ({self.proveedor.nombre_empresa})"

# Modelo para proveedores
class Proveedor(models.Model):
    nombre_encargado = models.CharField(max_length=100)
    nombre_empresa = models.CharField(max_length=100)
    contacto = models.CharField(max_length=15)

    def __str__(self):
        return self.nombre_empresa

# Modelo para órdenes de pedido
class OrdenPedido(models.Model):
    ESTADOS = [
        ('en_proceso', 'En Proceso'),
        ('recibido', 'Recibido'),
        ('anulado', 'Anulado'),
    ]

    fecha_creacion = models.DateField(auto_now_add=True)
    fecha_esperada = models.DateField()
    estado = models.CharField(max_length=20, choices=ESTADOS, default='en_proceso')
    notas = models.TextField(null=True, blank=True)
    costo = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, default=0)
    usuario = models.ForeignKey(User, on_delete=models.CASCADE)
    proveedor = models.ForeignKey(Proveedor, on_delete=models.CASCADE)
    orden_venta = models.CharField(max_length=20, null=True, blank=True)  # Nuevo campo

    def __str__(self):
        return f"Orden {self.id}"

# Modelo para detalles del pedido
class DetallePedido(models.Model):
    cantidad = models.IntegerField()
    especificaciones = models.TextField(null=True)
    referencia = models.ForeignKey(Referencia, on_delete=models.CASCADE, null=True)
    orden = models.ForeignKey(OrdenPedido, related_name='detalles', on_delete=models.CASCADE)

