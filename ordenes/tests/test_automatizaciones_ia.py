"""Regresiones de tareas personales: sin red externa ni datos operativos."""
from datetime import datetime, time, timedelta, timezone as utc
from unittest import mock

from django.test import override_settings
from django.utils import timezone

from ordenes.asistente import automatizaciones as tareas, gemini
from ordenes.asistente.programacion import BOGOTA, siguiente
from ordenes.models import (AutomatizacionAsistente, ConversacionAsistente, EjecucionAutomatizacionIA,
                           MensajeAsistente, PerfilAsistente)
from ordenes.tests.utils import LottusTestCase


@override_settings(GEMINI_API_KEY='clave-ficticia', GEMINI_MODELOS=['modelo-a'], ASISTENTE_EN_SEGUNDO_PLANO=False)
class AutomatizacionesIATests(LottusTestCase):
    def setUp(self):
        self.user = self.crear_usuario('responsable_tareas', 'administrador')
        self.otro = self.crear_usuario('otro_responsable', 'administrador')
        self.lector = self.crear_usuario('lector_ia')
        self.permisos('vendedor', ['USAR_ASISTENTE_IA'])
        self.admin = self.api(self.user)
        self.ajeno = self.api(self.otro)
        self.perfil = PerfilAsistente.objects.create(nombre='Analista aislado', rol='Ventas',
            instrucciones='Analiza los datos permitidos con precisión y presenta resultados verificables.', areas=['ventas'])
        self.datos = {'nombre':'Reporte diario', 'instrucciones':'Resume las ventas del período y las tres acciones más útiles.',
            'perfil':self.perfil.pk, 'frecuencia':'semanal', 'hora':'09:00', 'dias_semana':[0,1,2,3,4]}

    def crear(self, **extra):
        r = self.admin.post('/api/asistente/automatizaciones/', {**self.datos, **extra}, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        return AutomatizacionAsistente.objects.get(pk=r.data['id'])

    def manual(self, a, clave='intento-manual-01', api=None):
        return (api or self.admin).post(f'/api/asistente/automatizaciones/{a.pk}/ejecutar/', {}, format='json', HTTP_IDEMPOTENCY_KEY=clave)

    def responder(self, texto='Resultado verificable de prueba'):
        return mock.patch.object(gemini, 'responder', return_value={'texto':texto,'herramientas':[], 'modelo':'modelo-a', 'tokens':20})

    def test_permisos_y_propiedad_en_todas_las_rutas(self):
        a = self.crear()
        lector = self.api(self.lector)
        self.assertEqual(lector.post('/api/asistente/automatizaciones/', self.datos, format='json').status_code, 403)
        self.assertEqual(lector.patch(f'/api/asistente/automatizaciones/{a.pk}/', {'activa':False}, format='json').status_code,403)
        self.assertEqual(self.manual(a,api=lector).status_code,403)
        e = self.manual(a).data['id']
        for ruta in [f'/api/asistente/automatizaciones/{a.pk}/', f'/api/asistente/automatizaciones/{a.pk}/ejecuciones/', f'/api/asistente/ejecuciones/{e}/']:
            self.assertEqual(self.ajeno.get(ruta).status_code,404)
        self.assertEqual(self.manual(a,api=self.ajeno).status_code,404)
        self.assertEqual(self.ajeno.patch(f'/api/asistente/ejecuciones/{e}/', {'leida':True}, format='json').status_code,404)
        self.assertEqual(self.ajeno.get('/api/asistente/oficina-actividad/').data['automatizaciones'],[])
        self.assertEqual(lector.get('/api/asistente/automatizaciones/').data['automatizaciones'],[])

    def test_creacion_idempotente_sin_duplicados_ni_cambio_de_contenido(self):
        def post(datos):
            return self.admin.post('/api/asistente/automatizaciones/', datos, format='json', HTTP_IDEMPOTENCY_KEY='alta-unica-01')
        primero = post(self.datos)
        segundo = post(self.datos)
        self.assertEqual((primero.status_code,segundo.status_code),(201,201))
        self.assertEqual(primero.data['id'],segundo.data['id'])
        self.assertEqual(post({**self.datos,'nombre':'Otro contenido'}).status_code,409)
        self.assertEqual(AutomatizacionAsistente.objects.count(),1)

    def test_rechaza_calendario_modelo_perfil_y_textos_invalidos(self):
        for cambios in [{'dias_semana':[]},{'dias_semana':[True]},{'dias_semana':[7]}, {'modelo':'ajeno'},
                        {'perfil':999999}, {'nombre':' '}, {'instrucciones':'Muy corto'}, {'frecuencia':'cada_minuto'},
                        {'hora':'29:00'}, {'dia_mes':0}, {'dia_mes':32}, {'frecuencia':'una_vez'},
                        {'frecuencia':'una_vez','fecha_unica':(timezone.now()-timedelta(hours=1)).isoformat()},
                        {'fecha_fin':'2020-01-01'}]:
            r=self.admin.post('/api/asistente/automatizaciones/',{**self.datos,**cambios},format='json')
            self.assertEqual(r.status_code,400,(cambios,r.data))
        self.assertFalse(AutomatizacionAsistente.objects.exists())

    def test_calendario_bogota_semanal_mensual_y_fecha_limite(self):
        a=self.crear()
        despues=datetime(2026,10,9,14,1,tzinfo=utc.utc)  # viernes, 09:01 Bogotá
        self.assertEqual(siguiente(a,despues),datetime(2026,10,12,9,tzinfo=BOGOTA))
        a.frecuencia='diaria'
        self.assertEqual(siguiente(a,despues),datetime(2026,10,10,9,tzinfo=BOGOTA))
        a.frecuencia='mensual'; a.dia_mes=31
        self.assertEqual(siguiente(a,datetime(2027,1,31,10,tzinfo=BOGOTA)),datetime(2027,2,28,9,tzinfo=BOGOTA))
        self.assertEqual(siguiente(a,datetime(2028,1,31,10,tzinfo=BOGOTA)),datetime(2028,2,29,9,tzinfo=BOGOTA))
        a.fecha_fin=datetime(2027,2,20).date()
        self.assertIsNone(siguiente(a,datetime(2027,1,31,10,tzinfo=BOGOTA)))
        a.activa=False
        self.assertIsNone(siguiente(a,timezone.now()))

    def test_calendario_una_vez_y_limite_de_fin_incompatible(self):
        futuro=timezone.now()+timedelta(days=2)
        a=self.crear(frecuencia='una_vez',fecha_unica=futuro.isoformat())
        self.assertEqual(a.proxima_ejecucion,futuro)
        self.assertIsNone(siguiente(a,futuro))
        r=self.admin.post('/api/asistente/automatizaciones/',{**self.datos,'frecuencia':'una_vez','fecha_unica':futuro.isoformat(),
            'fecha_fin':timezone.localdate().isoformat()},format='json')
        self.assertEqual(r.status_code,400)

    def test_no_activa_un_calendario_sin_horarios_futuros(self):
        ahora=datetime(2026,10,9,18,tzinfo=BOGOTA)
        with mock.patch('ordenes.asistente.automatizaciones_views.timezone.now',return_value=ahora):
            r=self.admin.post('/api/asistente/automatizaciones/',{**self.datos,'frecuencia':'diaria',
                'hora':'09:00','fecha_fin':'2026-10-09'},format='json')
        self.assertEqual(r.status_code,400,r.data)
        self.assertFalse(AutomatizacionAsistente.objects.exists())

    def test_restaurar_una_tarea_pasada_siempre_la_deja_pausada(self):
        a=self.crear(frecuencia='una_vez',fecha_unica=(timezone.now()+timedelta(hours=1)).isoformat())
        AutomatizacionAsistente.objects.filter(pk=a.pk).update(archivada=True,activa=False,fecha_unica=timezone.now()-timedelta(days=1))
        r=self.admin.patch(f'/api/asistente/automatizaciones/{a.pk}/',{'archivada':False,'activa':True},format='json')
        self.assertEqual(r.status_code,200,r.data)
        a.refresh_from_db();self.assertFalse(a.activa);self.assertFalse(a.archivada);self.assertIsNone(a.proxima_ejecucion)

    def test_reserva_manual_idempotente_no_solapa_y_no_mueve_horario(self):
        a=self.crear(); horario=a.proxima_ejecucion
        r=self.manual(a); self.assertEqual(r.status_code,202,r.data)
        self.assertEqual(self.manual(a).data['id'],r.data['id'])
        self.assertEqual(self.manual(a,clave='intento-manual-02').status_code,409)
        self.assertEqual(EjecucionAutomatizacionIA.objects.count(),1)
        a.refresh_from_db(); self.assertEqual(a.proxima_ejecucion,horario)
        self.assertEqual(self.admin.post(f'/api/asistente/automatizaciones/{a.pk}/ejecutar/',{},format='json').status_code,400)

    def test_programacion_recupera_una_fraccion_del_atraso_sin_rafaga(self):
        a=self.crear(frecuencia='diaria'); vieja=timezone.now()-timedelta(days=10)
        AutomatizacionAsistente.objects.filter(pk=a.pk).update(proxima_ejecucion=vieja)
        ids=tareas.encolar_vencidas(); self.assertEqual(len(ids),1)
        self.assertEqual(tareas.encolar_vencidas(),[])
        a.refresh_from_db(); self.assertGreater(a.proxima_ejecucion,timezone.now())
        self.assertEqual(a.ejecuciones.get().programada_para,vieja)

    def test_programacion_unica_se_desactiva_y_no_se_repite(self):
        a=self.crear(frecuencia='una_vez',fecha_unica=(timezone.now()+timedelta(hours=1)).isoformat())
        AutomatizacionAsistente.objects.filter(pk=a.pk).update(proxima_ejecucion=timezone.now()-timedelta(minutes=1))
        self.assertEqual(len(tareas.encolar_vencidas()),1)
        a.refresh_from_db(); self.assertFalse(a.activa); self.assertIsNone(a.proxima_ejecucion)
        self.assertEqual(tareas.encolar_vencidas(),[])

    def test_worker_guarda_respuesta_chat_privado_y_no_ejecuta_dos_veces(self):
        a=self.crear(); e=self.manual(a).data['id']
        with self.responder() as proveedor:
            self.assertTrue(tareas.ejecutar(e))
            self.assertFalse(tareas.ejecutar(e))
            self.assertEqual(proveedor.call_count,1)
            self.assertEqual(proveedor.call_args.kwargs['perfil'].pk,self.perfil.pk)
        e=EjecucionAutomatizacionIA.objects.get(pk=e)
        self.assertEqual((e.estado,e.modelo_usado),('listo','modelo-a'))
        self.assertEqual(e.conversacion.usuario_id,self.user.pk)
        self.assertEqual(e.conversacion.perfil_id,self.perfil.pk)
        self.assertEqual(e.respuesta.texto,e.resultado)
        self.assertEqual(self.manual(a).data['id'],e.pk)
        pendientes=self.admin.get('/api/asistente/oficina-actividad/').data['pendientes']
        self.assertEqual([p['id'] for p in pendientes],[e.pk])
        self.assertEqual(self.admin.patch(f'/api/asistente/ejecuciones/{e.pk}/',{'leida':True},format='json').status_code,200)
        self.assertEqual(self.admin.get('/api/asistente/oficina-actividad/').data['pendientes'],[])

    def test_snapshot_instrucciones_no_cambia_una_ejecucion_encolada(self):
        a=self.crear(); e=self.manual(a).data['id']
        self.admin.patch(f'/api/asistente/automatizaciones/{a.pk}/',{'instrucciones':'Instrucciones nuevas para las próximas ejecuciones.'},format='json')
        with self.responder() as proveedor:
            tareas.ejecutar(e)
        self.assertEqual(proveedor.call_args.args[0][0]['texto'],self.datos['instrucciones'])

    def test_agente_pausado_o_eliminado_no_se_sustituye_por_general(self):
        for eliminar in [False,True]:
            a=self.crear(); e=self.manual(a,clave=f'agente-ausente-{eliminar}').data['id']
            if eliminar:
                self.perfil.delete()
            else:
                self.perfil.activo=False; self.perfil.save(update_fields=['activo'])
            with self.responder() as proveedor:
                tareas.ejecutar(e); proveedor.assert_not_called()
            self.assertEqual(EjecucionAutomatizacionIA.objects.get(pk=e).estado,'error')
            if not eliminar:
                self.perfil.activo=True; self.perfil.save(update_fields=['activo'])
        a.refresh_from_db(); self.assertFalse(a.es_general)
        self.assertEqual(self.admin.patch(f'/api/asistente/automatizaciones/{a.pk}/',{'activa':True},format='json').status_code,400)

    def test_worker_revisa_responsable_activo_y_permiso_actual(self):
        a=self.crear(); e=self.manual(a).data['id']
        self.user.role='vendedor'; self.user.save(update_fields=['role'])
        with self.responder() as proveedor:
            tareas.ejecutar(e); proveedor.assert_not_called()
        self.assertIn('permisos',EjecucionAutomatizacionIA.objects.get(pk=e).error)
        self.user.role='administrador'; self.user.save(update_fields=['role'])
        e=self.manual(a,clave='responsable-inactivo-02').data['id']
        self.user.is_active=False; self.user.save(update_fields=['is_active'])
        with self.responder() as proveedor:
            tareas.ejecutar(e); proveedor.assert_not_called()

    def test_perfil_eliminado_al_iniciar_respuesta_no_se_convierte_en_general(self):
        from ordenes.asistente import views
        original=views._procesar
        a=self.crear();e=self.manual(a).data['id']
        def desaparecer(*args,**kwargs):
            self.perfil.delete()
            return original(*args,**kwargs)
        with mock.patch.object(views,'_procesar',side_effect=desaparecer), self.responder() as proveedor:
            tareas.ejecutar(e);proveedor.assert_not_called()
        self.assertEqual(EjecucionAutomatizacionIA.objects.get(pk=e).estado,'error')

    def test_limite_de_preguntas_compartido_con_el_chat(self):
        a=self.crear(); e=self.manual(a).data['id']
        c=ConversacionAsistente.objects.create(usuario=self.user)
        MensajeAsistente.objects.bulk_create([MensajeAsistente(conversacion=c,rol='usuario',texto='Pregunta de prueba') for _ in range(40)])
        with self.responder() as proveedor:
            tareas.ejecutar(e); proveedor.assert_not_called()
        self.assertIn('40 preguntas',EjecucionAutomatizacionIA.objects.get(pk=e).error)
        self.assertEqual(MensajeAsistente.objects.filter(rol='usuario').count(),40)

    def test_error_del_proveedor_se_conserva_sin_reintento_automatico(self):
        a=self.crear(); e=self.manual(a).data['id']
        with mock.patch.object(gemini,'responder',side_effect=gemini.ErrorAsistente('Modelo saturado')) as proveedor:
            tareas.ejecutar(e); tareas.ejecutar(e); self.assertEqual(proveedor.call_count,1)
        e=EjecucionAutomatizacionIA.objects.get(pk=e)
        self.assertEqual((e.estado,e.error),('error','Modelo saturado'))
        self.assertEqual(e.respuesta.estado,'error')

    def test_interrupcion_y_cola_abandonada_son_visibles_y_no_reintentan(self):
        a=self.crear(); e=self.manual(a).data['id']
        EjecucionAutomatizacionIA.objects.filter(pk=e).update(estado='ejecutando',iniciada=timezone.now()-timedelta(minutes=6))
        tareas.recuperar_interrumpidas()
        with self.responder() as proveedor:
            self.assertFalse(tareas.ejecutar(e)); proveedor.assert_not_called()
        self.assertIn('interrumpió',EjecucionAutomatizacionIA.objects.get(pk=e).error)
        e2=self.manual(a,clave='cola-abandonada-02').data['id']
        EjecucionAutomatizacionIA.objects.filter(pk=e2).update(creada=timezone.now()-timedelta(minutes=31))
        tareas.recuperar_interrumpidas()
        self.assertEqual(EjecucionAutomatizacionIA.objects.get(pk=e2).estado,'error')

    def test_archivar_conserva_historial_y_restaurar_deja_pausada(self):
        a=self.crear(); e=self.manual(a).data['id']
        with self.responder(): tareas.ejecutar(e)
        r=self.admin.patch(f'/api/asistente/automatizaciones/{a.pk}/',{'archivada':True},format='json')
        self.assertEqual(r.status_code,200,r.data)
        self.assertFalse(r.data['activa']); self.assertIsNone(r.data['proxima_ejecucion'])
        self.assertEqual(self.manual(a,clave='archivada-intento-02').status_code,409)
        self.assertEqual(self.admin.get('/api/asistente/automatizaciones/').data['automatizaciones'],[])
        self.assertEqual(len(self.admin.get('/api/asistente/automatizaciones/',{'archivadas':1}).data['automatizaciones']),1)
        r=self.admin.patch(f'/api/asistente/automatizaciones/{a.pk}/',{'archivada':False,'activa':True},format='json')
        self.assertEqual(r.status_code,200,r.data); self.assertFalse(r.data['activa'])
        self.assertTrue(EjecucionAutomatizacionIA.objects.filter(pk=e).exists())

    def test_limites_de_automatizaciones_y_motor_sin_presencia_ficticia(self):
        self.assertFalse(self.admin.get('/api/asistente/oficina-actividad/').data['motor']['activo'])
        tareas.latido()
        self.assertTrue(self.admin.get('/api/asistente/oficina-actividad/').data['motor']['activo'])
        AutomatizacionAsistente.objects.bulk_create([AutomatizacionAsistente(usuario=self.user,es_general=True,
            nombre=f'Tarea {i}',instrucciones=self.datos['instrucciones'],frecuencia='diaria',hora=time(9)) for i in range(20)])
        self.assertEqual(self.admin.post('/api/asistente/automatizaciones/',self.datos,format='json').status_code,400)
        a=self.crear(activa=False)
        self.assertEqual(self.admin.patch(f'/api/asistente/automatizaciones/{a.pk}/',{'activa':True},format='json').status_code,400)
