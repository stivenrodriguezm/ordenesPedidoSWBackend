"""Impresión remota (2026-10-24): la plataforma deja el documento en cola y el agente de
la oficina lo recoge con el token de su impresora. Datos ficticios."""
import io
import json
import os
import tempfile
from datetime import timedelta
from pathlib import Path
from unittest import mock

from django.core.cache import cache
from django.core.management import call_command
from rest_framework.test import APIClient

from impresion import servicios as s
from impresion.models import Impresora, TrabajoImpresion as T
from ordenes.tests.utils import LottusTestCase

DOC = '<!DOCTYPE html><html><body><p>Remisión ficticia</p></body></html>'


class ImpresionRemotaTests(LottusTestCase):
    def setUp(self):
        cache.clear()
        self.token, h = s.nuevo_token()
        self.imp = Impresora.objects.create(nombre='Ricoh ficticia', ubicacion='Oficina principal', token_hash=h)
        self.vendedor = self.crear_usuario('vend_imp')
        self.c = self.api(self.vendedor)
        self.agente = APIClient()
        self.agente.credentials(HTTP_AUTHORIZATION=f'Impresora {self.token}')

    def enviar(self, **datos):
        with self.captureOnCommitCallbacks(execute=True):
            return self.c.post('/api/impresion/trabajos/', {'impresora': self.imp.pk, 'titulo': 'Remisión 1', 'html': DOC, **datos}, format='json')

    def siguiente(self, cliente=None):
        return (cliente or self.agente).post('/api/impresion/agente/siguiente/')

    def test_del_navegador_a_la_impresora_de_la_oficina(self):
        self.assertFalse(self.c.get('/api/impresion/impresoras/').data[0]['en_linea'])
        self.assertEqual(self.siguiente().status_code, 204)
        self.assertTrue(self.c.get('/api/impresion/impresoras/').data[0]['en_linea'])  # el agente se reportó

        r = self.enviar(copias=2)
        self.assertEqual((r.status_code, r.data['estado'], r.data['en_linea']), (201, 'pendiente', True))
        t = self.siguiente()
        self.assertEqual((t.status_code, t.data['html'], t.data['copias']), (200, DOC, 2))
        self.assertEqual(self.siguiente().status_code, 204)  # nadie más lo recibe

        url = f'/api/impresion/agente/trabajos/{t.data["id"]}/'
        self.assertEqual(self.agente.post(url, {'estado': 'enviado'}, format='json').status_code, 200)
        self.assertEqual(self.agente.post(url, {'estado': 'impreso'}, format='json').status_code, 200)
        estado = self.c.get(f'/api/impresion/trabajos/{t.data["id"]}/').data
        self.assertEqual((estado['estado'], estado['estado_nombre']), ('impreso', 'Impreso'))
        self.assertEqual(self.agente.post(url, {'estado': 'error'}, format='json').status_code, 409)

    def test_la_consulta_del_agente_sin_trabajos_no_usa_la_base(self):
        self.siguiente()  # valida el token y revisa la base una vez
        with self.assertNumQueries(0):
            self.assertEqual(self.siguiente().status_code, 204)
        self.enviar()
        self.assertEqual(self.siguiente().status_code, 200)

    def test_la_web_sabe_si_la_computadora_encuentra_la_impresora(self):
        lista = lambda: self.c.get('/api/impresion/impresoras/').data[0]['impresora_encontrada']
        self.assertIsNone(lista())  # sin noticias del agente
        self.siguiente()
        with self.assertNumQueries(0):  # el aviso no toca la base
            r = self.agente.post('/api/impresion/agente/siguiente/', {'impresora_ok': False}, format='json')
        self.assertEqual(r.status_code, 204)
        self.assertIs(lista(), False)
        self.agente.post('/api/impresion/agente/siguiente/', {'impresora_ok': True}, format='json')
        self.assertIs(lista(), True)

    def test_tokens_invalidos_o_de_impresora_inactiva(self):
        self.assertEqual(self.siguiente(APIClient()).status_code, 401)
        otro = APIClient()
        otro.credentials(HTTP_AUTHORIZATION='Impresora no-es-un-token')
        self.assertEqual(self.siguiente(otro).status_code, 401)
        Impresora.objects.filter(pk=self.imp.pk).update(activa=False)
        self.assertEqual(self.siguiente().status_code, 401)
        self.assertEqual(self.c.get('/api/impresion/impresoras/').data, [])
        self.assertEqual(self.enviar().status_code, 400)

    def test_validaciones_del_trabajo(self):
        self.assertEqual(self.enviar(copias=0).status_code, 400)
        self.assertEqual(self.enviar(copias=11).status_code, 400)
        self.assertEqual(self.enviar(html='sin documento').status_code, 400)
        with mock.patch.object(s, 'MAX_HTML', 50):
            self.assertEqual(self.enviar().status_code, 400)
        self.assertFalse(T.objects.exists())

    def test_cada_usuario_ve_solo_sus_trabajos(self):
        pk = self.enviar().data['id']
        otro = self.api(self.crear_usuario('vend_otro'))
        self.assertEqual(otro.get(f'/api/impresion/trabajos/{pk}/').status_code, 404)
        self.assertEqual(self.c.get(f'/api/impresion/trabajos/{pk}/').status_code, 200)

    def test_lo_que_lleva_horas_en_cola_ya_no_se_imprime(self):
        pk = self.enviar().data['id']
        T.objects.filter(pk=pk).update(creado=T.objects.get(pk=pk).creado - timedelta(hours=s.VENCE_HORAS + 1))
        self.assertEqual(self.siguiente().status_code, 204)
        self.assertEqual(T.objects.get(pk=pk).estado, T.ERROR)


class CrearImpresoraTests(LottusTestCase):
    def test_guarda_el_token_en_la_configuracion_sin_mostrarlo(self):
        with tempfile.TemporaryDirectory() as d:
            ruta = Path(d) / 'agente' / 'config.json'
            salida = io.StringIO()
            call_command('crear_impresora', nombre='Ricoh ficticia', ubicacion='Oficina', config=str(ruta),
                         servidor='local', api='http://127.0.0.1:8000/api/', cola='COLA_FICTICIA', stdout=salida)
            config = json.loads(ruta.read_text())
            token = config['servidores'][0]['token']
            self.assertEqual(oct(os.stat(ruta).st_mode & 0o777), '0o600')
            self.assertNotIn(token, salida.getvalue())
            self.assertEqual((config['cola'], config['servidores'][0]['api']), ('COLA_FICTICIA', 'http://127.0.0.1:8000/api'))
            imp = Impresora.objects.get()
            self.assertEqual(s.impresora_del_token(token), imp.pk)

            call_command('crear_impresora', renovar=imp.pk, config=str(ruta), servidor='local', api='http://x/api', stdout=io.StringIO())
            nuevo = json.loads(ruta.read_text())['servidores']
            self.assertEqual(len(nuevo), 1)
            self.assertIsNone(s.impresora_del_token(token))
            self.assertEqual(s.impresora_del_token(nuevo[0]['token']), imp.pk)
