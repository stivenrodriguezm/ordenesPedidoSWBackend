"""Preparación bancaria. Exportar un lote nunca confirma un pago."""
from django.conf import settings
from django.db import models
from django.db.models import Q


class EmpleadoPago(models.Model):
    nombre = models.CharField(max_length=160)
    usuario = models.OneToOneField(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name='empleado_pagos')
    pago_mensual = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    activo = models.BooleanField(default=True)

    class Meta:
        ordering = ['nombre', 'id']
        constraints = [models.CheckConstraint(check=Q(pago_mensual__gte=0), name='pago_empleado_no_negativo')]


class CuentaBancaria(models.Model):
    proveedor = models.ForeignKey('ordenes.Proveedor', null=True, blank=True, on_delete=models.PROTECT, related_name='cuentas_bancarias')
    proveedor_tela = models.ForeignKey('ordenes.ProveedorTela', null=True, blank=True, on_delete=models.PROTECT, related_name='cuentas_bancarias')
    empleado = models.ForeignKey(EmpleadoPago, null=True, blank=True, on_delete=models.PROTECT, related_name='cuentas')
    empresa = models.BooleanField(default=False)
    alias = models.CharField(max_length=80, blank=True)
    banco = models.CharField(max_length=6)
    tipo = models.CharField(max_length=2, choices=[('CA', 'Ahorros'), ('CC', 'Corriente'), ('DP', 'DaviPlata'), ('TP', 'Tarjeta prepago'), ('DE', 'Depósito electrónico')])
    numero = models.CharField(max_length=16)
    tipo_documento = models.CharField(max_length=2)
    documento = models.CharField(max_length=16)
    nombres = models.CharField(max_length=40)
    apellidos = models.CharField(max_length=40)
    principal = models.BooleanField(default=False)
    activa = models.BooleanField(default=True)
    revision = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['-principal', 'id']
        constraints = [models.CheckConstraint(check=(
            Q(empresa=True, proveedor__isnull=True, proveedor_tela__isnull=True, empleado__isnull=True) |
            Q(empresa=False, proveedor__isnull=False, proveedor_tela__isnull=True, empleado__isnull=True) |
            Q(empresa=False, proveedor__isnull=True, proveedor_tela__isnull=False, empleado__isnull=True) |
            Q(empresa=False, proveedor__isnull=True, proveedor_tela__isnull=True, empleado__isnull=False)
        ), name='cuenta_un_solo_titular')]


class LotePago(models.Model):
    tipo = models.CharField(max_length=12, choices=[('proveedores', 'Proveedores'), ('nomina', 'Nómina')])
    nombre = models.CharField(max_length=120)
    banco_origen = models.CharField(max_length=20, default='davivienda', choices=[('davivienda', 'Davivienda'), ('bancolombia', 'Bancolombia')])
    cuenta_origen = models.ForeignKey(CuentaBancaria, null=True, blank=True, on_delete=models.PROTECT, related_name='+')
    fecha_pago = models.DateField()
    estado = models.CharField(max_length=12, default='borrador', choices=[('borrador', 'Borrador'), ('exportado', 'Archivo generado'), ('anulado', 'Anulado')], db_index=True)
    # Una sola preparación por mes o cierre. Los reintentos devuelven el mismo lote.
    clave_nomina = models.CharField(max_length=60, unique=True, null=True, blank=True)
    revision = models.PositiveIntegerField(default=0)
    creado_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT, related_name='+')
    creado_en = models.DateTimeField(auto_now_add=True)
    exportado_en = models.DateTimeField(null=True, blank=True)
    origen_snapshot = models.JSONField(default=dict, blank=True)
    motivo_anulacion = models.CharField(max_length=300, blank=True)
    # Archivo original inmutable: volver a descargar no regenera ni duplica CE.
    archivo = models.BinaryField(null=True, editable=False)
    archivo_sha256 = models.CharField(max_length=64, blank=True)

    class Meta:
        ordering = ['-id']


class DetallePago(models.Model):
    lote = models.ForeignKey(LotePago, on_delete=models.PROTECT, related_name='pagos')
    comprobante = models.ForeignKey('ordenes.ComprobanteEgreso', null=True, blank=True, on_delete=models.PROTECT, related_name='pagos_bancarios')
    empleado = models.ForeignKey(EmpleadoPago, null=True, blank=True, on_delete=models.PROTECT, related_name='+')
    cuenta = models.ForeignKey(CuentaBancaria, null=True, blank=True, on_delete=models.PROTECT, related_name='+')
    valor = models.DecimalField(max_digits=12, decimal_places=2)
    incluido = models.BooleanField(default=True)
    rechazado = models.BooleanField(default=False)
    concepto = models.CharField(max_length=255, blank=True)
    cuenta_snapshot = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ['id']
        constraints = [
            models.UniqueConstraint(fields=['lote', 'comprobante'], name='ce_unico_en_lote'),
            models.UniqueConstraint(fields=['lote', 'empleado'], name='empleado_unico_en_lote'),
            models.CheckConstraint(check=Q(valor__gte=0), name='detalle_pago_no_negativo'),
        ]


class ArchivoLotePago(models.Model):
    """Originales de cada generación, incluso si luego se corrige el lote."""
    lote = models.ForeignKey(LotePago, on_delete=models.PROTECT, related_name='archivos')
    revision = models.PositiveIntegerField()
    contenido = models.BinaryField(editable=False)
    sha256 = models.CharField(max_length=64)
    generado_en = models.DateTimeField(auto_now_add=True)
    datos = models.JSONField(default=dict)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['lote', 'revision'], name='archivo_revision_unica')]


class ProgramacionNomina(models.Model):
    # Singleton: fila bloqueada para evitar dos preparaciones concurrentes.
    activa = models.BooleanField(default=False)
    dia = models.PositiveSmallIntegerField(default=25)
    cuenta_origen = models.ForeignKey(CuentaBancaria, null=True, blank=True, on_delete=models.PROTECT, related_name='+')
    habilitada_desde = models.DateField(null=True, blank=True)
    actualizado_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT, related_name='+')
    ultimo_intento = models.DateTimeField(null=True, blank=True)
    latido_motor = models.DateTimeField(null=True, blank=True)
    ultimo_error = models.CharField(max_length=300, blank=True)
    revision = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [models.CheckConstraint(check=Q(dia__gte=1, dia__lte=31), name='programacion_dia_valido')]
