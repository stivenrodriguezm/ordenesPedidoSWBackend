"""Agente de la oficina cuando no encuentra la impresora (2026-10-30): antes el documento se
quedaba en la cola de CUPS y la web cargando sin decir nada."""
import importlib.util
import subprocess
import time
from pathlib import Path
from unittest import TestCase, mock

RUTA = Path(__file__).resolve().parent.parent / 'scripts' / 'impresion' / 'agente.py'
_spec = importlib.util.spec_from_file_location('agente_impresion', RUTA)
agente = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(agente)

SERVIDOR = {'nombre': 'prueba', 'api': 'https://x/api', 'token': 't'}
URI = 'dispositivo para COLA: dnssd://RICOH%20SP%203710SF%20(50f7b8)._ipps._tcp.local./?uuid=abc\n'


def respuesta(stdout='', codigo=0):
    return subprocess.CompletedProcess([], codigo, stdout=stdout, stderr='')


class BuscarImpresoraTests(TestCase):
    def test_dnssd_usa_ippfind_con_el_nombre_del_servicio(self):
        for codigo, esperado in ((0, True), (1, False)):
            with mock.patch.object(agente.subprocess, 'run', side_effect=[respuesta(URI), respuesta(codigo=codigo)]) as run:
                self.assertIs(agente.impresora_encontrada('COLA'), esperado)
            self.assertEqual(run.call_args_list[1].args[0], ['ippfind', 'RICOH SP 3710SF (50f7b8)._ipps._tcp.local.', '-T', '3'])

    def test_direccion_fija_prueba_la_conexion(self):
        with mock.patch.object(agente.subprocess, 'run', return_value=respuesta('device for COLA: socket://10.0.0.9:9100\n')), \
                mock.patch.object(agente.socket, 'create_connection', side_effect=OSError) as con:
            self.assertIs(agente.impresora_encontrada('COLA'), False)
        con.assert_called_once_with(('10.0.0.9', 9100), timeout=3)

    def test_si_no_se_puede_saber_no_afirma_nada(self):
        with mock.patch.object(agente.subprocess, 'run', return_value=respuesta('device for COLA: usb://Ricoh/SP\n')):
            self.assertIsNone(agente.impresora_encontrada('COLA'))
        with mock.patch.object(agente.subprocess, 'run', side_effect=OSError):
            self.assertIsNone(agente.impresora_encontrada('COLA'))


class TrabajoAtascadoTests(TestCase):
    def setUp(self):
        with mock.patch.object(agente, 'cargar_config', return_value={'cola': 'COLA', 'servidores': [SERVIDOR]}):
            self.a = agente.Agente()
        for nombre in ('pedir', 'cancelar_en_cups', 'pendientes_cups', 'impresora_encontrada'):
            p = mock.patch.object(agente, nombre)
            setattr(self, nombre, p.start())
            self.addCleanup(p.stop)
        self.pendientes_cups.return_value = {'COLA-1'}

    def en_cola(self, hace):
        self.a.en_vuelo['COLA-1'] = (SERVIDOR, 7, time.time() - hace)

    def test_sin_impresora_avisa_una_vez_y_sigue_esperando(self):
        self.a.impresora_ok = False
        self.en_cola(10)
        self.a.revisar_en_vuelo()
        self.a.revisar_en_vuelo()
        self.pedir.assert_called_once_with(SERVIDOR, '/impresion/agente/trabajos/7/', {'estado': 'enviado', 'detalle': agente.NO_ENCONTRADA})
        self.cancelar_en_cups.assert_not_called()

    def test_sin_impresora_cancela_y_reporta_error_para_que_la_web_no_quede_cargando(self):
        self.a.impresora_ok = False
        self.impresora_encontrada.return_value = False
        self.en_cola(agente.CANCELAR_SEG + 1)
        self.a.revisar_en_vuelo()
        self.cancelar_en_cups.assert_called_once_with('COLA-1')
        datos = self.pedir.call_args.args[2]
        self.assertEqual(datos['estado'], 'error')
        self.assertIn('No se imprimió', datos['detalle'])
        self.assertLessEqual(len(datos['detalle']), 255)
        self.assertNotIn('COLA-1', self.a.en_vuelo)

    def test_no_cancela_si_al_volver_a_buscar_la_impresora_aparecio(self):
        self.a.impresora_ok = False
        self.impresora_encontrada.return_value = True
        self.en_cola(agente.CANCELAR_SEG + 1)
        self.a.revisar_en_vuelo()
        self.cancelar_en_cups.assert_not_called()
        self.assertIn('COLA-1', self.a.en_vuelo)

    def test_con_impresora_no_cancela_aunque_tarde(self):
        self.a.impresora_ok = True
        self.en_cola(agente.CANCELAR_SEG + 1)
        self.a.revisar_en_vuelo()
        self.cancelar_en_cups.assert_not_called()
        self.pedir.assert_not_called()

    def test_si_salio_de_la_cola_queda_impreso(self):
        self.a.impresora_ok = True
        self.pendientes_cups.return_value = set()
        self.en_cola(5)
        self.a.revisar_en_vuelo()
        self.pedir.assert_called_once_with(SERVIDOR, '/impresion/agente/trabajos/7/', {'estado': 'impreso'})
