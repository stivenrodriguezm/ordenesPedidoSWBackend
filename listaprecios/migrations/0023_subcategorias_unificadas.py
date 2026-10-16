"""Costos por subcategoría asignada; conserva los precios anteriores como archivo.

No se adivinan equivalencias ni se modifica Referencias. Una colección con
productos sin correspondencia exacta se conserva inactiva y se abre un borrador.
"""
from django.db import migrations, models
import django.db.models.deletion


def unificar(apps, schema_editor):
    alias = schema_editor.connection.alias
    Linea = apps.get_model('listaprecios', 'LineaProducto')
    Variante = apps.get_model('listaprecios', 'VarianteProducto')
    for linea in Linea.objects.using(alias).filter(referencia__isnull=False).select_related('referencia'):
        subs = list(linea.referencia.subcategorias.using(alias).select_related('categoria').order_by('categoria__nombre', 'nombre', 'pk'))
        ids = {s.pk for s in subs}
        productos = list(Variante.objects.using(alias).filter(linea_id=linea.pk))
        asignados = [v.subcategoria_id for v in productos]
        if any(i not in ids for i in asignados) or len(asignados) != len(set(asignados)):
            ref_id = linea.referencia_id
            # Los documentos históricos conservan los IDs de línea, producto y precios.
            Linea.objects.using(alias).filter(pk=linea.pk).update(
                referencia_id=None, referencia_archivada_id=ref_id, activo=False, slug=f'archivo-subcategorias-{linea.pk}')
            Variante.objects.using(alias).filter(linea_id=linea.pk).update(subcategoria_id=None, categoria_referencia_id=None)
            linea = Linea.objects.using(alias).create(
                referencia_id=ref_id, nombre=linea.referencia.nombre[:150], slug=f'referencia-{ref_id}',
                notas=linea.notas, fotos=linea.fotos, es_decorativo=linea.es_decorativo, activo=False, orden=linea.orden)
            productos = []
        existentes = {v.subcategoria_id for v in productos}
        orden = max((v.orden for v in productos), default=-1) + 1
        faltantes = [s for s in subs if s.pk not in existentes]
        Variante.objects.using(alias).bulk_create([
            Variante(linea_id=linea.pk, subcategoria_id=s.pk, categoria_referencia_id=s.categoria_id,
                     nombre=s.nombre, orden=orden+i, costo_base=0, costo_confirmado=False)
            for i, s in enumerate(faltantes)
        ])
        if faltantes:
            Linea.objects.using(alias).filter(pk=linea.pk).update(activo=False)
    # Duplicados de archivos anteriores tampoco participan de la identidad actual.
    Variante.objects.using(alias).filter(linea__referencia__isnull=True).update(subcategoria_id=None)


class Migration(migrations.Migration):
    dependencies = [('listaprecios', '0022_tipo_decorativo_referencia')]
    operations = [
        migrations.AddField(model_name='lineaproducto', name='referencia_archivada', field=models.ForeignKey(
            to='ordenes.referencia', null=True, blank=True, editable=False, related_name='listas_precios_archivadas', on_delete=django.db.models.deletion.PROTECT)),
        migrations.AddField(model_name='varianteproducto', name='costo_confirmado', field=models.BooleanField(default=True)),
        migrations.RunPython(unificar, migrations.RunPython.noop),
        migrations.AddConstraint(model_name='varianteproducto', constraint=models.UniqueConstraint(
            fields=['linea', 'subcategoria'], name='lp_subcategoria_unica_linea')),
    ]
