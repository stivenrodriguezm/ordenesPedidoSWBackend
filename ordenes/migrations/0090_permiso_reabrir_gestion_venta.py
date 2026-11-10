# Reabrir la gestión de productos de una venta (2026-11-10): nuevo permiso REABRIR_GESTION_VENTA.
# Se habilita solo al rol administrador (si su rol tiene configuración guardada; sin ella ya
# tiene acceso total). Los demás roles no lo reciben, aunque antes podían reabrir.
from django.db import migrations

PERMISO = 'REABRIR_GESTION_VENTA'


def habilitar_administrador(apps, schema_editor):
    RolePermission = apps.get_model('ordenes', 'RolePermission')
    rp = RolePermission.objects.using(schema_editor.connection.alias).filter(role='administrador').first()
    if rp is not None and isinstance(rp.permissions, list) and PERMISO not in rp.permissions:
        rp.permissions = [*rp.permissions, PERMISO]
        rp.save(update_fields=['permissions'])


def quitar_permiso(apps, schema_editor):
    RolePermission = apps.get_model('ordenes', 'RolePermission')
    for rp in RolePermission.objects.using(schema_editor.connection.alias).all():
        if isinstance(rp.permissions, list) and PERMISO in rp.permissions:
            rp.permissions = [p for p in rp.permissions if p != PERMISO]
            rp.save(update_fields=['permissions'])


class Migration(migrations.Migration):

    dependencies = [
        ('ordenes', '0088_usuario_telefono_enlace_qr'),
        ('ordenes', '0089_venta_tiene_anexo'),
    ]

    operations = [
        migrations.RunPython(habilitar_administrador, quitar_permiso),
    ]
