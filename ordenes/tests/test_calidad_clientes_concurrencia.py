"""Normalizaciones simultáneas sobre un MySQL de pruebas desechable."""
import unittest

from django.db import connection
from django.test import TransactionTestCase
from rest_framework.test import APIClient

from ordenes.models import Cliente, CorreccionCliente, CustomUser, RegistroAuditoria
from ordenes.tests.test_concurrencia import en_paralelo


@unittest.skipUnless(connection.vendor == 'mysql', 'Requiere MySQL aislado (settings_test_mysql)')
class CalidadClientesConcurrenciaTests(TransactionTestCase):
    def test_dos_revisiones_simultaneas_no_pisan_datos_ni_duplican_originales(self):
        admin = CustomUser.objects.create(username='admin-calidad-race', role='administrador')
        cliente = Cliente.objects.create(nombre='  Cliente  Ficticio ', cedula='race-cliente', telefono1='301 234 5678')
        url = f'/api/calidad-clientes/{cliente.pk}/'
        api = APIClient()
        api.force_authenticate(admin)
        version = api.get(url).data['version']

        def guardar(i):
            c = APIClient()
            c.force_authenticate(admin)
            return c.post(url + 'normalizar/', {'version': version, 'campos': ['telefono1']},
                          format='json', HTTP_IDEMPOTENCY_KEY=f'revision-{i}').status_code

        self.assertEqual(sorted(en_paralelo(2, guardar)), [200, 409])
        cliente.refresh_from_db()
        self.assertEqual(cliente.telefono1, '3012345678')
        self.assertEqual(cliente.nombre, '  Cliente  Ficticio ')
        self.assertEqual(CorreccionCliente.objects.count(), 1)
        self.assertEqual(CorreccionCliente.objects.get().cambios['telefono1']['antes'], '301 234 5678')
        self.assertEqual(RegistroAuditoria.objects.filter(accion='cliente.normalizar').count(), 1)
