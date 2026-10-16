# 2026-10-15: se retiran los tipos de cojín y los cojines por detalle (pedido del usuario) y
# llega «Cojines incluidos»: un cargo fijo «Decorativos x2» que da derecho a 2 productos de
# la línea Decorativos (que se crea vacía; el usuario agrega sus detalles).

from decimal import Decimal
from django.db import migrations, models


def crear_linea_decorativos(apps, schema_editor):
    LineaProducto = apps.get_model('listaprecios', 'LineaProducto')
    LineaProducto.objects.using(schema_editor.connection.alias).get_or_create(
        slug='decorativos', defaults={'nombre': 'Decorativos', 'activo': True})


class Migration(migrations.Migration):

    dependencies = [
        ('listaprecios', '0014_consumo_cuero_independiente'),
    ]

    operations = [
        migrations.DeleteModel(
            name='TipoCojin',
        ),
        migrations.RemoveField(
            model_name='varianteproducto',
            name='cojines',
        ),
        migrations.AddField(
            model_name='cargovariante',
            name='tipo',
            field=models.CharField(blank=True, choices=[('', 'Cargo'), ('decorativos', 'Cojines incluidos (Decorativos x2)')], default='', max_length=20),
        ),
        migrations.AddField(
            model_name='lineacotizacion',
            name='incluido',
            field=models.DecimalField(decimal_places=2, default=Decimal('0.00'), max_digits=12, verbose_name='Valor incluido'),
        ),
        migrations.RunPython(crear_linea_decorativos, migrations.RunPython.noop),
    ]
