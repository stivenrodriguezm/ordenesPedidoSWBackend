"""Agentes por rol (2026-10-09): quién ve cada agente y la IA general, y cómo les responde."""
from unittest import mock

from django.test import override_settings

from ordenes.asistente import gemini
from ordenes.models import ConversacionAsistente, MensajeAsistente, PerfilAsistente
from ordenes.tests.test_asistente import respuesta_texto
from ordenes.tests.utils import LottusTestCase

INSTRUCCIONES = 'Eres el coach de los asesores de Lottus. Respondes con pasos concretos y ejemplos de conversación.'


@override_settings(GEMINI_API_KEY='clave-de-prueba', GEMINI_MODELOS=['modelo-a'], ASISTENTE_EN_SEGUNDO_PLANO=False)
class VisibilidadAgentesTests(LottusTestCase):
    def setUp(self):
        gemini._saturados.clear()
        self.gerente = self.crear_usuario('gerente', 'administrador')
        self.g = self.api(self.gerente)
        self.vendedora = self.crear_usuario('vendedora', 'vendedor')
        self.auxiliar = self.crear_usuario('auxiliar', 'auxiliar')
        self.permisos('vendedor', ['USAR_ASISTENTE_IA'])
        self.permisos('auxiliar', ['USAR_ASISTENTE_IA'])
        self.v, self.a = self.api(self.vendedora), self.api(self.auxiliar)
        # Solo los perfiles de la prueba: el ejecutor del sistema (Alan) no cuenta aquí.
        PerfilAsistente.objects.filter(clave_sistema__isnull=False).delete()

    def perfil(self, **extra):
        datos = {'nombre': 'Coach', 'rol': 'Entrena asesores', 'instrucciones': INSTRUCCIONES, 'areas': [], **extra}
        r = self.g.post('/api/asistente/perfiles/', datos, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        return r.data

    def nombres(self, cliente):
        return [p['nombre'] for p in cliente.get('/api/asistente/perfiles/').data]

    def test_solo_los_roles_elegidos_ven_y_usan_el_agente(self):
        coach = self.perfil(visible_todos=False, roles_visibles=['vendedor'])
        self.perfil(nombre='Para todos')
        self.assertEqual(self.nombres(self.v), ['Coach', 'Para todos'])
        self.assertEqual(self.nombres(self.a), ['Para todos'])
        self.assertEqual(len(self.g.get('/api/asistente/perfiles/').data), 2)  # quien administra los ve todos
        self.assertEqual(self.a.get(f"/api/asistente/perfiles/{coach['id']}/").status_code, 404)
        r = self.a.post('/api/asistente/preguntar/', {'texto': 'Hola', 'perfil': coach['id']}, format='json')
        self.assertEqual(r.status_code, 400)
        # Quien no administra no recibe las reglas de visibilidad ni las instrucciones por rol.
        self.assertNotIn('instrucciones_roles', self.v.get('/api/asistente/perfiles/').data[0])

    def test_quitar_un_rol_bloquea_seguir_la_conversacion_pero_no_el_historial(self):
        coach = self.perfil()
        with mock.patch.object(gemini, '_llamar', return_value=respuesta_texto('Hola.')):
            r = self.v.post('/api/asistente/preguntar/', {'texto': 'Hola', 'perfil': coach['id']}, format='json')
        conv = r.data['conversacion']['id']
        self.g.patch(f"/api/asistente/perfiles/{coach['id']}/", {'visible_todos': False, 'roles_visibles': ['auxiliar']}, format='json')
        r = self.v.post('/api/asistente/preguntar/', {'texto': 'Sigo', 'conversacion': conv}, format='json')
        self.assertEqual(r.status_code, 403)
        self.assertEqual(self.v.get(f'/api/asistente/conversaciones/{conv}/').status_code, 200)

    def test_instrucciones_por_rol_llegan_solo_a_ese_rol(self):
        coach = self.perfil(instrucciones_roles={'vendedor': 'Sé breve y motivador; nunca muestres márgenes.', 'auxiliar': '  '})
        self.assertEqual(self.g.get(f"/api/asistente/perfiles/{coach['id']}/").data['instrucciones_roles'],
                         {'vendedor': 'Sé breve y motivador; nunca muestres márgenes.'})
        for cliente, esperado in ((self.v, True), (self.a, False)):
            with mock.patch.object(gemini, '_llamar', return_value=respuesta_texto('Ok.')) as m:
                cliente.post('/api/asistente/preguntar/', {'texto': 'Hola', 'perfil': coach['id']}, format='json')
            sistema = m.call_args[0][1]['systemInstruction']['parts'][0]['text']
            self.assertEqual('Sé breve y motivador' in sistema, esperado)
            self.assertEqual('Cómo responder a este usuario (rol: Vendedor)' in sistema, esperado)

    def test_validaciones(self):
        r = self.g.post('/api/asistente/perfiles/', {'nombre': 'X', 'rol': 'Y', 'instrucciones': INSTRUCCIONES,
                                                     'visible_todos': False, 'roles_visibles': []}, format='json')
        self.assertIn('roles_visibles', r.data)
        r = self.g.post('/api/asistente/perfiles/', {'nombre': 'X', 'rol': 'Y', 'instrucciones': INSTRUCCIONES,
                                                     'roles_visibles': ['jefe'], 'instrucciones_roles': {'jefe': 'x'}}, format='json')
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.v.put('/api/asistente/general/', {'visible_todos': True}, format='json').status_code, 403)

    def test_ia_general_por_rol(self):
        self.assertTrue(self.v.get('/api/asistente/estado/').data['general']['visible'])
        r = self.g.put('/api/asistente/general/', {'visible_todos': False, 'roles_visibles': ['auxiliar'],
                                                   'instrucciones_roles': {'auxiliar': 'Habla de procesos, no de cifras de ventas.'}}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(self.v.get('/api/asistente/estado/').data['general'], {'visible': False})
        self.assertEqual(self.v.post('/api/asistente/preguntar/', {'texto': 'Hola'}, format='json').status_code, 403)
        self.assertFalse(ConversacionAsistente.objects.filter(usuario=self.vendedora).exists())
        with mock.patch.object(gemini, '_llamar', return_value=respuesta_texto('Ok.')) as m:
            self.assertEqual(self.a.post('/api/asistente/preguntar/', {'texto': 'Hola'}, format='json').status_code, 202)
        self.assertIn('Habla de procesos', m.call_args[0][1]['systemInstruction']['parts'][0]['text'])
        estado = self.g.get('/api/asistente/estado/').data
        self.assertEqual(estado['general']['roles_visibles'], ['auxiliar'])
        self.assertIn({'id': 'vendedor', 'nombre': 'Vendedor'}, estado['roles'])

    def test_la_vendedora_califica_y_ensena(self):
        with mock.patch.object(gemini, '_llamar', return_value=respuesta_texto('Respuesta.')):
            r = self.v.post('/api/asistente/preguntar/', {'texto': 'Hola'}, format='json')
        respuesta = r.data['respuesta']['id']
        self.assertEqual(self.v.post(f'/api/asistente/mensajes/{respuesta}/valorar/', {'valoracion': 'gusto'}, format='json').status_code, 200)
        self.assertEqual(self.v.post(f'/api/asistente/mensajes/{respuesta}/notas/', {'texto': 'Usa viñetas'}, format='json').status_code, 201)
        self.assertTrue(MensajeAsistente.objects.filter(pk=respuesta).exists())
