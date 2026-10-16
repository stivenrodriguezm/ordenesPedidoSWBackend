from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('listaprecios', '0017_especialcatalogo_and_more')]

    operations = [
        migrations.AddField(
            model_name='componentejuego', name='costo_unitario',
            field=models.DecimalField(blank=True, null=True, max_digits=12, decimal_places=2,
                                      verbose_name='Costo base unitario solo en este conjunto'),
        ),
        migrations.AddField(
            model_name='componentejuego', name='multiplicador',
            field=models.DecimalField(blank=True, null=True, max_digits=6, decimal_places=3,
                                      verbose_name='Multiplicador solo en este conjunto'),
        ),
    ]
