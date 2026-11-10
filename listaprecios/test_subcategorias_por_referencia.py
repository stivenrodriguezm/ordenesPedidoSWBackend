"""(2026-11-10) Las subcategorías son propias de cada referencia (de un proveedor): renombrar,
cambiar de categoría o agregar desde Administrar lista solo cambia esa referencia, nunca las de
otros proveedores ni otras referencias, y no se fusiona con otras subcategorías del mismo nombre."""
from datetime import date

from django.core.cache import cache

from ordenes.models import DetallePedido, OrdenPedido
from ordenes.tests.utils import LottusTestCase
from suministros.models import Categoria, Subcategoria
from .models import DisposicionReferenciaPrecio, Multiplicador, VarianteProducto
from .referencias import crear_configuracion


class BaseSubcategorias(LottusTestCase):
    def setUp(self):
        cache.clear()
        Multiplicador.objects.all().delete()
        Multiplicador.objects.create(nombre='General subcategorías', valor=2, es_general=True)
        self.admin = self.crear_usuario('admin_subref', 'administrador')
        self.c = self.api(self.admin)
        self.cat = Categoria.objects.create(nombre='Comedor por referencia')
        self.silla = Subcategoria.objects.create(categoria=self.cat, nombre='Silla')
        self.mesa = Subcategoria.objects.create(categoria=self.cat, nombre='Mesa')
        # Valencia con dos proveedores (un grupo en la lista) y Cairo: comparten «Silla».
        self.valencia = [self.referencia(self.proveedor(n), 'Valencia') for n in ['Norte', 'Sur']]
        self.cairo = self.referencia(self.proveedor('Cairo SAS'), 'Cairo')
        for ref in [*self.valencia, self.cairo]:
            ref.categorias.add(self.cat)
            ref.subcategorias.add(self.silla, self.mesa)
            crear_configuracion(ref)
        DisposicionReferenciaPrecio.objects.create(clave='valencia', orden=[self.mesa.pk, self.silla.pk], retiradas=[])
        self.op = OrdenPedido.objects.create(proveedor=self.valencia[0].proveedor, usuario=self.admin, fecha_esperada=date(2026, 11, 1))
        self.det = DetallePedido.objects.create(orden=self.op, referencia=self.valencia[0], subcategoria=self.silla, cantidad=6)

    def renombrar(self, sub, nombre, ref):
        return self.c.post(f'/api/listaprecios/subcategorias/{sub.pk}/renombrar/', {'nombre': nombre, 'referencia': ref.pk}, format='json')

    def subs_de(self, ref):
        return sorted(ref.subcategorias.values_list('nombre', flat=True))


