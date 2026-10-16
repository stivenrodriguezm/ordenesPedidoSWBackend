from unittest.mock import patch

from django.db import connection
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient

from ordenes.calidad_clientes import clave_documento, telefono
from ordenes.models import Cliente, CorreccionCliente, RegistroAuditoria, Venta
from ordenes.tests.utils import LottusTestCase


class CalidadClientesTests(LottusTestCase):
    def setUp(self):
        self.admin = self.crear_usuario('admin-calidad', role='administrador')
        self.vendedor = self.crear_usuario('vendedor-calidad')
        self.c = self.api(self.admin)
        self.cliente1 = Cliente.objects.create(nombre='  María  López ', cedula='001.234-56',
            telefono1='+57 (301) 234-5678', telefono2='601 234 5678 ext 90', direccion='Cra.  12 #  4-50',
            ciudad=' Bogotá ', correo='Persona@example.com')

    def ficha(self, cliente=None, api=None):
        return (api or self.c).get(f'/api/calidad-clientes/{(cliente or self.cliente1).pk}/')

    def aplicar(self, cliente=None, api=None, **extra):
        cliente = cliente or self.cliente1
        return (api or self.c).post(f'/api/calidad-clientes/{cliente.pk}/normalizar/', {
            'version': self.ficha(cliente, api).data['version'], 'campos': ['telefono1'], **extra,
        }, format='json')

    def test_normalizacion_conservadora_no_inventa_pais_extension_ni_identidad(self):
        self.assertEqual(telefono('+57 (301) 234-5678'), '+573012345678')
        self.assertEqual(telefono('301 234 5678'), '3012345678')
        self.assertEqual(telefono('601 234 5678 ext 90'), '601 234 5678 ext 90')
        self.assertEqual(telefono('12-34'), '12-34')
        self.assertEqual(clave_documento('001.234-56'), '00123456')
        r = self.ficha()
        self.assertNotIn('cedula', r.data['cambios'])
        self.assertNotIn('correo', r.data['cambios'])
        self.assertEqual(r.data['cambios']['direccion']['despues'], 'Cra. 12 # 4-50')
        self.assertEqual(r.data['cambios']['nombre']['despues'], 'María López')

    def test_filtro_solo_fichas_con_correcciones(self):
        limpio = Cliente.objects.create(nombre='Ana Ruiz', cedula='998877', telefono1='3001234567', ciudad='Bogotá')
        todos = {f['cliente']['id'] for f in self.c.get('/api/calidad-clientes/').data['results']}
        self.assertEqual(todos, {self.cliente1.pk, limpio.pk})
        r = self.c.get('/api/calidad-clientes/', {'con_correcciones': '1'})
        self.assertEqual([f['cliente']['id'] for f in r.data['results']], [self.cliente1.pk])
        self.assertEqual(r.data['count'], 1)

    def test_lecturas_no_corrigen_ni_generan_historia(self):
        antes = list(Cliente.objects.values())
        self.c.get('/api/calidad-clientes/')
        self.c.get('/api/calidad-clientes/candidatos/')
        self.ficha()
        self.assertEqual(list(Cliente.objects.values()), antes)
        self.assertFalse(CorreccionCliente.objects.exists())
        self.assertFalse(RegistroAuditoria.objects.exists())

    def test_anonimo_y_permiso_basico_no_bastan(self):
        self.assertEqual(APIClient().get('/api/calidad-clientes/').status_code, 401)
        for permisos in (['VER_CLIENTES'], ['VER_CALIDAD_CLIENTES']):
            self.permisos('vendedor', permisos)
            self.assertEqual(self.api(self.vendedor).get('/api/calidad-clientes/').status_code, 403)

    def test_alcance_propio_compartido_y_clientes_sin_ventas(self):
        self.permisos('vendedor', ['VER_CLIENTES', 'VER_CALIDAD_CLIENTES', 'EDITAR_CLIENTE', 'NORMALIZAR_CLIENTES'])
        propia = self.venta(self.vendedor, cliente=self.cliente1)
        propia.vendedores_compartidos.add(self.vendedor, self.admin)
        ajeno = self.cliente('ajena-123', 'Persona ajena')
        self.venta(self.admin, cliente=ajeno)
        compartido = self.cliente('compartida-123', 'Persona compartida')
        self.venta(self.admin, cliente=compartido).vendedores_compartidos.add(self.vendedor)
        self.cliente('sin-ventas', 'Persona sin ventas')
        api = self.api(self.vendedor)
        r = api.get('/api/calidad-clientes/')
        self.assertEqual({v['cliente']['id'] for v in r.data['results']}, {self.cliente1.pk, compartido.pk})
        self.assertEqual(r.data['count'], 2)
        for sufijo in ('', 'historial/'):
            self.assertEqual(api.get(f'/api/calidad-clientes/{ajeno.pk}/{sufijo}').status_code, 404)
        self.assertEqual(api.post(f'/api/calidad-clientes/{ajeno.pk}/normalizar/', {
            'version': self.ficha(ajeno).data['version'], 'campos': ['telefono1'],
        }, format='json').status_code, 404)
        self.assertEqual(api.get('/api/calidad-clientes/comparar/', {'origen': self.cliente1.pk, 'destino': ajeno.pk}).status_code, 404)

    def test_candidatos_no_revelan_coincidencias_ajenas(self):
        self.permisos('vendedor', ['VER_CLIENTES', 'VER_CALIDAD_CLIENTES'])
        self.venta(self.vendedor, cliente=self.cliente1)
        self.cliente('00123456', 'Otro nombre')
        r = self.api(self.vendedor).get('/api/calidad-clientes/candidatos/')
        self.assertEqual(r.data['count'], 0)
        self.assertEqual(r.data['clientes_revisados'], 1)

    def test_documentos_coinciden_sin_quitar_ceros_o_letras(self):
        coincidente = self.cliente('00123456', 'Otro nombre')
        self.cliente('123456', 'Otra persona')
        self.cliente('AB00123456', 'Persona extranjera')
        r = self.c.get('/api/calidad-clientes/candidatos/')
        self.assertEqual(r.data['count'], 1)
        self.assertEqual({c['id'] for c in r.data['results'][0]['clientes']}, {self.cliente1.pk, coincidente.pk})

    def test_nombre_o_contacto_aislados_no_bastan(self):
        Cliente.objects.create(cedula='99001', nombre='María López', telefono1='9991234567')
        Cliente.objects.create(cedula='99002', nombre='Persona distinta', telefono1='+573012345678')
        self.assertEqual(self.c.get('/api/calidad-clientes/candidatos/').data['count'], 0)
        Cliente.objects.create(cedula='99003', nombre='MARIA LOPEZ', telefono1='+573012345678')
        self.assertEqual(self.c.get('/api/calidad-clientes/candidatos/').data['count'], 1)

    def test_misma_coincidencia_por_varios_criterios_no_duplica_grupo(self):
        Cliente.objects.create(cedula='00123456', nombre='María López', telefono1='+573012345678', correo='Persona@example.com')
        r = self.c.get('/api/calidad-clientes/candidatos/', {'buscar': '001.234', 'page_size': 1})
        self.assertEqual(r.data['count'], 1)
        self.assertEqual(len(r.data['results'][0]['razones']), 3)
        self.assertEqual(len(r.data['results'][0]['clientes']), 2)

    def test_revision_nunca_entrega_resultado_truncado(self):
        with patch('ordenes.calidad_clientes.LIMITE_CLIENTES', 0):
            self.assertEqual(self.c.get('/api/calidad-clientes/candidatos/').status_code, 413)
        self.cliente('00123456', 'Coincidencia')
        with patch('ordenes.calidad_clientes.LIMITE_GRUPO', 1):
            self.assertEqual(self.c.get('/api/calidad-clientes/candidatos/').status_code, 413)

    def test_permisos_normalizacion_son_adicionales(self):
        self.venta(self.vendedor, cliente=self.cliente1)
        for permiso in ('EDITAR_CLIENTE', 'NORMALIZAR_CLIENTES'):
            self.permisos('vendedor', ['VER_CLIENTES', 'VER_CALIDAD_CLIENTES', permiso])
            self.assertEqual(self.aplicar(api=self.api(self.vendedor)).status_code, 403)
        self.assertFalse(CorreccionCliente.objects.exists())

    def test_guardar_solo_campos_elegidos_preserva_original_y_documentos(self):
        v = self.venta(self.admin, cliente=self.cliente1)
        antes = list(Venta.objects.values())
        r = self.aplicar()
        self.assertEqual(r.status_code, 200, r.data)
        self.cliente1.refresh_from_db()
        self.assertEqual(self.cliente1.telefono1, '+573012345678')
        self.assertEqual(self.cliente1.nombre, '  María  López ')
        self.assertEqual(self.cliente1.cedula, '001.234-56')
        self.assertEqual(list(Venta.objects.values()), antes)
        h = CorreccionCliente.objects.get()
        self.assertEqual(h.cliente_id, v.cliente_id)
        self.assertEqual(h.cambios, {'telefono1': {'antes': '+57 (301) 234-5678', 'despues': '+573012345678'}})
        log = RegistroAuditoria.objects.get(accion='cliente.normalizar')
        self.assertEqual(log.detalle, {'revision': h.pk, 'campos': ['telefono1']})
        self.assertNotIn('301', str(log.detalle))

    def test_cambio_concurrente_rechaza_version_desactualizada(self):
        version = self.ficha().data['version']
        Cliente.objects.filter(pk=self.cliente1.pk).update(direccion='Dirección actualizada')
        r = self.aplicar(version=version)
        self.assertEqual(r.status_code, 409)
        self.assertFalse(CorreccionCliente.objects.exists())
        self.cliente1.refresh_from_db()
        self.assertEqual(self.cliente1.direccion, 'Dirección actualizada')

    def test_version_adulterada_o_de_otro_cliente_no_se_acepta(self):
        otro = self.cliente('otro123', 'Otro')
        for version in ('inventada', self.ficha(otro).data['version']):
            self.assertEqual(self.aplicar(version=version).status_code, 409)
        self.assertFalse(CorreccionCliente.objects.exists())

    def test_version_expirada_requiere_nueva_revision(self):
        with patch('django.core.signing.time.time', return_value=1000):
            version = self.ficha().data['version']
        with patch('django.core.signing.time.time', return_value=3000):
            self.assertEqual(self.aplicar(version=version).status_code, 409)

    def test_no_acepta_identidad_campos_no_propuestos_ni_seleccion_vacia(self):
        for campos in (['cedula'], ['correo'], [], ['telefono1', 'telefono1']):
            self.assertEqual(self.aplicar(campos=campos).status_code, 400, campos)
        self.assertFalse(CorreccionCliente.objects.exists())

    def test_reintento_idempotente_no_duplica_historial(self):
        data = {'version': self.ficha().data['version'], 'campos': ['telefono1']}
        for _ in range(2):
            r = self.c.post(f'/api/calidad-clientes/{self.cliente1.pk}/normalizar/', data, format='json', HTTP_IDEMPOTENCY_KEY='formato-1')
            self.assertEqual(r.status_code, 200)
        self.assertEqual(CorreccionCliente.objects.count(), 1)
        self.assertEqual(RegistroAuditoria.objects.filter(accion='cliente.normalizar').count(), 1)

    def test_reintento_revalida_alcance_antes_de_devolver_datos_anteriores(self):
        self.permisos('vendedor', ['VER_CLIENTES', 'VER_CALIDAD_CLIENTES', 'EDITAR_CLIENTE', 'NORMALIZAR_CLIENTES'])
        venta = self.venta(self.admin, cliente=self.cliente1)
        venta.vendedores_compartidos.add(self.vendedor)
        api = self.api(self.vendedor)
        data = {'version': self.ficha(api=api).data['version'], 'campos': ['telefono1']}
        url = f'/api/calidad-clientes/{self.cliente1.pk}/normalizar/'
        self.assertEqual(api.post(url, data, format='json', HTTP_IDEMPOTENCY_KEY='alcance').status_code, 200)
        venta.vendedores_compartidos.clear()
        self.assertEqual(api.post(url, data, format='json', HTTP_IDEMPOTENCY_KEY='alcance').status_code, 404)
        self.assertEqual(CorreccionCliente.objects.count(), 1)

    def test_fallo_de_auditoria_revierte_cambio_e_historia(self):
        with patch('ordenes.calidad_clientes.auditar', side_effect=RuntimeError('Fallo simulado')):
            self.assertEqual(self.aplicar().status_code, 500)
        self.cliente1.refresh_from_db()
        self.assertEqual(self.cliente1.telefono1, '+57 (301) 234-5678')
        self.assertFalse(CorreccionCliente.objects.exists())

    def test_identificadores_genericos_no_sugieren_identidad_compartida(self):
        self.cliente('000000', 'Sin documento A')
        self.cliente('000.000', 'Sin documento B')
        self.assertEqual(self.c.get('/api/calidad-clientes/candidatos/').data['count'], 0)

    def test_historial_se_pagina_y_no_admite_edicion_ni_borrado(self):
        self.aplicar()
        self.aplicar(campos=['direccion'])
        r = self.c.get(f'/api/calidad-clientes/{self.cliente1.pk}/historial/', {'page_size': 1})
        self.assertEqual(r.data['count'], 2)
        self.assertEqual(len(r.data['results']), 1)
        self.assertEqual(self.c.delete(f'/api/calidad-clientes/{self.cliente1.pk}/').status_code, 405)

    def test_comparacion_destaca_conflictos_y_no_fusiona(self):
        otro = self.cliente('otro123', 'Otro nombre')
        self.venta(self.admin, cliente=self.cliente1)
        self.venta(self.admin, cliente=otro)
        antes = list(Venta.objects.values()), list(Cliente.objects.values())
        r = self.c.get('/api/calidad-clientes/comparar/', {'origen': self.cliente1.pk, 'destino': otro.pk})
        self.assertEqual(r.status_code, 200, r.data)
        self.assertFalse(r.data['puede_fusionar'])
        self.assertIn('cedula', r.data['conflictos'])
        self.assertEqual(r.data['ventas_visibles'], {'origen': 1, 'destino': 1})
        self.assertEqual(antes, (list(Venta.objects.values()), list(Cliente.objects.values())))
        self.assertEqual(self.c.post('/api/calidad-clientes/comparar/', {}, format='json').status_code, 405)
        self.assertEqual(self.c.get('/api/calidad-clientes/comparar/', {'origen': otro.pk, 'destino': otro.pk}).status_code, 400)

    def test_consultas_no_crecen_por_fila(self):
        with CaptureQueriesContext(connection) as pocas:
            self.c.get('/api/calidad-clientes/')
        for n in range(12):
            self.cliente(f'cliente-{n}', f' Nombre  {n} ')
        with CaptureQueriesContext(connection) as muchas:
            self.c.get('/api/calidad-clientes/')
        self.assertEqual(len(pocas), len(muchas))
        self.assertLessEqual(len(muchas), 15)
