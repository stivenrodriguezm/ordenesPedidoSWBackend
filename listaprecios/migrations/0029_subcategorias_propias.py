# Subcategorías propias de cada referencia (decisión del usuario, 2026-11-10).
#
# Antes una subcategoría («Sofá 3 puestos» en Salas) era un solo registro compartido por todas las
# referencias que la tenían asignada; renombrarla o cambiarla de categoría desde Administrar lista
# podía cambiar otras referencias. Esta migración deja cada subcategoría en una sola referencia:
# la conserva la referencia que tiene su ficha de precios (o la de menor id) y cada una de las
# demás recibe una copia con el mismo nombre y categoría, llevándose lo suyo (ficha de precios,
# pedidos, inventario, facturas y grupos de inventario) y su lugar en el orden de la lista.
# No borra nada ni cambia nombres. No se revierte (unir de nuevo podría mezclar referencias).
from collections import defaultdict

from django.db import migrations

from suministros.subcategorias import ajustar_disposicion, mover_registros


def separar_compartidas(apps, schema_editor):
    Subcategoria = apps.get_model('suministros', 'Subcategoria')
    Referencia = apps.get_model('ordenes', 'Referencia')
    Disposicion = apps.get_model('listaprecios', 'DisposicionReferenciaPrecio')
    VarianteProducto = apps.get_model('listaprecios', 'VarianteProducto')
    modelos = [(VarianteProducto, 'linea__referencia_id'), (apps.get_model('ordenes', 'DetallePedido'), 'referencia_id'),
               (apps.get_model('suministros', 'Inventario'), 'referencia_id'), (apps.get_model('suministros', 'DetalleFactura'), 'referencia_id'),
               (apps.get_model('suministros', 'GrupoInventarioComponente'), 'referencia_id')]
    Asignacion = Referencia.subcategorias.through
    usos = defaultdict(list)
    for sub_id, ref_id in Asignacion.objects.order_by('referencia_id').values_list('subcategoria_id', 'referencia_id'):
        usos[sub_id].append(ref_id)
    referencias = {r.pk: r for r in Referencia.objects.all()}
    for sub_id, ref_ids in usos.items():
        if len(ref_ids) < 2:
            continue
        sub = Subcategoria.objects.get(pk=sub_id)
        duena = (VarianteProducto.objects.filter(subcategoria_id=sub_id, linea__referencia_id__in=ref_ids)
                 .order_by('pk').values_list('linea__referencia_id', flat=True).first()) or ref_ids[0]
        for ref_id in ref_ids:
            if ref_id == duena:
                continue
            nueva = Subcategoria.objects.create(categoria_id=sub.categoria_id, nombre=sub.nombre)
            Asignacion.objects.filter(referencia_id=ref_id, subcategoria_id=sub_id).update(subcategoria_id=nueva.pk)
            mover_registros(modelos, sub_id, nueva.pk, [ref_id])
            ajustar_disposicion(Disposicion, Referencia, Subcategoria, referencias[ref_id], sub_id, nueva.pk)


class Migration(migrations.Migration):

    dependencies = [
        ('listaprecios', '0028_cargos_porcentaje_tela_y_cuero'),
        ('suministros', '0041_ajustes_factura'),
        ('ordenes', '0090_permiso_reabrir_gestion_venta'),
    ]

    operations = [
        migrations.RunPython(separar_compartidas, migrations.RunPython.noop),
    ]
