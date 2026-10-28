# Recibos de caja (2026-10-28): fotos de los comprobantes de pago y el vendedor puede crear recibos.
# El rol vendedor recibe ACCESO_RECIBOS (ve solo los recibos de sus ventas) y CREAR_RECIBO, si su
# rol tiene configuración guardada. Encadenada antes de 0061_merge (que depende de esta).
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion

PERMISOS_VENDEDOR = ['ACCESO_RECIBOS', 'CREAR_RECIBO']


def habilitar_vendedor(apps, schema_editor):
    RolePermission = apps.get_model('ordenes', 'RolePermission')
    rp = RolePermission.objects.using(schema_editor.connection.alias).filter(role='vendedor').first()
    if rp is not None and isinstance(rp.permissions, list):
        faltan = [p for p in PERMISOS_VENDEDOR if p not in rp.permissions]
        if faltan:
            rp.permissions = [*rp.permissions, *faltan]
            rp.save(update_fields=['permissions'])


def quitar_vendedor(apps, schema_editor):
    RolePermission = apps.get_model('ordenes', 'RolePermission')
    rp = RolePermission.objects.using(schema_editor.connection.alias).filter(role='vendedor').first()
    if rp is not None and isinstance(rp.permissions, list):
        rp.permissions = [p for p in rp.permissions if p not in PERMISOS_VENDEDOR]
        rp.save(update_fields=['permissions'])


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('ordenes', '0083_detalle_pedido_subcategoria'),
    ]

    operations = [
        migrations.CreateModel(
            name='ComprobanteReciboCaja',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('url', models.URLField(max_length=500)),
                ('creado_en', models.DateTimeField(auto_now_add=True)),
                ('recibo', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='comprobantes', to='ordenes.recibocaja')),
                ('subido_por', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['id'],
            },
        ),
        migrations.RunPython(habilitar_vendedor, quitar_vendedor),
    ]
