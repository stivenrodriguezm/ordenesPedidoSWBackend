from django.db import models
from django.contrib.auth.models import AbstractUser
from django.utils import timezone

class CustomUser(AbstractUser):
    ROLE_CHOICES = (
        ('vendedor', 'Vendedor'),
        ('administrador', 'Administrador'),
    )
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='vendedor')

class Proveedor(models.Model):
    nombre_empresa = models.CharField(max_length=255, unique=True, default='N/A')
    nombre_contacto = models.CharField(max_length=255, default='N/A')
    nit = models.CharField(max_length=20, unique=True, null=True, blank=True)
    direccion = models.CharField(max_length=255, default='N/A')
    ciudad = models.CharField(max_length=100, default='N/A')
    telefono = models.CharField(max_length=20, default='0')
    correo = models.EmailField(default='na@na.com')

    def __str__(self):
        return self.nombre_empresa

class Referencia(models.Model):
    proveedor = models.ForeignKey(Proveedor, on_delete=models.CASCADE, related_name='referencias')
    nombre = models.CharField(max_length=255)
    descripcion = models.TextField(blank=True, null=True)

    def __str__(self):
        return f'{self.nombre} ({self.proveedor.nombre_empresa})'

class Cliente(models.Model):
    nombre = models.CharField(max_length=255, db_index=True)
    cedula = models.CharField(max_length=20, unique=True, db_index=True)
    correo = models.EmailField(blank=True, null=True)
    direccion = models.CharField(max_length=255, blank=True, null=True)
    ciudad = models.CharField(max_length=100, blank=True, null=True)
    telefono1 = models.CharField(max_length=20)
    telefono2 = models.CharField(max_length=20, blank=True, null=True)

    def __str__(self):
        return self.nombre

class Venta(models.Model):
    ESTADO_CHOICES = [
        ('activa', 'Activa'),
        ('finalizada', 'Finalizada'),
        ('anulada', 'Anulada'),
    ]
    id = models.PositiveIntegerField(primary_key=True)
    cliente = models.ForeignKey(Cliente, on_delete=models.CASCADE, related_name='ventas')
    vendedor = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='ventas')
    valor_total = models.DecimalField(max_digits=10, decimal_places=2)
    abono = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    saldo = models.DecimalField(max_digits=10, decimal_places=2)
    fecha_venta = models.DateField(default=timezone.now, db_index=True)
    fecha_entrega = models.DateField(db_index=True)
    estado = models.CharField(max_length=20, choices=ESTADO_CHOICES, default='activa', db_index=True)
    estado_pedidos = models.BooleanField(default=False)

    def __str__(self):
        return f"Venta {self.id} - {self.cliente.nombre}"

class OrdenPedido(models.Model):
    ESTADO_CHOICES = [
        ('pendiente', 'Pendiente'),
        ('en_proceso', 'En Proceso'),
        ('finalizado', 'Finalizado'),
    ]
    proveedor = models.ForeignKey(Proveedor, on_delete=models.CASCADE, related_name='ordenes')
    usuario = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='ordenes')
    venta = models.ForeignKey(Venta, on_delete=models.CASCADE, related_name='ordenes_pedido', null=True, blank=True)
    fecha_creacion = models.DateField(auto_now_add=True, db_index=True)
    fecha_esperada = models.DateField()
    estado = models.CharField(max_length=20, choices=ESTADO_CHOICES, default='pendiente', db_index=True)
    observacion = models.TextField(blank=True, null=True)
    tela = models.CharField(max_length=255, blank=True, null=True)
    costo = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    orden_venta = models.CharField(max_length=50, blank=True, null=True)

    def __str__(self):
        return f"Orden {self.id} para {self.proveedor.nombre_empresa}"

class DetallePedido(models.Model):
    orden = models.ForeignKey(OrdenPedido, on_delete=models.CASCADE, related_name='detalles')
    referencia = models.ForeignKey(Referencia, on_delete=models.CASCADE)
    cantidad = models.PositiveIntegerField()
    especificaciones = models.TextField()

    def __str__(self):
        return f"Detalle de Orden {self.orden.id} - Ref: {self.referencia.nombre}"

class ObservacionVenta(models.Model):
    venta = models.ForeignKey(Venta, on_delete=models.CASCADE, related_name='observaciones')
    autor = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True)
    texto = models.TextField()
    fecha = models.DateTimeField(auto_now_add=True)

class ObservacionCliente(models.Model):
    cliente = models.ForeignKey(Cliente, on_delete=models.CASCADE, related_name='observaciones')
    autor = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True)
    texto = models.TextField()
    fecha = models.DateTimeField(auto_now_add=True)

class Remision(models.Model):
    venta = models.ForeignKey(Venta, on_delete=models.CASCADE, related_name='remisiones')
    codigo = models.CharField(max_length=50, unique=True)
    fecha = models.DateField(default=timezone.now)
    descripcion = models.TextField()

class ReciboCaja(models.Model):
    MEDIO_PAGO_CHOICES = [
        ('Efectivo', 'Efectivo'),
        ('Transferencia', 'Transferencia'),
    ]
    ESTADO_CHOICES = [
        ('Pendiente', 'Pendiente'),
        ('Confirmado', 'Confirmado'),
    ]
    venta = models.ForeignKey(Venta, on_delete=models.CASCADE, related_name='recibos')
    fecha = models.DateField(default=timezone.now, db_index=True)
    valor = models.DecimalField(max_digits=10, decimal_places=2)
    metodo_pago = models.CharField(max_length=20, choices=MEDIO_PAGO_CHOICES, db_index=True)
    estado = models.CharField(max_length=20, choices=ESTADO_CHOICES, default='Pendiente', db_index=True)

class Caja(models.Model):
    TIPO_CHOICES = [
        ('ingreso', 'Ingreso'),
        ('egreso', 'Egreso'),
        ('cierre', 'Cierre'),
    ]
    usuario = models.ForeignKey(CustomUser, on_delete=models.CASCADE)
    fecha_hora = models.DateTimeField(default=timezone.now, db_index=True)
    concepto = models.CharField(max_length=255)
    tipo = models.CharField(max_length=10, choices=TIPO_CHOICES)
    valor = models.DecimalField(max_digits=10, decimal_places=2)
    total_acumulado = models.DecimalField(max_digits=12, decimal_places=2)

class ComprobanteEgreso(models.Model):
    MEDIO_PAGO_CHOICES = [
        ('Efectivo', 'Efectivo'),
        ('Transferencia', 'Transferencia'),
    ]
    proveedor = models.ForeignKey(Proveedor, on_delete=models.CASCADE)
    fecha = models.DateField(default=timezone.now, db_index=True)
    valor = models.DecimalField(max_digits=10, decimal_places=2)
    medio_pago = models.CharField(max_length=20, choices=MEDIO_PAGO_CHOICES, db_index=True)
    nota = models.TextField(blank=True, null=True)
