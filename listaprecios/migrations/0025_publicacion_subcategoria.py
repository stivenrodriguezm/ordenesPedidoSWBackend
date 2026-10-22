from django.db import migrations, models


def conservar_publicacion(apps, schema_editor):
    # Conserva exactamente las fichas que ya estaban publicadas; no toca costos.
    Variante = apps.get_model('listaprecios', 'VarianteProducto')
    Variante.objects.using(schema_editor.connection.alias).filter(
        linea__activo=True, costo_confirmado=True).update(publicado=True)


class Migration(migrations.Migration):
    dependencies = [('listaprecios', '0024_disposicion_subcategorias')]
    operations = [
        migrations.AddField(model_name='varianteproducto', name='publicado',
                            field=models.BooleanField(default=False, verbose_name='Publicado en consulta y ventas')),
        migrations.RunPython(conservar_publicacion, migrations.RunPython.noop),
    ]
