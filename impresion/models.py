"""Impresión remota (2026-10-24): la plataforma deja trabajos en cola y el agente de la
computadora de la oficina (scripts/impresion/agente.py) los recoge y los manda a su
impresora. La oficina no abre puertos: el agente es el que consulta al servidor."""
from django.conf import settings
from django.db import models


class Impresora(models.Model):
    nombre = models.CharField(max_length=80)
    ubicacion = models.CharField(max_length=80, blank=True)
    # SHA-256 del token del agente; el token solo se muestra al crearlo (crear_impresora).
    token_hash = models.CharField(max_length=64, unique=True)
    activa = models.BooleanField(default=True)
    creada = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['nombre']

    def __str__(self):
        return f'{self.nombre} · {self.ubicacion}' if self.ubicacion else self.nombre


class TrabajoImpresion(models.Model):
    PENDIENTE, PROCESANDO, ENVIADO, IMPRESO, ERROR = 'pendiente', 'procesando', 'enviado', 'impreso', 'error'
    ESTADOS = [
        (PENDIENTE, 'En cola'),
        (PROCESANDO, 'Preparando'),
        (ENVIADO, 'En la impresora'),
        (IMPRESO, 'Impreso'),
        (ERROR, 'Error'),
    ]

    impresora = models.ForeignKey(Impresora, on_delete=models.PROTECT, related_name='trabajos')
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='+')
    titulo = models.CharField(max_length=150)
    html = models.TextField()  # documento completo e independiente, como el que se imprime en el navegador
    copias = models.PositiveSmallIntegerField(default=1)
    estado = models.CharField(max_length=12, choices=ESTADOS, default=PENDIENTE, db_index=True)
    detalle = models.CharField(max_length=255, blank=True)
    creado = models.DateTimeField(auto_now_add=True, db_index=True)
    actualizado = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['creado']

    def __str__(self):
        return f'{self.titulo} ({self.get_estado_display()})'
