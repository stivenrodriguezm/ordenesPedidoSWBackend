"""Reserva y ejecución de informes simultáneos en MySQL desechable."""
import unittest
from uuid import uuid4
from django.db import connection
from django.test import TransactionTestCase, override_settings
from rest_framework.test import APIClient
from ordenes.models import (CustomUser, ConfiguracionOficina, MiembroOficina, CoordinacionOficina, InformeAreas)
from ordenes.coordinacion import ejecutar
from ordenes.tests.test_concurrencia_automatizaciones_ia import competir


@unittest.skipUnless(connection.vendor=='mysql','Requiere MySQL aislado (settings_test_mysql)')
@override_settings(ASISTENTE_EN_SEGUNDO_PLANO=True)
class ConcurrenciaCoordinacionTests(TransactionTestCase):
    def setUp(self):
        self.gerente=CustomUser.objects.create(username='gerente_coordinacion_aislado',role='administrador')
        ConfiguracionOficina.objects.create(responsable=self.gerente)
        MiembroOficina.objects.create(usuario=self.gerente)
        c=CoordinacionOficina.objects.create()
        c.destinatarios.add(self.gerente)

    def pedir(self,clave):
        api=APIClient();api.force_authenticate(self.gerente)
        r=api.post('/api/oficina/informes/',{'clave':clave},format='json')
        return (r.status_code,r.data.get('id'))

    def test_misma_clave_devuelve_la_misma_reserva(self):
        clave=str(uuid4())
        resultados=competir(lambda n:self.pedir(clave))
        self.assertEqual([r[0] for r in resultados],[202,202])
        self.assertEqual(resultados[0][1],resultados[1][1])
        self.assertEqual(InformeAreas.objects.count(),1)

    def test_dos_peticiones_distintas_no_solapan_recorridos(self):
        resultados=competir(lambda n:self.pedir(str(uuid4())))
        self.assertEqual(sorted(r[0] for r in resultados),[202,409])
        self.assertEqual(InformeAreas.objects.count(),1)

    def test_dos_workers_entregan_el_informe_solo_una_vez(self):
        pk=self.pedir(str(uuid4()))[1]
        competir(lambda n:ejecutar(pk))
        informe=InformeAreas.objects.get(pk=pk)
        self.assertEqual(informe.estado,'listo')
        self.assertEqual(informe.interacciones.filter(tipo='informe').count(),1)
