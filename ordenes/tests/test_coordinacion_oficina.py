from datetime import datetime, time, timedelta
from unittest.mock import patch
from uuid import uuid4
from zoneinfo import ZoneInfo

from django.test import override_settings
from django.utils import timezone
from ordenes import coordinacion
from ordenes.models import (CoordinacionOficina, ConfiguracionOficina, MiembroOficina, PerfilAsistente,
    ZonaOficinaIA, InformeAreas, InteraccionOficina, TrabajoOficina, MensajeAsistente, OrdenPedido)
from ordenes.tests.utils import LottusTestCase


class CoordinacionTests(LottusTestCase):
    def setUp(self):
        self.stiven=self.crear_usuario('stiven_coordinacion','administrador')
        self.oscar=self.crear_usuario('oscar_coordinacion','administrador')
        self.ana=self.crear_usuario('ana_coordinacion')
        self.ajeno=self.crear_usuario('ajeno_coordinacion','administrador')
        ConfiguracionOficina.objects.create(responsable=self.stiven)
        for u in [self.stiven,self.oscar,self.ana]:MiembroOficina.objects.create(usuario=u)
        self.entrenamiento=ZonaOficinaIA.objects.filter(ambiente='entrenamiento').first()
        self.comercial=ZonaOficinaIA.objects.filter(ambiente='showroom').first()
        self.coach=PerfilAsistente.objects.create(nombre='Coach de prueba aislada',rol='Entrenar',instrucciones='Usa hechos',zona=self.entrenamiento)
        self.analista=PerfilAsistente.objects.create(nombre='Analista de prueba aislada',rol='Ventas',instrucciones='Usa hechos',zona=self.comercial)
        self.config=CoordinacionOficina.objects.create(lideres={str(self.entrenamiento.pk):self.coach.pk,str(self.comercial.pk):self.analista.pk},hora_inicio=time(9,50),hora_fin=time(18,50),dias=list(range(7)),activa=True,modelo='automatico')
        self.config.destinatarios.set([self.stiven,self.oscar])
        self.api_stiven=self.api(self.stiven)

    def test_horario_bogota_slots_y_siguiente_dia(self):
        zona=ZoneInfo('America/Bogota')
        self.assertEqual(coordinacion.siguiente(self.config,datetime(2026,10,9,9,49,tzinfo=zona)),datetime(2026,10,9,9,50,tzinfo=zona))
        self.assertEqual(coordinacion.siguiente(self.config,datetime(2026,10,9,9,50,tzinfo=zona)),datetime(2026,10,9,10,50,tzinfo=zona))
        self.assertEqual(coordinacion.siguiente(self.config,datetime(2026,10,9,18,51,tzinfo=zona)),datetime(2026,10,10,9,50,tzinfo=zona))
        self.config.dias=[0,1,2,3,4]
        self.assertEqual(coordinacion.siguiente(self.config,datetime(2026,10,9,18,51,tzinfo=zona)),datetime(2026,10,12,9,50,tzinfo=zona))

    def test_solo_destinatarios_invitados_pueden_pedir_y_ver(self):
        for u in [self.ana,self.ajeno]:
            self.assertEqual(self.api(u).post('/api/oficina/informes/',{'clave':str(uuid4())},format='json').status_code,403)
        i=coordinacion.reservar(self.stiven,'manual:unica')
        self.assertEqual(self.api(self.oscar).get(f'/api/oficina/informes/{i.pk}/').status_code,200)
        self.assertEqual(self.api(self.ana).get(f'/api/oficina/informes/{i.pk}/').status_code,403)
        MiembroOficina.objects.filter(usuario=self.oscar).update(habilitado=False)
        self.assertEqual(self.api(self.oscar).get(f'/api/oficina/informes/{i.pk}/').status_code,403)

    def test_idempotencia_un_recorrido_y_errores_de_proveedor_conservan_evidencia(self):
        i=coordinacion.reservar(self.stiven,'manual:unica')
        self.assertEqual(coordinacion.reservar(self.stiven,'manual:unica').pk,i.pk)
        with self.assertRaises(Exception):coordinacion.reservar(self.oscar,'manual:otra')
        v=self.venta(self.ana)
        v.vendedores_compartidos.add(self.oscar)
        with patch('ordenes.coordinacion.consultar_lider',side_effect=coordinacion.gemini.ErrorAsistente('Proveedor saturado')) as consulta:
            coordinacion.ejecutar(i.pk);coordinacion.ejecutar(i.pk)
        self.assertEqual(consulta.call_count,2)
        i.refresh_from_db();self.assertEqual(i.estado,'parcial')
        self.assertEqual(i.datos['ventas']['total_pendientes'],1)
        self.assertEqual(len(i.datos['ventas']['vendedores']),2)
        self.assertEqual(len(i.datos['coach']),3)
        self.assertFalse(i.datos['coach'][0]['formacion']['disponible'])
        self.assertEqual(i.interacciones.filter(tipo='informe').count(),2)
        self.assertEqual(i.interacciones.first().destino,f'ia-{self.coach.pk}')

    def test_modo_erp_no_llama_proveedor_y_conserva_informe_util(self):
        self.config.modelo='';self.config.save()
        i=coordinacion.reservar(self.stiven,'manual:solo-erp')
        with patch('ordenes.coordinacion.consultar_lider') as consulta:coordinacion.ejecutar(i.pk)
        consulta.assert_not_called()
        i.refresh_from_db();self.assertEqual(i.estado,'listo')
        self.assertFalse(i.datos['analisis_ia_habilitado'])
        self.assertIn('No se enviaron estos datos',i.resumen)
        self.assertEqual(coordinacion.memoria(self.stiven),'')

    def test_activar_gemini_requiere_autorizacion_explicita(self):
        self.config.modelo='';self.config.save()
        d={'revision':1,'activa':True,'hora_inicio':'09:50','hora_fin':'18:50','dias':[0],
           'modelo':'automatico','lideres':self.config.lideres}
        self.assertEqual(self.api_stiven.put('/api/oficina/coordinacion/',d,format='json').status_code,400)
        self.config.refresh_from_db();self.assertEqual(self.config.modelo,'')
        d['autorizar_envio']=True
        self.assertEqual(self.api_stiven.put('/api/oficina/coordinacion/',d,format='json').status_code,200)

    def test_analista_incluye_pedidos_finalizados_aun_no_recibidos_y_no_saldos_vencidos(self):
        v=self.venta(self.ana,fecha=timezone.localdate()-timedelta(days=10))
        pedido=OrdenPedido.objects.create(proveedor=self.proveedor(),usuario=self.ana,venta=v,estado='finalizado',fecha_esperada=timezone.localdate()-timedelta(days=2))
        datos=coordinacion.evidencia(self.stiven)
        self.assertEqual(datos['ventas']['gestion_atrasada'],1)
        self.assertEqual(datos['ventas']['plan_analista'][0]['pedidos'],[pedido.pk])
        self.assertNotIn('saldo_vencido',datos['ventas'])

    def test_solicitud_a_oscar_y_entrega_emiten_solo_eventos_genericos_una_vez(self):
        api=self.api(self.ana)
        r=api.post('/api/oficina/trabajos/',{'tipo':'solicitud','titulo':'Información privada de mi trabajo','responsable':self.oscar.pk},format='json')
        self.assertEqual(r.status_code,201,r.data);pk=r.data['id']
        evento=InteraccionOficina.objects.get(trabajo_id=pk)
        self.assertEqual(evento.actor,f'persona-{self.ana.pk}');self.assertEqual(evento.destino,f'persona-{self.oscar.pk}')
        api_oscar=self.api(self.oscar)
        r=api_oscar.patch(f'/api/oficina/trabajos/{pk}/',{'revision':1,'estado':'hecha'},format='json')
        self.assertEqual(r.status_code,200,r.data)
        r=api_oscar.patch(f'/api/oficina/trabajos/{pk}/',{'revision':2,'estado':'hecha'},format='json')
        self.assertEqual(r.status_code,200,r.data)
        self.assertEqual(InteraccionOficina.objects.filter(trabajo_id=pk,tipo='entrega').count(),1)
        texto=str(self.api_stiven.get('/api/oficina/interacciones/').data)
        self.assertNotIn('Información privada',texto)
        self.assertIsNotNone(TrabajoOficina.objects.get(pk=pk).entregado_en)

    def test_rechazar_no_gerente_y_rollback_sin_eventos(self):
        r=self.api(self.ana).post('/api/oficina/trabajos/',{'tipo':'solicitud','titulo':'Mi tarea','responsable':self.ana.pk},format='json')
        self.assertEqual(r.status_code,404)
        self.assertFalse(InteraccionOficina.objects.exists())

    def test_entrega_visita_quien_realmente_marco_el_trabajo(self):
        t=TrabajoOficina.objects.create(creador=self.ana,responsable=self.oscar,tipo='solicitud',titulo='Solicitud aislada')
        r=self.api_stiven.patch(f'/api/oficina/trabajos/{t.pk}/',{'revision':1,'estado':'hecha'},format='json')
        self.assertEqual(r.status_code,200)
        self.assertEqual(t.interacciones.get(tipo='entrega').actor,f'persona-{self.stiven.pk}')

    def test_latido_de_presencia_no_se_confunde_con_avance(self):
        antes=coordinacion._huella(coordinacion.evidencia(self.stiven))
        MiembroOficina.objects.filter(usuario=self.ana).update(ultima_presencia=timezone.now())
        despues=coordinacion._huella(coordinacion.evidencia(self.stiven))
        self.assertEqual(antes,despues)

    def test_chat_general_activa_informe_sin_depender_de_gemini(self):
        with patch('ordenes.coordinacion.consultar_lider',return_value={'texto':'Resultado basado en evidencia','modelo':'prueba-aislada'}):
            r=self.api_stiven.post('/api/asistente/preguntar/',{'texto':'Dame un informe de las áreas'},format='json')
        self.assertEqual(r.status_code,202,r.data)
        self.assertEqual(r.data['respuesta']['estado'],'listo')
        i=InformeAreas.objects.get(pk=r.data['respuesta']['informe_areas']['id'])
        self.assertEqual(i.destinatarios.count(),2)
        self.assertTrue(coordinacion.memoria(self.oscar))
        self.assertEqual(coordinacion.memoria(self.ana),'')

    @override_settings(GEMINI_API_KEY='prueba-aislada')
    def test_frase_en_otro_agente_no_activa_coordinador(self):
        with patch('ordenes.asistente.views._procesar') as procesar:
            r=self.api_stiven.post('/api/asistente/preguntar/',{'texto':'dame un informe de las areas','perfil':self.coach.pk},format='json')
        self.assertEqual(r.status_code,202);self.assertTrue(procesar.called)
        self.assertFalse(InformeAreas.objects.exists())

    def test_recuperar_informe_sin_repetir_ni_entregar_error(self):
        i=coordinacion.reservar(self.stiven,'manual:unica')
        InformeAreas.objects.filter(pk=i.pk).update(estado='ejecutando',iniciado=timezone.now()-timedelta(minutes=6))
        coordinacion.recuperar_interrumpidos()
        i.refresh_from_db();self.assertEqual(i.estado,'error')
        self.assertFalse(i.interacciones.filter(tipo='informe').exists())

    def test_programa_revierte_horario_invalido_y_solo_dueno_edita(self):
        d={'revision':1,'activa':True,'hora_inicio':'09:50','hora_fin':'18:00','dias':[0],'modelo':'','lideres':self.config.lideres}
        self.assertEqual(self.api_stiven.put('/api/oficina/coordinacion/',d,format='json').status_code,400)
        d['hora_fin']='18:50'
        self.assertEqual(self.api(self.oscar).put('/api/oficina/coordinacion/',d,format='json').status_code,403)
        self.assertEqual(self.api_stiven.put('/api/oficina/coordinacion/',d,format='json').status_code,200)
        self.assertEqual(self.api_stiven.put('/api/oficina/coordinacion/',d,format='json').status_code,409)

    def test_entregadas_hoy_no_cambian_por_comentarios_posteriores(self):
        t=TrabajoOficina.objects.create(creador=self.ana,responsable=self.ana,tipo='tarea',titulo='Trabajo antiguo',estado='hecha',entregado_en=timezone.now()-timedelta(days=2))
        self.api(self.ana).post(f'/api/oficina/trabajos/{t.pk}/comentarios/',{'texto':'Comentario de hoy'},format='json')
        p=next(p for p in coordinacion.evidencia(self.stiven)['coach'] if p['usuario']['id']==self.ana.pk)
        self.assertEqual(p['entregadas_hoy'],0)
