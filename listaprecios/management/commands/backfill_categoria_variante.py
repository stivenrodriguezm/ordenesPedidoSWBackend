"""Migración de datos puntual (paso 1→paso 2 del refactor "colección puede
tener variantes de distintos tipos de producto"):

1. Backfill: VarianteProducto.categoria = VarianteProducto.linea.categoria
   para toda variante que todavía no tenga categoría propia asignada.
2. Dedupe: cuando el mismo nombre de colección quedó repartido en varias
   LineaProducto (porque venían de hojas distintas del Excel — ej. "Alaska"
   como línea de Salas Y como línea de Poltronas), se fusionan en una sola
   línea, moviendo todas sus variantes.

Idempotente: correrlo de nuevo no hace nada si ya no hay categorías nulas
ni nombres duplicados."""
from collections import defaultdict

from django.core.management.base import BaseCommand
from django.db import transaction

from listaprecios.models import LineaProducto, VarianteProducto


class Command(BaseCommand):
    help = "Backfill de VarianteProducto.categoria + fusión de líneas con nombre duplicado."

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true', help="Escribe los cambios (por defecto es dry-run).")

    def handle(self, *args, **options):
        apply_changes = options['apply']

        with transaction.atomic():
            backfilled = self._backfill_categoria()
            fusiones = self._dedupe_lineas()

            if not apply_changes:
                transaction.set_rollback(True)
                self.stdout.write(self.style.WARNING("[DRY RUN] No se escribió nada. Usa --apply para confirmar."))

        self.stdout.write(f"Variantes con categoría rellenada: {backfilled}")
        self.stdout.write(f"Líneas fusionadas: {len(fusiones)}")
        for nombre, info in fusiones.items():
            self.stdout.write(f"  - '{nombre}': sobrevive línea #{info['survivor']}, se eliminaron {info['eliminadas']}")

    def _backfill_categoria(self):
        variantes = VarianteProducto.objects.filter(categoria__isnull=True).select_related('linea')
        count = 0
        for v in variantes:
            if v.linea.categoria_id:
                v.categoria_id = v.linea.categoria_id
                v.save(update_fields=['categoria'])
                count += 1
        return count

    def _dedupe_lineas(self):
        por_nombre = defaultdict(list)
        for linea in LineaProducto.objects.all().order_by('id'):
            por_nombre[linea.nombre.strip().lower()].append(linea)

        fusiones = {}
        for nombre, lineas in por_nombre.items():
            if len(lineas) < 2:
                continue

            # Sobrevive la que tenga fotos; si varias, la de más variantes; si empatan, la más antigua.
            def puntaje(l):
                return (1 if l.fotos else 0, l.variantes.count(), -l.id)
            survivor = max(lineas, key=puntaje)
            otras = [l for l in lineas if l.id != survivor.id]

            fotos_extra = []
            notas_extra = []
            for otra in otras:
                for foto in (otra.fotos or []):
                    if foto not in (survivor.fotos or []) and foto not in fotos_extra:
                        fotos_extra.append(foto)
                if otra.notas and otra.notas.strip() and otra.notas.strip() not in (survivor.notas or ''):
                    notas_extra.append(otra.notas.strip())

                VarianteProducto.objects.filter(linea=otra).update(linea=survivor)

            if fotos_extra:
                survivor.fotos = (survivor.fotos or []) + fotos_extra
            if notas_extra:
                survivor.notas = (survivor.notas + ' ' if survivor.notas else '') + ' '.join(notas_extra)
            survivor.save(update_fields=['fotos', 'notas'])

            eliminadas_ids = [l.id for l in otras]
            LineaProducto.objects.filter(id__in=eliminadas_ids).delete()

            fusiones[survivor.nombre] = {'survivor': survivor.id, 'eliminadas': eliminadas_ids}

        return fusiones
