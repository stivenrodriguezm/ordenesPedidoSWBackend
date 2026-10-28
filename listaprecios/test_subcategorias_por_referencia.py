"""(2026-10-28) Las subcategorías van asociadas a la referencia: renombrar desde Administrar lista
solo cambia esa referencia (y las de su grupo); se pueden agregar subcategorías nuevas a una referencia."""
from datetime import date

from django.core.cache import cache

from ordenes.models import DetallePedido, OrdenPedido
from ordenes.tests.utils import LottusTestCase
from suministros.models import Categoria, Subcategoria
from .models import DisposicionReferenciaPrecio, Multiplicador, VarianteProducto
from .referencias import crear_configuracion


class SubcategoriasPorReferenciaTests(LottusTestCase):
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

    def test_renombrar_en_una_referencia_no_cambia_las_demas(self):
        r = self.renombrar(self.silla, 'Silla de comedor', self.valencia[0])
        self.assertEqual(r.status_code, 200, r.data)
        self.assertTrue(r.data['separada'])
        nueva = Subcategoria.objects.get(pk=r.data['id'])
        self.silla.refresh_from_db()
        self.assertEqual((self.silla.nombre, nueva.nombre, nueva.categoria_id), ('Silla', 'Silla de comedor', self.cat.pk))
        # Valencia (sus dos proveedores) pasa a la nueva; Cairo conserva «Silla».
        for ref in self.valencia:
            self.assertEqual(self.subs_de(ref), ['Mesa', 'Silla de comedor'])
            v = VarianteProducto.objects.get(linea__referencia=ref, subcategoria=nueva)
            self.assertEqual(v.nombre, 'Silla de comedor')
        self.assertEqual(self.subs_de(self.cairo), ['Mesa', 'Silla'])
        self.assertTrue(VarianteProducto.objects.filter(linea__referencia=self.cairo, subcategoria=self.silla, nombre='Silla').exists())
        # Sus pedidos y su orden en la lista van con la nueva.
        self.det.refresh_from_db()
        self.assertEqual(self.det.subcategoria_id, nueva.pk)
        self.assertEqual(DisposicionReferenciaPrecio.objects.get(clave='valencia').orden, [self.mesa.pk, nueva.pk])

    def test_si_solo_la_usa_esta_referencia_se_renombra_tal_cual(self):
        propia = Subcategoria.objects.create(categoria=self.cat, nombre='Bufé')
        self.cairo.subcategorias.add(propia)
        r = self.renombrar(propia, 'Bifé', self.cairo)
        self.assertEqual((r.status_code, r.data['id'], r.data['separada']), (200, propia.pk, False))
        propia.refresh_from_db()
        self.assertEqual(propia.nombre, 'Bifé')

    def test_si_el_nombre_ya_existe_en_la_categoria_usa_esa(self):
        otra = Subcategoria.objects.create(categoria=self.cat, nombre='Silla tapizada')
        r = self.renombrar(self.silla, 'silla tapizada', self.cairo)
        self.assertEqual((r.status_code, r.data['id']), (200, otra.pk))
        self.assertEqual(self.subs_de(self.cairo), ['Mesa', 'Silla tapizada'])
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
        # «Todas» la agrega a todos los proveedores del grupo y reutiliza la del catálogo; si estaba retirada, vuelve.
        DisposicionReferenciaPrecio.objects.filter(clave='valencia').update(retiradas=[r.data['id']])
        r2 = self.c.post(f'/api/listaprecios/referencias/{self.valencia[0].pk}/subcategoria-nueva/', {'nombre': 'Banca', 'categoria': self.cat.pk, 'todas': True}, format='json')
        self.assertEqual((r2.status_code, r2.data['id']), (201, r.data['id']))
        for ref in self.valencia:
            self.assertIn('Banca', self.subs_de(ref))
        self.assertEqual(DisposicionReferenciaPrecio.objects.get(clave='valencia').retiradas, [])
        # Requiere poder editar la lista.
        vendedor = self.crear_usuario('vend_subref')
        self.assertEqual(self.api(vendedor).post(url, {'nombre': 'Z', 'categoria': self.cat.pk}, format='json').status_code, 403)
