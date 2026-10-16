"""La referencia existente es la identidad del catálogo comercial.

No escribe en Referencia, Proveedor, Categoria ni Subcategoria. Los registros
anteriores que no se pueden asociar de forma inequívoca quedan fuera de venta.
"""
from collections import defaultdict
import unicodedata

from django.db import migrations, models
import django.db.models.deletion


def clave(nombre):
    texto = unicodedata.normalize('NFKD', nombre or '').casefold()
    return ''.join(c for c in texto if c.isalnum())


def vincular(apps, schema_editor):
    alias = schema_editor.connection.alias
    Referencia = apps.get_model('ordenes', 'Referencia')
    Linea = apps.get_model('listaprecios', 'LineaProducto')
    Variante = apps.get_model('listaprecios', 'VarianteProducto')
    refs, lineas = defaultdict(list), defaultdict(list)
    for ref in Referencia.objects.using(alias).prefetch_related('categorias', 'subcategorias__categoria'):
        refs[clave(ref.nombre)].append(ref)
    for linea in Linea.objects.using(alias).all():
        lineas[clave(linea.nombre)].append(linea)
    for nombre, filas in lineas.items():
        candidatas = refs.get(nombre, [])
        if not nombre or len(filas) != 1 or len(candidatas) != 1:
            Linea.objects.using(alias).filter(pk__in=[l.pk for l in filas]).update(activo=False)
            continue
        linea, ref = filas[0], candidatas[0]
        Linea.objects.using(alias).filter(pk=linea.pk).update(referencia_id=ref.pk)
        cats, subs = list(ref.categorias.all()), list(ref.subcategorias.all())
        for variante in Variante.objects.using(alias).filter(linea_id=linea.pk):
            iguales = [s for s in subs if clave(s.nombre) == clave(variante.nombre)]
            sub = iguales[0] if len(iguales) == 1 else None
            Variante.objects.using(alias).filter(pk=variante.pk).update(
                subcategoria_id=sub.pk if sub else None,
                categoria_referencia_id=sub.categoria_id if sub else cats[0].pk if len(cats) == 1 else None,
            )


class Migration(migrations.Migration):
    dependencies = [
        ('listaprecios', '0020_cargovariante_preseleccionado'),
        ('ordenes', '0017_remove_referencia_categoria_referencia_categorias_and_more'),
        ('suministros', '0001_initial'),
    ]
    operations = [
        migrations.AddField(model_name='lineaproducto', name='referencia', field=models.OneToOneField(
            to='ordenes.referencia', null=True, blank=True, related_name='lista_precios', on_delete=django.db.models.deletion.PROTECT)),
        migrations.AlterField(model_name='varianteproducto', name='categoria', field=models.ForeignKey(
            to='listaprecios.categorialista', null=True, blank=True, related_name='variantes', on_delete=django.db.models.deletion.PROTECT)),
        migrations.AddField(model_name='varianteproducto', name='categoria_referencia', field=models.ForeignKey(
            to='suministros.categoria', null=True, blank=True, related_name='variantes_precio', on_delete=django.db.models.deletion.PROTECT)),
        migrations.AddField(model_name='varianteproducto', name='subcategoria', field=models.ForeignKey(
            to='suministros.subcategoria', null=True, blank=True, related_name='variantes_precio', on_delete=django.db.models.deletion.PROTECT)),
        migrations.RunPython(vincular, migrations.RunPython.noop),
    ]
