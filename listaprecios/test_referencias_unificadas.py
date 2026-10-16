from decimal import Decimal

from django.core.cache import cache
from django.db import connection
from django.test.utils import CaptureQueriesContext

from ordenes.models import Referencia
from ordenes.productos_venta import referencias_sugeridas
from ordenes.tests.utils import LottusTestCase
from suministros.models import Categoria, Subcategoria
from .models import LineaProducto, Multiplicador, VarianteProducto


class ReferenciasUnificadasTests(LottusTestCase):
    def setUp(self):
        cache.clear()
        Multiplicador.objects.all().delete()
        Multiplicador.objects.create(nombre='General', valor=2, es_general=True)
        self.c = self.api(self.crear_usuario('admin_unificado', 'administrador'))
        self.ref = self.referencia(self.proveedor(), 'Detroit')
        self.cat = Categoria.objects.create(nombre='Sala unificada')
        self.sub = Subcategoria.objects.create(categoria=self.cat, nombre='Sofá 3 puestos')
        self.ref.categorias.add(self.cat)
        self.ref.subcategorias.add(self.sub)

    def configurar(self, ref=None):
        r = self.c.post('/api/listaprecios/lineas/', {'referencia': (ref or self.ref).pk}, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        return r.data

    def producto(self, linea, **datos):
        producto = next(v for v in linea['variantes'] if v['subcategoria'] == self.sub.pk)
        r = self.c.patch(f"/api/listaprecios/variantes/{producto['id']}/", {'costo_base': 100000, **datos}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        return r.data

    def test_configurar_precios_no_crea_ni_modifica_referencias(self):
        antes = list(Referencia.objects.values('id', 'nombre', 'proveedor_id'))
        linea = self.configurar()
        self.producto(linea)
        self.assertEqual(list(Referencia.objects.values('id', 'nombre', 'proveedor_id')), antes)
        self.assertEqual(list(self.ref.categorias.values_list('pk', flat=True)), [self.cat.pk])
        self.assertEqual(list(self.ref.subcategorias.values_list('pk', flat=True)), [self.sub.pk])

    def test_referencias_iguales_de_distintos_proveedores_son_independientes(self):
        otra = self.referencia(self.proveedor('Otro fabricante'), 'Detroit')
        a, b = self.configurar(), self.configurar(otra)
        self.assertNotEqual(a['id'], b['id'])
        self.assertNotEqual(a['proveedor'], b['proveedor'])
        self.assertEqual(a['nombre'], b['nombre'])

    def test_nombre_de_la_referencia_es_canonico_incluso_si_el_precio_guarda_otro(self):
        linea = self.configurar()
        LineaProducto.objects.filter(pk=linea['id']).update(nombre='Nombre antiguo')
        self.ref.nombre = 'Detroit actualizado'
        self.ref.save()
        r = self.c.get(f"/api/listaprecios/lineas/{linea['id']}/")
        self.assertEqual(r.data['nombre'], self.ref.nombre)
        self.assertEqual(r.data['proveedor_nombre'], self.ref.proveedor.nombre_empresa)

    def test_no_se_puede_reasignar_la_configuracion_a_otra_referencia(self):
        linea = self.configurar()
        otra = self.referencia(self.proveedor(), 'Roma')
        r = self.c.patch(f"/api/listaprecios/lineas/{linea['id']}/", {'referencia': otra.pk}, format='json')
        self.assertEqual(r.status_code, 400)
        self.assertEqual(LineaProducto.objects.get(pk=linea['id']).referencia_id, self.ref.pk)

    def test_variante_usa_categoria_y_tipo_de_referencia_sin_catalogo_paralelo(self):
        variante = self.producto(self.configurar())
        self.assertEqual(variante['nombre'], self.sub.nombre)
        self.assertEqual(variante['categoria'], self.cat.pk)
        self.assertEqual(variante['subcategoria'], self.sub.pk)
        self.assertEqual(variante['referencia'], self.ref.pk)
        obj = VarianteProducto.objects.get(pk=variante['id'])
        self.assertIsNone(obj.categoria_id)
        self.assertEqual(obj.categoria_referencia_id, self.cat.pk)

    def test_tipo_y_categoria_ajenos_se_rechazan(self):
        linea = self.configurar()
        cat = Categoria.objects.create(nombre='Otra categoría')
        sub = Subcategoria.objects.create(categoria=cat, nombre='Otra pieza')
        for datos in ({'subcategoria': sub.pk}, {'categoria': cat.pk}):
            r = self.c.post('/api/listaprecios/variantes/', {'linea': linea['id'], 'nombre': 'Producto', 'costo_base': 100, **datos}, format='json')
            self.assertEqual(r.status_code, 400, r.data)

    def test_referencia_sin_subcategorias_no_inventa_variantes(self):
        ref = self.referencia(self.proveedor(), 'Sin clasificación')
        linea = self.configurar(ref)
        self.assertEqual(linea['variantes'], [])
        r = self.c.post('/api/listaprecios/variantes/', {'linea': linea['id'], 'nombre': 'Medida 180 cm', 'costo_base': 120000}, format='json')
        self.assertEqual(r.status_code, 400, r.data)
        self.assertFalse(ref.subcategorias.exists())

    def test_catalogo_publica_solo_despues_de_revisar_y_conserva_privacidad(self):
        linea = self.configurar()
        producto = self.producto(linea)
        self.assertNotIn(linea['id'], [l['id'] for l in self.c.get('/api/listaprecios/catalogo/').data])
        self.c.patch(f"/api/listaprecios/lineas/{linea['id']}/", {'activo': True}, format='json')
        cache.clear()
        item = next(l for l in self.c.get('/api/listaprecios/catalogo/').data if l['id'] == linea['id'])
        self.assertEqual(item['referencia'], self.ref.pk)
        self.assertEqual(item['variantes'][0]['id'], producto['id'])
        self.assertEqual(Decimal(item['variantes'][0]['precios'][0]['precio']), Decimal(200000))
        self.assertNotIn('costo_base', item['variantes'][0])
        self.assertNotIn('multiplicador', item['variantes'][0])

    def test_referencias_incluye_pendientes_y_listas_sin_calcular_precios(self):
        self.configurar()
        pendiente = self.referencia(self.proveedor(), 'Pendiente')
        with CaptureQueriesContext(connection) as consultas:
            r = self.c.get('/api/listaprecios/referencias/')
        self.assertEqual(r.status_code, 200, r.data)
        self.assertIsNone(next(d for d in r.data if d['id'] == pendiente.pk)['linea'])
        self.assertEqual(next(d for d in r.data if d['id'] == self.ref.pk)['linea']['referencia'], self.ref.pk)
        self.assertLessEqual(len(consultas), 18)
        self.assertFalse(any('listaprecios_grupotela' in q['sql'] for q in consultas))

    def test_pedidos_y_ventas_reciben_la_referencia_exacta_sin_adivinar_nombre(self):
        producto = self.producto(self.configurar())
        self.referencia(self.proveedor('Proveedor parecido'), 'Detroit')
        self.assertEqual([r.pk for r in referencias_sugeridas(VarianteProducto.objects.get(pk=producto['id']))], [self.ref.pk])

    def test_conjunto_usa_clasificacion_existente_y_suma_sin_nuevo_margen(self):
        linea = self.configurar()
        pieza = self.producto(linea)
        conjunto = Subcategoria.objects.create(categoria=self.cat, nombre='Conjunto')
        self.ref.subcategorias.add(conjunto)
        self.c.post(f"/api/listaprecios/lineas/{linea['id']}/sincronizar-subcategorias/")
        r = self.c.post(f"/api/listaprecios/lineas/{linea['id']}/agrupaciones/", {
            'subcategoria': conjunto.pk, 'componentes': [{'variante': pieza['id'], 'cantidad': 2}],
        }, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(Decimal(r.data['costo_total_producto']), Decimal(200000))
        self.assertEqual(Decimal(r.data['precios_venta'][0]['precio']), Decimal(400000))

    def test_lectura_de_referencias_no_concede_escritura(self):
        lector = self.crear_usuario('lector_precio_unificado', 'marketing')
        self.permisos('marketing', ['VER_COSTOS_LISTA_PRECIOS'])
        api = self.api(lector)
        self.assertEqual(api.get('/api/listaprecios/referencias/').status_code, 200)
        self.assertEqual(api.get('/api/listaprecios/clasificacion/').status_code, 200)
        self.assertEqual(api.post('/api/listaprecios/referencias/', {'nombre': 'No crear'}, format='json').status_code, 405)
        self.assertEqual(api.post('/api/listaprecios/lineas/', {'referencia': self.ref.pk}, format='json').status_code, 403)
        self.assertEqual(self.c.post('/api/listaprecios/categorias/', {'nombre': 'Categoría duplicada'}, format='json').status_code, 405)

    def test_importacion_usa_referencia_inequivoca_y_no_inventa_consumo_de_cuero(self):
        from .management.commands.importar_lista_precios import Command
        comando = Command()
        comando.reporte = {'lineas_creadas': 0, 'variantes_creadas': 0, 'filas_omitidas': [], 'precios_calculados': 0, 'precios_override': 0}
        datos = {'nombre': self.ref.nombre, 'notas': '', 'variantes': [{'nombre': self.sub.nombre, 'costo': Decimal(100), 'metraje': Decimal(2), 'precios_cache': {}}]}
        linea = comando._guardar_linea(datos, None, {}, Decimal(2), {}, 'SALAS')
        self.assertEqual(linea.referencia_id, self.ref.pk)
        self.assertFalse(linea.activo)
        self.assertIsNone(linea.variantes.get().decimetraje_cuero)
        self.referencia(self.proveedor('Segundo fabricante'), self.ref.nombre)
        self.assertIsNone(comando._guardar_linea(datos, None, {}, Decimal(2), {}, 'SALAS'))
        self.assertEqual(linea.variantes.count(), 1)

    def test_decorativos_se_identifican_por_configuracion_y_no_por_slug(self):
        from .decorativos import es_decorativo
        linea = self.configurar()
        producto = self.producto(linea)
        r = self.c.patch(f"/api/listaprecios/lineas/{linea['id']}/", {'es_decorativo': True, 'activo': True}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.assertTrue(es_decorativo(VarianteProducto.objects.get(pk=producto['id'])))
        cache.clear()
        publico = next(l for l in self.c.get('/api/listaprecios/catalogo/').data if l['id'] == linea['id'])
        self.assertTrue(publico['es_decorativo'])

    def test_configurar_crea_una_ficha_por_subcategoria_y_no_publica_ceros_iniciales(self):
        segunda = Subcategoria.objects.create(categoria=self.cat, nombre='Poltrona')
        self.ref.subcategorias.add(segunda)
        linea = self.configurar()
        self.assertEqual({v['subcategoria'] for v in linea['variantes']}, {self.sub.pk, segunda.pk})
        self.assertTrue(all(not v['costo_confirmado'] for v in linea['variantes']))
        r = self.c.patch(f"/api/listaprecios/lineas/{linea['id']}/", {'activo': True}, format='json')
        self.assertEqual(r.status_code, 400, r.data)
        for v in linea['variantes']:
            self.c.patch(f"/api/listaprecios/variantes/{v['id']}/", {'costo_base': 0}, format='json')
        r = self.c.patch(f"/api/listaprecios/lineas/{linea['id']}/", {'activo': True}, format='json')
        self.assertEqual(r.status_code, 200, r.data)

    def test_no_duplica_ni_reasigna_ni_renombra_subcategorias_desde_precios(self):
        linea = self.configurar()
        producto = linea['variantes'][0]
        otra = Subcategoria.objects.create(categoria=self.cat, nombre='Otro tipo')
        self.ref.subcategorias.add(otra)
        for patch in ({'subcategoria': otra.pk}, {'subcategoria': None}, {'nombre': 'Nombre inventado'}):
            r = self.c.patch(f"/api/listaprecios/variantes/{producto['id']}/", patch, format='json')
            self.assertEqual(r.status_code, 400, r.data)
        r = self.c.post('/api/listaprecios/variantes/', {'linea': linea['id'], 'subcategoria': self.sub.pk, 'costo_base': 200}, format='json')
        self.assertEqual(r.status_code, 400, r.data)
        r = self.c.delete(f"/api/listaprecios/variantes/{producto['id']}/")
        self.assertEqual(r.status_code, 400, r.data)
        self.assertEqual(VarianteProducto.objects.filter(linea_id=linea['id']).count(), 1)

    def test_actualizar_subcategorias_es_idempotente_preserva_costos_y_exige_revision(self):
        linea = self.configurar()
        producto = self.producto(linea)
        self.c.patch(f"/api/listaprecios/lineas/{linea['id']}/", {'activo': True}, format='json')
        nueva = Subcategoria.objects.create(categoria=self.cat, nombre='Poltrona')
        self.ref.subcategorias.add(nueva)
        for _ in range(2):
            r = self.c.post(f"/api/listaprecios/lineas/{linea['id']}/sincronizar-subcategorias/")
            self.assertEqual(r.status_code, 200, r.data)
            self.assertFalse(r.data['activo'])
            self.assertEqual(len(r.data['variantes']), 2)
            anterior = next(v for v in r.data['variantes'] if v['id'] == producto['id'])
            self.assertEqual(Decimal(anterior['costo_base']), 100000)
        self.assertEqual(Referencia.objects.get(pk=self.ref.pk).subcategorias.count(), 2)

    def test_cambiar_nombre_y_categoria_maestros_se_refleja_en_admin_y_consulta(self):
        linea = self.configurar()
        self.producto(linea)
        cat = Categoria.objects.create(nombre='Categoría actual')
        self.sub.nombre, self.sub.categoria = 'Nombre actual', cat
        self.sub.save()
        self.c.patch(f"/api/listaprecios/lineas/{linea['id']}/", {'activo': True}, format='json')
        cache.clear()
        for url in (f"/api/listaprecios/lineas/{linea['id']}/", '/api/listaprecios/catalogo/'):
            r = self.c.get(url)
            datos = r.data if isinstance(r.data, dict) else next(l for l in r.data if l['id'] == linea['id'])
            self.assertEqual(datos['variantes'][0]['nombre'], 'Nombre actual')
            self.assertEqual(datos['variantes'][0]['categoria'], cat.pk)

    def test_migracion_archiva_sin_perder_costos_ni_identidad_historica(self):
        from importlib import import_module
        from types import SimpleNamespace
        from django.apps import apps
        from .models import PrecioVariante
        linea = self.configurar()
        producto = self.producto(linea)
        historico = VarianteProducto.objects.create(linea_id=linea['id'], nombre='Medida sin equivalencia', costo_base=123456)
        precio = PrecioVariante.objects.create(variante=historico, precio_manual=234567)
        migracion = import_module('listaprecios.migrations.0023_subcategorias_unificadas')
        migracion.unificar(apps, SimpleNamespace(connection=connection))
        anterior = LineaProducto.objects.get(pk=linea['id'])
        self.assertFalse(anterior.activo)
        self.assertIsNone(anterior.referencia_id)
        self.assertEqual(anterior.referencia_archivada_id, self.ref.pk)
        precio.refresh_from_db()
        self.assertEqual(precio.variante_id, historico.pk)
        self.assertEqual(VarianteProducto.objects.get(pk=producto['id']).costo_base, 100000)
        actual = LineaProducto.objects.get(referencia=self.ref)
        self.assertNotEqual(actual.pk, anterior.pk)
        self.assertFalse(actual.activo)
        self.assertEqual(actual.variantes.get().subcategoria_id, self.sub.pk)
        self.assertFalse(actual.variantes.get().costo_confirmado)
        self.assertEqual(self.ref.subcategorias.get().pk, self.sub.pk)

    def test_quitar_piezas_requiere_confirmar_el_costo_individual_antes_de_publicar(self):
        from .services import guardar_componentes
        linea = self.configurar()
        pieza = self.producto(linea)
        sub = Subcategoria.objects.create(categoria=self.cat, nombre='Conjunto para convertir')
        self.ref.subcategorias.add(sub)
        self.c.post(f"/api/listaprecios/lineas/{linea['id']}/sincronizar-subcategorias/")
        juego = VarianteProducto.objects.get(linea_id=linea['id'], subcategoria=sub)
        guardar_componentes(juego, [{'variante': pieza['id'], 'cantidad': 2}])
        self.c.patch(f"/api/listaprecios/lineas/{linea['id']}/", {'activo': True}, format='json')
        guardar_componentes(juego, [])
        juego.refresh_from_db()
        self.assertFalse(juego.costo_confirmado)
        self.assertFalse(LineaProducto.objects.get(pk=linea['id']).activo)

    def test_buscar_subcategoria_usa_nombre_maestro_actual(self):
        linea = self.configurar()
        self.producto(linea)
        self.sub.nombre = 'Nombre exclusivo actualizado'
        self.sub.save()
        self.c.patch(f"/api/listaprecios/lineas/{linea['id']}/", {'activo': True}, format='json')
        r = self.c.get('/api/listaprecios/catalogo/', {'q': 'Nombre exclusivo actualizado'})
        self.assertIn(linea['id'], [l['id'] for l in r.data])
