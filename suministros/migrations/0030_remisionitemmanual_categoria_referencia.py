import django.db.models.deletion
from django.db import migrations, models


def a_nuevos_campos(apps, schema_editor):
    """Antes: `descripcion` = nombre del producto y `observacion` = detalle.
    Ahora: `referencia` = nombre y `descripcion` = texto para el cliente."""
    Item = apps.get_model('suministros', 'RemisionItemManual')
    for item in Item.objects.all():
        item.referencia = (item.descripcion or '')[:255]
        item.descripcion = item.observacion or ''
        item.save(update_fields=['referencia', 'descripcion'])


def a_campos_anteriores(apps, schema_editor):
    Item = apps.get_model('suministros', 'RemisionItemManual')
    for item in Item.objects.all():
        item.observacion = item.descripcion or ''
        item.descripcion = (item.referencia or item.descripcion or 'Producto')[:255]
        item.save(update_fields=['observacion', 'descripcion'])


class Migration(migrations.Migration):

    dependencies = [
        ('suministros', '0029_remision_novedades'),
    ]

    operations = [
        migrations.AddField(
            model_name='remisionitemmanual',
            name='categoria',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to='suministros.categoria'),
        ),
        migrations.AddField(
            model_name='remisionitemmanual',
            name='subcategoria',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to='suministros.subcategoria'),
        ),
        migrations.AddField(
            model_name='remisionitemmanual',
            name='referencia',
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AlterField(
            model_name='remisionitemmanual',
            name='descripcion',
            field=models.TextField(blank=True),
        ),
        migrations.RunPython(a_nuevos_campos, a_campos_anteriores),
        migrations.RemoveField(
            model_name='remisionitemmanual',
            name='observacion',
        ),
    ]
