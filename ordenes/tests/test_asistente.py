"""Chat gerencial con IA (Gemini simulado: nunca se llama a la API real en pruebas)."""
from unittest import mock

from django.test import override_settings

from ordenes.asistente import gemini, herramientas
from ordenes.models import AsesorNomina, MensajeAsistente, OrdenPedido, RegistroAuditoria, Venta
from ordenes.tests.utils import LottusTestCase


def respuesta_texto(texto):
    return {'candidates': [{'content': {'role': 'model', 'parts': [{'text': texto}]}}], 'usageMetadata': {'totalTokenCount': 50}}


def respuesta_llamada(nombre, args, id_='call_1'):
    return {'candidates': [{'content': {'role': 'model', 'parts': [{'functionCall': {'name': nombre, 'args': args, 'id': id_}, 'thoughtSignature': 'firma'}]}}],
            'usageMetadata': {'totalTokenCount': 30}}


@override_settings(GEMINI_API_KEY='clave-de-prueba', GEMINI_MODELOS=['modelo-a', 'modelo-b'], ASISTENTE_EN_SEGUNDO_PLANO=False)
class AsistenteTests(LottusTestCase):
    def setUp(self):
        gemini._saturados.clear()
        self.gerente = self.crear_usuario('gerente', 'administrador', first_name='Gerente')
        self.asesor = self.crear_usuario('asesora', first_name='Ana')
        self.otro = self.crear_usuario('otro', first_name='Otro')
        self.permisos('vendedor', ['VER_VENTAS'])
        self.v = self.venta(self.asesor, valor='1000000', valor_lista='1200000')
        self.v.vendedores_compartidos.add(self.otro)
        AsesorNomina.objects.create(asesor=self.asesor, salario_basico=1, meta=2000000)
        OrdenPedido.objects.create(proveedor=self.proveedor(), usuario=self.gerente, venta=self.v, fecha_esperada='2020-01-01', tela='Por pedir')
        self.api_gerente = self.api(self.gerente)

    def preguntar(self, texto='¿Cómo vamos?', cliente=None, **extra):
        return (cliente or self.api_gerente).post('/api/asistente/preguntar/', {'texto': texto, **extra}, format='json')

    def test_solo_con_permiso(self):
        r = self.api(self.asesor).post('/api/asistente/preguntar/', {'texto': 'hola'}, format='json')
        self.assertEqual(r.status_code, 403)
        self.assertEqual(self.api(self.asesor).get('/api/asistente/conversaciones/').status_code, 403)
        self.permisos('vendedor', ['VER_VENTAS', 'USAR_ASISTENTE_IA'])
        self.assertEqual(self.api(self.asesor).get('/api/asistente/conversaciones/').status_code, 200)

    def test_consulta_los_datos_y_responde(self):
        llamadas = []

        def falso(modelo, cuerpo):
            llamadas.append((modelo, cuerpo))
            if len(llamadas) == 1:
                return respuesta_llamada('ventas_por_asesor', {})
            return respuesta_texto('**Conclusión:** vamos bien.')

        with mock.patch.object(gemini, '_llamar', side_effect=falso):
            r = self.preguntar('¿Quién vende más?')
        self.assertEqual(r.status_code, 202, r.data)
        respuesta = r.data['respuesta']
        self.assertEqual((respuesta['estado'], respuesta['texto'], respuesta['consultas']), ('listo', '**Conclusión:** vamos bien.', ['Ventas por asesor']))
        # El sistema lleva el contexto del negocio y la fecha; la respuesta de la herramienta
        # vuelve con su id y la parte del modelo conserva su firma.
        segundo = llamadas[1][1]
        self.assertIn('Período comercial actual', segundo['systemInstruction']['parts'][0]['text'])
        self.assertEqual(segundo['contents'][1]['parts'][0]['thoughtSignature'], 'firma')
        resultado = segundo['contents'][2]['parts'][0]['functionResponse']
        self.assertEqual(resultado['id'], 'call_1')
        asesores = {a['asesor']: a for a in resultado['response']['resultado']['asesores']}
        self.assertEqual(asesores['Ana']['total_atribuido'], 500000)  # venta compartida: Total / 2
        self.assertEqual(asesores['Ana']['cumplimiento_meta_pct'], 25.0)
        self.assertTrue(RegistroAuditoria.objects.filter(accion='asistente.respuesta').exists())
        # La conversación queda guardada y la siguiente pregunta lleva el historial.
        conv = r.data['conversacion']['id']
        with mock.patch.object(gemini, '_llamar', return_value=respuesta_texto('Sí.')) as m:
            self.preguntar('¿Y la semana pasada?', conversacion=conv)
        contenidos = m.call_args[0][1]['contents']
        self.assertEqual([c['role'] for c in contenidos], ['user', 'model', 'user'])
        self.assertEqual(len(self.api_gerente.get(f'/api/asistente/conversaciones/{conv}/').data['mensajes']), 4)

    def test_modelo_saturado_usa_el_siguiente(self):
        def falso(modelo, cuerpo):
            if modelo == 'modelo-a':
                gemini._saturados[modelo] = 1e12
                raise gemini._Saturado(modelo)
            return respuesta_texto('Respuesta del respaldo')

        with mock.patch.object(gemini, '_llamar', side_effect=falso):
            r = self.preguntar()
        self.assertEqual(r.data['respuesta']['texto'], 'Respuesta del respaldo')
        self.assertEqual(MensajeAsistente.objects.get(pk=r.data['respuesta']['id']).modelo, 'modelo-b')

    def test_error_de_gemini_queda_en_el_mensaje(self):
        with mock.patch.object(gemini, '_llamar', side_effect=gemini.ErrorAsistente('Gemini respondió 400: mala solicitud')):
            r = self.preguntar()
        self.assertEqual((r.data['respuesta']['estado'], r.data['respuesta']['error']), ('error', 'Gemini respondió 400: mala solicitud'))

    @override_settings(GEMINI_API_KEY='')
    def test_sin_clave_no_esta_disponible(self):
        self.assertEqual(self.preguntar().status_code, 503)
        self.assertFalse(self.api_gerente.get('/api/asistente/estado/').data['configurado'])

    def test_cada_quien_ve_solo_sus_conversaciones(self):
        with mock.patch.object(gemini, '_llamar', return_value=respuesta_texto('ok')):
            r = self.preguntar()
        otro_admin = self.api(self.crear_usuario('otro-admin', 'administrador'))
        self.assertEqual(otro_admin.get(f"/api/asistente/conversaciones/{r.data['conversacion']['id']}/").status_code, 404)
        self.assertEqual(otro_admin.get(f"/api/asistente/mensajes/{r.data['respuesta']['id']}/").status_code, 404)
        self.assertEqual(otro_admin.get('/api/asistente/conversaciones/').data, [])

    def test_todas_las_herramientas_responden_con_datos(self):
        for nombre in herramientas.HERRAMIENTAS:
            args = {'venta_id': self.v.pk} if nombre == 'detalle_venta' else {}
            resultado = herramientas.ejecutar(nombre, args)
            if nombre in ['asignar_tarea_oficina', 'leer_codigo_pagina_web', 'ver_imagen_pagina_web']:
                self.assertIn('error',resultado)  # requieren responsable/contexto o un archivo concreto
                continue
            self.assertNotIn('error', resultado if nombre != 'nomina' else {}, f'{nombre}: {resultado}')
        self.assertEqual(herramientas.ejecutar('pedidos_proveedor', {})['vencidas'], 1)
        self.assertEqual(herramientas.ejecutar('detalle_venta', {'venta_id': self.v.pk})['descuento_pct'], 16.7)
        self.assertIn('error', herramientas.ejecutar('no_existe', {}))


class PostferiaTests(LottusTestCase):
    def test_postferia_se_guarda_al_editar_la_venta(self):
        admin = self.crear_usuario('admin', 'administrador')
        v = self.venta(admin)
        r = self.api(admin).put(f'/api/ventas/{v.pk}/editar/', {'venta': {'es_postferia': True}}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        v.refresh_from_db()
        self.assertTrue(v.es_postferia)
        self.assertTrue(self.api(admin).get(f'/api/ventas/{v.pk}/').data['es_postferia'])
        self.assertFalse(Venta.objects.get(pk=v.pk).es_feria_hogar)
