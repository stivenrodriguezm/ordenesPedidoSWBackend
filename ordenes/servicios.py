"""Servicios de dominio financiero (auditoría 2026-10-02: P03-01/02/03/06/07).

Reglas que las vistas ya no implementan por su cuenta:
* Todo movimiento de caja pasa por registrar_movimiento_caja(), que bloquea la
  fila estable de CuentaCaja, valida importe positivo y saldo no negativo y
  calcula el saldo en servidor.
* Las operaciones de negocio corren dentro de transaction.atomic() y los errores
  se capturan FUERA del bloque, para que un 400/403/409 no deje escrituras
  parciales (H03).
"""
import functools
import hashlib
import json
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from django.db import IntegrityError, transaction
from rest_framework import status
from rest_framework.exceptions import APIException
from rest_framework.response import Response

from .models import Caja, ClaveIdempotencia, ConsecutivoDocumento, CuentaCaja, RegistroAuditoria

CENTAVO = Decimal('0.01')


class ErrorNegocio(APIException):
    """Rechazo de una operación de negocio. Al propagarse revierte la transacción
    que lo contiene y DRF lo convierte en la respuesta HTTP indicada; también
    puede capturarse fuera del bloque atómico y responderse con .respuesta()."""

    def __init__(self, mensaje, estado=status.HTTP_400_BAD_REQUEST, campo='detail'):
        super().__init__({campo: mensaje})
        self.status_code = estado
        self.mensaje = mensaje
        self.estado = estado
        self.campo = campo

    def respuesta(self):
        return Response({self.campo: self.mensaje}, status=self.estado)


def a_decimal(valor, campo='valor', positivo=True):
    """Convierte a Decimal con 2 decimales (ROUND_HALF_UP). Rechaza NaN/inf."""
    try:
        d = Decimal(str(valor))
    except (InvalidOperation, TypeError, ValueError):
        raise ErrorNegocio(f'El campo {campo} debe ser un número válido.', campo=campo)
    if not d.is_finite():
        raise ErrorNegocio(f'El campo {campo} debe ser un número válido.', campo=campo)
    d = d.quantize(CENTAVO, rounding=ROUND_HALF_UP)
    if positivo and d <= 0:
        raise ErrorNegocio(f'El campo {campo} debe ser mayor a cero.', campo=campo)
    return d


def formato_cop(valor):
    return '$' + f'{Decimal(valor):,.0f}'.replace(',', '.')


# ---------------------------------------------------------------------------
# Caja
# ---------------------------------------------------------------------------

def cuenta_principal(bloquear=False):
    qs = CuentaCaja.objects.select_for_update() if bloquear else CuentaCaja.objects
    cuenta = qs.filter(nombre=CuentaCaja.PRINCIPAL).first()
    if cuenta is None:
        # Solo ocurre en una base sin la migración 0037 (p. ej. pruebas que la
        # vaciaron): get_or_create bajo la restricción unique evita duplicados.
        try:
            with transaction.atomic():
                cuenta, _ = CuentaCaja.objects.get_or_create(nombre=CuentaCaja.PRINCIPAL)
        except IntegrityError:
            pass
        cuenta = qs.get(nombre=CuentaCaja.PRINCIPAL)
    return cuenta


def saldo_caja():
    return cuenta_principal().saldo


def registrar_movimiento_caja(usuario, tipo, valor, concepto, comprobante_egreso=None,
                              pago_recibo=None, reversa_de=None):
    """Aplica un ingreso o egreso de efectivo. Debe llamarse dentro de una
    transacción: bloquea la cuenta, valida y actualiza saldo y movimiento juntos."""
    if tipo not in ('ingreso', 'egreso'):
        raise ErrorNegocio('Tipo de movimiento inválido. Usa ingreso o egreso; el cierre tiene su propia acción.', campo='tipo')
    valor = a_decimal(valor)
    concepto = (concepto or '').strip()
    if not concepto:
        raise ErrorNegocio('El concepto es obligatorio.', campo='concepto')
    if not transaction.get_connection().in_atomic_block:
        raise RuntimeError('registrar_movimiento_caja requiere una transacción activa')

    cuenta = cuenta_principal(bloquear=True)
    if tipo == 'egreso' and valor > cuenta.saldo:
        raise ErrorNegocio(
            f'Saldo insuficiente en caja. Saldo disponible en efectivo: {formato_cop(cuenta.saldo)}. '
            f'Intenta retirar: {formato_cop(valor)}.'
        )
    cuenta.saldo = cuenta.saldo + valor if tipo == 'ingreso' else cuenta.saldo - valor
    cuenta.save(update_fields=['saldo'])
    return Caja.objects.create(
        usuario=usuario, cuenta=cuenta, tipo=tipo, valor=valor, concepto=concepto[:255],
        total_acumulado=cuenta.saldo, comprobante_egreso=comprobante_egreso,
        pago_recibo=pago_recibo, reversa_de=reversa_de,
    )


