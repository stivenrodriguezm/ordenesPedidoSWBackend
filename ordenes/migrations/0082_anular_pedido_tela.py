# Anular pedidos de tela desde «Editar estado» (2026-10-26). El permiso ANULAR_PEDIDO_TELA se
# habilita inicialmente solo al rol administrador (si su rol tiene configuración guardada; sin
# ella ya tiene acceso total). Los demás roles no lo reciben.
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

PERMISO = 'ANULAR_PEDIDO_TELA'


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
        ('ordenes', '0081_cliente_tipo_persona'),
    ]

    operations = [
        migrations.AlterField(
            model_name='pedidotela',
            name='estado',
            field=models.CharField(choices=[('En fabrica', 'En fabrica'), ('En Lottus', 'En Lottus'), ('Pendiente', 'Pendiente'), ('Anulado', 'Anulado')], db_index=True, default='Pendiente', max_length=20),
        ),
        migrations.AddField(
            model_name='pedidotela',
            name='motivo_anulacion',
            field=models.TextField(blank=True, default=''),
        ),
        migrations.AddField(
            model_name='pedidotela',
            name='anulado_por',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='pedidos_tela_anulados', to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name='pedidotela',
            name='anulado_en',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.RunPython(habilitar_administrador, quitar_permiso),
    ]
