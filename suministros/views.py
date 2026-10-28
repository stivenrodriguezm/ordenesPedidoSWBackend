import uuid
from django.db.models import Count, Prefetch, Q
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.filters import SearchFilter, OrderingFilter
from .models import (
    Categoria, Subcategoria, Inventario,
    FacturaProveedor, DetalleFactura, RemisionSuministro, RemisionItemManual, RemisionEvento,
    GrupoInventario, Sede, Zona, HistorialTraslado, CostoAdicionalInventario, ItemInventarioTelaCuero
)
from .serializers import (
    REMISION_ESTADOS_ACTIVOS, REMISION_ESTADOS_VIGENTES, ventas_remisionables_para, tiene_permiso,
    items_retenidos_por_remision, unidad_protegida,
    CategoriaSerializer, SubcategoriaSerializer,
    InventarioSerializer, FacturaProveedorSerializer, FacturaProveedorListSerializer,
    DetalleFacturaSerializer, RemisionSuministroSerializer, GrupoInventarioSerializer,
    SedeSerializer, ZonaSerializer, HistorialTrasladoSerializer,
    CostoAdicionalInventarioSerializer, ItemInventarioTelaCueroSerializer
)
from rest_framework.permissions import IsAuthenticated, BasePermission
from ordenes.permissions import check_feature_permission, tiene_permiso_codigo
from rest_framework.exceptions import PermissionDenied
from ordenes.servicios import idempotente
from django.db import transaction
from . import entregas, movimientos, recepcion
from ordenes.gestion_venta import texto_remision, texto_tela
from ordenes.models import DetallePedido, OrdenPedido, Referencia, Venta


class CategoriaViewSet(viewsets.ModelViewSet):
    def get_permissions(self):
        if self.action in ['create', 'update', 'partial_update', 'destroy']:
            return [IsAuthenticated(), check_feature_permission('ADMINISTRAR_REFERENCIAS')()]
        return [IsAuthenticated()]
    queryset = Categoria.objects.all()
    serializer_class = CategoriaSerializer

class SubcategoriaViewSet(viewsets.ModelViewSet):
    def get_permissions(self):
        if self.action in ['create', 'update', 'partial_update', 'destroy']:
            return [IsAuthenticated(), check_feature_permission('ADMINISTRAR_REFERENCIAS')()]
        return [IsAuthenticated()]
    # categoria_nombre en la misma consulta (antes una por subcategoría).
    queryset = Subcategoria.objects.select_related('categoria')
    serializer_class = SubcategoriaSerializer
    filter_backends = [DjangoFilterBackend, SearchFilter]
    filterset_fields = ['categoria']
    search_fields = ['nombre']

