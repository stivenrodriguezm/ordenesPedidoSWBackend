"""Perfiles de IA y aprendizaje por retroalimentación (Gemini simulado)."""
import io
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings

from ordenes.asistente import gemini, herramientas, perfiles
from ordenes.models import AprendizajeAsistente, PerfilAsistente
from ordenes.tests.test_asistente import respuesta_llamada, respuesta_texto
from ordenes.tests.utils import LottusTestCase

INSTRUCCIONES = 'Eres el analista de ventas de Lottus. Respondes con tablas cortas y siempre comparas contra la meta.'


def pdf_con_texto(texto):
    """PDF mínimo de una página con texto (sin dependencias extra)."""
    contenido = f'BT /F1 12 Tf 72 720 Td ({texto}) Tj ET'.encode('latin-1')
    objetos = [b'<< /Type /Catalog /Pages 2 0 R >>', b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
               b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>',
               b'<< /Length %d >>\nstream\n' % len(contenido) + contenido + b'\nendstream',
               b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>']
    salida, posiciones = io.BytesIO(), []
    salida.write(b'%PDF-1.4\n')
    for i, o in enumerate(objetos, 1):
        posiciones.append(salida.tell())
        salida.write(b'%d 0 obj\n' % i + o + b'\nendobj\n')
    xref = salida.tell()
    salida.write(b'xref\n0 %d\n0000000000 65535 f \n' % (len(objetos) + 1))
    for p in posiciones:
        salida.write(b'%010d 00000 n \n' % p)
    salida.write(b'trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF' % (len(objetos) + 1, xref))
    return salida.getvalue()


@override_settings(GEMINI_API_KEY='clave-de-prueba', GEMINI_MODELOS=['modelo-a'], ASISTENTE_EN_SEGUNDO_PLANO=False)
class PerfilesIATests(LottusTestCase):
    def setUp(self):
        gemini._saturados.clear()
        self.gerente = self.crear_usuario('gerente', 'administrador', first_name='Gerente')
        self.api_gerente = self.api(self.gerente)
        self.asesor = self.crear_usuario('asesora', first_name='Ana')
        self.permisos('vendedor', ['USAR_ASISTENTE_IA'])

    def crear_perfil(self, **extra):
        datos = {'nombre': 'Analista de ventas', 'rol': 'Analista comercial', 'instrucciones': INSTRUCCIONES,
                 'icono': 'grafica', 'color': 'verde', 'areas': ['ventas'], **extra}
        r = self.api_gerente.post('/api/asistente/perfiles/', datos, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        return r.data

    def test_solo_quien_gestiona_crea_y_los_demas_ven_los_activos(self):
        perfil = self.crear_perfil()
        archivado=self.crear_perfil(nombre='Archivado', activo=False)
        asesora = self.api(self.asesor)
        self.assertEqual(asesora.post('/api/asistente/perfiles/', {'nombre': 'x'}, format='json').status_code, 403)
        self.assertEqual(asesora.delete(f"/api/asistente/perfiles/{perfil['id']}/").status_code, 403)
        visibles=asesora.get('/api/asistente/perfiles/').data
        self.assertIn(perfil['id'],[p['id'] for p in visibles])
        self.assertNotIn(archivado['id'],[p['id'] for p in visibles])
        self.assertTrue(all(p['activo'] for p in visibles))
        self.assertTrue({perfil['id'],archivado['id']}.issubset({p['id'] for p in self.api_gerente.get('/api/asistente/perfiles/').data}))
        self.assertFalse(asesora.get('/api/asistente/estado/').data['puede_gestionar_perfiles'])

    def test_valida_instrucciones_areas_e_icono(self):
        r = self.api_gerente.post('/api/asistente/perfiles/', {'nombre': 'X', 'rol': 'Y', 'instrucciones': 'corto', 'areas': ['bancos'], 'icono': 'otro'}, format='json')
        self.assertEqual(r.status_code, 400)
        self.assertEqual(set(r.data), {'instrucciones', 'areas', 'icono'})

    def test_documentos_md_y_pdf_alimentan_el_perfil(self):
        perfil = self.crear_perfil()
        url = f"/api/asistente/perfiles/{perfil['id']}/documentos/"
        md = SimpleUploadedFile('Politica de descuentos.md', '# Descuentos\n- Máximo 15 % sin aprobación del gerente.'.encode())
        r = self.api_gerente.post(url, {'archivo': md}, format='multipart')
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual((r.data['tipo'], r.data['recortado']), ('md', False))
        pdf = SimpleUploadedFile('Manual.pdf', pdf_con_texto('Garantia de 5 anos en estructura'), content_type='application/pdf')
        r = self.api_gerente.post(url, {'archivo': pdf}, format='multipart')
        self.assertEqual(r.status_code, 201, r.data)
        self.assertIn('Garantia de 5 anos', r.data['vista_previa'])
        malo = SimpleUploadedFile('foto.png', b'\x89PNG....')
        self.assertIn('Formato no admitido', self.api_gerente.post(url, {'archivo': malo}, format='multipart').data['error'])
        vacio = SimpleUploadedFile('vacio.txt', b'   ')
        self.assertIn('No se encontró texto', self.api_gerente.post(url, {'archivo': vacio}, format='multipart').data['error'])
        detalle = self.api_gerente.get(f"/api/asistente/perfiles/{perfil['id']}/").data
        self.assertEqual([d['nombre'] for d in detalle['documentos']], ['Politica de descuentos.md', 'Manual.pdf'])

        # La IA recibe instrucciones, documentos y solo las herramientas de sus áreas.
        with mock.patch.object(gemini, '_llamar', return_value=respuesta_texto('Listo.')) as m:
            r = self.api_gerente.post('/api/asistente/preguntar/', {'texto': '¿Puedo dar 20 %?', 'perfil': perfil['id']}, format='json')
        self.assertEqual(r.data['conversacion']['perfil']['nombre'], 'Analista de ventas')
        cuerpo = m.call_args[0][1]
        sistema = cuerpo['systemInstruction']['parts'][0]['text']
        self.assertIn('Perfil especializado activo: Analista de ventas', sistema)
        # Todo perfil entiende la plataforma: pantallas (frontend) y modelos (base de datos).
        self.assertIn('Menú lateral (sidebar) y pantallas', sistema)
        self.assertIn('- Venta', sistema)
        self.assertNotIn('password', sistema)
        self.assertIn('Máximo 15 % sin aprobación', sistema)
        self.assertIn('Garantia de 5 anos', sistema)
        nombres = {f['name'] for f in cuerpo['tools'][0]['functionDeclarations']}
        self.assertIn('ventas_por_asesor', nombres)
        self.assertNotIn('nomina', nombres)
        self.assertNotIn('finanzas', nombres)
        dominios = next(f for f in cuerpo['tools'][0]['functionDeclarations'] if f['name'] == 'consulta_datos')['parameters']['properties']['dominio']['enum']
        self.assertEqual(dominios, ['ventas', 'productos'])
        # La siguiente pregunta de la conversación conserva el perfil aunque no se envíe.
        with mock.patch.object(gemini, '_llamar', return_value=respuesta_texto('Sí.')) as m:
            self.api_gerente.post('/api/asistente/preguntar/', {'texto': '¿Y 18 %?', 'conversacion': r.data['conversacion']['id']}, format='json')
        self.assertIn('Analista de ventas', m.call_args[0][1]['systemInstruction']['parts'][0]['text'])

    def test_no_supera_la_capacidad_de_conocimiento(self):
        perfil = self.crear_perfil()
        url = f"/api/asistente/perfiles/{perfil['id']}/documentos/"
        with mock.patch.object(perfiles, 'MAX_CONOCIMIENTO_PERFIL', 100):
            r = self.api_gerente.post(url, {'archivo': SimpleUploadedFile('largo.txt', ('texto ' * 50).encode())}, format='multipart')
        self.assertEqual(r.status_code, 400)
        self.assertIn('no tiene espacio', r.data['error'])

    def test_perfil_no_puede_consultar_areas_no_habilitadas(self):
        perfil = PerfilAsistente.objects.create(nombre='Cobranza', rol='Cartera', instrucciones=INSTRUCCIONES, areas=['cobros'])
        self.assertIn('error', herramientas.ejecutar('nomina', {}, perfil.areas))
        self.assertIn('error', herramientas.ejecutar('consulta_datos', {'dominio': 'ventas'}, perfil.areas))
        self.assertNotIn('error', herramientas.ejecutar('saldos_por_cobrar', {}, perfil.areas))
        # Aunque el modelo pida una herramienta ajena, recibe el error y no los datos.
        respuestas = [respuesta_llamada('nomina', {}), respuesta_texto('No tengo acceso a nómina.')]
        with mock.patch.object(gemini, '_llamar', side_effect=respuestas) as m:
            self.api_gerente.post('/api/asistente/preguntar/', {'texto': 'Nómina', 'perfil': perfil.pk}, format='json')
        devuelto = m.call_args[0][1]['contents'][2]['parts'][0]['functionResponse']['response']['resultado']
        self.assertIn('no tiene acceso', devuelto['error'])
        # Un perfil sin áreas conserva solo colaboración; no recibe herramientas de datos.
        solo_conocimiento = PerfilAsistente.objects.create(nombre='Redactor', rol='Textos', instrucciones=INSTRUCCIONES, areas=[])
        with mock.patch.object(gemini, '_llamar', return_value=respuesta_texto('Hola.')) as m:
            self.api_gerente.post('/api/asistente/preguntar/', {'texto': 'Hola', 'perfil': solo_conocimiento.pk}, format='json')
        funciones=m.call_args[0][1]['tools'][0]['functionDeclarations']
        self.assertEqual({f['name'] for f in funciones},{'consultar_agente_oficina','pedir_orientacion_administrador'})

    def test_retroalimentacion_entrena_las_siguientes_respuestas(self):
        perfil = self.crear_perfil()
        with mock.patch.object(gemini, '_llamar', return_value=respuesta_texto('Vendimos $10 en una tabla larga.')):
            r = self.api_gerente.post('/api/asistente/preguntar/', {'texto': '¿Cómo vamos?', 'perfil': perfil['id']}, format='json')
        mensaje = r.data['respuesta']['id']
        r = self.api_gerente.post(f'/api/asistente/mensajes/{mensaje}/valorar/', {'valoracion': 'mejora', 'comentario': 'Muy largo, dame solo 3 viñetas'}, format='json')
        self.assertEqual((r.data['valoracion'], r.data['comentario']), ('mejora', 'Muy largo, dame solo 3 viñetas'))
        # Cambiar de opinión reemplaza la valoración (una por respuesta).
        r = self.api_gerente.post(f'/api/asistente/mensajes/{mensaje}/valorar/', {'valoracion': 'gusto'}, format='json')
        self.assertEqual((r.data['valoracion'], r.data['comentario']), ('gusto', ''))
        self.api_gerente.post(f'/api/asistente/mensajes/{mensaje}/valorar/', {'valoracion': 'mejora', 'comentario': 'Muy largo, dame solo 3 viñetas'}, format='json')
        r = self.api_gerente.post(f'/api/asistente/mensajes/{mensaje}/notas/', {'texto': 'Resalta siempre el saldo por cobrar'}, format='json')
        self.assertEqual(r.status_code, 201)
        self.assertEqual([n['texto'] for n in r.data['notas']], ['Resalta siempre el saldo por cobrar'])
        self.assertEqual(AprendizajeAsistente.objects.filter(usuario=self.gerente).count(), 2)

        with mock.patch.object(gemini, '_llamar', return_value=respuesta_texto('Ok.')) as m:
            self.api_gerente.post('/api/asistente/preguntar/', {'texto': '¿Y hoy?', 'perfil': perfil['id']}, format='json')
        sistema = m.call_args[0][1]['systemInstruction']['parts'][0]['text']
        self.assertIn('Preferencias aprendidas', sistema)
        self.assertIn('No le gustó tu respuesta (sobre «¿Cómo vamos?»): Muy largo, dame solo 3 viñetas', sistema)
        self.assertIn('Recuerda (sobre «¿Cómo vamos?»): Resalta siempre el saldo por cobrar', sistema)
        # Lo aprendido con un perfil no se mezcla con la IA general ni con otros usuarios.
        with mock.patch.object(gemini, '_llamar', return_value=respuesta_texto('Ok.')) as m:
            self.api_gerente.post('/api/asistente/preguntar/', {'texto': 'General'}, format='json')
        self.assertNotIn('Preferencias aprendidas', m.call_args[0][1]['systemInstruction']['parts'][0]['text'])

        # El usuario puede pausar o borrar lo aprendido.
        lista = self.api_gerente.get(f"/api/asistente/aprendizajes/?perfil={perfil['id']}").data
        self.assertEqual({a['tipo'] for a in lista}, {'mejora', 'nota'})
        for a in lista:
            self.assertEqual(self.api_gerente.patch(f"/api/asistente/aprendizajes/{a['id']}/", {'activo': False}, format='json').status_code, 200)
        with mock.patch.object(gemini, '_llamar', return_value=respuesta_texto('Ok.')) as m:
            self.api_gerente.post('/api/asistente/preguntar/', {'texto': '¿Y ayer?', 'perfil': perfil['id']}, format='json')
        self.assertNotIn('Preferencias aprendidas', m.call_args[0][1]['systemInstruction']['parts'][0]['text'])
        otro = self.api(self.crear_usuario('otro-admin', 'administrador'))
        self.assertEqual(otro.delete(f"/api/asistente/aprendizajes/{lista[0]['id']}/").status_code, 404)
        self.assertEqual(otro.post(f'/api/asistente/mensajes/{mensaje}/valorar/', {'valoracion': 'gusto'}, format='json').status_code, 404)
        self.assertEqual(self.api_gerente.delete(f"/api/asistente/aprendizajes/{lista[0]['id']}/").status_code, 204)

    def test_nota_directa_y_valoracion_sin_comentario(self):
        r = self.api_gerente.post('/api/asistente/aprendizajes/', {'texto': 'Siempre en millones'}, format='json')
        self.assertEqual(r.status_code, 201)
        with mock.patch.object(gemini, '_llamar', return_value=respuesta_texto('Conclusión: vamos bien con ventas altas.')) as m:
            r = self.api_gerente.post('/api/asistente/preguntar/', {'texto': '¿Cómo vamos?'}, format='json')
        self.assertIn('Recuerda: Siempre en millones', m.call_args[0][1]['systemInstruction']['parts'][0]['text'])
        self.api_gerente.post(f"/api/asistente/mensajes/{r.data['respuesta']['id']}/valorar/", {'valoracion': 'gusto'}, format='json')
        self.assertIn('Le gustó tu respuesta (sobre «¿Cómo vamos?»); conserva ese enfoque. Empezaba así: «Conclusión: vamos bien',
                      perfiles.bloque_aprendizajes(self.gerente, None))
        self.assertEqual(self.api_gerente.get(f"/api/asistente/conversaciones/{r.data['conversacion']['id']}/").data['mensajes'][1]['valoracion'], 'gusto')
