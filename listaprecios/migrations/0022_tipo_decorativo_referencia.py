from django.db import migrations, models


def conservar(apps, schema_editor):
    apps.get_model('listaprecios', 'LineaProducto').objects.using(schema_editor.connection.alias).filter(slug='decorativos').update(es_decorativo=True)


class Migration(migrations.Migration):
    dependencies = [('listaprecios', '0021_precios_por_referencia')]
    operations = [
        migrations.AddField(model_name='lineaproducto', name='es_decorativo', field=models.BooleanField(default=False)),
        migrations.RunPython(conservar, migrations.RunPython.noop),
    ]
