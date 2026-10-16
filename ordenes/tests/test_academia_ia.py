import tempfile
import uuid
from datetime import timedelta
from pathlib import Path
from unittest import mock

from django.test import override_settings
from django.core.cache import cache
from django.utils import timezone
from ordenes.asistente import academia, gemini
from ordenes.models import ConexionAcademia, CursoAcademia, PerfilAsistente
from ordenes.tests.test_asistente import respuesta_llamada, respuesta_texto
from ordenes.tests.utils import LottusTestCase


@override_settings(GEMINI_API_KEY='prueba', GEMINI_MODELOS=['modelo-a'], ASISTENTE_EN_SEGUNDO_PLANO=False)
class AcademiaTests(LottusTestCase):
    def setUp(self):
        self.dir=tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.config=override_settings(ACADEMIA_ROOT=self.dir.name, ACADEMIA_CHROME_USUARIO_ID=0)
        self.config.enable();self.addCleanup(self.config.disable)
        self.u=self.crear_usuario('admin','administrador')
        self.otro=self.crear_usuario('otro','administrador')
        self.p=PerfilAsistente.objects.create(nombre='Coach',rol='Formación',instrucciones='Enseña',areas=['ventas','formacion'])
        self.api_u=self.api(self.u)
        for usuario in (self.u, self.otro):
            for scope in ('academia_lectura', 'academia_acciones'):
                cache.delete('throttle_%s_%s' % (scope, usuario.pk))

    def test_consultas_de_progreso_tienen_limite_independiente_de_la_oficina(self):
        contador = cache.get('throttle_user_%s' % self.u.pk)
        for _ in range(60):
            self.assertEqual(self.api_u.get('/api/asistente/academia/cursos/').status_code, 200)
        self.assertEqual(self.api_u.get('/api/asistente/academia/cursos/').status_code, 429)
        self.assertEqual(cache.get('throttle_user_%s' % self.u.pk), contador)
        # Las acciones tienen su propio límite y la lectura no las agota.
        for _ in range(10):
            self.assertEqual(self.api_u.post('/api/asistente/academia/conexion/', {'accion':'verificar'}, format='json').status_code, 400)
        self.assertEqual(self.api_u.post('/api/asistente/academia/conexion/', {'accion':'verificar'}, format='json').status_code, 429)

    def crear(self,**extra):
        return self.api_u.post('/api/asistente/academia/cursos/',{
            'perfil':self.p.pk,'clave':str(uuid.uuid4()),'solicitud':'Enséñame a atender al cliente con casos prácticos.',
            'numero_modulos':2,'con_videos':True,**extra},format='json')

    def conectado(self):
        p=academia.storage(self.u.pk);p.parent.mkdir(parents=True);p.write_text('{}')
        ConexionAcademia.objects.create(usuario=self.u,estado='conectada')

    def procesar(self):
        CursoAcademia.objects.update(proxima_revision=timezone.now()-timedelta(seconds=1))
        return academia.ejecutar_un_paso()

    def test_sin_conexion_guarda_y_no_finge_material(self):
        r=self.crear()
        self.assertEqual(r.status_code,202,r.data)
        self.assertEqual(r.data['estado'],'conexion')
        self.assertIsNone(r.data['notebook_url'])
        self.assertEqual(r.data['modulos'],[])
        with mock.patch.object(academia,'operacion') as op:
            self.assertFalse(self.procesar());op.assert_not_called()

    def test_privacidad_curso_video_y_conexion(self):
        r=self.crear();pk=r.data['id']
        api_otro=self.api(self.otro)
        self.assertEqual(api_otro.get('/api/asistente/academia/cursos/').data['cursos'],[])
        self.assertEqual(api_otro.get('/api/asistente/academia/cursos/%s/'%pk).status_code,404)
        self.assertEqual(api_otro.get('/api/asistente/academia/cursos/%s/videos/0/'%pk).status_code,404)
        self.assertEqual(self.api_u.post('/api/asistente/academia/conexion/',{'accion':'chrome','consentimiento':True},format='json').status_code,403)
        self.assertEqual(self.api_u.post('/api/asistente/academia/conexion/',{'accion':'verificar'},format='json').status_code,400)
        v=self.crear_usuario('vendedor')
        self.assertEqual(self.api(v).get('/api/asistente/academia/cursos/').status_code,403)

    def test_limites_fuentes_y_agente(self):
        for urls in [['http://example.com'],['https://127.0.0.1/'],['https://localhost/'],['https://user:secret@example.com/']]:
            self.assertEqual(self.crear(urls=urls).status_code,400)
        self.assertEqual(self.crear(numero_modulos=20).status_code,400)
        self.assertEqual(self.crear(investigar=False,urls=[]).status_code,400)
        self.p.areas=['ventas'];self.p.save()
        self.assertEqual(self.crear().status_code,403)

    def test_solicitud_idempotente_no_consume_otro_curso(self):
        clave=str(uuid.uuid4())
        a,b=self.crear(clave=clave),self.crear(clave=clave)
        self.assertEqual(a.data['id'],b.data['id'])
        self.assertEqual(CursoAcademia.objects.count(),1)
        self.assertEqual(self.api(self.otro).post('/api/asistente/academia/cursos/',{'perfil':self.p.pk,'clave':clave,'solicitud':'Otro curso diferente'},format='json').status_code,403)
        self.crear();self.crear()
        self.assertEqual(self.crear().status_code,400)

    def test_chat_y_fallback_crean_una_sola_tarea_y_usan_solo_solicitud(self):
        respuestas=[respuesta_llamada('crear_curso',{'modulos':2}),respuesta_texto('Guardé tu curso.')]
        with mock.patch.object(gemini,'_llamar',side_effect=respuestas):
            r=self.api_u.post('/api/asistente/preguntar/',{'perfil':self.p.pk,'texto':'Hazme un curso de atención al cliente en dos módulos.'},format='json')
        self.assertEqual(r.status_code,202,r.data)
        curso=CursoAcademia.objects.get()
        self.assertEqual(r.data['respuesta']['curso_academia']['id'],curso.pk)
        self.assertEqual(curso.solicitud,'Hazme un curso de atención al cliente en dos módulos.')
        segundo=academia.crear_desde_chat(self.u,self.p,curso.mensaje_id,{'modulos':4})
        self.assertEqual(segundo['curso_id'],curso.pk)
        self.assertEqual(CursoAcademia.objects.count(),1)

    def test_crea_material_por_pasos_y_descarga_video_autenticado(self):
        self.conectado();r=self.crear(investigar=False,urls=['https://example.com/guia']);pk=r.data['id']
        llamadas=[]
        def fake(uid,op,**kw):
            llamadas.append(op)
            if op=='cuaderno':return {'notebook':'nb-real'}
            if op=='fuente':return {'fuentes':[{'id':'s1','titulo':'Guía','url':'https://example.com/guia'}]}
            if op=='plan':return {'plan':{'titulo':'Atención excelente','resumen':'Curso con fuentes','modulos':[{'titulo':'Escuchar','objetivo':'Comprender','minutos':10},{'titulo':'Resolver','objetivo':'Ayudar','minutos':15}]}}
            if op=='leccion':return {'contenido':'# Lección\nEjercicio con una fuente [1].'}
            if op=='evaluacion':return {'preguntas':[{'pregunta':'¿Escuchar?','opciones':['Sí','No'],'correcta':0,'explicacion':'Comprender primero'}]}
            if op=='video':return {'video':str(uuid.uuid4())}
            if op=='video_estado':return {'estado':'completed'}
            if op=='descargar':
                p=Path(kw['archivo']);p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b'video-ficticio');return {'descargado':True}
            raise AssertionError(op)
        with mock.patch.object(academia,'operacion',side_effect=fake):
            avances=[]
            for _ in range(14):
                self.procesar();avances.append(CursoAcademia.objects.get(pk=pk).avance)
        self.assertEqual(avances,sorted(avances))
        c=CursoAcademia.objects.get(pk=pk)
        self.assertEqual((c.estado,c.avance),('listo',100))
        self.assertEqual(llamadas.count('video'),2)
        self.assertEqual(llamadas.count('cuaderno'),1)
        f=self.api_u.get('/api/asistente/academia/cursos/%s/videos/0/'%pk)
        self.assertEqual(f.status_code,200)
        self.assertEqual(b''.join(f.streaming_content),b'video-ficticio')
        self.assertEqual(f['Cache-Control'],'private, no-store')

    def test_video_ambiguo_no_se_repite_y_puede_terminar_sin_video(self):
        self.conectado();r=self.crear();c=CursoAcademia.objects.get(pk=r.data['id'])
        c.datos={'notebook':'n','investigacion':'i','descubiertas':[]}
        c.fuentes=[{'id':'s','titulo':'Fuente','url':'https://example.com'}]
        c.modulos=[{'titulo':'Módulo','objetivo':'Aprender','contenido':'Texto','contenido_version':2,'preguntas':[{}]}]
        c.save()
        with mock.patch.object(academia,'operacion',side_effect=academia.ErrorAcademia('Sin confirmación','Timeout')) as op:
            self.procesar();op.assert_called_once()
        c.refresh_from_db();self.assertEqual(c.estado,'error');self.assertTrue(c.datos['video_solicitando'])
        with mock.patch.object(academia,'operacion') as op:
            self.assertEqual(self.api_u.post('/api/asistente/academia/cursos/%s/'%c.pk,{'accion':'retomar'},format='json').status_code,400)
            op.assert_not_called()
            self.assertEqual(self.api_u.post('/api/asistente/academia/cursos/%s/'%c.pk,{'accion':'sin_videos'},format='json').status_code,200)
            self.procesar();op.assert_not_called()
        c.refresh_from_db();self.assertEqual(c.estado,'listo')

    def test_pausa_del_coach_detiene_nuevas_operaciones(self):
        self.conectado();self.crear();self.p.activo=False;self.p.save()
        with mock.patch.object(academia,'operacion') as op:
            self.procesar();op.assert_not_called()
        self.assertEqual(CursoAcademia.objects.get().estado,'error')

    def test_cambiar_cuenta_no_envia_material_del_curso_a_otra_cuenta(self):
        self.conectado();r=self.crear();c=CursoAcademia.objects.get(pk=r.data['id'])
        c.datos={'notebook':'existente','google_cuenta':'primera@example.com'};c.save()
        ConexionAcademia.objects.filter(usuario=self.u).update(cuenta='segunda@example.com')
        with mock.patch.object(academia,'operacion') as op:
            self.procesar();op.assert_not_called()
        c.refresh_from_db()
        self.assertEqual(c.estado,'error');self.assertIn('otra cuenta',c.error)

    def test_fuente_de_investigacion_no_disponible_no_bloquea_otros_materiales(self):
        self.conectado();r=self.crear();c=CursoAcademia.objects.get(pk=r.data['id'])
        c.datos={'notebook':'n','investigacion':'i','descubiertas':[{'url':'https://example.com/bloqueada','titulo':'Referencia'}]}
        c.fuentes=[{'id':'s','titulo':'Fuente legible','url':'https://example.com/legible'}];c.save()
        with mock.patch.object(academia,'operacion',return_value={'omitida':True,'fuentes':c.fuentes}) as op:
            self.procesar()
        c.refresh_from_db()
        self.assertEqual(c.estado,'trabajando');self.assertEqual(c.datos['fuente_indice'],1)
        self.assertEqual(c.datos['omitidas'],['https://example.com/bloqueada'])
        self.assertEqual(op.call_args.kwargs['fuente_ids'],['s'])
        self.assertTrue(op.call_args.kwargs['opcional'])

    def test_recupera_escritura_de_checkpoint_sin_repetir_operacion_google(self):
        from django.db import OperationalError
        qs=mock.Mock();qs.update.side_effect=[OperationalError('Conexión interrumpida'),1]
        with mock.patch.object(academia,'connection') as db:
            db.in_atomic_block=False
            self.assertEqual(academia.actualizar(qs,detalle='Guardado'),1)
            db.close.assert_called_once()
        self.assertEqual(qs.update.call_count,2)
