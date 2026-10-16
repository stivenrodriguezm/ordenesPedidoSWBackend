from django.db import migrations, models


def conservar_consumos_existentes(apps, schema_editor):
    # Hasta ahora ambos materiales se calculaban con metraje_tela. Copiar
    # literalmente conserva los precios históricos; NO es una conversión de unidades.
    Variante = apps.get_model('listaprecios', 'VarianteProducto')
    Variante.objects.using(schema_editor.connection.alias).filter(metraje_tela__isnull=False).update(
        decimetraje_cuero=models.F('metraje_tela'))


class Migration(migrations.Migration):
    dependencies = [('listaprecios', '0013_cojines')]
    operations = [
        migrations.AddField(
            model_name='varianteproducto', name='decimetraje_cuero',
            field=models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True,
                                      verbose_name='Consumo de cuero (decímetros)'),
        ),
        migrations.RunPython(conservar_consumos_existentes, migrations.RunPython.noop),
    ]
