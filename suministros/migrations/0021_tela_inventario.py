# Generated manually

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('suministros', '0020_costo_adicional_inventario'),
    ]

    operations = [
        migrations.AddField(
            model_name='detallefactura',
            name='lleva_tela',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='detallefactura',
            name='tela_cantidad_metros',
            field=models.DecimalField(decimal_places=2, default=0, max_digits=8),
        ),
        migrations.AddField(
            model_name='detallefactura',
            name='tela_color',
            field=models.CharField(blank=True, max_length=50, null=True),
        ),
        migrations.AddField(
            model_name='detallefactura',
            name='tela_costo_metro',
            field=models.DecimalField(decimal_places=2, default=0, max_digits=12),
        ),
        migrations.AddField(
            model_name='detallefactura',
            name='tela_referencia',
            field=models.CharField(blank=True, max_length=100, null=True),
        ),
        migrations.AddField(
            model_name='inventario',
            name='lleva_tela',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='inventario',
            name='tela_cantidad_metros',
            field=models.DecimalField(decimal_places=2, default=0, max_digits=8),
        ),
        migrations.AddField(
            model_name='inventario',
            name='tela_color',
            field=models.CharField(blank=True, max_length=50, null=True),
        ),
        migrations.AddField(
            model_name='inventario',
            name='tela_costo_metro',
            field=models.DecimalField(decimal_places=2, default=0, max_digits=12),
        ),
        migrations.AddField(
            model_name='inventario',
            name='tela_referencia',
            field=models.CharField(blank=True, max_length=100, null=True),
        ),
    ]
