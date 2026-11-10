"""Por módulos es una opción de pedido; no asigna referencias ni publica precios."""
import unicodedata

from django.db import migrations


def normalizar(texto):
    return ' '.join(unicodedata.normalize('NFKD', texto).encode('ascii', 'ignore').decode().lower().split())


def agregar_por_modulos(apps, schema_editor):
    Categoria = apps.get_model('suministros', 'Categoria')
    Subcategoria = apps.get_model('suministros', 'Subcategoria')
    db = schema_editor.connection.alias
    salas = [c for c in Categoria.objects.using(db).all() if normalizar(c.nombre) in {'sala', 'salas'}]
    if not salas:
        salas = [Categoria.objects.using(db).create(nombre='Salas')]
    for categoria in salas:
        if not any(normalizar(s.nombre) == 'por modulos' for s in Subcategoria.objects.using(db).filter(categoria=categoria)):
            Subcategoria.objects.using(db).create(categoria=categoria, nombre='Por módulos')


class Migration(migrations.Migration):
    dependencies = [('suministros', '0041_ajustes_factura')]
    # Revertir conserva el maestro porque puede estar referenciado en pedidos posteriores.
    operations = [migrations.RunPython(agregar_por_modulos, migrations.RunPython.noop)]
