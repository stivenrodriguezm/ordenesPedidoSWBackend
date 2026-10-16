"""Escrituras humanas simultáneas en un MySQL desechable, sin datos reales."""
import threading
import unittest
from unittest import mock
from django.db import connection, connections, transaction
from django.test import TransactionTestCase
from rest_framework.test import APIClient
from ordenes import oficina
from ordenes.models import ConfiguracionOficina, MiembroOficina, MensajeOficina, TrabajoOficina, CustomUser
from ordenes.tests.test_concurrencia_automatizaciones_ia import competir


@unittest.skipUnless(connection.vendor=='mysql','Requiere MySQL aislado (settings_test_mysql)')
class ConcurrenciaOficinaPersonasTests(TransactionTestCase):
    def setUp(self):
        self.dueno=CustomUser.objects.create(username='dueno_aislado',role='administrador')
        self.persona=CustomUser.objects.create(username='persona_aislada',role='vendedor')
        ConfiguracionOficina.objects.create(responsable=self.dueno)
        MiembroOficina.objects.create(usuario=self.persona)

    def api(self,u):
        c=APIClient();c.force_authenticate(u);return c

    def test_dos_selecciones_con_misma_revision_no_se_sobrescriben(self):
        r=competir(lambda i:self.api(self.dueno).put('/api/oficina/equipo/',{'revision':1,'personas':[{'usuario':self.persona.pk}] if i else []},format='json').status_code)
        self.assertEqual(sorted(r),[200,409])
        self.assertEqual(ConfiguracionOficina.objects.get().revision,2)

    def test_dos_destacados_simultaneos_dejan_una_sola_burbuja(self):
        r=competir(lambda i:self.api(self.persona).post('/api/oficina/mensajes/',{'texto':f'Aviso aislado {i}','destacar':True},format='json').status_code)
        self.assertEqual(r,[201,201])
        self.assertEqual(MensajeOficina.objects.count(),2)
        self.assertEqual(MensajeOficina.objects.filter(destacado_hasta__isnull=False).count(),1)

    def test_dos_cambios_de_trabajo_no_pierden_revision(self):
        t=TrabajoOficina.objects.create(tipo='tarea',creador=self.dueno,responsable=self.persona,titulo='Trabajo aislado')
        r=competir(lambda i:self.api(self.persona).patch(f'/api/oficina/trabajos/{t.pk}/',{'revision':1,'estado':['en_curso','bloqueada'][i]},format='json').status_code)
        self.assertEqual(sorted(r),[200,409])
        t.refresh_from_db();self.assertEqual(t.revision,2)
        self.assertEqual(t.comentarios.count(),1)

    def test_retiro_impide_un_mensaje_que_esperaba_el_bloqueo(self):
        entrando=threading.Event();resultados=[];errores=[];bloquear=oficina._bloquear
        def antes(request):
            entrando.set();return bloquear(request)
        def publicar():
            try:resultados.append(self.api(self.persona).post('/api/oficina/mensajes/',{'texto':'No debe guardarse'},format='json').status_code)
            except Exception as exc:errores.append(exc)
            finally:connections.close_all()
        with mock.patch.object(oficina,'_bloquear',side_effect=antes):
            with transaction.atomic():
                ConfiguracionOficina.objects.select_for_update().get(pk=1)
                h=threading.Thread(target=publicar);h.start()
                self.assertTrue(entrando.wait(10))
                MiembroOficina.objects.filter(usuario=self.persona).update(habilitado=False)
            h.join(20)
        self.assertFalse(h.is_alive())
        if errores:raise errores[0]
        self.assertEqual(resultados,[403]);self.assertFalse(MensajeOficina.objects.exists())
