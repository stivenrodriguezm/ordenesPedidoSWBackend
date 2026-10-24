from django.core.cache import cache

from ordenes.tests.utils import LottusTestCase
from suministros.models import Categoria, Subcategoria
from .disposicion import clave_referencia
from .models import ComponenteJuego, DisposicionReferenciaPrecio, LineaProducto, Multiplicador, VarianteProducto
from .referencias import crear_configuracion


class CatalogoSubcategoriasTests(LottusTestCase):
    def setUp(self):
        cache.clear()
        Multiplicador.objects.all().delete()
        Multiplicador.objects.create(nombre='General catálogo actual', valor=2, es_general=True)
        self.c = self.api(self.crear_usuario('catalogo_actual_admin', 'administrador'))
        self.cat = Categoria.objects.create(nombre='Comedor actual')
        self.mesa = Subcategoria.objects.create(categoria=self.cat, nombre='Mesa de 6p.')
        self.silla = Subcategoria.objects.create(categoria=self.cat, nombre='Silla de comedor')
        self.ref = self.referencia(self.proveedor('Mesas Norte'), 'Valencia')
        self.ref.categorias.add(self.cat)
        self.ref.subcategorias.add(self.mesa, self.silla)
        self.linea = crear_configuracion(self.ref, activo=False)
        self.linea.variantes.update(costo_base=100000, costo_confirmado=True, publicado=True)
        LineaProducto.objects.filter(pk=self.linea.pk).update(activo=True)
        self.producto = self.linea.variantes.get(subcategoria=self.mesa)
        self.antigua = LineaProducto.objects.create(nombre='Valencia antigua', slug='valencia-anterior', activo=True, referencia_archivada=self.ref)
        self.viejo = VarianteProducto.objects.create(linea=self.antigua, nombre='Medida anterior', costo_base=500000)

    def test_consulta_y_ventas_comparten_identidad_y_nombre_del_maestro(self):
        publico = self.c.get('/api/listaprecios/catalogo/').data
        self.assertEqual([l['id'] for l in publico], [self.linea.pk])
        ventas = self.c.get('/api/productos-venta/catalogo/').data['results']
        self.assertEqual({p['id'] for p in ventas}, {p['id'] for p in publico[0]['variantes']})
        self.assertEqual({p['subcategoria'] for p in ventas}, {self.mesa.pk, self.silla.pk})
        for p in ventas:
            self.assertEqual(p['referencia'], self.ref.pk)
            self.assertEqual(p['nombre'], f"Valencia · {p['subcategoria_nombre']}")
            self.assertEqual(p['proveedor'], self.ref.proveedor_id)
            self.assertTrue(p['seleccionable'])
        self.assertNotIn('costo_base', str(publico))
        self.assertNotIn('costo_base', str(ventas))
        self.assertTrue(VarianteProducto.objects.filter(pk=self.viejo.pk).exists())

    def test_proveedores_publicos_pertenecen_a_cada_subcategoria_y_a_las_piezas_del_conjunto(self):
        proveedor_sillas = self.proveedor('Sillas Sur catálogo')
        ref_sillas = self.referencia(proveedor_sillas, 'Valencia')
        ref_sillas.subcategorias.add(self.silla)
        sillas = crear_configuracion(ref_sillas).variantes.get()
        sillas.costo_base, sillas.costo_confirmado = 150000, True
        sillas.save()
        sub = Subcategoria.objects.create(categoria=self.cat, nombre='Comedor de 6p.')
        ref_interna = self.referencia(self.proveedor('Alojamiento interno'), 'Valencia')
        ref_interna.subcategorias.add(sub)
        juego = crear_configuracion(ref_interna).variantes.get()
        ComponenteJuego.objects.create(juego=juego, variante=self.producto, cantidad=1)
        ComponenteJuego.objects.create(juego=juego, variante=sillas, cantidad=6)
        juego.costo_confirmado, juego.publicado = True, True
        juego.save()
        publico = self.c.get('/api/listaprecios/catalogo/', {'q': 'Valencia'}).data
        fichas = {v['id']: v for linea in publico for v in linea['variantes']}
        self.assertEqual(fichas[self.producto.pk]['proveedores'], [{'id': self.ref.proveedor_id, 'nombre': 'Mesas Norte'}])
        self.assertEqual({p['id'] for p in fichas[juego.pk]['proveedores']}, {self.ref.proveedor_id, proveedor_sillas.pk})
        self.assertNotIn(ref_interna.proveedor_id, [p['id'] for p in fichas[juego.pk]['proveedores']])
        self.assertEqual(fichas[juego.pk]['subcategoria'], sub.pk)
        self.assertNotIn('costo_base', fichas[juego.pk])

    def test_un_nombre_actualizado_aparece_en_ambos_selectores_sin_reasignar_ids(self):
        self.c.get('/api/listaprecios/catalogo/')
        with self.captureOnCommitCallbacks(execute=True):
            r = self.c.post(f'/api/listaprecios/subcategorias/{self.mesa.pk}/renombrar/', {'nombre': 'Mesa grande'}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        publico = self.c.get('/api/listaprecios/catalogo/').data[0]['variantes']
        self.assertEqual(next(v for v in publico if v['id'] == self.producto.pk)['nombre'], 'Mesa grande')
        ventas = self.c.get('/api/productos-venta/catalogo/', {'q': 'Mesa grande'}).data['results']
        self.assertEqual([v['id'] for v in ventas], [self.producto.pk])
        self.assertEqual(ventas[0]['subcategoria'], self.mesa.pk)

    def test_no_ofrece_fichas_sin_subcategoria_o_ya_desasignadas(self):
        suelta = Subcategoria.objects.create(categoria=self.cat, nombre='No asignada')
        for sub in [None, suelta]:
            VarianteProducto.objects.create(linea=self.linea, subcategoria=sub, nombre='No ofrecer', costo_base=20000)
        ids = {v.pk for v in self.linea.variantes.filter(subcategoria__in=[self.mesa, self.silla])}
        self.assertEqual({p['id'] for p in self.c.get('/api/productos-venta/catalogo/').data['results']}, ids)
        self.assertEqual({p['id'] for p in self.c.get('/api/listaprecios/catalogo/').data[0]['variantes']}, ids)

    def test_borradores_y_costos_no_confirmados_no_se_pueden_seleccionar(self):
        self.linea.variantes.filter(pk=self.producto.pk).update(costo_confirmado=False)
        r = self.c.get('/api/productos-venta/catalogo/').data['results']
        item = next(p for p in r if p['id'] == self.producto.pk)
        self.assertEqual(item['estado_precio'], 'sin_costo')
        self.assertFalse(item['seleccionable'])
        self.assertEqual(self.c.get(f'/api/listaprecios/variantes/{self.producto.pk}/precio/').status_code, 404)
        LineaProducto.objects.filter(pk=self.linea.pk).update(activo=False)
        self.linea.variantes.update(publicado=False)
        cache.clear()  # cambio directo en la base (sin señales): la caché del catálogo no se entera
        self.assertEqual(self.c.get('/api/listaprecios/catalogo/', {'q': 'Valencia'}).data, [])
        self.assertTrue(all(not p['seleccionable'] and p['estado_precio'] == 'borrador' for p in self.c.get('/api/productos-venta/catalogo/').data['results']))

    def test_historia_sigue_legible_por_id_pero_no_se_ofrece_en_busquedas(self):
        r = self.c.get('/api/productos-venta/catalogo/', {'id': self.viejo.pk})
        self.assertEqual(r.status_code, 200, r.data)
        self.assertFalse(r.data['results'][0]['catalogo_actual'])
        self.assertFalse(r.data['results'][0]['seleccionable'])
        self.assertEqual(self.c.get('/api/listaprecios/variantes/%s/precio/' % self.viejo.pk).status_code, 404)

    def test_orden_y_bajas_de_administracion_se_respetan_en_ambos_selectores(self):
        DisposicionReferenciaPrecio.objects.create(clave=clave_referencia(self.ref.nombre), orden=[self.silla.pk, self.mesa.pk])
        publico = self.c.get('/api/listaprecios/catalogo/', {'q': 'Valencia'}).data[0]['variantes']
        ventas = self.c.get('/api/productos-venta/catalogo/').data['results']
        self.assertEqual([v['subcategoria'] for v in publico], [self.silla.pk, self.mesa.pk])
        self.assertEqual([v['subcategoria'] for v in ventas], [self.silla.pk, self.mesa.pk])
        DisposicionReferenciaPrecio.objects.update(retiradas=[self.mesa.pk])
        cache.clear()  # cambio directo en la base (sin señales)
        self.assertEqual([v['subcategoria'] for v in self.c.get('/api/productos-venta/catalogo/').data['results']], [self.silla.pk])

    def test_proveedores_homonimos_no_se_mezclan_al_buscar_y_elegir(self):
        otra = self.referencia(self.proveedor('Sillas Sur'), 'Valencia')
        otra.subcategorias.add(self.silla)
        linea = crear_configuracion(otra, activo=False)
        linea.variantes.update(costo_base=150000, costo_confirmado=True, publicado=True)
        LineaProducto.objects.filter(pk=linea.pk).update(activo=True)
        r = self.c.get('/api/productos-venta/catalogo/', {'q': 'Sillas Sur'}).data['results']
        self.assertEqual(len(r), 1)
        self.assertEqual(r[0]['referencia'], otra.pk)
        self.assertEqual(r[0]['subcategoria'], self.silla.pk)
        detalle = self.c.get('/api/productos-venta/catalogo/', {'id': r[0]['id']}).data['results'][0]
        self.assertEqual(detalle['referencias'], [{'id': otra.pk, 'nombre': 'Valencia · Silla de comedor · Sillas Sur'}])

    def test_publicar_una_ficha_no_publica_la_otra_ni_exige_su_costo(self):
        self.linea.variantes.update(publicado=False)
        self.linea.variantes.exclude(pk=self.producto.pk).update(costo_confirmado=False)
        LineaProducto.objects.filter(pk=self.linea.pk).update(activo=False)
        r = self.c.patch(f'/api/listaprecios/variantes/{self.producto.pk}/', {'publicado': True}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.assertTrue(r.data['publicado'])
        self.assertEqual(self.linea.variantes.filter(publicado=True).count(), 1)
        publico = self.c.get('/api/listaprecios/catalogo/', {'q': 'Valencia'}).data
        self.assertEqual([v['id'] for v in publico[0]['variantes']], [self.producto.pk])
        estados = {v['id']: v['seleccionable'] for v in self.c.get('/api/productos-venta/catalogo/').data['results']}
        self.assertTrue(estados[self.producto.pk])
        self.assertFalse(next(valor for pk, valor in estados.items() if pk != self.producto.pk))
        self.assertEqual(self.c.get(f'/api/listaprecios/variantes/{self.producto.pk}/precio/').status_code, 200)

    def test_cero_debe_confirmarse_y_publicar_no_modifica_el_costo(self):
        self.linea.variantes.filter(pk=self.producto.pk).update(publicado=False, costo_confirmado=False, costo_base=0)
        url = f'/api/listaprecios/variantes/{self.producto.pk}/'
        r = self.c.patch(url, {'publicado': True}, format='json')
        self.assertEqual(r.status_code, 400, r.data)
        self.assertIn('publicado', r.data)
        self.assertFalse(VarianteProducto.objects.get(pk=self.producto.pk).publicado)
        self.assertEqual(self.c.patch(url, {'costo_base': 0}, format='json').status_code, 200)
        r = self.c.patch(url, {'publicado': True}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data['costo_base'], '0.00')
        self.assertTrue(r.data['publicado'])

    def test_quitar_publicacion_de_una_ficha_conserva_las_otras_y_los_proveedores(self):
        otra = self.referencia(self.proveedor('Proveedor publicación independiente'), 'Valencia')
        otra.subcategorias.add(self.mesa)
        linea = crear_configuracion(otra)
        linea.variantes.update(costo_base=777000, costo_confirmado=True, publicado=True)
        r = self.c.patch(f'/api/listaprecios/variantes/{self.producto.pk}/', {'publicado': False}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        cache.clear()
        publico = self.c.get('/api/listaprecios/catalogo/').data
        ids = {v['id'] for l in publico for v in l['variantes']}
        self.assertNotIn(self.producto.pk, ids)
        self.assertIn(linea.variantes.get().pk, ids)
        self.assertIn(self.linea.variantes.get(subcategoria=self.silla).pk, ids)
        self.producto.refresh_from_db()
        self.assertEqual(self.producto.costo_base, 100000)
        self.assertEqual(self.c.get(f'/api/listaprecios/variantes/{self.producto.pk}/precio/').status_code, 404)

    def test_subcategoria_retirada_no_se_publica_y_costo_se_revalida_al_guardar(self):
        from rest_framework.exceptions import ValidationError
        from .serializers import VarianteProductoSerializer
        self.producto.publicado = False
        self.producto.save()
        serializador = VarianteProductoSerializer(self.producto, data={'publicado': True}, partial=True)
        self.assertTrue(serializador.is_valid(), serializador.errors)
        VarianteProducto.objects.filter(pk=self.producto.pk).update(costo_confirmado=False)
        with self.assertRaises(ValidationError):
            serializador.save()
        self.assertFalse(VarianteProducto.objects.get(pk=self.producto.pk).publicado)
        VarianteProducto.objects.filter(pk=self.producto.pk).update(costo_confirmado=True)
        DisposicionReferenciaPrecio.objects.create(clave=clave_referencia(self.ref.nombre), retiradas=[self.mesa.pk])
        r = self.c.patch(f'/api/listaprecios/variantes/{self.producto.pk}/', {'publicado': True}, format='json')
        self.assertEqual(r.status_code, 400, r.data)
        self.assertIn('publicado', r.data)

    def test_agregar_subcategoria_no_retira_las_ya_publicadas(self):
        from .referencias import sincronizar_subcategorias
        nueva = Subcategoria.objects.create(categoria=self.cat, nombre='Banca de comedor')
        self.ref.subcategorias.add(nueva)
        sincronizar_subcategorias(self.linea)
        self.assertFalse(self.linea.variantes.get(subcategoria=nueva).publicado)
        self.producto.refresh_from_db()
        self.assertTrue(self.producto.publicado)
        publico = self.c.get('/api/listaprecios/catalogo/', {'q': 'Valencia'}).data
        self.assertIn(self.producto.pk, {v['id'] for l in publico for v in l['variantes']})