class SedeViewSet(viewsets.ModelViewSet):
    def get_permissions(self):
        if self.action in ['create', 'update', 'partial_update', 'destroy']:
            return [IsAuthenticated(), check_feature_permission('ADMINISTRAR_SEDES')()]
        return [IsAuthenticated()]
    queryset = Sede.objects.all()
    serializer_class = SedeSerializer

    def destroy(self, request, *args, **kwargs):
        sede = self.get_object()
        if sede.zonas.exists():
            return Response(
                {'error': 'No se puede eliminar una sede que tiene zonas asociadas. Elimina o reasigna las zonas primero.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        return super().destroy(request, *args, **kwargs)

class ZonaViewSet(viewsets.ModelViewSet):
    def get_permissions(self):
        if self.action in ['create', 'update', 'partial_update', 'destroy']:
            return [IsAuthenticated(), check_feature_permission('ADMINISTRAR_SEDES')()]
        return [IsAuthenticated()]
    queryset = Zona.objects.select_related('sede').all()
    serializer_class = ZonaSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['sede']

    def destroy(self, request, *args, **kwargs):
        zona = self.get_object()
        if zona.items_inventario.exists():
            return Response(
                {'error': 'No se puede eliminar una zona que tiene inventario asignado. Traslada el inventario a otra zona primero.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        return super().destroy(request, *args, **kwargs)

class HistorialTrasladoViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = HistorialTraslado.objects.select_related('item_inventario', 'zona_origen', 'zona_destino', 'usuario').all().order_by('-fecha')
    serializer_class = HistorialTrasladoSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['item_inventario', 'zona_origen', 'zona_destino', 'usuario']

class InventarioViewSet(viewsets.ModelViewSet):
    def get_permissions(self):
        if self.action in ['create']:
            return [IsAuthenticated(), check_feature_permission('CREAR_ITEM_INVENTARIO')()]
        elif self.action in ['update', 'partial_update', 'destroy', 'trasladar', 'devolver_proveedor']:
            return [IsAuthenticated(), check_feature_permission('EDITAR_ITEM_INVENTARIO')()]
        return [IsAuthenticated(), check_feature_permission('VER_INVENTARIO')()]
    queryset = Inventario.objects.select_related(
        'referencia',
        'referencia__proveedor',
        'categoria',
        'subcategoria',
        'factura',
        'factura__proveedor',
        'detalle_factura',
        'detalle_factura__referencia',
        'detalle_factura__referencia__proveedor',
        'detalle_factura__categoria',
        'detalle_factura__subcategoria',
        'detalle_factura__factura',
        'detalle_factura__factura__proveedor',
        'venta',
        'grupo',
        'zona',
        'zona__sede',
    ).prefetch_related(
        'costos_adicionales',
        'telas_cueros',
        'venta__vendedores_compartidos',
    )
    serializer_class = InventarioSerializer

    def get_queryset(self):
        try:
            return self.queryset.all()
        except Exception:
            return Inventario.objects.all()
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ['disponibilidad', 'categoria', 'subcategoria', 'referencia__proveedor']
    search_fields = ['id_referencia', 'referencia__nombre', 'variacion', 'factura_manual']
    ordering_fields = ['fecha_ingreso', 'id_referencia']

    @action(detail=False, methods=['get'], url_path='por-qr')
    def por_qr(self, request):
        qr_uuid = request.query_params.get('qr')
        if not qr_uuid:
            return Response({'error': 'Parámetro qr es requerido'}, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            item = self.get_queryset().get(qr_uuid=qr_uuid)
            serializer = self.get_serializer(item)
            return Response(serializer.data)
        except Inventario.DoesNotExist:
            return Response({'error': 'Ítem no encontrado'}, status=status.HTTP_404_NOT_FOUND)

    @transaction.atomic
    def perform_create(self, serializer):
        item = serializer.save()
        movimientos.ingreso(item, self.request.user, motivo='Alta manual')

    def _bloquear(self):
        """La unidad bajo bloqueo de fila, leída después de bloquear."""
        Inventario.objects.select_for_update().filter(pk=self.kwargs.get('pk')).first()
        return self.get_object()

    @transaction.atomic
    def perform_update(self, serializer):
        # P11-02: la edición directa no cambia lo que manejan los procesos
        # (remisión activa, devolución al proveedor) y deja su movimiento.
        item = Inventario.objects.select_for_update().get(pk=serializer.instance.pk)
        datos = serializer.validated_data
        cambia_estado = any(c in datos and datos[c] != getattr(item, c) for c in ('disponibilidad', 'estado_fisico'))
        if cambia_estado and not tiene_permiso_codigo(self.request, 'EDITAR_ESTADO_ITEM'):
            raise PermissionDenied('No tienes permiso para cambiar el estado físico o la disponibilidad.')
        venta = datos['venta'].pk if datos.get('venta') else None
        movimientos.validar_edicion_manual(
            item, datos.get('disponibilidad'), venta if 'venta' in datos else False,
            en_remision_activa=bool(items_retenidos_por_remision([item.pk])),
        )
        antes = movimientos.foto(item)
        zona_antes = item.zona_id
        item = serializer.save()
        movimientos.registrar(item, antes, 'edicion', self.request.user, motivo='Edición manual')
        if zona_antes != item.zona_id:
            HistorialTraslado.objects.create(item_inventario=item, zona_origen_id=zona_antes, zona_destino=item.zona,
                                             usuario=self.request.user, observacion='Cambio de zona desde la edición')

    @transaction.atomic
    def destroy(self, request, *args, **kwargs):
        item = self._bloquear()
        motivo = unidad_protegida(item) or ('ya fue entregado' if item.disponibilidad == 'entregado' else '')
        if motivo:
            return Response({'error': f'No se puede eliminar el producto {item.pk}: {motivo}.'}, status=status.HTTP_409_CONFLICT)
        return super().destroy(request, *args, **kwargs)

    @action(detail=True, methods=['post'])
    @transaction.atomic
    def trasladar(self, request, pk=None):
        item = self._bloquear()
        zona_destino_id = request.data.get('zona_destino')
        observacion = request.data.get('observacion', '')

        if not zona_destino_id:
            return Response({'error': 'zona_destino es requerido'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            zona_destino = Zona.objects.get(id=zona_destino_id)
        except Zona.DoesNotExist:
            return Response({'error': 'Zona de destino no existe'}, status=status.HTTP_400_BAD_REQUEST)

        # Movimiento + historial de traslado (P11-02).
        movimientos.aplicar([item], 'traslado', request.user, motivo=observacion, zona=zona_destino)
        return Response({'status': 'Traslado exitoso', 'nueva_zona': zona_destino.nombre})

    @action(detail=True, methods=['post'], url_path='devolver-proveedor')
    @transaction.atomic
    def devolver_proveedor(self, request, pk=None):
        """Devolución al proveedor (P11-02): la unidad sale de la disponibilidad y,
        si estaba ligada a una línea de orden de pedido, esa línea vuelve a quedar
        pendiente para la reposición."""
        item = self._bloquear()
        motivo = str(request.data.get('motivo') or '').strip()
        if not motivo:
            return Response({'motivo': ['Indica por qué se devuelve.']}, status=status.HTTP_400_BAD_REQUEST)
        if item.disponibilidad == 'devuelto_proveedor':
            return Response({'error': 'Ya fue devuelto al proveedor.'}, status=status.HTTP_409_CONFLICT)
        retenido = items_retenidos_por_remision([item.pk])
        if retenido or item.disponibilidad in ('por_despachar', 'despachado', 'entregado'):
            donde = f'va en la remisión #{retenido[item.pk]}' if retenido else f'está {item.get_disponibilidad_display().lower()}'
            return Response({'error': f'No se puede devolver: {donde}.'}, status=status.HTTP_409_CONFLICT)
        movimientos.aplicar([item], 'devolucion_proveedor', request.user, motivo=motivo,
                            documento=f'factura:{item.factura_id}' if item.factura_id else '',
                            disponibilidad='devuelto_proveedor')
        item.refresh_from_db()
        return Response(self.get_serializer(item).data)

    @action(detail=True, methods=['get'], url_path='movimientos')
    def historial_movimientos(self, request, pk=None):
        item = self.get_object()
        filas = item.movimientos.select_related('usuario').order_by('-fecha', '-id')[:200]
        return Response([{
            'tipo': m.tipo, 'tipo_label': m.get_tipo_display(), 'fecha': m.fecha,
            'usuario': (m.usuario.first_name or m.usuario.username) if m.usuario else None,
            'antes': m.antes, 'despues': m.despues, 'motivo': m.motivo, 'documento': m.documento,
        } for m in filas])


class CostoAdicionalInventarioViewSet(viewsets.ModelViewSet):
    """CRUD de costos adicionales por ítem de inventario."""
    def get_permissions(self):
        if self.action in ['create', 'update', 'partial_update', 'destroy']:
            return [IsAuthenticated(), check_feature_permission('EDITAR_ITEM_INVENTARIO')()]
        return [IsAuthenticated(), check_feature_permission('VER_COSTOS_INVENTARIO')()]
    serializer_class = CostoAdicionalInventarioSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['inventario']

    def get_queryset(self):
        return CostoAdicionalInventario.objects.all()


class ItemInventarioTelaCueroViewSet(viewsets.ModelViewSet):
    """CRUD de telas y cueros asociadas a ítems de inventario."""
    def get_permissions(self):
        if self.action in ['create', 'update', 'partial_update', 'destroy']:
            return [IsAuthenticated(), check_feature_permission('EDITAR_ITEM_INVENTARIO')()]
        return [IsAuthenticated(), check_feature_permission('VER_COSTOS_INVENTARIO')()]
    serializer_class = ItemInventarioTelaCueroSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['inventario', 'tipo']

    def get_queryset(self):
        return ItemInventarioTelaCuero.objects.all()

def _dia(valor):
    """Día local de una fecha o fecha-hora (el formulario reenvía la hora del momento)."""
    from datetime import datetime
    from django.utils import timezone
    if isinstance(valor, datetime):
        return timezone.localtime(valor).date() if timezone.is_aware(valor) else valor.date()
    return valor


class FacturaProveedorViewSet(viewsets.ModelViewSet):
    def get_permissions(self):
        if self.action in ['create']:
            return [IsAuthenticated(), check_feature_permission('CREAR_FACTURA')()]
        elif self.action in ['update', 'partial_update', 'destroy']:
            return [IsAuthenticated(), check_feature_permission('EDITAR_FACTURA')()]
        return [IsAuthenticated(), check_feature_permission('VER_FACTURAS')()]
    
    queryset = FacturaProveedor.objects.all()

    def get_queryset(self):
        qs = FacturaProveedor.objects.select_related('proveedor')
        full = self.request.query_params.get('full')
        if self.action != 'list' or full == 'true':
            qs = qs.prefetch_related(
                'items_inventario',
                'items_inventario__referencia',
                'items_inventario__referencia__proveedor',
                'items_inventario__categoria',
                'items_inventario__subcategoria',
                'items_inventario__venta',
                'items_inventario__venta__vendedor',
                'items_inventario__venta__vendedores_compartidos',
                # Usados por FacturasInventarioReadSerializer: sin ellos eran
                # ~4 consultas por ítem (P08-04).
                'items_inventario__grupo__categoria',
                'items_inventario__grupo__subcategoria',
                'items_inventario__zona',
                'items_inventario__telas_cueros',
                'ajustes',
            )
        return qs.all()
        
    def get_serializer_class(self):
        full = self.request.query_params.get('full')
        if self.action == 'list' and full != 'true':
            return FacturaProveedorListSerializer
        return FacturaProveedorSerializer
        
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ['estado', 'proveedor']
    search_fields = ['id_manual', 'proveedor__nombre_empresa']
    ordering_fields = ['fecha_factura', 'fecha_pago']
    ordering = ['-fecha_factura', '-id']

    def perform_update(self, serializer):
        # Las fechas de una factura ya registrada solo las cambia quien tiene el permiso.
        if not tiene_permiso_codigo(self.request, 'EDITAR_FECHAS_FACTURA'):
            factura, datos = serializer.instance, serializer.validated_data
            if 'fecha_factura' in datos and _dia(datos['fecha_factura']) != _dia(factura.fecha_factura) \
                    or 'fecha_pago' in datos and datos['fecha_pago'] != factura.fecha_pago:
                raise PermissionDenied('No tienes permiso para cambiar las fechas de la factura.')
        serializer.save()

    @idempotente('factura.crear')
    def create(self, request, *args, **kwargs):
        # Reintentar el mismo envío (red caída, doble envío) no duplica la
        # factura ni sus ítems de inventario (P08-06).
        return super().create(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        """Una factura vinculada a un pago o con mercancía comprometida es un
        documento histórico: no se borra (H12). Antes el DELETE se saltaba el
        resguardo que sí tenía la edición."""
        from django.db import transaction
        from .serializers import unidad_protegida
        with transaction.atomic():
            factura = FacturaProveedor.objects.select_for_update().get(pk=self.get_object().pk)
            if factura.comprobante_egreso_id or factura.estado in ('pagada', 'pago_en_proceso'):
                return Response({'error': 'La factura tiene un pago asociado y no puede eliminarse.'}, status=status.HTTP_409_CONFLICT)
            for item in factura.items_inventario.all():
                motivo = unidad_protegida(item) or ('ya fue entregado' if item.disponibilidad == 'entregado' else '')
                if motivo:
                    return Response({'error': f'No se puede eliminar: el producto {item.pk} {motivo}.'}, status=status.HTTP_409_CONFLICT)
            for item in factura.items_inventario.all():
                item.telas_cueros.all().delete()
                item.delete()
            from ordenes.servicios import auditar
            auditar(request.user, 'factura.eliminar', factura, {'id_manual': factura.id_manual, 'valor': str(factura.valor)})
            factura.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

class DetalleFacturaViewSet(viewsets.ModelViewSet):
    def get_permissions(self):
        if self.action in ['create']:
            return [IsAuthenticated(), check_feature_permission('CREAR_FACTURA')()]
        elif self.action in ['update', 'partial_update', 'destroy']:
            return [IsAuthenticated(), check_feature_permission('EDITAR_FACTURA')()]
        return [IsAuthenticated(), check_feature_permission('VER_FACTURAS')()]

    queryset = DetalleFactura.objects.all()
    serializer_class = DetalleFacturaSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['factura']

def sugerencias_por_referencia(nombres=None):
    """{nombre de referencia en minúsculas: (categoria_id, subcategoria_id)} para
    autocompletar productos de remisión. Manda la combinación más frecuente en el
    inventario (ahí sí está bien clasificado); si la referencia aún no tiene inventario,
    se usa el catálogo de la referencia cuando la categoría/subcategoría es única."""
    inventario = Inventario.objects.filter(referencia__isnull=False, categoria__isnull=False)
    referencias = Referencia.objects.prefetch_related('categorias', 'subcategorias')
    if nombres is not None:
        nombres = [n for n in nombres if n]
        inventario = inventario.filter(referencia__nombre__in=nombres)
        referencias = referencias.filter(nombre__in=nombres)

    sugerencias = {}
    conteo = (
        inventario.values('referencia__nombre', 'categoria_id', 'subcategoria_id')
        .annotate(n=Count('pk')).order_by('-n')
    )
    for fila in conteo:
        sugerencias.setdefault(fila['referencia__nombre'].strip().lower(), (fila['categoria_id'], fila['subcategoria_id']))

    catalogo = {}
    for ref in referencias:
        cats, subs = catalogo.setdefault(ref.nombre.strip().lower(), (set(), set()))
        cats.update(c.id for c in ref.categorias.all())
        subs.update((s.id, s.categoria_id) for s in ref.subcategorias.all())
    for clave, (cats, subs) in catalogo.items():
        if clave in sugerencias:
            continue
        if len(cats) != 1:
            cats = {c for _, c in subs}
        categoria = next(iter(cats)) if len(cats) == 1 else None
        subs_de_categoria = [s for s, c in subs if c == categoria] if categoria else []
        subcategoria = subs_de_categoria[0] if len(subs_de_categoria) == 1 else None
        if categoria:
            sugerencias[clave] = (categoria, subcategoria)
    return sugerencias


class RemisionSuministroViewSet(viewsets.ModelViewSet):
    # Las remisiones nunca se borran ni se reemplazan completas: se editan por partes
    # (PATCH) y se anulan, para conservar el historial y liberar bien el inventario.
    http_method_names = ['get', 'post', 'patch', 'head', 'options']

    # Campos de seguimiento (los maneja logística/transportador); el resto es "edición".
    CAMPOS_ESTADO = {'estado', 'nota_transportador', 'costo_entrega'}
    # Datos de la petición que no son campos del modelo sino instrucciones del cambio.
    CAMPOS_INSTRUCCION = {'cerrar_ventas', 'motivo', 'no_entregados'}

    CAMPOS_HISTORIAL = {
        'fecha_entrega': 'Fecha de entrega',
        'hora_desde': 'Hora desde',
        'hora_hasta': 'Hora hasta',
        'direccion_entrega': 'Dirección',
        'barrio': 'Barrio',
        'ciudad': 'Ciudad',
        'cliente_nombre': 'Recibe',
        'cliente_documento': 'Documento',
        'cliente_telefono1': 'Teléfono',
        'cliente_telefono2': 'Teléfono alterno',
        'transportador_usuario': 'Transportador',
        'transportador': 'Transportador externo',
        'sin_saldo': 'Sin saldo',
        'saldo': 'Valor a cobrar',
        'metodo_pago': 'Método de pago',
        'vendedor': 'Asesor',
        'observacion': 'Indicaciones',
        'novedades': 'Novedades',
        'costo_entrega': 'Costo del flete',
        'nota_transportador': 'Nota del transportador',
    }

    def get_permissions(self):
        # El transportador siempre puede ver las remisiones que se le asignaron (en cualquier
        # estado) y marcarlas despachadas/entregadas sin depender de que un administrador le
        # configure VER_REMISIONES. Las reglas finas de edición viven en partial_update().
        if self.action in ['create', 'ventas_disponibles', 'datos_ventas', 'inventario_disponible']:
            return [IsAuthenticated(), check_feature_permission('CREAR_REMISION')()]
        if self.action == 'catalogo':
            class CatalogoPermission(BasePermission):
                def has_permission(self, request, view):
                    return tiene_permiso(request, 'CREAR_REMISION') or tiene_permiso(request, 'EDITAR_REMISION')
            return [IsAuthenticated(), CatalogoPermission()]

        class RemisionViewPermission(BasePermission):
            def has_permission(self, request, view):
                if not request.user or not request.user.is_authenticated:
                    return False
                if request.user.role == 'transportador':
                    return True
                return check_feature_permission('VER_REMISIONES')().has_permission(request, view)
        return [IsAuthenticated(), RemisionViewPermission()]

    serializer_class = RemisionSuministroSerializer
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ['estado', 'vendedor']
    search_fields = ['id', 'direccion_entrega', 'ciudad']
    ordering_fields = ['fecha_creacion', 'fecha_entrega']
    ordering = ['-fecha_creacion', '-id']

    def _base_queryset(self):
        return RemisionSuministro.objects.select_related(
            'orden_asociada',
            'orden_asociada__cliente',
            'transportador_usuario',
            'vendedor',
            'creado_por',
        ).prefetch_related(
            'ventas',
            'items_manuales',
            'items_manuales__categoria',
            'items_manuales__subcategoria',
            'eventos',
            'eventos__usuario',
            'novedades_entrega',
            'inventario_items',
            'inventario_items__referencia',
            'inventario_items__referencia__proveedor',
            'inventario_items__categoria',
            'inventario_items__subcategoria',
            'inventario_items__grupo',
            'textos_inventario',
        ).order_by('-fecha_creacion', '-id')

    # Class-level queryset is needed for DRF router registration
    queryset = RemisionSuministro.objects.all().order_by('-fecha_creacion', '-id')

    def get_queryset(self):
        user = self.request.user
        queryset = self._base_queryset()
        if getattr(user, 'role', None) == 'transportador':
            name_filters = Q(transportador__iexact=user.first_name) if user.first_name else Q()
            username_filter = Q(transportador__iexact=user.username)
            queryset = queryset.filter(
                Q(transportador_usuario=user) | name_filters | username_filter
            )
        elif not tiene_permiso(self.request, 'VER_TODAS_REMISIONES'):
            # Sin el permiso de ver todas: solo las de sus ventas (propias o compartidas),
            # las que tiene como asesor o las que creó.
            queryset = queryset.filter(
                Q(vendedor=user) | Q(creado_por=user)
                | Q(ventas__vendedor=user) | Q(ventas__vendedores_compartidos=user)
            ).distinct()
        return queryset

    def _es_remision_del_transportador(self, instance, user):
        if instance.transportador_usuario_id == user.id:
            return True
        if user.first_name and instance.transportador and instance.transportador.lower() == user.first_name.lower():
            return True
        if instance.transportador and instance.transportador.lower() == (user.username or '').lower():
            return True
        return False

    @transaction.atomic
    def partial_update(self, request, *args, **kwargs):
        # Bloqueo de la fila antes de leerla: dos confirmaciones simultáneas (dos
        # transportadores, o transportador y oficina) se serializan y la segunda
        # ve el estado que dejó la primera (P11-03).
        RemisionSuministro.objects.select_for_update().filter(pk=kwargs.get('pk')).first()
        instance = self.get_object()
        user = request.user
        campos = set(request.data.keys()) - self.CAMPOS_INSTRUCCION
        nuevo_estado = request.data.get('estado', instance.estado)
        cambia_estado = 'estado' in campos and nuevo_estado != instance.estado

        def prohibido(mensaje):
            return Response({'error': mensaje}, status=status.HTTP_403_FORBIDDEN)

        if user.role == 'transportador':
            if not self._es_remision_del_transportador(instance, user):
                return prohibido('No tienes permiso para modificar esta remisión.')
            if campos - {'estado', 'nota_transportador'} or (cambia_estado and nuevo_estado not in ('despachada', 'finalizada')):
                return prohibido('Como transportador solo puedes marcar la remisión como despachada o entregada y dejar una nota.')
        else:
            if cambia_estado:
                if nuevo_estado == 'anulada' and not tiene_permiso(request, 'ANULAR_REMISION'):
                    return prohibido('No tienes permiso para anular remisiones.')
                if nuevo_estado != 'anulada' and not tiene_permiso(request, 'CAMBIAR_ESTADO_REMISION'):
                    return prohibido('No tienes permiso para cambiar el estado de las remisiones.')
            if 'nota_transportador' in campos and not tiene_permiso(request, 'CAMBIAR_ESTADO_REMISION'):
                return prohibido('No tienes permiso para registrar el seguimiento de la entrega.')
            if 'costo_entrega' in campos and not (
                tiene_permiso(request, 'CAMBIAR_ESTADO_REMISION') and tiene_permiso(request, 'VER_COSTO_ENTREGA_REMISION')
            ):
                return prohibido('No tienes permiso para registrar el costo del flete.')
            if campos - self.CAMPOS_ESTADO and not tiene_permiso(request, 'EDITAR_REMISION'):
                return prohibido('No tienes permiso para editar remisiones.')

        if cambia_estado and nuevo_estado in ('anulada', 'devuelta') and not str(request.data.get('motivo') or '').strip():
            return Response({'motivo': ['Indica el motivo.']}, status=status.HTTP_400_BAD_REQUEST)
        self._no_entregados = []
        if request.data.get('no_entregados'):
            if nuevo_estado != 'finalizada':
                return Response({'no_entregados': ['Los productos no entregados se indican al confirmar la entrega.']},
                                status=status.HTTP_400_BAD_REQUEST)
            # Reintento de una confirmación que ya quedó (p. ej. sin señal en el celular):
            # responde con el estado actual sin volver a registrar nada (P11-05).
            if cambia_estado:
                self._no_entregados = entregas.validar_no_entregados(instance, request.data.get('no_entregados'))
        return super().partial_update(request, *args, **kwargs)

    def perform_create(self, serializer):
        # La disponibilidad 'por_despachar' se aplica dentro del serializer, en
        # la misma transacción que verifica la reserva bajo bloqueo.
        remision = serializer.save()
        RemisionEvento.objects.create(
            remision=remision,
            tipo='creada',
            usuario=self.request.user,
            detalle=f'Entrega programada para el {remision.fecha_entrega:%d/%m/%Y}' if remision.fecha_entrega else '',
        )

    # ── Apoyo al formulario "Nueva Remisión" ─────────────────────────────────────

    @staticmethod
    def _item_inventario_dict(item, venta_id=None):
        ref = item.referencia
        return {
            'id_referencia': item.id_referencia,
            'producto_nombre': ref.nombre if ref else '',
            'proveedor_nombre': ref.proveedor.nombre_empresa if ref and ref.proveedor else '',
            'categoria_nombre': item.categoria.nombre if item.categoria else '',
            'subcategoria_nombre': item.subcategoria.nombre if item.subcategoria else '',
            'variacion': item.variacion or '',
            'observacion': item.observacion or '',
            'imagen': item.imagen,
            'disponibilidad': item.disponibilidad,
            'disponibilidad_label': item.get_disponibilidad_display(),
            'grupo_id': item.grupo_id,
            'grupo_nombre': item.grupo.nombre if item.grupo else '',
            'venta_id': venta_id if venta_id is not None else item.venta_id,
        }

    @staticmethod
    def _remisiones_por_item(item_ids):
        """{id_referencia: (remision_id, estado)} con la remisión vigente más reciente de cada ítem."""
        filas = RemisionSuministro.inventario_items.through.objects.filter(
            inventario_id__in=list(item_ids),
            remisionsuministro__estado__in=REMISION_ESTADOS_VIGENTES,
        ).order_by('remisionsuministro_id').values_list(
            'inventario_id', 'remisionsuministro_id', 'remisionsuministro__estado'
        )
        return {inv_id: (rem_id, estado) for inv_id, rem_id, estado in filas}

    @staticmethod
    def _estado_item(item, remision_info):
        """(seleccionable, motivo) de un ítem de inventario dentro del formulario."""
        if remision_info:
            rem_id, estado = remision_info
            if estado in REMISION_ESTADOS_ACTIVOS:
                return False, f'Ya va en la remisión #{rem_id}'
            if item.disponibilidad == 'entregado':
                return False, f'Entregado (remisión #{rem_id})'
        if item.disponibilidad in ('despachado', 'entregado', 'devuelto_proveedor'):
            return False, item.get_disponibilidad_display()
        return True, ''

    @action(detail=False, methods=['get'], url_path='ventas-disponibles')
    def ventas_disponibles(self, request):
        """Ventas sin entregar que el usuario puede remisionar (todas con
        CREAR_REMISION_TODAS_VENTAS; si no, solo propias/compartidas). Búsqueda por número
        de venta, nombre o cédula del cliente."""
        user = request.user
        search = (request.query_params.get('search') or '').strip()
        qs = ventas_remisionables_para(request).select_related(
            'cliente', 'vendedor'
        ).prefetch_related('vendedores_compartidos')
        if search:
            filtro = Q(cliente__nombre__icontains=search) | Q(cliente__cedula__icontains=search)
            if search.isdigit():
                filtro |= Q(id=int(search))
            qs = qs.filter(filtro)
        ventas = list(qs.order_by('-fecha_venta', '-id')[:40])

        remisiones = {}
        filas = RemisionSuministro.ventas.through.objects.filter(
            venta_id__in=[v.id for v in ventas],
            remisionsuministro__estado__in=REMISION_ESTADOS_VIGENTES,
        ).values_list('venta_id', 'remisionsuministro_id', 'remisionsuministro__estado')
        for venta_id, rem_id, estado in filas:
            remisiones.setdefault(venta_id, []).append({'id': rem_id, 'estado': estado})

        data = []
        for v in ventas:
            compartidos = list(v.vendedores_compartidos.all())
            data.append({
                'id': v.id,
                'cliente_nombre': v.cliente.nombre if v.cliente else '',
                'cliente_cedula': v.cliente.cedula if v.cliente else '',
                'fecha_venta': v.fecha_venta,
                'fecha_entrega': v.fecha_entrega,
                'valor_total': v.valor_total,
                'saldo': v.saldo,
                'vendedor_nombre': (v.vendedor.first_name or v.vendedor.username) if v.vendedor else '',
                'es_compartida': bool(compartidos),
                'es_mia': v.vendedor_id == user.id or any(c.id == user.id for c in compartidos),
                'remisiones': sorted(remisiones.get(v.id, []), key=lambda r: r['id']),
            })
        return Response(data)

    @action(detail=False, methods=['get'], url_path='datos-ventas')
    def datos_ventas(self, request):
        """Todo lo necesario para autocompletar la remisión a partir de una o varias ventas:
        cliente, dirección, vendedor, saldo, productos en inventario (de facturas) y líneas
        de sus órdenes de pedido que todavía no llegan al inventario."""
        raw = request.query_params.get('ids') or ''
        try:
            ids = [int(x) for x in raw.split(',') if x.strip()]
        except ValueError:
            return Response({'error': 'ids inválidos'}, status=status.HTTP_400_BAD_REQUEST)
        ids = list(dict.fromkeys(ids))[:10]
        if not ids:
            return Response({'error': 'Debes indicar al menos una venta.'}, status=status.HTTP_400_BAD_REQUEST)

        ventas = {
            v.id: v for v in ventas_remisionables_para(request).filter(id__in=ids).select_related(
                'cliente', 'vendedor'
            ).prefetch_related('vendedores_compartidos')
        }
        faltantes = [i for i in ids if i not in ventas]
        if faltantes:
            cerradas = dict(Venta.objects.filter(id__in=faltantes).exclude(estado='pendiente').values_list('id', 'estado'))
            motivos = [
                f'la venta {i} ya fue entregada' if cerradas.get(i) == 'entregado'
                else f'la venta {i} está anulada' if cerradas.get(i) == 'anulada'
                else f'la venta {i} no es tuya'
                for i in faltantes
            ]
            return Response(
                {'error': 'No se puede remisionar: ' + '; '.join(motivos) + '.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        # Productos de inventario ligados a las ventas (vía factura o vía orden de pedido)
        items = list(
            Inventario.objects.filter(Q(venta_id__in=ids) | Q(pedido__venta_id__in=ids))
            .select_related('referencia', 'referencia__proveedor', 'categoria', 'subcategoria', 'grupo', 'pedido', 'detalle_pedido__linea_venta__grupo_catalogo', 'linea_venta_origen__grupo_catalogo')
            .order_by('grupo_id', 'id_referencia')
        )
        rem_por_item = self._remisiones_por_item(i.id_referencia for i in items)

        inventario_por_venta = {i: [] for i in ids}
        # Unidades de cada referencia que ya llegaron al inventario por venta, para no
        # volver a sugerir como "manual" las líneas de pedido que ya tienen su ítem.
        llegadas = {}
        for item in items:
            venta_id = item.venta_id or (item.pedido.venta_id if item.pedido else None)
            if venta_id not in inventario_por_venta:
                continue
            seleccionable, motivo = self._estado_item(item, rem_por_item.get(item.id_referencia))
            d = self._item_inventario_dict(item, venta_id)
            comercial = item.detalle_pedido.linea_venta if item.detalle_pedido_id and item.detalle_pedido.linea_venta_id else getattr(item, 'linea_venta_origen', None)
            d['texto_cliente'] = texto_remision(comercial)
            d['tela'] = texto_tela(comercial)
            d.update({'seleccionable': seleccionable, 'motivo': motivo})
            inventario_por_venta[venta_id].append(d)
            if item.referencia_id:
                key = (venta_id, item.referencia_id)
                llegadas[key] = llegadas.get(key, 0) + 1

        ordenes = list(
            OrdenPedido.objects.filter(venta_id__in=ids).exclude(estado='anulado')
            .select_related('proveedor').prefetch_related(Prefetch(
                'detalles', queryset=DetallePedido.objects.select_related('referencia', 'linea_venta__grupo_catalogo').annotate(
                    n_recibidas=recepcion.contar_recibidas()))).order_by('id')
        )
        detalle_ids = [d.id for o in ordenes for d in o.detalles.all()]
        # Cantidad ya remisionada por línea, descontando lo declarado no entregado (P11-03).
        remisionados = entregas.comprometido_por_linea(detalle_ids, REMISION_ESTADOS_VIGENTES)
        # Las unidades ligadas por factura a su línea (P11-01) cuentan solo para esa línea.
        for orden in ordenes:
            for det in orden.detalles.all():
                if det.n_recibidas and det.referencia_id:
                    key = (orden.venta_id, det.referencia_id)
                    llegadas[key] = max(llegadas.get(key, 0) - det.n_recibidas, 0)
        sugerencias = sugerencias_por_referencia(
            {d.referencia.nombre for o in ordenes for d in o.detalles.all() if d.referencia}
        )
        pedidos_por_venta = {i: [] for i in ids}
        for orden in ordenes:
            for det in orden.detalles.all():
                en_inventario = det.n_recibidas >= det.cantidad
                if not det.n_recibidas and det.referencia_id:
                    key = (orden.venta_id, det.referencia_id)
                    disponibles = llegadas.get(key, 0)
                    if disponibles >= det.cantidad:
                        en_inventario = True
                        llegadas[key] = disponibles - det.cantidad
                faltante = det.cantidad - det.n_recibidas
                remisionada, ultima = remisionados.get(det.id, (0, None))
                pedidos_por_venta[orden.venta_id].append({
                    'detalle_id': det.id,
                    'orden_id': orden.id,
                    'orden_estado': orden.estado,
                    'orden_estado_label': orden.get_estado_display(),
                    'proveedor_nombre': orden.proveedor.nombre_empresa if orden.proveedor else '',
                    'referencia_nombre': det.referencia.nombre if det.referencia else '',
                    'categoria': sugerencias.get(det.referencia.nombre.strip().lower(), (None, None))[0] if det.referencia else None,
                    'subcategoria': sugerencias.get(det.referencia.nombre.strip().lower(), (None, None))[1] if det.referencia else None,
                    'cantidad': det.cantidad,
                    'especificaciones': texto_remision(det.linea_venta) if det.linea_venta_id else (det.especificaciones or ''),
                    'tela': texto_tela(det.linea_venta) if det.linea_venta_id else '',
                    'en_inventario': en_inventario,
                    'recibidas': det.n_recibidas,
                    # Lo recibido se entrega como unidad de inventario; a mano solo va el resto.
                    # Con entrega parcial lo no entregado vuelve a sugerirse (P11-01/P11-03).
                    'remision_previa': ultima if remisionada and remisionada >= faltante else None,
                    'cantidad_por_remisionar': max(faltante - remisionada, 0),
                })

        remisiones_previas = {}
        filas = RemisionSuministro.ventas.through.objects.filter(
            venta_id__in=ids, remisionsuministro__estado__in=REMISION_ESTADOS_VIGENTES,
        ).values_list('venta_id', 'remisionsuministro_id', 'remisionsuministro__estado', 'remisionsuministro__fecha_entrega')
        for venta_id, rem_id, estado, fecha in filas:
            remisiones_previas.setdefault(venta_id, []).append({'id': rem_id, 'estado': estado, 'fecha_entrega': fecha})

        data = []
        for venta_id in ids:
            v = ventas[venta_id]
            c = v.cliente
            data.append({
                'id': v.id,
                'fecha_venta': v.fecha_venta,
                'fecha_entrega': v.fecha_entrega,
                'valor_total': v.valor_total,
                'saldo': v.saldo,
                'vendedor': v.vendedor_id,
                'vendedor_nombre': (v.vendedor.first_name or v.vendedor.username) if v.vendedor else '',
                'vendedores_compartidos_nombres': ', '.join(
                    (u.first_name or u.username) for u in v.vendedores_compartidos.all()
                ),
                'cliente': {
                    'id': c.id,
                    'nombre': c.nombre,
                    'cedula': c.cedula,
                    'telefono1': c.telefono1 or '',
                    'telefono2': c.telefono2 or '',
                    'direccion': c.direccion or '',
                    'barrio': c.barrio or '',
                    'ciudad': c.ciudad or '',
                } if c else None,
                'inventario': inventario_por_venta[venta_id],
                'pedidos': pedidos_por_venta[venta_id],
                'remisiones_previas': sorted(remisiones_previas.get(venta_id, []), key=lambda r: r['id']),
            })
        return Response(data)

    @action(detail=False, methods=['get'])
    def catalogo(self, request):
        """Categorías con sus subcategorías y referencias conocidas (sin repetir por
        proveedor) con su categoría/subcategoría sugerida, para describir productos."""
        categorias = [
            {'id': c.id, 'nombre': c.nombre, 'subcategorias': [
                {'id': s.id, 'nombre': s.nombre} for s in sorted(c.subcategorias.all(), key=lambda s: s.nombre.lower())
            ]}
            for c in Categoria.objects.prefetch_related('subcategorias').order_by('nombre')
        ]
        sugerencias = sugerencias_por_referencia()
        referencias = {}
        for nombre in Referencia.objects.order_by('nombre').values_list('nombre', flat=True):
            clave = nombre.strip().lower()
            if clave and clave not in referencias:
                categoria, subcategoria = sugerencias.get(clave, (None, None))
                referencias[clave] = {'nombre': nombre.strip(), 'categoria': categoria, 'subcategoria': subcategoria}
        return Response({'categorias': categorias, 'referencias': list(referencias.values())})

    @action(detail=False, methods=['get'], url_path='inventario-disponible')
    def inventario_disponible(self, request):
        """Productos que no pertenecen a ninguna venta (exhibición/consignación) para
        agregarlos a la remisión, o un ítem puntual por su código QR / ID."""
        qr = (request.query_params.get('qr') or '').strip()
        search = (request.query_params.get('search') or '').strip()
        base = Inventario.objects.select_related(
            'referencia', 'referencia__proveedor', 'categoria', 'subcategoria', 'grupo'
        )

        if qr:
            try:
                item = base.filter(qr_uuid=uuid.UUID(qr)).first()
            except ValueError:
                item = base.filter(id_referencia__iexact=qr).first()
            if not item:
                return Response({'error': 'No se encontró ningún producto con ese código.'}, status=status.HTTP_404_NOT_FOUND)
            items = [item]
        else:
            qs = base.filter(venta__isnull=True, disponibilidad__in=['exhibicion', 'consignacion'])
            if search:
                qs = qs.filter(
                    Q(id_referencia__icontains=search) | Q(referencia__nombre__icontains=search)
                    | Q(variacion__icontains=search)
                )
            items = list(qs.order_by('referencia__nombre', 'id_referencia')[:40])

        rem_por_item = self._remisiones_por_item(i.id_referencia for i in items)
        data = []
        for item in items:
            seleccionable, motivo = self._estado_item(item, rem_por_item.get(item.id_referencia))
            d = self._item_inventario_dict(item)
            comercial = item.detalle_pedido.linea_venta if item.detalle_pedido_id and item.detalle_pedido.linea_venta_id else getattr(item, 'linea_venta_origen', None)
            d['texto_cliente'] = texto_remision(comercial)
            d['tela'] = texto_tela(comercial)
            d.update({'seleccionable': seleccionable, 'motivo': motivo})
            data.append(d)
        return Response(data)

    @staticmethod
    def _valor_legible(remision, campo):
        valor = getattr(remision, campo)
        if campo in ('transportador_usuario', 'vendedor'):
            return (valor.first_name or valor.username) if valor else '—'
        if valor in (None, ''):
            return '—'
        if isinstance(valor, bool):
            return 'Sí' if valor else 'No'
        if campo == 'fecha_entrega':
            return valor.strftime('%d/%m/%Y')
        if campo in ('hora_desde', 'hora_hasta'):
            return valor.strftime('%H:%M')
        if campo in ('saldo', 'costo_entrega'):
            return '$' + f'{int(valor):,}'.replace(',', '.')
        return str(valor)

    @staticmethod
    def _resumen_productos(remision):
        """Productos escritos o de pedido, legibles para el historial."""
        partes = []
        for m in RemisionItemManual.objects.filter(remision=remision).select_related('subcategoria'):
            nombre = m.referencia or (m.subcategoria.nombre if m.subcategoria else '') or m.descripcion[:40]
            detalle = f' ({m.descripcion[:60]})' if m.descripcion and nombre != m.descripcion[:40] else ''
            partes.append(f'{m.cantidad} × {nombre}{detalle}')
        return ' · '.join(partes) or 'ninguno'

    @staticmethod
    def _liberar_items(items, usuario=None, motivo='', documento=''):
        """Productos de vuelta en bodega (remisión anulada o devuelta, o no entregados):
        los de una venta quedan como 'cliente' y los demás como 'exhibicion', listos
        para otra remisión. Cada uno deja su movimiento (P11-02)."""
        de_venta = Q(venta__isnull=False) | Q(pedido__venta__isnull=False)
        movimientos.aplicar(items.filter(de_venta), 'liberacion', usuario, motivo, documento, disponibilidad='cliente')
        movimientos.aplicar(items.exclude(de_venta), 'liberacion', usuario, motivo, documento, disponibilidad='exhibicion')

    def perform_update(self, serializer):
        request = self.request
        remision = serializer.instance
        enviados = [c for c in serializer.validated_data if c in self.CAMPOS_HISTORIAL]
        antes = {c: self._valor_legible(remision, c) for c in enviados}
        productos_antes = self._resumen_productos(remision) if 'items_manuales' in serializer.validated_data else None
        old_estado = remision.estado

        remision = serializer.save()
        new_estado = remision.estado

        cambios = []
        for campo in enviados:
            despues = self._valor_legible(remision, campo)
            if despues != antes[campo]:
                if campo in ('observacion', 'novedades', 'nota_transportador'):
                    cambios.append(f'{self.CAMPOS_HISTORIAL[campo]}: {despues}')
                else:
                    cambios.append(f'{self.CAMPOS_HISTORIAL[campo]}: {antes[campo]} → {despues}')
        if productos_antes is not None:
            productos_despues = self._resumen_productos(remision)
            if productos_despues != productos_antes:
                cambios.append(f'Productos: {productos_despues}')

        if old_estado != new_estado:
            items = remision.inventario_items.all()
            usuario, doc = request.user, f'remision:{remision.pk}'
            motivo_cambio = str(request.data.get('motivo') or '').strip()
            if new_estado == 'despachada':
                movimientos.aplicar(items, 'despacho', usuario, documento=doc, disponibilidad='despachado')
            elif new_estado == 'creada':
                movimientos.aplicar(items, 'reserva', usuario, motivo_cambio or 'Devuelta a programada', doc,
                                    disponibilidad='por_despachar')
            elif new_estado in ('anulada', 'devuelta'):
                self._liberar_items(items, usuario, motivo_cambio, doc)
            elif new_estado == 'finalizada':
                # Lo declarado como no entregado vuelve a bodega, libre para otra remisión (P11-03).
                no_entregados = getattr(self, '_no_entregados', [])
                ids_no = [f['inventario'].pk for f in no_entregados if 'inventario' in f]
                if ids_no:
                    self._liberar_items(items.filter(pk__in=ids_no), usuario, 'No entregado', doc)
                items = items.exclude(pk__in=ids_no)
                movimientos.aplicar(items, 'entrega', usuario, documento=doc, disponibilidad='entregado')
                if no_entregados:
                    entregas.guardar_no_entregados(remision, no_entregados, request.user)
                    cambios.append(entregas.resumen(no_entregados))
                # Check groups: if all items in a group are delivered, deactivate group
                grupos = set(item.grupo for item in items if item.grupo)
                for grupo in grupos:
                    # If all items in this group are delivered
                    if not grupo.items_inventario.exclude(disponibilidad='entregado').exists():
                        grupo.activo = False
                        grupo.save()

                # Opcional: dejar también la(s) venta(s) como entregadas (así no se les pueden
                # crear más remisiones). Requiere el permiso de ventas correspondiente.
                cerrar = request.data.get('cerrar_ventas') or []
                if cerrar and no_entregados:
                    # Con productos pendientes la venta no está completamente entregada.
                    cambios.append('La venta no se marcó entregada: quedaron productos pendientes')
                    cerrar = []
                if cerrar and tiene_permiso(request, 'EDITAR_ESTADO_VENTA'):
                    ids = [int(x) for x in cerrar if str(x).isdigit()]
                    cerradas = list(
                        remision.ventas.filter(id__in=ids, estado='pendiente').values_list('id', flat=True)
                    )
                    if cerradas:
                        Venta.objects.filter(id__in=cerradas).update(estado='entregado')
                        cambios.append('Venta ' + ', '.join(f'#{v}' for v in cerradas) + ' marcada como entregada')

            motivo = str(request.data.get('motivo') or '').strip()
            RemisionEvento.objects.create(
                remision=remision,
                tipo='reprogramada' if new_estado == 'creada' else new_estado,
                usuario=request.user,
                detalle=' · '.join(([f'Motivo: {motivo}'] if motivo else []) + cambios),
            )
        elif cambios:
            RemisionEvento.objects.create(
                remision=remision, tipo='editada', usuario=request.user, detalle=' · '.join(cambios),
            )


class GrupoInventarioViewSet(viewsets.ModelViewSet):
    def get_permissions(self):
        if self.action in ['create']:
            return [IsAuthenticated(), check_feature_permission('CREAR_GRUPO_INVENTARIO')()]
        elif self.action in ['update', 'partial_update', 'destroy']:
            return [IsAuthenticated(), check_feature_permission('EDITAR_ITEM_INVENTARIO')()]
        return [IsAuthenticated(), check_feature_permission('VER_INVENTARIO')()]
    # categoria/subcategoria del grupo en la misma consulta y de los ítems solo
    # lo que usan items_count y costo_total: antes eran 2 consultas por grupo
    # y se traían todas las columnas de cada ítem (P08-04).
    queryset = GrupoInventario.objects.select_related('categoria', 'subcategoria').prefetch_related(
        'componentes',
        'componentes__referencia',
        'componentes__categoria',
        'componentes__subcategoria',
        Prefetch('items_inventario', queryset=Inventario.objects.only('grupo', 'costo_especifico')),
    )

    def get_queryset(self):
        qs = self.queryset.all()
        return qs.exclude(activo=False)
    serializer_class = GrupoInventarioSerializer
    filter_backends = [SearchFilter]
    search_fields = ['nombre']
