from django.db import migrations, models


def texto_a_lista(apps, schema_editor):
    VarianteProducto = apps.get_model('listaprecios', 'VarianteProducto')
    for v in VarianteProducto.objects.exclude(notas_temp='').only('id', 'notas_temp'):
        VarianteProducto.objects.filter(pk=v.pk).update(notas_json=[v.notas_temp])


def lista_a_texto(apps, schema_editor):
    VarianteProducto = apps.get_model('listaprecios', 'VarianteProducto')
    for v in VarianteProducto.objects.exclude(notas_json=[]).only('id', 'notas_json'):
        texto = ' / '.join(v.notas_json) if v.notas_json else ''
        VarianteProducto.objects.filter(pk=v.pk).update(notas_temp=texto)


class Migration(migrations.Migration):

    dependencies = [
        ('listaprecios', '0007_grupotela_tipo'),
    ]

    operations = [
        migrations.RenameField(
            model_name='varianteproducto',
            old_name='notas',
            new_name='notas_temp',
        ),
        migrations.AddField(
            model_name='varianteproducto',
            name='notas_json',
            field=models.JSONField(blank=True, default=list, verbose_name='Notas'),
        ),
        migrations.RunPython(texto_a_lista, lista_a_texto),
        migrations.RemoveField(
            model_name='varianteproducto',
            name='notas_temp',
        ),
        migrations.RenameField(
            model_name='varianteproducto',
            old_name='notas_json',
            new_name='notas',
        ),
    ]
