"""Crea líneas/variantes de Lista de Precios a partir del catálogo de
compras (`ordenes.Referencia`, visible en /referencias del ERP).

Ese catálogo es pequeño (6 filas al momento de escribir esto) y no trae
ningún precio — cada Referencia es proveedor + nombre + categorías/
subcategorías (M2M). Este comando solo crea la ESTRUCTURA (línea por
nombre de referencia, variante por subcategoría, mapeada a su
CategoriaLista correspondiente) con costo_base=0 y una nota indicando el
proveedor de origen, lista para que un administrador complete el precio
real desde /lista-precios/administrar.

Si el mismo nombre de referencia aparece con varios proveedores (ej.
"Valencia" vendido por 3 proveedores distintos — típico: mesa+sillas+base
de fabricantes distintos armados como una sola colección comercial), se
fusionan en una sola línea; una subcategoría repetida dentro del mismo
grupo se agrega una sola vez (se anota el proveedor alterno en la nota)."""
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils.text import slugify

from ordenes.models import Referencia
from listaprecios.models import CategoriaLista, LineaProducto, VarianteProducto


class DryRunRollback(Exception):
    pass


# Subcategoría (suministros) -> nombre de CategoriaLista (listaprecios).
# Confirmado 1:1 contra el catálogo real de Subcategoria — ver conversación.
SUBCATEGORIA_A_CATEGORIA = {
    'Sala completa': 'Salas', 'Sofá de 3': 'Salas', 'Sofá de 2': 'Salas',
    'Esquinero': 'Salas', 'Pouf': 'Salas', 'Sala en L': 'Salas',
    'Silla de comedor': 'Sillas',
    'Mesa de 4': 'Comedores', 'Mesa de 6': 'Comedores', 'Mesa de 8': 'Comedores',
    'Base de comedor': 'Comedores',
    'Tapa de comedor de 4': 'Comedores', 'Tapa de comedor de 6': 'Comedores', 'Tapa de comedor de 8': 'Comedores',
    'Comedor 4p.': 'Comedores', 'Comedor 6p.': 'Comedores', 'Comedor 8p.': 'Comedores',
    'Cama de 1.40': 'Alcobas', 'Cama de 1.60': 'Alcobas', 'Cama de 2x2': 'Alcobas', 'Mesa de noche': 'Alcobas',
}


class Command(BaseCommand):
    help = "Crea líneas/variantes de Lista de Precios (sin precio) a partir de ordenes.Referencia."

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true', help="Escribe en la base de datos (por defecto es dry-run).")

    def handle(self, *args, **options):
        apply_changes = options['apply']
        self.reporte = {'lineas_creadas': 0, 'lineas_reutilizadas': 0, 'variantes_creadas': 0, 'sin_mapeo': []}

        categorias = {c.nombre: c for c in CategoriaLista.objects.all()}
        faltantes = {v for v in SUBCATEGORIA_A_CATEGORIA.values()} - set(categorias)
        if faltantes:
            self.stderr.write(f"Faltan estas categorías en la base de datos: {faltantes}. Corre importar_lista_precios primero.")
            return

        referencias = list(
            Referencia.objects.select_related('proveedor').prefetch_related('subcategorias').order_by('id')
        )

        por_nombre = {}
        for ref in referencias:
            por_nombre.setdefault(ref.nombre.strip().lower(), []).append(ref)

        try:
            with transaction.atomic():
                for nombre_key, refs in por_nombre.items():
                    self._procesar_grupo(refs, categorias)
                if not apply_changes:
                    raise DryRunRollback()
        except DryRunRollback:
            self.stdout.write(self.style.WARNING("[DRY RUN] No se escribió nada. Usa --apply para confirmar."))

        r = self.reporte
        self.stdout.write(f"Líneas creadas: {r['lineas_creadas']} | reutilizadas: {r['lineas_reutilizadas']}")
        self.stdout.write(f"Variantes creadas: {r['variantes_creadas']}")
        if r['sin_mapeo']:
            self.stdout.write(self.style.WARNING(f"Subcategorías sin mapeo a categoría ({len(r['sin_mapeo'])}): {r['sin_mapeo']}"))

    def _procesar_grupo(self, refs, categorias):
        nombre = refs[0].nombre.strip()
        linea = LineaProducto.objects.filter(nombre__iexact=nombre).first()
        if linea is None:
            slug = slugify(nombre)
            base_slug, count = slug, 1
            while LineaProducto.objects.filter(slug=slug).exists():
                count += 1
                slug = f"{base_slug}-{count}"
            linea = LineaProducto.objects.create(nombre=nombre, slug=slug, activo=True)
            self.reporte['lineas_creadas'] += 1
        else:
            self.reporte['lineas_reutilizadas'] += 1

        existentes = {(v.nombre, v.categoria_id) for v in linea.variantes.all()}
        orden = linea.variantes.count()

        for ref in refs:
            proveedor_nombre = ref.proveedor.nombre_empresa
            for subcat in ref.subcategorias.all():
                categoria_nombre = SUBCATEGORIA_A_CATEGORIA.get(subcat.nombre)
                if not categoria_nombre:
                    self.reporte['sin_mapeo'].append(subcat.nombre)
                    continue
                categoria = categorias[categoria_nombre]
                key = (subcat.nombre, categoria.id)
                if key in existentes:
                    continue
                existentes.add(key)
                VarianteProducto.objects.create(
                    linea=linea, categoria=categoria, nombre=subcat.nombre, orden=orden,
                    costo_base=0, metraje_tela=None,
                    notas=f"Proveedor: {proveedor_nombre}. Sin precio — completar en Administrar Lista de Precios.",
                )
                orden += 1
                self.reporte['variantes_creadas'] += 1
