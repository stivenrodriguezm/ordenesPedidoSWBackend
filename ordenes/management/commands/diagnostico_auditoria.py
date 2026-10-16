"""Diagnóstico de SOLO LECTURA de inconsistencias (P06-01, auditoría 2026-10-02).

Uso (siempre primero sobre una copia autorizada, nunca como reparación):
    python manage.py diagnostico_auditoria [--ids 20] [--json]

Muestra conteos y, como máximo, `--ids` identificadores por hallazgo. No
imprime nombres, documentos ni teléfonos. Todo corre dentro de una transacción
que se revierte al final, como garantía adicional de que nada se escribe.
"""
import json
from collections import Counter
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone
from django.db.models import Count, F, Sum

from ordenes.models import Caja, ComprobanteEgreso, CuentaCaja, PagoReciboCaja, RolePermission, Venta
from ordenes.permissions import AUXILIAR_FINANCIAL_FEATURES, PERMISSION_ALIASES
from suministros.models import FacturaProveedor, Inventario, RemisionSuministro


class _Revertir(Exception):
    pass


class Command(BaseCommand):
    help = 'Diagnóstico de solo lectura de inconsistencias de datos (no modifica nada).'

    def add_arguments(self, parser):
        parser.add_argument('--ids', type=int, default=20)
        parser.add_argument('--json', action='store_true')

    def handle(self, *args, **opts):
        self.limite = opts['ids']
        resultado = {}
        try:
            with transaction.atomic():
                resultado = self._diagnosticar()
                raise _Revertir()
        except _Revertir:
            pass
        if opts['json']:
            self.stdout.write(json.dumps(resultado, indent=2, default=str))
            return
        for clave, datos in resultado.items():
            self.stdout.write(f"{clave}: {datos['total']}" + (f"  ejemplos={datos['ids']}" if datos.get('ids') else ''))

    def _hallazgo(self, ids):
        ids = list(ids)
        return {'total': len(ids), 'ids': ids[:self.limite]}

    def _diagnosticar(self):
        r = {}
        # Caja
        r['caja_movimientos_con_saldo_negativo'] = self._hallazgo(Caja.objects.filter(total_acumulado__lt=0).values_list('id', flat=True))
        r['caja_movimientos_valor_negativo'] = self._hallazgo(Caja.objects.filter(valor__lt=0).values_list('id', flat=True))
        ultimo = Caja.objects.order_by('-fecha_hora', '-id').first()
        cuenta = CuentaCaja.objects.filter(nombre=CuentaCaja.PRINCIPAL).first()
        r['caja_cuenta_vs_ultimo_movimiento'] = {
            'total': int(bool(cuenta and ultimo and cuenta.saldo != ultimo.total_acumulado)),
            'ids': [f'cuenta={cuenta.saldo if cuenta else None} ultimo={ultimo.total_acumulado if ultimo else None}'],
        }
        # Documentos anteriores al primer movimiento de caja no pueden tener
        # movimiento: se reportan aparte para no confundirlos con inconsistencias.
        primero = Caja.objects.order_by('fecha_hora').values_list('fecha_hora', flat=True).first()
        inicio_caja = timezone.localtime(primero).date() if primero else None
        r['caja_inicio'] = {'total': 1 if inicio_caja else 0, 'ids': [str(inicio_caja)]}

        def menciona(numero, prefijo):
            # Formatos históricos: "OC. 1, RC. 2", "RC. 2 OC. 1", "REM. 3 OC. 1 RC. 2"…
            return Caja.objects.filter(concepto__regex=rf'{prefijo}\.? ?{numero}(\D|$)').exists()

        sin_mov, previos = [], []
        for p in PagoReciboCaja.objects.filter(estado='Confirmado', metodo_pago='Efectivo').select_related('recibo').iterator():
            if p.movimientos_caja.exists() or menciona(p.recibo_id, 'RC'):
                continue
            (previos if inicio_caja is None or p.recibo.fecha < inicio_caja else sin_mov).append(p.id)
        r['pagos_efectivo_confirmados_sin_ingreso_de_caja'] = self._hallazgo(sin_mov)
        r['pagos_efectivo_anteriores_a_la_caja'] = self._hallazgo(previos)
        # Ventas: abono vs suma de pagos confirmados
        descuadres = []
        confirmados = dict(PagoReciboCaja.objects.filter(estado='Confirmado').values('recibo__venta_id')
                           .annotate(t=Sum('valor')).values_list('recibo__venta_id', 't'))
        for v in Venta.objects.only('id', 'abono', 'saldo', 'valor_total').iterator():
            if v.abono != (confirmados.get(v.id) or Decimal('0')) or v.saldo != v.valor_total - v.abono:
                descuadres.append(v.id)
        r['ventas_abono_o_saldo_descuadrado'] = self._hallazgo(descuadres)
        r['ventas_vendedor_repetido_en_compartidos'] = self._hallazgo(
            Venta.objects.filter(vendedores_compartidos=F('vendedor')).values_list('id', flat=True).distinct())
        # Egresos y facturas
        r['facturas_pagadas_sin_comprobante'] = self._hallazgo(
            FacturaProveedor.objects.filter(estado__in=['pagada', 'pago_en_proceso'], comprobante_egreso__isnull=True).values_list('id', flat=True))
        r['facturas_de_otro_proveedor_que_su_comprobante'] = self._hallazgo(
            FacturaProveedor.objects.filter(comprobante_egreso__isnull=False, comprobante_egreso__proveedor__isnull=False)
            .exclude(proveedor_id=F('comprobante_egreso__proveedor_id')).values_list('id', flat=True))
        sin_mov_e, previos_e = [], []
        for e in ComprobanteEgreso.objects.filter(estado='Pagado', medio_pago='Efectivo').iterator():
            if e.movimientos_caja.exists() or menciona(e.id, 'CE'):
                continue
            (previos_e if inicio_caja is None or e.fecha < inicio_caja else sin_mov_e).append(e.id)
        r['egresos_efectivo_pagados_sin_movimiento'] = self._hallazgo(sin_mov_e)
        r['egresos_efectivo_anteriores_a_la_caja'] = self._hallazgo(previos_e)
        # Inventario
        activos = RemisionSuministro.inventario_items.through.objects.filter(remisionsuministro__estado__in=['creada', 'despachada'])
        r['items_en_varias_remisiones_activas'] = self._hallazgo(
            activos.values('inventario_id').annotate(n=Count('id')).filter(n__gt=1).values_list('inventario_id', flat=True))
        r['items_por_despachar_sin_remision_activa'] = self._hallazgo(
            Inventario.objects.filter(disponibilidad='por_despachar').exclude(pk__in=activos.values('inventario_id')).values_list('pk', flat=True))
        r['items_con_tela_heredada_y_nueva'] = self._hallazgo(
            Inventario.objects.filter(lleva_tela=True, telas_cueros__isnull=False).values_list('pk', flat=True).distinct())
        # Permisos
        conocidos = set(PERMISSION_ALIASES) | {c for v in PERMISSION_ALIASES.values() for c in v} | AUXILIAR_FINANCIAL_FEATURES
        desconocidos = Counter()
        for rp in RolePermission.objects.all():
            for c in rp.permissions or []:
                if c not in conocidos and not c.isupper():
                    desconocidos[rp.role] += 1
        r['permisos_con_formato_invalido'] = {'total': sum(desconocidos.values()), 'ids': dict(desconocidos)}
        from listaprecios.models import Multiplicador
        r['multiplicadores_generales'] = {'total': Multiplicador.objects.filter(es_general=True).count(), 'ids': ['debe ser exactamente 1']}
        return r

