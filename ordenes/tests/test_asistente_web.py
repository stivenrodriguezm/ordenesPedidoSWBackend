"""Permiso de web, confinamiento de archivos y transporte visual, sin red real."""
import base64
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from django.test import override_settings
from PIL import Image

from ordenes.asistente import gemini, herramientas, web
from ordenes.models import PerfilAsistente
from ordenes.tests.test_asistente import respuesta_llamada, respuesta_texto
from ordenes.tests.utils import LottusTestCase
from paginaweb.models import PaginawebProducto, PaginawebSetting


@override_settings(GEMINI_API_KEY='clave-ficticia', GEMINI_MODELOS=['gemini-3.8-flash'], ASISTENTE_EN_SEGUNDO_PLANO=False)
class WebAsistenteTests(LottusTestCase):
    def setUp(self):
        gemini._saturados.clear()
        self.usuario = self.crear_usuario('director', 'administrador')
        self.api_director = self.api(self.usuario)
        self.temporal = TemporaryDirectory()
        self.addCleanup(self.temporal.cleanup)
        self.raiz = Path(self.temporal.name)
        self.web = self.raiz / 'web'
        (self.web / 'public/css').mkdir(parents=True)
        (self.web / 'public/img').mkdir()
        (self.web / 'public/index.html').write_text('<html><head><meta name="description" content="Muebles LOTTUS"></head><body><h1>Diseño para vivir</h1><p>Contenido público.</p><img src="/img/hero.jpg" alt="Sala"><script>OCULTO_SCRIPT</script></body></html>')
        (self.web / 'public/css/style.css').write_text(':root {--marca: #c9a227;} h1 {font-family: Inter;} @media (max-width: 600px) {h1 {color: #fff;}}')
        Image.new('RGB', (60, 40), '#334455').save(self.web / 'public/img/hero.jpg')
        self.opciones = override_settings(ASISTENTE_WEB_ROOT=self.web, ASISTENTE_LANDING_ROOT=self.raiz / 'landing')
        self.opciones.enable()
        self.addCleanup(self.opciones.disable)

    def test_permiso_se_guarda_por_agente_y_restringe_las_tres_herramientas(self):
        estado = self.api_director.get('/api/asistente/estado/').data
        self.assertIn('pagina_web', [a['id'] for a in estado['areas']])
        r = self.api_director.post('/api/asistente/perfiles/', {'nombre':'Director web', 'rol':'Marketing',
            'instrucciones':'Tu objetivo es mejorar el contenido y la experiencia de la web de LOTTUS.', 'areas':['pagina_web']}, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        pk = r.data['id']
        self.assertEqual(PerfilAsistente.objects.get(pk=pk).areas, ['pagina_web'])
        nombres, dominios = herramientas.permitidas(['pagina_web'])
        self.assertEqual(nombres, {'consultar_pagina_web','leer_codigo_pagina_web','ver_imagen_pagina_web'})
        self.assertEqual(dominios, set())
        self.api_director.patch(f'/api/asistente/perfiles/{pk}/', {'areas':[]}, format='json')
        for nombre in nombres:
            with mock.patch.object(web, '_archivos') as archivos:
                r = herramientas.ejecutar(nombre, {}, areas=PerfilAsistente.objects.get(pk=pk).areas)
            self.assertIn('no tiene acceso', r['error'])
            archivos.assert_not_called()

    def test_contenido_publico_y_diseno_no_incluyen_configuracion_privada(self):
        PaginawebSetting.objects.create(key='heroTitle', value='Título vigente')
        PaginawebSetting.objects.create(key='smtpPassword', value='DATO_FICTICIO_PRIVADO')
        r = web.consultar({})
        self.assertEqual(r['pagina']['encabezados'], [{'nivel':'h1','texto':'Diseño para vivir'}])
        self.assertNotIn('OCULTO_SCRIPT', r['pagina']['texto'])
        self.assertEqual(r['configuracion_publica'], {'heroTitle':'Título vigente'})
        self.assertIn('#c9a227', r['diseno']['colores'])
        self.assertNotIn('DATO_FICTICIO_PRIVADO', json.dumps(r))
        self.assertLess(len(json.dumps(r)), gemini.MAX_RESULTADO_CARACTERES)

    def test_codigo_pagina_y_confinamiento_frente_a_rutas_y_enlaces(self):
        secreto = self.raiz / 'fuera.js'
        secreto.write_text('MARCADOR_FUERA_DEL_SITIO')
        (self.web / '.env').write_text('MARCADOR_FUERA_DEL_SITIO')
        (self.web / 'public/enlace.js').symlink_to(secreto)
        (self.web / 'privado.js').write_text('MARCADOR_FUERA_DEL_SITIO')
        (self.web / 'public/enlace-interno.js').symlink_to(self.web / 'privado.js')
        for nombre in ['../fuera.js', str(secreto), 'public/enlace.js', 'public/enlace-interno.js', '.env', 'public/../../fuera.js']:
            with self.assertRaises(ValueError):
                web.leer_codigo({'archivo':nombre})
        r = web.leer_codigo({'archivo':'public/css/style.css','lineas':1})
        self.assertIn('1: :root', r['codigo'])
        self.assertIsNone(r['siguiente_linea'])
        self.assertNotIn('MARCADOR_FUERA_DEL_SITIO', json.dumps(web.consultar({'seccion':'archivos'})))

    def test_codigo_de_gestion_y_api_sin_acceso_al_resto_de_la_plataforma(self):
        gestion = self.raiz / 'gestion'
        (gestion / 'src/pages/paginaweb').mkdir(parents=True)
        (gestion / 'src/pages/paginaweb/Panel.jsx').write_text('export default function PanelWeb() {}')
        (gestion / 'src/AppContext.jsx').write_text('CONTEXTO_FUERA_DEL_ALCANCE')
        api = self.raiz / 'api-web'
        api.mkdir()
        (api / 'views.py').write_text('def public_products(request): pass')
        (api / 'settings.py').write_text('AJUSTES_FUERA_DEL_ALCANCE')
        with override_settings(ASISTENTE_GESTION_WEB_ROOT=gestion, ASISTENTE_BACKEND_WEB_ROOT=api):
            self.assertIn('PanelWeb', web.leer_codigo({'proyecto':'gestion','archivo':'src/pages/paginaweb/Panel.jsx'})['codigo'])
            self.assertIn('public_products', web.leer_codigo({'proyecto':'backend_web','archivo':'views.py'})['codigo'])
            for proyecto, archivo in [('gestion','src/AppContext.jsx'),('backend_web','settings.py')]:
                with self.assertRaises(ValueError):
                    web.leer_codigo({'proyecto':proyecto,'archivo':archivo})

    def test_catalogo_solo_publicados_y_sin_precios_internos(self):
        PaginawebProducto.objects.create(id='uno', slug='uno', name='Sofá', active=True, price=777,
            variants=[{'name':'Roble', 'price':999}], images=['/img/hero.jpg'])
        PaginawebProducto.objects.create(id='dos', slug='dos', name='BORRADOR_PRIVADO', active=False)
        r = web.consultar({'seccion':'catalogo'})
        self.assertEqual(r['total'], 1)
        self.assertEqual(r['productos'][0]['variants'], [{'name':'Roble'}])
        self.assertNotIn('price', json.dumps(r))
        self.assertNotIn('BORRADOR_PRIVADO', json.dumps(r))

    def test_imagen_real_y_bloqueo_de_descargas_arbitrarias(self):
        r = web.ver_imagen({'archivo':'public/img/hero.jpg'})
        self.assertEqual(r['dimensiones_originales'], {'ancho':60,'alto':40})
        self.assertTrue(base64.b64decode(r['_imagenes'][0]['data']).startswith(b'\xff\xd8'))
        for url in ['http://127.0.0.1:8000/admin/', 'https://otro.invalid/a.jpg', 'file:///tmp/a.jpg', '//res.cloudinary.com/a.jpg']:
            with mock.patch.object(web.requests, 'get') as descargar, self.assertRaises(ValueError):
                web._bytes_publicados(url)
            descargar.assert_not_called()

    def test_gemini_recibe_imagen_multimodal_sin_base64_en_texto_ni_historial_guardado(self):
        perfil = PerfilAsistente.objects.create(nombre='Director web', rol='Marketing', areas=['pagina_web'],
            instrucciones='Tu objetivo es estudiar las fotografías de la web.')
        for modelo in ['gemini-3.8-flash', 'gemini-2.5-flash']:
            with self.subTest(modelo=modelo), override_settings(GEMINI_MODELOS=[modelo]), mock.patch.object(gemini, '_llamar', side_effect=[
                respuesta_llamada('ver_imagen_pagina_web', {'archivo':'public/img/hero.jpg'}), respuesta_texto('Fotografía analizada.')]) as proveedor:
                r = self.api_director.post('/api/asistente/preguntar/', {'perfil':perfil.pk,'texto':'Estudia la imagen hero del sitio.'}, format='json')
            self.assertEqual(r.data['respuesta']['estado'], 'listo', r.data)
            partes = proveedor.call_args[0][1]['contents'][-1]['parts']
            funcion = partes[0]['functionResponse']
            visual = funcion['parts'] if modelo.startswith('gemini-3') else [p for p in partes if 'inlineData' in p]
            self.assertEqual(visual[0]['inlineData']['mimeType'], 'image/jpeg')
            self.assertNotIn('_imagenes', json.dumps(funcion['response']))
            self.assertNotIn('base64', json.dumps(r.data))
