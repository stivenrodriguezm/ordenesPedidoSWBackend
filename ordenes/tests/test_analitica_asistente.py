from datetime import date
from unittest import mock

from django.test import override_settings
from ordenes.asistente import analitica, gemini, graficos, herramientas
from ordenes.models import LineaVenta, MensajeAsistente, PagoReciboCaja, ReciboCaja
from ordenes.tests.utils import LottusTestCase
from ordenes.tests.test_asistente import respuesta_llamada, respuesta_texto


class AnaliticaTests(LottusTestCase):
    def setUp(self):
        self.admin = self.crear_usuario('admin', 'administrador')
        self.v = self.venta(self.admin, valor='1000.25', fecha=date(2026, 9, 10), sede='Lottus 1', productos_confirmados=True)
        self.venta(self.admin, valor='2000', fecha=date(2026, 9, 11), sede='Lottus 2')
        self.venta(self.admin, valor='9000', fecha=date(2026, 9, 10), estado='anulada')
        self.venta(self.admin, valor='9000', fecha=date(2026, 8, 1))
        self.args = {'desde': '2026-09-01', 'hasta': '2026-09-30'}

    def test_total_no_se_limita_al_top_y_suma_con_centavos(self):
        with self.assertNumQueries(3):
            r = analitica.consultar({**self.args, 'limite': 1, 'metrica': 'valor_vendido'})
        self.assertEqual(r['totales']['valor_vendido'], 3000.25)
        self.assertEqual(r['filas'][0]['etiqueta'], 'Lottus 2')
        self.assertTrue(r['truncado'])
        self.assertEqual(r['grupos_totales'], 2)
        self.assertNotIn('cliente', str(r))

    def test_filtros_y_fechas_inclusivas_y_agrupacion_temporal(self):
        r = analitica.consultar({**self.args, 'sede': 'Lottus 1', 'agrupar': 'dia'})
        self.assertEqual(r['filas'][0]['etiqueta'], '2026-09-10')
        self.assertEqual(r['totales']['ventas'], 1)
        self.assertEqual(analitica.consultar({'desde': '2026-09-10', 'hasta': '2026-09-10'})['totales']['ventas'], 1)

    def test_rechaza_sql_campos_libres_rangos_y_limites(self):
        for invalido in ({'sql': 'DELETE FROM ordenes_venta'}, {'agrupar': 'cliente__cedula'}, {'limite': 90000}, {'metrica': 'password'}, {'desde': 'xxx'}, {'desde': '2026-12-01', 'hasta': '2026-01-01'}, {'proveedor_id': 5}):
            with self.assertRaises((ValueError, TypeError)):
                analitica.consultar({**self.args, **invalido})

    def test_producto_multiplica_precio_por_cantidad_y_excluye_borrador(self):
        LineaVenta.objects.create(venta=self.v, producto_nombre='Sofá', cantidad=3, precio_lista_unitario='250.50')
        r = analitica.consultar({**self.args, 'dominio': 'productos', 'agrupar': 'producto'})
        self.assertEqual(r['totales']['valor_lista'], 751.5)
        self.v.productos_confirmados = False
        self.v.save()
        self.assertEqual(analitica.consultar({**self.args, 'dominio': 'productos'})['filas'], [])

    def test_cobros_excluyen_pendientes_y_recibos_anulados(self):
        recibo = ReciboCaja.objects.create(id=901, venta=self.v, fecha='2026-09-10')
        PagoReciboCaja.objects.create(recibo=recibo, metodo_pago='Bancolombia', valor=100, estado='Confirmado')
        PagoReciboCaja.objects.create(recibo=recibo, metodo_pago='Bancolombia', valor=500, estado='Pendiente')
        r = analitica.consultar({**self.args, 'dominio': 'cobros'})
        self.assertEqual(r['totales']['valor_confirmado'], 100)
        recibo.pagos.update(estado='Anulado')
        self.assertEqual(analitica.consultar({**self.args, 'dominio': 'cobros'})['filas'], [])

    def test_grafico_solo_toma_valores_consultados(self):
        fuente = analitica.consultar(self.args)
        g = graficos.construir({'consulta_id': 'q1', 'tipo': 'barras', 'metrica': 'valor_vendido', 'valores': [999]}, {'q1': fuente})
        self.assertEqual(sorted(g['valores']), [1000.25, 2000])
        with self.assertRaises(ValueError):
            graficos.construir({'consulta_id': 'otra', 'tipo': 'barras', 'metrica': 'valor_vendido'}, {'q1': fuente})
        fuente['truncado'] = True
        with self.assertRaises(ValueError):
            graficos.construir({'consulta_id': 'q1', 'tipo': 'dona', 'metrica': 'valor_vendido'}, {'q1': fuente})

    @override_settings(GEMINI_API_KEY='test', GEMINI_MODELOS=['test'], ASISTENTE_EN_SEGUNDO_PLANO=False)
    def test_grafico_persiste_cache_y_error_recuperable(self):
        gemini._saturados.clear()
        respuestas = [respuesta_llamada('consulta_datos', self.args), respuesta_llamada('consulta_datos', self.args),
                      respuesta_llamada('graficar_consulta', {'consulta_id': 'inventada', 'tipo': 'barras', 'metrica': 'valor_vendido'}),
                      respuesta_llamada('graficar_consulta', {'consulta_id': 'q1', 'tipo': 'barras', 'metrica': 'valor_vendido'}), respuesta_texto('Análisis con datos.')]
        with mock.patch.object(gemini, '_llamar', side_effect=respuestas), mock.patch.object(herramientas, 'ejecutar', wraps=herramientas.ejecutar) as ejecutar:
            r = self.api(self.admin).post('/api/asistente/preguntar/', {'texto': 'Grafica ventas'}, format='json')
        self.assertEqual(r.data['respuesta']['estado'], 'listo', r.data)
        self.assertEqual(ejecutar.call_count, 1)
        g = r.data['respuesta']['graficos']
        self.assertEqual(len(g), 1)
        recargado = self.api(self.admin).get(f"/api/asistente/mensajes/{r.data['respuesta']['id']}/")
        self.assertEqual(recargado.data['graficos'], g)
        self.assertTrue(MensajeAsistente.objects.filter(estado='listo').exists())

    def test_bancos_ya_no_tiene_rutas(self):
        self.assertEqual(self.api(self.admin).get('/api/bancos/cuentas/').status_code, 404)

    @override_settings(GEMINI_API_KEY='test', GEMINI_MODELOS=['test'])
    def test_resultado_grande_no_se_envia_al_modelo(self):
        gemini._saturados.clear()
        contenido_grande = 'detalle-' * gemini.MAX_RESULTADO_CARACTERES
        with mock.patch.object(herramientas, 'ejecutar', return_value={'datos': contenido_grande}), mock.patch.object(
            gemini, '_llamar', side_effect=[respuesta_llamada('consulta_datos', self.args), respuesta_texto('Acota la consulta.')]
        ) as llamar:
            gemini.responder([{'rol': 'usuario', 'texto': 'Consulta ventas'}], self.admin)
        enviado = llamar.call_args.args[1]['contents'][-1]['parts'][0]['functionResponse']['response']['resultado']
        self.assertIn('Resultado demasiado grande', enviado['error'])
        self.assertNotIn('datos', enviado)
        self.assertEqual(enviado['consulta_id'], 'q1')