def registrar_cierre_caja(usuario, concepto):
    """Cierre: deja constancia sin alterar el saldo (un descuadre se corrige con
    un ajuste autorizado y trazable, nunca sobrescribiendo el saldo)."""
    cuenta = cuenta_principal(bloquear=True)
    return Caja.objects.create(
        usuario=usuario, cuenta=cuenta, tipo='cierre', valor=Decimal('0'),
        concepto=concepto[:255], total_acumulado=cuenta.saldo,
    )


# ---------------------------------------------------------------------------
# Numeración y bitácora
# ---------------------------------------------------------------------------

def siguiente_consecutivo(serie, minimo, existentes_max=0):
    """Siguiente número de la serie bajo bloqueo de su fila. `existentes_max`
    sincroniza la serie con documentos creados antes de que existiera."""
    contador, _ = ConsecutivoDocumento.objects.get_or_create(serie=serie)
    contador = ConsecutivoDocumento.objects.select_for_update().get(pk=contador.pk)
    numero = max(contador.ultimo + 1, minimo, (existentes_max or 0) + 1)
    contador.ultimo = numero
    contador.save(update_fields=['ultimo'])
    return numero


def auditar(usuario, accion, objeto, detalle=None):
    RegistroAuditoria.objects.create(
        usuario=usuario if getattr(usuario, 'is_authenticated', False) else None,
        accion=accion, objeto_tipo=objeto.__class__.__name__, objeto_id=str(objeto.pk),
        detalle=json.loads(json.dumps(detalle or {}, default=str)),
    )


# ---------------------------------------------------------------------------
# Idempotencia (cabecera Idempotency-Key)
# ---------------------------------------------------------------------------

def _huella(request):
    datos = json.dumps(request.data, sort_keys=True, default=str) if hasattr(request, 'data') else ''
    return hashlib.sha256(f'{request.method}:{request.path}:{datos}'.encode()).hexdigest()


def idempotente(operacion):
    """Decorador para vistas de alta. Con `Idempotency-Key`: una repetición con el
    mismo contenido devuelve la respuesta original sin repetir efectos; contenido
    distinto con la misma clave es 409. Sin cabecera se comporta como antes.
    La respuesta se guarda en la MISMA transacción que la operación.
    Sirve para vistas de función (request primero) y para métodos de clase
    (self, request): la petición DRF es el argumento que tiene `data`."""
    def decorador(vista):
        @functools.wraps(vista)
        def envoltura(*args, **kwargs):
            request = next((a for a in args[:2] if hasattr(a, 'data')), None)
            if request is None:
                return vista(*args, **kwargs)
            clave = (request.headers.get('Idempotency-Key') or '').strip()[:100]
            if not clave:
                return vista(*args, **kwargs)
            huella = _huella(request)
            previa = ClaveIdempotencia.objects.filter(usuario=request.user, operacion=operacion, clave=clave).first()
            if previa:
                if previa.huella != huella:
                    return Response({'detail': 'La clave de idempotencia ya se usó con otro contenido.'}, status=status.HTTP_409_CONFLICT)
                return Response(previa.respuesta, status=previa.estado_http)
            try:
                with transaction.atomic():
                    respuesta = vista(*args, **kwargs)
                    if 200 <= respuesta.status_code < 300:
                        ClaveIdempotencia.objects.create(
                            usuario=request.user, operacion=operacion, clave=clave, huella=huella,
                            estado_http=respuesta.status_code,
                            respuesta=json.loads(json.dumps(respuesta.data, default=str)),
                        )
                    return respuesta
            except IntegrityError:
                # Otra petición con la misma clave terminó primero: devolver la suya.
                previa = ClaveIdempotencia.objects.filter(usuario=request.user, operacion=operacion, clave=clave).first()
                if previa and previa.huella == huella:
                    return Response(previa.respuesta, status=previa.estado_http)
                return Response({'detail': 'Conflicto de idempotencia.'}, status=status.HTTP_409_CONFLICT)
        return envoltura
    return decorador
