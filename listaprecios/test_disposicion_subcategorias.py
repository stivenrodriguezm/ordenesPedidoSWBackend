from decimal import Decimal

from django.core.cache import cache
from ordenes.models import Referencia
from ordenes.tests.utils import LottusTestCase
from suministros.models import Categoria, Subcategoria
from .models import Cotizacion, DisposicionReferenciaPrecio, LineaCotizacion, Multiplicador, VarianteProducto
from .referencias import crear_configuracion


class DisposicionSubcategoriasTests(LottusTestCase):
    def setUp(self):
        cache.clear()
        Multiplicador.objects.all().delete()
        Multiplicador.objects.create(nombre='General disposición', valor=2, es_general=True)
        self.admin = self.crear_usuario('admin_disposicion', 'administrador')
        self.c = self.api(self.admin)
        self.cat = Categoria.objects.create(nombre='Comedor edición')
        self.subs = [Subcategoria.objects.create(categoria=self.cat, nombre=n) for n in ['Mesa', 'Silla', 'Comedor']]
        self.refs = [self.referencia(self.proveedor(n), 'Valencia') for n in ['Norte', 'Sur']]
        self.lineas = []
        for ref in self.refs:
            ref.categorias.add(self.cat)
            ref.subcategorias.add(*self.subs)
            linea = crear_configuracion(ref)
            linea.variantes.update(costo_base=100, costo_confirmado=True, publicado=True)
            linea.activo = True
            linea.save()
            self.lineas.append(linea)
        self.url = f'/api/listaprecios/referencias/{self.refs[0].pk}/disposicion/'

    def guardar(self, revision=0, **datos):
        with self.captureOnCommitCallbacks(execute=True):
            return self.c.post(self.url, {'revision': revision, **datos}, format='json')

    def catalogo(self):
        cache.clear()
        return [l for l in self.c.get('/api/listaprecios/catalogo/').data if l['id'] in [x.pk for x in self.lineas]]

    def test_orden_compartido_persiste_en_admin_y_consulta_para_ambos_proveedores(self):
        orden = [s.pk for s in reversed(self.subs)]
        r = self.guardar(orden=orden)
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data['revision'], 1)
        self.assertEqual(set(r.data['referencias']), {r.pk for r in self.refs})
        for linea in self.catalogo():
            self.assertEqual([v['subcategoria'] for v in linea['variantes']], orden)
        for linea in self.lineas:
            datos = self.c.get(f'/api/listaprecios/lineas/{linea.pk}/').data
            self.assertEqual([v['subcategoria'] for v in datos['variantes']], orden)

    def test_rechaza_orden_incompleto_repetido_y_ajeno_sin_escribir(self):
        ajena = Subcategoria.objects.create(categoria=self.cat, nombre='Ajena')
        for orden in ([self.subs[0].pk], [s.pk for s in self.subs] + [self.subs[0].pk], [self.subs[0].pk, self.subs[1].pk, ajena.pk]):
            r = self.guardar(orden=orden)
            self.assertEqual(r.status_code, 400, r.data)
        self.assertFalse(DisposicionReferenciaPrecio.objects.exists())

    def test_conflicto_de_sesion_devuelve_409_y_conserva_orden_confirmado(self):
        orden = [s.pk for s in self.subs]
        self.assertEqual(self.guardar(orden=orden).status_code, 200)
        r = self.guardar(orden=list(reversed(orden)))
        self.assertEqual(r.status_code, 409, r.data)
        self.assertEqual(DisposicionReferenciaPrecio.objects.get().orden, orden)

    def test_eliminar_es_reversible_sin_borrar_costos_ni_asignaciones_maestras(self):
        antes = list(VarianteProducto.objects.filter(linea__in=self.lineas).values('pk', 'subcategoria_id', 'costo_base'))
        r = self.guardar(retiradas=[self.subs[0].pk])
        self.assertEqual(r.status_code, 200, r.data)
        for linea in self.catalogo():
            self.assertNotIn(self.subs[0].pk, [v['subcategoria'] for v in linea['variantes']])
            self.assertEqual(Decimal(linea['desde']), 200)
        variante = self.lineas[0].variantes.get(subcategoria=self.subs[0])
        self.assertEqual(self.c.get(f'/api/listaprecios/variantes/{variante.pk}/precio/').status_code, 404)
        self.assertEqual(list(VarianteProducto.objects.filter(linea__in=self.lineas).values('pk', 'subcategoria_id', 'costo_base')), antes)
        self.assertTrue(all(r.subcategorias.count() == 3 for r in self.refs))
        self.assertEqual(self.guardar(1, retiradas=[]).status_code, 200)
        self.assertEqual(len(self.catalogo()[0]['variantes']), 3)

    def test_publicacion_ignora_costos_de_subcategorias_retiradas_y_no_publica_lista_vacia(self):
        self.lineas[0].variantes.filter(subcategoria=self.subs[0]).update(costo_confirmado=False)
        self.guardar(retiradas=[self.subs[0].pk])
        url = f'/api/listaprecios/lineas/{self.lineas[0].pk}/'
        self.assertEqual(self.c.patch(url, {'activo': True}, format='json').status_code, 200)
        self.guardar(1, retiradas=[s.pk for s in self.subs])
        self.assertEqual(self.c.patch(url, {'activo': True}, format='json').status_code, 400)
        self.assertEqual(self.catalogo(), [])

    def test_arrastre_por_proveedor_actualiza_el_orden_unificado(self):
        productos = list(self.lineas[0].variantes.all())
        antes = [v.pk for v in productos]
        r = self.c.post(f'/api/listaprecios/lineas/{self.lineas[0].pk}/orden-variantes/', {
            'variantes': list(reversed(antes)), 'orden_anterior': antes,
        }, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.assertIn('referencias', r.data['disposicion'])
        esperado = [v.subcategoria_id for v in reversed(productos)]
        self.assertEqual([v['subcategoria'] for v in self.catalogo()[1]['variantes']], esperado)

    def test_renombrar_actualiza_el_maestro_compartido_sin_reescribir_documentos(self):
        variante = self.lineas[0].variantes.get(subcategoria=self.subs[0])
        cot = Cotizacion.objects.create(numero='EDICION-HISTORICA', asesor=self.admin)
        historica = LineaCotizacion.objects.create(cotizacion=cot, variante=variante, linea_nombre='Valencia', variante_nombre='Mesa original', precio_unitario=200, subtotal=200)
        refs_antes = list(Referencia.objects.values('pk', 'nombre', 'proveedor_id'))
        r = self.c.post(f'/api/listaprecios/subcategorias/{self.subs[0].pk}/renombrar/', {'nombre': 'Mesa de seis puestos'}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data['referencias_uso'], 2)
        self.assertEqual(list(Referencia.objects.values('pk', 'nombre', 'proveedor_id')), refs_antes)
        for linea in self.catalogo():
            self.assertIn('Mesa de seis puestos', [v['nombre'] for v in linea['variantes']])
        self.guardar(retiradas=[self.subs[0].pk])
        historica.refresh_from_db()
        self.assertEqual(historica.variante_nombre, 'Mesa original')
        self.assertEqual(historica.variante_id, variante.pk)
        self.assertEqual(historica.precio_unitario, 200)

    def test_nombre_vacio_largo_o_duplicado_se_rechaza(self):
        url = f'/api/listaprecios/subcategorias/{self.subs[0].pk}/renombrar/'
        for nombre in ['  ', 'X' * 101, 'silla']:
            r = self.c.post(url, {'nombre': nombre}, format='json')
            self.assertEqual(r.status_code, 400, r.data)
        self.subs[0].refresh_from_db()
        self.assertEqual(self.subs[0].nombre, 'Mesa')

    def test_solo_el_editor_puede_ordenar_eliminar_o_renombrar(self):
        lector = self.crear_usuario('lector_disposicion', 'marketing')
        self.permisos('marketing', ['VER_COSTOS_LISTA_PRECIOS'])
        api = self.api(lector)
        self.assertEqual(api.get('/api/listaprecios/referencias/').status_code, 200)
        self.assertEqual(api.post(self.url, {'revision': 0, 'retiradas': [self.subs[0].pk]}, format='json').status_code, 403)
        self.assertEqual(api.post(f'/api/listaprecios/subcategorias/{self.subs[0].pk}/renombrar/', {'nombre': 'Cambio'}, format='json').status_code, 403)


    def test_cotizacion_nueva_rechaza_una_seleccion_retirada_aunque_llegue_desde_un_carrito_anterior(self):
        variante = self.lineas[0].variantes.get(subcategoria=self.subs[0])
        self.guardar(retiradas=[self.subs[0].pk])
        r = self.c.post('/api/listaprecios/cotizaciones/', {'cliente_nombre': 'Prueba', 'lineas': [{
            'variante': variante.pk, 'linea_nombre': 'Valencia', 'variante_nombre': 'Mesa', 'cantidad': 1, 'precio_unitario': '200',
        }]}, format='json')
        self.assertEqual(r.status_code, 400, r.data)
        self.assertFalse(Cotizacion.objects.filter(cliente_nombre='Prueba').exists())