class SubcategoriasPorReferenciaTests(BaseSubcategorias):

    def test_renombrar_en_una_referencia_no_cambia_las_demas(self):
        r = self.renombrar(self.silla, 'Silla de comedor', self.valencia[0])
        self.assertEqual(r.status_code, 200, r.data)
        self.assertTrue(r.data['separada'])
        nueva = Subcategoria.objects.get(pk=r.data['id'])
        self.silla.refresh_from_db()
        self.assertEqual((self.silla.nombre, nueva.nombre, nueva.categoria_id), ('Silla', 'Silla de comedor', self.cat.pk))
        # Solo Valencia de este proveedor pasa a la nueva; el otro proveedor y Cairo conservan «Silla».
        self.assertEqual(self.subs_de(self.valencia[0]), ['Mesa', 'Silla de comedor'])
        v = VarianteProducto.objects.get(linea__referencia=self.valencia[0], subcategoria=nueva)
        self.assertEqual(v.nombre, 'Silla de comedor')
        self.assertEqual(self.subs_de(self.valencia[1]), ['Mesa', 'Silla'])
        self.assertEqual(self.subs_de(self.cairo), ['Mesa', 'Silla'])
        self.assertTrue(VarianteProducto.objects.filter(linea__referencia=self.cairo, subcategoria=self.silla, nombre='Silla').exists())
        # Sus pedidos y su orden en la lista van con la nueva.
        self.det.refresh_from_db()
        self.assertEqual(self.det.subcategoria_id, nueva.pk)
        # El otro proveedor de Valencia sigue con «Silla»: en el orden de la lista quedan las dos.
        self.assertEqual(DisposicionReferenciaPrecio.objects.get(clave='valencia').orden, [self.mesa.pk, self.silla.pk, nueva.pk])

    def test_si_solo_la_usa_esta_referencia_se_renombra_tal_cual(self):
        propia = Subcategoria.objects.create(categoria=self.cat, nombre='Bufé')
        self.cairo.subcategorias.add(propia)
        r = self.renombrar(propia, 'Bifé', self.cairo)
        self.assertEqual((r.status_code, r.data['id'], r.data['separada']), (200, propia.pk, False))
        propia.refresh_from_db()
        self.assertEqual(propia.nombre, 'Bifé')

    def test_no_se_fusiona_con_otra_del_mismo_nombre(self):
        otra = Subcategoria.objects.create(categoria=self.cat, nombre='Silla tapizada')
        self.valencia[1].subcategorias.add(otra)
        r = self.renombrar(self.silla, 'Silla tapizada', self.cairo)
        self.assertEqual(r.status_code, 200, r.data)
        self.assertNotEqual(r.data['id'], otra.pk)  # una propia de Cairo, no la de otra referencia
        self.assertEqual(self.subs_de(self.cairo), ['Mesa', 'Silla tapizada'])
        self.assertEqual(Subcategoria.objects.get(pk=r.data['id']).referencias.count(), 1)
        self.assertEqual(self.subs_de(self.valencia[0]), ['Mesa', 'Silla'])
        # No se puede renombrar a una que la referencia ya tiene.
        self.assertEqual(self.renombrar(self.mesa, 'Silla tapizada', self.cairo).status_code, 400)

    def test_agregar_subcategoria_nueva_a_una_referencia(self):
        url = f'/api/listaprecios/referencias/{self.cairo.pk}/subcategoria-nueva/'
        r = self.c.post(url, {'nombre': 'Banca', 'categoria': self.cat.pk}, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(self.subs_de(self.cairo), ['Banca', 'Mesa', 'Silla'])
        self.assertEqual(self.subs_de(self.valencia[0]), ['Mesa', 'Silla'])
        self.assertEqual(self.c.post(url, {'nombre': 'banca', 'categoria': self.cat.pk}, format='json').status_code, 400)  # ya la tiene
        self.assertEqual(self.c.post(url, {'nombre': 'Otra', 'categoria': 'x'}, format='json').status_code, 400)
        # «Todas» le crea una propia a cada proveedor del grupo; nunca reutiliza la de Cairo.
        r2 = self.c.post(f'/api/listaprecios/referencias/{self.valencia[0].pk}/subcategoria-nueva/', {'nombre': 'Banca', 'categoria': self.cat.pk, 'todas': True}, format='json')
        self.assertEqual(r2.status_code, 201, r2.data)
        self.assertEqual(len(set(r2.data['ids']) | {r.data['id']}), 3)
        for ref in self.valencia:
            self.assertIn('Banca', self.subs_de(ref))
        # Requiere poder editar la lista.
        vendedor = self.crear_usuario('vend_subref')
        self.assertEqual(self.api(vendedor).post(url, {'nombre': 'Z', 'categoria': self.cat.pk}, format='json').status_code, 403)


class CategoriaPorReferenciaTests(BaseSubcategorias):
    """(2026-10-29) La categoría de una subcategoría también se cambia solo en esa referencia."""

    def setUp(self):
        super().setUp()
        self.sala = Categoria.objects.create(nombre='Sala por referencia')

    def cambiar(self, sub, categoria, ref):
        return self.c.post(f'/api/listaprecios/subcategorias/{sub.pk}/categoria/', {'categoria': categoria.pk, 'referencia': ref.pk}, format='json')

    def test_cambia_solo_en_esta_referencia(self):
        from suministros.models import Inventario
        item = Inventario.objects.create(id_referencia='CO-PRUEBA-1', referencia=self.valencia[0], categoria=self.cat, subcategoria=self.silla, costo_especifico=10)
        r = self.cambiar(self.silla, self.sala, self.valencia[0])
        self.assertEqual(r.status_code, 200, r.data)
        self.assertTrue(r.data['separada'])
        nueva = Subcategoria.objects.get(pk=r.data['id'])
        self.assertEqual((nueva.nombre, nueva.categoria_id), ('Silla', self.sala.pk))
        self.silla.refresh_from_db()
        self.assertEqual(self.silla.categoria_id, self.cat.pk)
        self.assertTrue(self.valencia[0].subcategorias.filter(pk=nueva.pk).exists())
        self.assertEqual(set(self.valencia[0].categorias.values_list('pk', flat=True)), {self.cat.pk, self.sala.pk})
        # El otro proveedor de Valencia y Cairo no cambian.
        for ref in (self.valencia[1], self.cairo):
            self.assertTrue(ref.subcategorias.filter(pk=self.silla.pk).exists())
        item.refresh_from_db()
        self.det.refresh_from_db()
        self.assertEqual((item.categoria_id, item.subcategoria_id, self.det.subcategoria_id), (self.sala.pk, nueva.pk, nueva.pk))
        # Sus precios (y la consulta) la muestran en la nueva categoría.
        from .referencias import categoria_variante
        v = VarianteProducto.objects.get(linea__referencia=self.valencia[0], subcategoria=nueva)
        self.assertEqual(categoria_variante(v), self.sala)

    def test_si_solo_la_usa_esta_referencia_cambia_tal_cual(self):
        propia = Subcategoria.objects.create(categoria=self.cat, nombre='Butaco')
        self.cairo.subcategorias.add(propia)
        r = self.cambiar(propia, self.sala, self.cairo)
        self.assertEqual(r.status_code, 200, r.data)
        self.assertFalse(r.data['separada'])
        propia.refresh_from_db()
        self.assertEqual(propia.categoria_id, self.sala.pk)

    def test_misma_categoria_o_ajena(self):
        self.assertEqual(self.cambiar(self.silla, self.cat, self.cairo).status_code, 400)
        otra = Subcategoria.objects.create(categoria=self.cat, nombre='Ajena')
        self.assertEqual(self.cambiar(otra, self.sala, self.cairo).status_code, 400)


class AsignarYSepararTests(BaseSubcategorias):
    """Asignar desde Referencias y la migración que separa las compartidas (2026-11-10)."""

    def test_elegir_del_catalogo_una_ajena_crea_una_propia(self):
        nueva_ref = self.referencia(self.proveedor('Nuevo SAS'), 'Milán')
        r = self.c.patch(f'/api/referencias/{nueva_ref.pk}/', {'subcategorias': [self.silla.pk]}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        propia = nueva_ref.subcategorias.get()
        self.assertNotEqual(propia.pk, self.silla.pk)
        self.assertEqual((propia.nombre, propia.categoria_id), ('Silla', self.cat.pk))
        # Guardar de nuevo con la suya no crea otra.
        self.c.patch(f'/api/referencias/{nueva_ref.pk}/', {'subcategorias': [propia.pk]}, format='json')
        self.assertEqual(list(nueva_ref.subcategorias.values_list('pk', flat=True)), [propia.pk])

    def test_la_migracion_separa_las_compartidas_y_lleva_lo_de_cada_referencia(self):
        import importlib
        from django.apps import apps
        migracion = importlib.import_module('listaprecios.migrations.0029_subcategorias_propias')
        migracion.separar_compartidas(apps, None)
        for sub in (self.silla, self.mesa):
            self.assertEqual(sub.referencias.count(), 1)
        for ref in [*self.valencia, self.cairo]:
            self.assertEqual(self.subs_de(ref), ['Mesa', 'Silla'])
            # Cada ficha de precios apunta a la subcategoría de su referencia.
            for v in VarianteProducto.objects.filter(linea__referencia=ref):
                self.assertTrue(ref.subcategorias.filter(pk=v.subcategoria_id).exists())
        self.det.refresh_from_db()
        self.assertTrue(self.valencia[0].subcategorias.filter(pk=self.det.subcategoria_id).exists())
        # Los dos proveedores de Valencia quedan en el orden de la lista.
        orden = DisposicionReferenciaPrecio.objects.get(clave='valencia').orden
        ids = set(self.valencia[0].subcategorias.values_list('pk', flat=True)) | set(self.valencia[1].subcategorias.values_list('pk', flat=True))
        self.assertEqual(set(orden), ids)

    def test_un_registro_toma_la_subcategoria_de_su_referencia(self):
        # El formulario eligió «Silla» de otra referencia: se guarda con la de Cairo, del mismo nombre.
        import importlib
        from django.apps import apps
        from suministros.models import Inventario
        importlib.import_module('listaprecios.migrations.0029_subcategorias_propias').separar_compartidas(apps, None)
        silla_cairo = self.cairo.subcategorias.get(nombre='Silla')
        ajena = self.valencia[0].subcategorias.get(nombre='Silla')
        self.assertNotEqual(silla_cairo.pk, ajena.pk)
        item = Inventario.objects.create(id_referencia='CO-PROPIA-1', referencia=self.cairo, categoria=self.cat, subcategoria=ajena, costo_especifico=10)
        self.assertEqual(item.subcategoria_id, silla_cairo.pk)
