"""Equipo IA (2026-10-14): IA Lottus le encarga a Alan, Alan responde al terminar y ambos aprenden."""
import json
from unittest import mock

from django.core.cache import cache
from django.test import override_settings

from ordenes.asistente import agente, equipo, gemini, perfiles
from ordenes.models import (AprendizajeAsistente, ConversacionAsistente, InteraccionOficina, MensajeAsistente,
                            MensajeEquipoIA, PerfilAsistente, TrabajoAgenteIA)
from ordenes.tests.test_asistente import respuesta_llamada, respuesta_texto
from ordenes.tests.utils import LottusTestCase

RETRO = json.dumps({'ejecutor': 'Antes de crear un proveedor, confirma que no exista uno con el mismo nombre.',
                    'solicitante': 'Al delegar altas de proveedores, incluye el nombre exacto de la empresa.'})


@override_settings(GEMINI_API_KEY='prueba', GEMINI_MODELOS=['modelo-a'], ASISTENTE_EN_SEGUNDO_PLANO=False)
class EquipoIATests(LottusTestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        gemini._saturados.clear()
        self.u = self.crear_usuario('gerente-equipo', 'administrador', first_name='Stiven')
        self.alan = perfiles.asegurar_agente_ejecutor()
        self.alan.areas = ['operaciones', 'ventas', 'clientes', 'pedidos', 'inventario']
        self.alan.save()
        self.c = ConversacionAsistente.objects.create(usuario=self.u, titulo='Alta de proveedor')
        MensajeAsistente.objects.create(conversacion=self.c, rol='usuario', texto='Crea el proveedor Maderas del Sur en la plataforma.')
        self.m = MensajeAsistente.objects.create(conversacion=self.c, rol='asistente', estado='procesando')
        self.yo = f'ia-{self.alan.pk}'

    def encargar(self):
        return agente.encolar(self.u, self.m.pk, None, 'Crea el proveedor Maderas del Sur.')

    def test_el_ejecutor_se_llama_alan(self):
        self.assertEqual(self.alan.nombre, 'Alan')
        self.assertTrue(self.alan.instrucciones.startswith('Eres Alan'))

    def test_ia_lottus_le_encarga_a_alan_con_un_por_favor(self):
        datos = self.encargar()
        self.assertEqual(datos['agente']['nombre'], 'Alan')
        m = MensajeEquipoIA.objects.get(tipo='solicitud')
        self.assertEqual((m.de, m.para, m.usuario_id), ('ia-general', self.yo, self.u.pk))
        self.assertEqual(m.texto, 'Por favor, Alan: Crea el proveedor Maderas del Sur.')
        aviso = InteraccionOficina.objects.get(tipo='solicitud')
        self.assertEqual((aviso.actor, aviso.destino), ('ia-general', self.yo))
        # El globo del plano dice qué tipo de cambio es, sin el contenido.
        self.assertEqual(aviso.texto, 'Por favor, Alan, registra este proveedor.')

    def test_alan_trabaja_va_a_la_oficina_de_ia_lottus_y_ambos_aprenden(self):
        datos = self.encargar()
        with mock.patch.object(gemini, '_llamar', side_effect=[
                respuesta_llamada('ejecutar_operacion_plataforma', {'operacion': 'crear_proveedor', 'paso': 'proveedor',
                                                                    'datos_json': json.dumps({'nombre_empresa': 'Maderas del Sur'})}),
                respuesta_texto('Proveedor creado.'), respuesta_texto(RETRO)]):
            self.assertTrue(agente.procesar(datos['id']))
        t = TrabajoAgenteIA.objects.get(pk=datos['id'])
        self.assertEqual(t.estado, 'listo')
        hilo = list(MensajeEquipoIA.objects.order_by('id').values_list('de', 'tipo'))
        self.assertEqual(hilo, [('ia-general', 'solicitud'), (self.yo, 'avance'), (self.yo, 'resultado'),
                                ('ia-general', 'respuesta'), (self.yo, 'aprendizaje'), ('ia-general', 'aprendizaje')])
        self.assertTrue(MensajeEquipoIA.objects.get(tipo='resultado').texto.startswith('Listo, la tarea se ejecutó con éxito.'))
        self.assertEqual(MensajeEquipoIA.objects.get(tipo='respuesta').texto, '¡Gracias, Alan! Le confirmo el resultado a Stiven.')
        entrega = InteraccionOficina.objects.get(tipo='entrega')
        self.assertEqual((entrega.actor, entrega.destino, entrega.texto), (self.yo, 'ia-general', 'IA Lottus, la tarea se ejecutó con éxito.'))
        lecciones = AprendizajeAsistente.objects.filter(usuario=self.u, origen='equipo', tipo='nota')
        self.assertEqual(lecciones.get(perfil=self.alan).texto, json.loads(RETRO)['ejecutor'])
        self.assertEqual(lecciones.get(perfil__isnull=True).texto, json.loads(RETRO)['solicitante'])
        # La lección entra en las instrucciones de las siguientes respuestas de Alan.
        self.assertIn('confirma que no exista', perfiles.bloque_aprendizajes(self.u, self.alan))

    def test_necesita_datos_avisa_y_retomar_lo_pide_de_nuevo(self):
        datos = self.encargar()
        with mock.patch.object(gemini, '_llamar', side_effect=[
                respuesta_llamada('solicitar_datos_operacion', {'pregunta': 'Indica el NIT del proveedor.'}),
                respuesta_texto('Necesito el NIT.'), respuesta_texto('{"ejecutor": "", "solicitante": ""}')]):
            agente.procesar(datos['id'])
        self.assertEqual(InteraccionOficina.objects.get(tipo='revision').texto, 'IA Lottus, necesito unos datos para terminar la tarea.')
        self.assertFalse(AprendizajeAsistente.objects.filter(origen='equipo').exists())
        r = self.api(self.u).post(f"/api/asistente/agente/trabajos/{datos['id']}/", {'accion': 'retomar', 'datos_adicionales': 'NIT 900123'}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(MensajeEquipoIA.objects.filter(tipo='solicitud').last().texto, 'Ya tengo los datos que pediste. Por favor, retoma la tarea.')

    def test_hilos_privados_y_legibles(self):
        self.encargar()
        r = self.api(self.u).get('/api/asistente/equipo/hilos/')
        self.assertEqual(r.status_code, 200)
        [hilo] = r.data['hilos']
        self.assertEqual(hilo['clave'], f'ia-general~{self.yo}')
        self.assertEqual([p['nombre'] for p in hilo['participantes']], ['IA Lottus', 'Alan'])
        self.assertTrue(hilo['activo'])
        d = self.api(self.u).get(f"/api/asistente/equipo/hilos/{hilo['clave']}/")
        self.assertEqual(d.status_code, 200)
        self.assertEqual(d.data['mensajes'][0]['nombre'], 'IA Lottus')
        self.assertEqual(d.data['mensajes'][0]['trabajo']['estado'], 'pendiente')
        # Mismo hilo con las claves al revés; claves inválidas no existen.
        self.assertEqual(self.api(self.u).get(f'/api/asistente/equipo/hilos/{self.yo}~ia-general/').data['clave'], hilo['clave'])
        self.assertEqual(self.api(self.u).get('/api/asistente/equipo/hilos/ia-general~ia-general/').status_code, 404)
        self.assertEqual(self.api(self.u).get('/api/asistente/equipo/hilos/x~y/').status_code, 404)
        otro = self.crear_usuario('otro-gerente', 'administrador')
        self.assertEqual(self.api(otro).get('/api/asistente/equipo/hilos/').data['hilos'], [])

    def test_el_chat_de_trabajo_sale_de_mis_chats(self):
        datos = self.encargar()
        with mock.patch.object(gemini, '_llamar', side_effect=[respuesta_texto('No hay nada que guardar.'), respuesta_texto('{}')]):
            agente.procesar(datos['id'])
        trabajo = TrabajoAgenteIA.objects.get(pk=datos['id'])
        ids = [c['id'] for c in self.api(self.u).get('/api/asistente/conversaciones/', {'sin_ejecuciones': '1'}).data]
        self.assertIn(self.c.pk, ids)
        self.assertNotIn(trabajo.conversacion_id, ids)
        todas = {c['id']: c for c in self.api(self.u).get('/api/asistente/conversaciones/').data}
        self.assertTrue(todas[trabajo.conversacion_id]['de_ejecucion'])

    def test_chat_directo_con_alan_no_abre_hilo_del_equipo(self):
        c = ConversacionAsistente.objects.create(usuario=self.u, perfil=self.alan, titulo='Directo')
        MensajeAsistente.objects.create(conversacion=c, rol='usuario', texto='Crea el proveedor Maderas del Norte.')
        m = MensajeAsistente.objects.create(conversacion=c, rol='asistente', estado='procesando')
        datos = agente.encolar(self.u, m.pk, self.alan)
        with mock.patch.object(gemini, '_llamar', side_effect=[respuesta_texto('Sin cambios.')]):
            agente.procesar(datos['id'])
        self.assertFalse(MensajeEquipoIA.objects.exists())

    def test_aviso_corto(self):
        self.assertEqual(equipo.aviso_corto('Cámbiale la fecha de entrega a la venta 45133', 'Alan'), 'Por favor, Alan, actualiza esta venta.')
        self.assertEqual(equipo.aviso_corto('anula el recibo 9001', 'Alan'), 'Por favor, Alan, anula este recibo de caja.')
        self.assertEqual(equipo.aviso_corto('hola', 'Alan'), 'Por favor, Alan, ejecuta este cambio en la plataforma.')

    def test_el_ejecutor_se_puede_renombrar_y_nadie_mas_usa_su_nombre(self):
        api = self.api(self.u)
        self.assertEqual(api.patch(f'/api/asistente/perfiles/{self.alan.pk}/', {'nombre': 'Alan R.'}, format='json').status_code, 200)
        nuevo = {'nombre': 'alan r.', 'rol': 'Otro', 'instrucciones': 'Otra identidad suficientemente extensa para la prueba.', 'areas': ['ventas']}
        self.assertEqual(api.post('/api/asistente/perfiles/', nuevo, format='json').status_code, 400)
        self.assertEqual(PerfilAsistente.objects.get(clave_sistema='ejecutor').nombre, 'Alan R.')
