"""Datos de la auditoría 2026-10-02 (P02-03, P03-02). Idempotente.

1. Crea la cuenta "Caja principal" con el saldo del último movimiento y le
   asigna los movimientos existentes. Si el saldo histórico es negativo NO se
   inventa un ajuste: la migración se detiene para revisión (P06).
2. Siembra RolePermission para roles sin fila, con exactamente los permisos
   que ya tenían por defecto — así el GET de configuración deja de crear filas
   vacías y nadie pierde acceso (H20).
3. Concede CERRAR_CAJA a los roles que hoy acceden a caja (antes cualquier
   usuario con VER_CAJA podía cerrar).
"""
from decimal import Decimal

from django.db import migrations

AUXILIAR_POR_DEFECTO = [
    'VER_RECIBOS', 'ACCESO_RECIBOS', 'VER_CAJA', 'ACCESO_CAJA', 'CERRAR_CAJA',
    'VER_COMPROBANTES_EGRESO', 'ACCESO_EGRESOS', 'VER_TODOS_EGRESOS', 'VER_PROPIOS_EGRESOS',
    'CREAR_RECIBO', 'APROBAR_RECIBO', 'CREAR_INGRESO_CAJA', 'CREAR_EGRESO_CAJA',
    'CREAR_COMPROBANTE_EGRESO', 'APROBAR_EGRESO', 'EXPORTAR_EGRESOS', 'VER_VENTAS',
    'VER_ORDENES', 'VER_CLIENTES', 'VER_INVENTARIO', 'CREAR_FACTURA',
    'EDITAR_FACTURA', 'VER_FACTURAS', 'CREAR_ITEM_INVENTARIO',
    'CREAR_ENTRADA_MANUAL', 'CREAR_GRUPO_INVENTARIO', 'EDITAR_ITEM_INVENTARIO',
]
ROLES = ('vendedor', 'administrador', 'auxiliar', 'transportador', 'marketing')


def adelante(apps, schema_editor):
    Caja = apps.get_model('ordenes', 'Caja')
    CuentaCaja = apps.get_model('ordenes', 'CuentaCaja')
    RolePermission = apps.get_model('ordenes', 'RolePermission')

    ultimo = Caja.objects.order_by('-fecha_hora', '-id').first()
    saldo = ultimo.total_acumulado if ultimo else Decimal('0')
    if saldo < 0:
        raise RuntimeError(
            'El último movimiento de caja tiene saldo negativo. No se crea la cuenta de caja con un '
            'saldo inventado: revisar los movimientos (plan P06) y corregir con un ajuste autorizado '
            'antes de aplicar esta migración.'
        )
    cuenta, creada = CuentaCaja.objects.get_or_create(nombre='Caja principal', defaults={'saldo': saldo})
    Caja.objects.filter(cuenta__isnull=True).update(cuenta=cuenta)

    for role in ROLES:
        if role == 'administrador':
            continue
        rp = RolePermission.objects.filter(role=role).first()
        if rp is None:
            RolePermission.objects.create(
                role=role, permissions=list(AUXILIAR_POR_DEFECTO) if role == 'auxiliar' else []
            )
        elif isinstance(rp.permissions, list):
            perms = set(rp.permissions)
            if perms & {'VER_CAJA', 'ACCESO_CAJA'} and 'CERRAR_CAJA' not in perms:
                rp.permissions = list(rp.permissions) + ['CERRAR_CAJA']
                rp.save(update_fields=['permissions'])


class Migration(migrations.Migration):
    dependencies = [
        ('ordenes', '0036_auditoria_integridad'),
    ]

    operations = [
        # Reversa: no se borran datos (la cuenta y los permisos sembrados se conservan).
        migrations.RunPython(adelante, migrations.RunPython.noop),
    ]
