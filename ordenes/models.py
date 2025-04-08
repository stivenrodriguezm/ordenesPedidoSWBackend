from django.db import models
from django.contrib.auth.models import User
from django.contrib.auth.models import AbstractUser
from django.conf import settings

class CustomUser(AbstractUser):
    AUXILIAR = 'AUXILIAR'
    VENDEDOR = 'VENDEDOR'
    ADMINISTRADOR = 'ADMINISTRADOR'

    ROLE_CHOICES = [
        (AUXILIAR, 'Auxiliar'),
        (VENDEDOR, 'Vendedor'),
        (ADMINISTRADOR, 'Administrador'),
    ]

    role = models.CharField(max_length=15, choices=ROLE_CHOICES, default=AUXILIAR)
    first_name = models.CharField(max_length=30, blank=True, null=True)
    last_name = models.CharField(max_length=30, blank=True, null=True)

    def __str__(self):
        return f"{self.username} - {self.role}"
    
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

    TELA_ESTADOS = [
        ('Por pedir', 'Por pedir'),
        ('Sin tela', 'Sin tela'),
        ('Por llegar', 'Por llegar'),
        ('En fabrica', 'En fabrica'),
        ('En Lottus', 'En Lottus'),
    ]

    fecha_creacion = models.DateField(auto_now_add=True)
    fecha_esperada = models.DateField()
    estado = models.CharField(max_length=20, choices=ESTADOS, default='en_proceso')
    notas = models.TextField(null=True, blank=True)
    costo = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, default=0)
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    proveedor = models.ForeignKey(Proveedor, on_delete=models.CASCADE)
    orden_venta = models.CharField(max_length=20, null=True, blank=True)
    tela = models.CharField(max_length=20, choices=TELA_ESTADOS, default='Por pedir')  # Nuevo campo

    def __str__(self):
        return f"Orden {self.id}"

# Modelo para detalles del pedido
class DetallePedido(models.Model):
    cantidad = models.IntegerField()
    especificaciones = models.TextField(null=True)
    referencia = models.ForeignKey(Referencia, on_delete=models.CASCADE, null=True)
    orden = models.ForeignKey(OrdenPedido, related_name='detalles', on_delete=models.CASCADE)

