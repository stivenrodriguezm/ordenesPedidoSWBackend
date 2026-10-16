import json
from unittest import mock

from django.core.cache import cache
from django.test import override_settings
from ordenes.models import (ConversacionAsistente, MensajeAsistente, PerfilAsistente,
                            TrabajoAgenteIA, TrabajoOficina, Venta, Cliente)
from ordenes.asistente import agente, gemini, herramientas, operaciones, perfiles
from ordenes.asistente.views import _procesar, _mensaje
from ordenes.tests.test_asistente import respuesta_llamada, respuesta_texto
from ordenes.tests.utils import LottusTestCase


@override_settings(GEMINI_API_KEY='prueba',GEMINI_MODELOS=['modelo-a'],ASISTENTE_EN_SEGUNDO_PLANO=False)
class AgenteEjecutorTests(LottusTestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.u = self.crear_usuario('admin','administrador')
        self.otro = self.crear_usuario('otro','administrador')
        self.vendedor = self.crear_usuario('asesor','vendedor')
        self.p = perfiles.asegurar_agente_ejecutor()
        if not self.p:
            self.p = PerfilAsistente.objects.create(clave_sistema='ejecutor',nombre='Agente',rol='Ejecutor',instrucciones='Ejecuta operaciones reales.',areas=['operaciones','ventas','clientes','pedidos','inventario'])
        self.p.areas=['operaciones','ventas','clientes','pedidos','inventario']
        self.p.save()
        self.c = ConversacionAsistente.objects.create(usuario=self.u,titulo='Registro de prueba')
        MensajeAsistente.objects.create(conversacion=self.c,rol='usuario',texto='Registra estas ventas de prueba con sus productos.')
        self.m = MensajeAsistente.objects.create(conversacion=self.c,rol='asistente',estado='procesando')
        self.cliente = self.cliente()
        self.ref = self.referencia(self.proveedor())

    def lote(self,n=1):
        return [{'cliente_nuevo':False,'cliente':{'id':self.cliente.pk},'venta':{
            'id_vendedor':self.vendedor.pk,'sede':'Lottus 1','fecha_venta':'2026-10-09',
            'fecha_entrega':'2026-10-30','valor_total':'1000'},'productos':[{
                'producto_nombre':f'Mesa de prueba {i+1}','cantidad':1,'referencia':self.ref.pk,
                'precio_lista_override':'1000','motivo_precio':'Precio de prueba solicitado',
                'texto_cliente':'Mesa de prueba','sin_texto_proveedor':True,'tela_modo':'no_aplica'}]} for i in range(n)]

    def activar(self):
        datos=agente.encolar(self.u,self.m.pk)
        t=TrabajoAgenteIA.objects.get(pk=datos['id'])
        t.estado='ejecutando';t.save()
        token=operaciones.trabajo_actual.set(t.pk)
        self.addCleanup(operaciones.trabajo_actual.reset,token)
        return t

    def test_quince_ventas_pasan_por_formulario_y_productos_sin_duplicar(self):
        t=self.activar()
        args={'paso':'lote-octubre','ventas_json':json.dumps(self.lote(15))}
        salida=operaciones.ejecutar('registrar_ventas_con_productos',args)
        self.assertTrue(salida.get('guardado'),salida)
        self.assertEqual(salida['ventas_registradas'],15)
        self.assertEqual(Venta.objects.count(),15)
        for v in Venta.objects.all():
            self.assertTrue(v.productos_confirmados)
            self.assertEqual(v.revision_productos,1)
            self.assertEqual(v.lineas.count(),1)
            self.assertEqual(str(v.valor_lista),'1000.00')
            self.assertEqual(v.cliente_id,self.cliente.pk)
        self.assertEqual(operaciones.ejecutar('registrar_ventas_con_productos',args),salida)
        self.assertEqual(Venta.objects.count(),15)
        t.refresh_from_db();self.assertEqual(len(t.pasos),1)
        self.assertIn('modo=range',salida['ventas'][0]['url'])

    def test_productos_invalidos_revierten_ventas_clientes_y_pasos(self):
        t=self.activar()
        lote=self.lote(2)
        lote[1]['cliente_nuevo']=True
        lote[1]['cliente']={'cedula':'ficticio-nuevo','nombre':'Cliente ficticio nuevo'}
        lote[1]['productos'][0]['tela_modo']='aparte'
        salida=operaciones.ejecutar('registrar_ventas_con_productos',{'paso':'lote','ventas_json':json.dumps(lote)})
        self.assertFalse(salida['guardado'])
        self.assertFalse(Venta.objects.exists())
        self.assertFalse(Cliente.objects.filter(cedula='ficticio-nuevo').exists())
        t.refresh_from_db();self.assertEqual(t.pasos,[])

    def test_no_eleva_permisos_del_usuario_ni_del_agente(self):
        t=self.activar()
        self.u.role='marketing';self.u.save()
        self.permisos('marketing',['USAR_ASISTENTE_IA','VER_VENTAS','VER_PRECIOS_VENTA'])
        salida=operaciones.ejecutar('registrar_ventas_con_productos',{'paso':'lote','ventas_json':json.dumps(self.lote())})
        self.assertFalse(salida['guardado']);self.assertFalse(Venta.objects.exists())
        self.u.role='administrador';self.u.save()
        self.p.areas=['operaciones'];self.p.save()
        self.assertFalse(operaciones.ejecutar('registrar_ventas_con_productos',{'paso':'lote','ventas_json':json.dumps(self.lote())})['guardado'])

    def test_solo_ejecucion_real_contextual_y_sin_rutas_arbitrarias(self):
        salida=operaciones.ejecutar('registrar_ventas_con_productos',{'paso':'lote','ventas_json':json.dumps(self.lote())})
        self.assertFalse(salida['guardado'])
        self.activar()
        salida=operaciones.ejecutar('ejecutar_operacion_plataforma',{'paso':'hack','operacion':'http://localhost/admin/','datos_json':'{}'})
        self.assertFalse(salida['guardado']);self.assertFalse(Venta.objects.exists())

    def test_delegacion_es_privada_durable_y_unica_por_mensaje(self):
        uno=agente.encolar(self.u,self.m.pk)
        dos=agente.encolar(self.u,self.m.pk)
        self.assertEqual(uno['id'],dos['id'])
        self.assertEqual(TrabajoAgenteIA.objects.count(),1)
        self.assertEqual(self.api(self.otro).get(f'/api/asistente/agente/trabajos/{uno["id"]}/').status_code,404)
        self.assertEqual(self.api(self.u).get(f'/api/asistente/agente/trabajos/{uno["id"]}/').data['estado'],'pendiente')

    def test_pendiente_muestra_motor_desconectado_y_su_recuperacion(self):
        from ordenes.asistente import automatizaciones
        datos = agente.encolar(self.u,self.m.pk)
        ruta = f'/api/asistente/agente/trabajos/{datos["id"]}/'
        self.assertFalse(self.api(self.u).get(ruta).data['motor']['activo'])
        automatizaciones.latido()
        self.assertTrue(self.api(self.u).get(ruta).data['motor']['activo'])
        self.assertEqual(TrabajoAgenteIA.objects.get(pk=datos['id']).estado,'pendiente')

    @override_settings(ALLOWED_HOSTS=['api.lottus.test'])
    def test_consulta_paginada_funciona_sin_permitir_testserver(self):
        self.activar()
        Cliente.objects.bulk_create([Cliente(cedula=f'ficticio-pagina-{i}',nombre=f'Cliente ficticio {i}')
                                     for i in range(30)])
        salida = operaciones.ejecutar('consultar_registros_plataforma',{'recurso':'clientes'})
        self.assertNotIn('error',salida)
        self.assertIn('api.lottus.test',salida['next'])
        self.assertEqual(len(salida['results']),25)

    def test_ia_lottus_delega_y_agente_ejecuta_realmente(self):
        with mock.patch.object(gemini,'_llamar',side_effect=[
            respuesta_llamada('ejecutar_con_agente',{'objetivo':'Registrar venta de prueba'}),
            respuesta_texto('Agente recibió la solicitud; está en cola.')]):
            _procesar(self.m.pk,[{'rol':'usuario','texto':'Registra una venta de prueba.'}],self.u.pk,False)
        self.m.refresh_from_db();self.assertEqual(self.m.estado,'listo')
        t=TrabajoAgenteIA.objects.get(origen=self.m)
        with mock.patch.object(gemini,'_llamar',side_effect=[
            respuesta_llamada('registrar_ventas_con_productos',{'paso':'lote','ventas_json':json.dumps(self.lote())}),
            respuesta_texto('Venta registrada con sus productos.')]):
            self.assertTrue(agente.procesar(t.pk))
        t.refresh_from_db()
        self.assertEqual(t.estado,'listo')
        self.assertEqual(Venta.objects.count(),1)
        self.assertEqual(len(t.pasos),1)
        self.assertFalse(TrabajoOficina.objects.exists())
        self.assertTrue(t.respuesta.herramientas[0]['operacion_guardada']['guardado'])

    def test_consultas_con_listas_y_quince_ventas_en_la_misma_ejecucion(self):
        datos=agente.encolar(self.u,self.m.pk)
        with mock.patch.object(gemini,'_llamar',side_effect=[
            respuesta_llamada('consultar_registros_plataforma',{'recurso':'vendedores'}),
            respuesta_llamada('consultar_registros_plataforma',{'recurso':'referencias'}),
            respuesta_llamada('registrar_ventas_con_productos',{'paso':'lote','ventas_json':json.dumps(self.lote(15))}),
            respuesta_texto('Quince ventas registradas con productos.')]):
            self.assertTrue(agente.procesar(datos['id']))
        t=TrabajoAgenteIA.objects.get(pk=datos['id'])
        self.assertEqual(t.estado,'listo');self.assertEqual(Venta.objects.count(),15)
        self.assertEqual(t.pasos[0]['resultado']['ventas_registradas'],15)
        # El resultado final también está enlazado en la respuesta del propio Agente.
        self.assertEqual(_mensaje(t.respuesta)['trabajo_agente']['id'],t.pk)
        self.assertEqual(_mensaje(t.respuesta)['estado'],'listo')

    def test_defensa_si_una_herramienta_devuelve_una_lista(self):
        t=self.activar()
        with mock.patch.object(operaciones,'ejecutar',return_value=[]), mock.patch.object(gemini,'_llamar',side_effect=[
            respuesta_llamada('consultar_registros_plataforma',{'recurso':'vendedores'}),respuesta_texto('No hay vendedores.')]):
            r=gemini.responder([{'rol':'usuario','texto':t.solicitud}],self.u,perfil=self.p,mensaje_id=self.m.pk)
        self.assertEqual(r['texto'],'No hay vendedores.')

    def test_aclarar_y_completar_reanuda_el_trabajo_sin_contexto_recursivo(self):
        self.c.perfil=self.p;self.c.save()
        datos=agente.encolar(self.u,self.m.pk)
        with mock.patch.object(gemini,'_llamar',side_effect=[
            respuesta_llamada('solicitar_datos_operacion',{'pregunta':'Indica los datos de ventas.'}),
            respuesta_texto('Necesito los datos.')]):
            agente.procesar(datos['id'])
        t=TrabajoAgenteIA.objects.get(pk=datos['id'])
        c=t.conversacion
        for texto in ('es solo una prueba, crealas, inventalas para este ejemplo','completala'):
            t.estado='error';t.save(update_fields=['estado'])
            MensajeAsistente.objects.create(conversacion=c,rol='usuario',texto=texto)
            respuesta=MensajeAsistente.objects.create(conversacion=c,rol='asistente',estado='procesando')
            _procesar(respuesta.pk,[],self.u.pk,False,perfil_id=self.p.pk)
            respuesta.refresh_from_db()
            self.assertEqual(_mensaje(respuesta)['trabajo_agente']['id'],t.pk)
        t.refresh_from_db()
        self.assertEqual(TrabajoAgenteIA.objects.count(),1)
        self.assertEqual([p['texto'] for p in t.contexto_usuario],
            ['Registra estas ventas de prueba con sus productos.','es solo una prueba, crealas, inventalas para este ejemplo','completala'])
        self.assertEqual(t.solicitud,'Registra estas ventas de prueba con sus productos.')
        self.assertEqual(c.mensajes.filter(rol='usuario').first().texto,t.solicitud)
        with mock.patch.object(gemini,'_llamar',side_effect=[
            respuesta_llamada('consultar_registros_plataforma',{'recurso':'vendedores'}),
            respuesta_llamada('registrar_ventas_con_productos',{'paso':'lote','ventas_json':json.dumps(self.lote())}),
            respuesta_texto('Registro comprobado.')]):
            self.assertTrue(agente.procesar(t.pk))
        t.refresh_from_db();self.assertEqual(t.estado,'listo')
        self.assertEqual(Venta.objects.count(),1);self.assertFalse(TrabajoOficina.objects.exists())

    def test_enlaces_antiguos_retoman_el_original_y_respetan_privacidad(self):
        datos=agente.encolar(self.u,self.m.pk)
        t=TrabajoAgenteIA.objects.get(pk=datos['id']);t.estado='error';t.save()
        m=MensajeAsistente.objects.create(conversacion=self.c,rol='asistente',estado='error',error='Fallo anterior')
        alias=TrabajoAgenteIA.objects.create(origen=m,usuario=self.u,agente=self.p,solicitud='completala',
            estado='error',respuesta=m,continuacion_de=t)
        self.assertEqual(_mensaje(m)['trabajo_agente']['id'],t.pk)
        self.assertEqual(self.api(self.otro).get(f'/api/asistente/agente/trabajos/{alias.pk}/').status_code,404)
        r=self.api(self.u).post(f'/api/asistente/agente/trabajos/{alias.pk}/',{'accion':'retomar'},format='json')
        self.assertEqual(r.status_code,200);self.assertEqual(r.data['id'],t.pk)
        self.assertEqual(r.data['estado'],'pendiente')
        self.assertEqual(len(self.api(self.u).get('/api/asistente/agente/trabajos/').data['trabajos']),1)
        self.assertFalse(agente.procesar(alias.pk))

    def test_otra_operacion_es_un_trabajo_nuevo(self):
        datos=agente.encolar(self.u,self.m.pk)
        TrabajoAgenteIA.objects.filter(pk=datos['id']).update(estado='error')
        MensajeAsistente.objects.create(conversacion=self.c,rol='usuario',texto='Crea un proveedor diferente.')
        m=MensajeAsistente.objects.create(conversacion=self.c,rol='asistente')
        otro=agente.encolar(self.u,m.pk)
        self.assertNotEqual(otro['id'],datos['id'])

    def test_aclaracion_antes_de_arrancar_no_se_pierde_ni_crea_otro_trabajo(self):
        datos=agente.encolar(self.u,self.m.pk)
        MensajeAsistente.objects.create(conversacion=self.c,rol='usuario',texto='es solo una prueba, inventalas')
        m=MensajeAsistente.objects.create(conversacion=self.c,rol='asistente')
        aclarado=agente.encolar(self.u,m.pk)
        t=TrabajoAgenteIA.objects.get(pk=datos['id'])
        self.assertEqual(aclarado['id'],t.pk);self.assertEqual(TrabajoAgenteIA.objects.count(),1)
        self.assertEqual(t.contexto_usuario[-1]['texto'],'es solo una prueba, inventalas')

    def test_una_consulta_no_completa_una_solicitud_de_guardado(self):
        self.c.mensajes.filter(rol='usuario').update(texto='Agrega 15 ventas de prueba.')
        datos=agente.encolar(self.u,self.m.pk)
        with mock.patch.object(gemini,'_llamar',side_effect=[
            respuesta_llamada('consultar_registros_plataforma',{'recurso':'vendedores'}),
            respuesta_texto('Todo listo.')]):
            agente.procesar(datos['id'])
        t=TrabajoAgenteIA.objects.get(pk=datos['id'])
        self.assertEqual(t.estado,'necesita_datos');self.assertEqual(t.pasos,[])
        self.assertIn('todavía no se ha guardado',t.resultado)

    def test_corregir_el_mismo_lote_resuelve_el_error_anterior(self):
        datos=agente.encolar(self.u,self.m.pk)
        incorrecto=self.lote();incorrecto[0]['productos'][0]['tela_modo']='aparte'
        with mock.patch.object(gemini,'_llamar',side_effect=[
            respuesta_llamada('registrar_ventas_con_productos',{'paso':'lote-v1','ventas_json':json.dumps(incorrecto)}),
            respuesta_llamada('registrar_ventas_con_productos',{'paso':'lote-v2','ventas_json':json.dumps(self.lote())}),
            respuesta_texto('Venta registrada con productos.')]):
            agente.procesar(datos['id'])
        t=TrabajoAgenteIA.objects.get(pk=datos['id'])
        self.assertEqual(t.estado,'listo');self.assertEqual(t.error,'')
        self.assertEqual(Venta.objects.count(),1);self.assertEqual(len(t.pasos),1)

    def test_otro_lote_exitoso_no_oculta_un_lote_que_fallo(self):
        uno=self.lote();otro=self.lote();otro[0]['venta']['fecha_venta']='2026-10-10'
        escrituras=[{'nombre':'registrar_ventas_con_productos','args':{'paso':'uno','ventas_json':json.dumps(uno)},'error_operacion':'Producto inválido'},
                    {'nombre':'registrar_ventas_con_productos','args':{'paso':'dos','ventas_json':json.dumps(otro)},'operacion_guardada':{'guardado':True}}]
        self.assertTrue(agente.fallos_pendientes(escrituras))

    def test_chat_directo_agente_encola_sin_asignar_a_personas(self):
        self.c.perfil=self.p;self.c.save()
        with mock.patch.object(gemini,'responder') as proveedor:
            _procesar(self.m.pk,[{'rol':'usuario','texto':'Registra una venta.'}],self.u.pk,False,perfil_id=self.p.pk)
        proveedor.assert_not_called()
        self.assertEqual(TrabajoAgenteIA.objects.get(origen=self.m).agente_id,self.p.pk)
        self.assertFalse(TrabajoOficina.objects.exists())

    def test_pedir_el_resultado_no_repite_la_operacion_en_ningun_chat(self):
        datos=agente.encolar(self.u,self.m.pk)
        t=TrabajoAgenteIA.objects.get(pk=datos['id']);t.estado='listo';t.resultado='Registro comprobado.';t.save()
        for perfil in (None,self.p):
            self.c.perfil=perfil;self.c.save()
            MensajeAsistente.objects.create(conversacion=self.c,rol='usuario',texto='¿Y el resultado?')
            m=MensajeAsistente.objects.create(conversacion=self.c,rol='asistente',estado='procesando')
            with mock.patch.object(gemini,'responder') as proveedor:
                _procesar(m.pk,[],self.u.pk,False,perfil_id=perfil.pk if perfil else None)
            proveedor.assert_not_called()
            m.refresh_from_db();salida=_mensaje(m)
            self.assertEqual(salida['trabajo_agente']['id'],t.pk)
            self.assertEqual(salida['trabajo_agente']['resultado'],'Registro comprobado.')
            self.assertEqual(TrabajoAgenteIA.objects.count(),1)

    def test_asignar_a_personas_exige_orden_humana_explicita(self):
        args={'responsable':self.vendedor.pk,'titulo':'Registrar ventas'}
        salida=herramientas.ejecutar('asignar_tarea_oficina',args,usuario=self.u,mensaje_id=self.m.pk)
        self.assertIn('error',salida);self.assertFalse(TrabajoOficina.objects.exists())
        p=self.c.mensajes.filter(rol='usuario').first();p.texto='Asígnale a asesor la tarea de registrar estas ventas.';p.save()
        salida=herramientas.ejecutar('asignar_tarea_oficina',args,usuario=self.u,mensaje_id=self.m.pk)
        self.assertTrue(salida.get('asignada'),salida)

    def test_get_no_crea_perfiles_y_nombre_agente_es_unico(self):
        n=PerfilAsistente.objects.count()
        self.assertEqual(self.api(self.u).get('/api/asistente/perfiles/').status_code,200)
        self.assertEqual(PerfilAsistente.objects.count(),n)
        nuevo={'nombre':self.p.nombre.upper(),'rol':'Otro','instrucciones':'Otra identidad suficientemente extensa para una prueba de duplicado.','areas':['operaciones']}
        self.assertEqual(self.api(self.u).post('/api/asistente/perfiles/',nuevo,format='json').status_code,400)
        # El ejecutor sí se puede renombrar (por defecto se llama Alan).
        r=self.api(self.u).patch(f'/api/asistente/perfiles/{self.p.pk}/',{'nombre':'Alan'},format='json')
        self.assertEqual(r.status_code,200,r.data);self.assertEqual(r.data['nombre'],'Alan')

    def test_campos_formulario_y_guardado_de_paso_general(self):
        self.activar()
        catalogo=operaciones.ejecutar('consultar_formulario',{})
        self.assertIn('crear_venta',[o['operacion'] for o in catalogo['operaciones']])
        salida=operaciones.ejecutar('ejecutar_operacion_plataforma',{'operacion':'crear_proveedor','paso':'proveedor','datos_json':json.dumps({'nombre_empresa':'Proveedor ficticio nuevo'})})
        self.assertTrue(salida.get('guardado'),salida)

    def test_datos_faltantes_y_retomar_conservan_la_misma_ejecucion(self):
        datos=agente.encolar(self.u,self.m.pk)
        with mock.patch.object(gemini,'_llamar',side_effect=[
            respuesta_llamada('consultar_formulario',{'operacion':'crear_venta'}),
            respuesta_llamada('solicitar_datos_operacion',{'pregunta':'Indica cliente, asesor y productos.'}),
            respuesta_texto('Necesito cliente, asesor y productos para continuar.')]):
            self.assertTrue(agente.procesar(datos['id']))
        t=TrabajoAgenteIA.objects.get(pk=datos['id'])
        self.assertEqual(t.estado,'necesita_datos');self.assertFalse(Venta.objects.exists())
        r=self.api(self.u).post(f'/api/asistente/agente/trabajos/{t.pk}/',
            {'accion':'retomar','datos_adicionales':'Usa los datos completos de prueba siguientes.'},format='json')
        self.assertEqual(r.status_code,200);self.assertEqual(r.data['id'],t.pk)
        t.refresh_from_db()
        self.assertEqual(_mensaje(t.respuesta)['estado'],'procesando')
        self.assertEqual(_mensaje(t.respuesta)['error'],'')
        with mock.patch.object(gemini,'_llamar',side_effect=[
            respuesta_llamada('registrar_ventas_con_productos',{'paso':'lote','ventas_json':json.dumps(self.lote())}),
            respuesta_texto('Guardada.')]):
            self.assertTrue(agente.procesar(t.pk))
        t.refresh_from_db();self.assertEqual(t.estado,'listo')
        self.assertEqual(Venta.objects.count(),1)
        self.assertEqual(TrabajoAgenteIA.objects.count(),1)

    def test_un_fallo_despues_de_un_paso_guardado_no_se_anuncia_completado(self):
        datos=agente.encolar(self.u,self.m.pk)
        with mock.patch.object(gemini,'_llamar',side_effect=[
            respuesta_llamada('ejecutar_operacion_plataforma',{'operacion':'crear_proveedor','paso':'proveedor','datos_json':'{"nombre_empresa":"Proveedor de prueba"}'}),
            respuesta_llamada('registrar_ventas_con_productos',{'paso':'lote','ventas_json':'[]'}),
            respuesta_texto('Se terminó todo.')]):
            self.assertTrue(agente.procesar(datos['id']))
        t=TrabajoAgenteIA.objects.get(pk=datos['id'])
        self.assertEqual(t.estado,'error');self.assertEqual(len(t.pasos),1)
        self.assertFalse(Venta.objects.exists())

    @override_settings(GEMINI_MODELOS=['modelo-a','modelo-b'])
    def test_cambio_de_modelo_conserva_los_pasos_y_no_duplica_escrituras(self):
        datos=agente.encolar(self.u,self.m.pk)
        llamada=respuesta_llamada('registrar_ventas_con_productos',{'paso':'lote','ventas_json':json.dumps(self.lote())})
        with mock.patch.object(gemini,'_llamar',side_effect=[llamada,gemini._Saturado('Proveedor ocupado'),llamada,respuesta_texto('Venta guardada.')]):
            self.assertTrue(agente.procesar(datos['id']))
        t=TrabajoAgenteIA.objects.get(pk=datos['id'])
        self.assertEqual(t.estado,'listo');self.assertEqual(len(t.pasos),1)
        self.assertEqual(Venta.objects.count(),1)
        self.assertEqual(len(t.respuesta.herramientas),2)

    def test_consolidacion_conserva_chat_documentos_y_notas_en_oficina(self):
        from importlib import import_module
        from django.apps import apps
        from ordenes.models import ZonaOficinaIA, DocumentoPerfilAsistente, AprendizajeAsistente
        zona=ZonaOficinaIA.objects.filter(ambiente='oficina').first() or ZonaOficinaIA.objects.create(nombre='Oficina',ambiente='oficina')
        self.p.zona=zona;self.p.save()
        self.p.nombre='Agente';self.p.save()  # estado previo a 0074, que lo renombra a Alan
        duplicado=PerfilAsistente.objects.create(nombre='Agente',rol='Duplicado',areas=['ventas'])
        self.c.perfil=duplicado;self.c.save()
        doc=DocumentoPerfilAsistente.objects.create(perfil=duplicado,nombre='Prueba.md',tipo='md',texto='Conservar estas instrucciones.')
        nota=AprendizajeAsistente.objects.create(usuario=self.u,perfil=duplicado,tipo='nota',texto='Conservar este aprendizaje.')
        import_module('ordenes.migrations.0072_ejecutor_operativo_ia').consolidar(apps,None)
        self.c.refresh_from_db();doc.refresh_from_db();nota.refresh_from_db()
        self.assertEqual(self.c.perfil_id,self.p.pk)
        self.assertEqual(doc.perfil_id,self.p.pk);self.assertEqual(nota.perfil_id,self.p.pk)
        self.assertEqual(PerfilAsistente.objects.filter(nombre__iexact='Agente').count(),1)
        self.p.refresh_from_db();self.assertEqual(self.p.zona_id,zona.pk)
