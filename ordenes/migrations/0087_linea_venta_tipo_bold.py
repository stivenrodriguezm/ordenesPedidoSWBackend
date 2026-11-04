from django.db import migrations, models


class Migration(migrations.Migration):
    """Bold (2026-11-04): tipo de línea para el cobro por datáfono. Solo cambia las opciones."""

    dependencies = [
        ('ordenes', '0086_linea_venta_tela_sin_pedir'),
    ]

    operations = [
        migrations.AlterField(
            model_name='lineaventa',
            name='tipo',
            field=models.CharField(choices=[('producto', 'Producto'), ('transporte', 'Transporte'), ('articulo', 'Artículo adicional'), ('ajuste', 'Ajuste'), ('bold', 'Bold (datáfono)')], default='producto', max_length=12),
        ),
    ]
