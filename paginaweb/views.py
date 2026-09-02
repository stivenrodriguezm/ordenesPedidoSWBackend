from rest_framework import viewsets, status, permissions
from rest_framework.decorators import api_view, permission_classes, action
from rest_framework.response import Response
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.views import APIView
from rest_framework.throttling import ScopedRateThrottle
from django.conf import settings
from django.db.models import Q
from django.http import HttpResponse
from django.utils import timezone
from django.utils.text import slugify
import io
import logging
import os
import uuid
import datetime
import qrcode

from .models import PaginawebProducto, PaginawebSetting, AsesorPerfil, PqrsTicket
from .serializers import (
    PaginawebProductoSerializer, PaginawebSettingSerializer, CATEGORIES,
    AsesorPublicSerializer, AsesorAdminSerializer,
    PqrsPublicCreateSerializer, PqrsAdminSerializer, PqrsTrackingSerializer,
)
from .cloudinary_client import upload_to_cloudinary, CloudinaryUploadError
from .image_utils import (
    convert_raw_to_jpeg, RawConversionError, RAW_EXTENSIONS,
    validate_image, InvalidImageError, validate_video, InvalidVideoError,
    optimize_image_for_upload,
)
from . import emails as pqrs_emails
from ordenes.permissions import check_feature_permission

logger = logging.getLogger(__name__)


@api_view(['GET'])
@permission_classes([permissions.AllowAny])
def public_products(request):
    """
    GET /api/paginaweb/products/
    Parámetros: category, q, featured, sort
    """
    queryset = PaginawebProducto.objects.filter(active=True)
    
    category = request.GET.get('category')
    q = request.GET.get('q')
    featured = request.GET.get('featured')
    sort = request.GET.get('sort')

    if category:
        queryset = queryset.filter(category=category)
    if featured == '1':
        queryset = queryset.filter(featured=True)
    if q:
        needle = q.strip().lower()
        queryset = queryset.filter(
            Q(name__icontains=needle) |
            Q(short_description__icontains=needle) |
            Q(description__icontains=needle)
        )

    products_list = list(queryset)

    if sort == 'price-asc':
        products_list.sort(key=lambda p: float(p.price))
    elif sort == 'price-desc':
        products_list.sort(key=lambda p: float(p.price), reverse=True)
    elif sort == 'new':
        products_list.sort(key=lambda p: p.created_at, reverse=True)
    else:
        products_list.sort(key=lambda p: (1 if p.featured else 0, p.created_at), reverse=True)

    serializer = PaginawebProductoSerializer(products_list, many=True)
    return Response({
        "products": serializer.data,
        "categories": CATEGORIES
    })


@api_view(['GET'])
@permission_classes([permissions.AllowAny])
def public_product_detail(request, slug_or_id):
    """
    GET /api/paginaweb/products/<slug_or_id>/
    """
    product = PaginawebProducto.objects.filter(Q(slug=slug_or_id) | Q(id=slug_or_id), active=True).first()
    if not product:
        return Response({"error": "Producto no encontrado"}, status=status.HTTP_404_NOT_FOUND)

    related = PaginawebProducto.objects.filter(category=product.category, active=True).exclude(id=product.id)[:4]
    
    serializer = PaginawebProductoSerializer(product)
    related_serializer = PaginawebProductoSerializer(related, many=True)

    return Response({
        "product": serializer.data,
        "related": related_serializer.data,
        "categories": CATEGORIES
    })


@api_view(['GET'])
@permission_classes([permissions.AllowAny])
def public_settings(request):
    """
    GET /api/paginaweb/settings/
    """
    # get_or_create (no update_or_create): esto solo debe sembrar el valor
    # por defecto la primera vez que no existe el registro — antes usaba
    # update_or_create, que reescribía el texto editado por un admin de
    # vuelta al default en cada solicitud de este endpoint público.
    PaginawebSetting.objects.get_or_create(
        key="heroSubtitle",
        defaults={"value": "Cada pieza nace en nuestro estudio creativo y toma forma en manos de maestros artesanos bogotanos. Para quienes entienden que un hogar no se decora: se compone."}
    )
    PaginawebSetting.objects.get_or_create(
        key="aboutText",
        defaults={"value": "Desde hace más de 5 años, en LOTTUS entendemos que un mueble bien hecho no pasa de moda: se convierte en parte de la memoria del hogar y se hereda. Cada pieza nace en nuestro taller, donde maestros ebanistas combinan maderas flor morado, roble, cuero, telas, hornamentacion, entre otros, con un diseño concebido para perdurar."}
    )
    settings_objs = PaginawebSetting.objects.all()
    settings_dict = {}
    for obj in settings_objs:
        settings_dict[obj.key] = obj.value

    return Response({
        "settings": settings_dict,
        "categories": CATEGORIES
    })


class PaginawebProductoAdminViewSet(viewsets.ModelViewSet):
    queryset = PaginawebProducto.objects.all()
    serializer_class = PaginawebProductoSerializer

    def get_permissions(self):
        if self.action == 'create':
            return [permissions.IsAuthenticated(), check_feature_permission('CREAR_PRODUCTO_WEB')()]
        if self.action in ['update', 'partial_update']:
            return [permissions.IsAuthenticated(), check_feature_permission('EDITAR_PRODUCTO_WEB')()]
        if self.action == 'destroy':
            return [permissions.IsAuthenticated(), check_feature_permission('ELIMINAR_PRODUCTO_WEB')()]
        return [permissions.IsAuthenticated(), check_feature_permission('GESTION_WEB')()]

    def perform_create(self, serializer):
        data = self.request.data
        name = data.get('name', 'Producto')
        slug = data.get('slug')
        if not slug:
            slug = slugify(name)
            base_slug = slug
            count = 1
            while PaginawebProducto.objects.filter(slug=slug).exists():
                slug = f"{base_slug}-{count}"
                count += 1
        
        prod_id = str(data.get('id') or uuid.uuid4())
        serializer.save(id=prod_id, slug=slug)

    def perform_update(self, serializer):
        data = self.request.data
        if 'name' in data and 'slug' not in data:
            slug = slugify(data['name'])
            serializer.save(slug=slug)
        else:
            serializer.save()


@api_view(['POST', 'GET'])
@permission_classes([permissions.IsAuthenticated, check_feature_permission('GESTION_WEB')])
def admin_settings(request):
    """
    POST /api/paginaweb/admin/settings/
    GET /api/paginaweb/admin/settings/
    """
    if request.method == 'GET':
        settings_objs = PaginawebSetting.objects.all()
        settings_dict = {obj.key: obj.value for obj in settings_objs}
        return Response({"settings": settings_dict})

    if not check_feature_permission('EDITAR_CONFIGURACION_WEB')().has_permission(request, None):
        return Response({"error": "No tienes permiso para editar la configuración del sitio."}, status=status.HTTP_403_FORBIDDEN)

    data = request.data
    if isinstance(data, dict):
        for key, val in data.items():
            PaginawebSetting.objects.update_or_create(
                key=key,
                defaults={"value": val}
            )
        return Response({"ok": True, "message": "Configuraciones actualizadas"})
    return Response({"error": "Formato inválido"}, status=status.HTTP_400_BAD_REQUEST)


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated, check_feature_permission('GESTION_WEB')])
def admin_upload_image(request):
    """
    POST /api/paginaweb/upload/
    Subida de imágenes para productos o configuraciones
    """
    files = request.FILES.getlist('images') or request.FILES.getlist('file') or request.FILES.getlist('image')
    if not files:
        return Response({"error": "No se enviaron archivos"}, status=status.HTTP_400_BAD_REQUEST)

    max_image_size = 40 * 1024 * 1024
    max_video_size = 100 * 1024 * 1024
    uploaded_urls = []
    for f in files:
        if f.size > max_video_size:
            return Response({"error": f"'{f.name}' supera el máximo de 100 MB"}, status=status.HTTP_400_BAD_REQUEST)

        ext = os.path.splitext(f.name)[1].lower()
        file_bytes = f.read()

        if ext in RAW_EXTENSIONS:
            # Los navegadores no pueden mostrar RAW directamente — se revela a JPEG
            # antes de subir para que el producto realmente se vea en la web.
            try:
                file_bytes = convert_raw_to_jpeg(file_bytes)
            except RawConversionError:
                logger.exception(f"Error convirtiendo RAW a JPEG: {f.name}")
                return Response(
                    {"error": f"No se pudo procesar el archivo RAW '{f.name}'."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            ext = '.jpg'
            content_type = 'image/jpeg'
            file_bytes, ext, content_type = optimize_image_for_upload(file_bytes, ext, content_type)
        else:
            # No confiar en la extensión ni el content-type declarados por el
            # cliente: se verifica que los bytes sean realmente una imagen o
            # un video decodificable antes de subirlos a Cloudinary (evita
            # subir un archivo arbitrario disfrazado con extensión .jpg/.mp4).
            # La galería del sitio soporta ambos en el mismo campo "images".
            try:
                ext, content_type = validate_image(file_bytes)
                if f.size > max_image_size:
                    return Response(
                        {"error": f"'{f.name}' supera el máximo de 40 MB para imágenes"},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
                # Cloudinary (plan gratis) rechaza cualquier imagen de más de
                # 10 MB tal cual — se redimensiona/recomprime solo si hace
                # falta para caber, sin pérdida de calidad perceptible (una
                # foto no necesita más resolución que la de la pantalla más
                # grande en la que se va a mostrar).
                file_bytes, ext, content_type = optimize_image_for_upload(file_bytes, ext, content_type)
            except InvalidImageError:
                try:
                    ext, content_type = validate_video(file_bytes)
                except InvalidVideoError:
                    return Response(
                        {"error": f"'{f.name}' no es una imagen ni un video válido (usa JPG, PNG, WEBP, MP4, MOV o WEBM)."},
                        status=status.HTTP_400_BAD_REQUEST,
                    )

        filename = f"paginaweb/{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}{ext}"
        try:
            url = upload_to_cloudinary(file_bytes, filename, content_type)
        except CloudinaryUploadError:
            logger.exception("Error subiendo imagen a Cloudinary")
            return Response({"error": "No se pudo subir la imagen. Intenta de nuevo."}, status=status.HTTP_502_BAD_GATEWAY)
        uploaded_urls.append(url)

    return Response({
        "ok": True,
        "urls": uploaded_urls,
        "url": uploaded_urls[0] if uploaded_urls else None
    })


# ============================================================
# Asesores — Tarjetas digitales ("Paleta de Vendedores")
# Contenido independiente, administrado igual que los productos web.
# ============================================================

@api_view(['GET'])
@permission_classes([permissions.AllowAny])
def public_asesores(request):
    """
    GET /api/paginaweb/asesores/
    Lista pública de asesores habilitados por un administrador.
    """
    perfiles = AsesorPerfil.objects.filter(activo=True).order_by('orden', 'nombre')
    serializer = AsesorPublicSerializer(perfiles, many=True)
    return Response({"asesores": serializer.data})


@api_view(['GET'])
@permission_classes([permissions.AllowAny])
def public_asesor_detail(request, slug):
    """
    GET /api/paginaweb/asesores/<slug>/
    """
    perfil = AsesorPerfil.objects.filter(slug=slug, activo=True).first()
    if not perfil:
        return Response({"error": "Asesor no encontrado"}, status=status.HTTP_404_NOT_FOUND)
    serializer = AsesorPublicSerializer(perfil)
    return Response({"asesor": serializer.data})


@api_view(['GET'])
@permission_classes([permissions.AllowAny])
def asesor_qr_png(request, slug):
    """
    GET /api/paginaweb/asesores/<slug>/qr.png
    Genera un código QR real (PNG) que apunta a la tarjeta pública del asesor.
    """
    perfil = AsesorPerfil.objects.filter(slug=slug, activo=True).first()
    if not perfil:
        return Response({"error": "Asesor no encontrado"}, status=status.HTTP_404_NOT_FOUND)

    profile_url = f"{settings.PUBLIC_SITE_URL}/asesor/{perfil.slug}"
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=2,
    )
    qr.add_data(profile_url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="#0a0a0a", back_color="#ffffff").convert('RGB')

    buffer = io.BytesIO()
    img.save(buffer, format='PNG')
    response = HttpResponse(buffer.getvalue(), content_type='image/png')
    response['Cache-Control'] = 'public, max-age=3600'
    return response


class AsesorPerfilAdminViewSet(viewsets.ModelViewSet):
    """
    CRUD de tarjetas de asesores para "Paleta de Vendedores" (Gestión Web).
    Mismo esquema de permisos que productos/ajustes web.
    """
    queryset = AsesorPerfil.objects.all()
    serializer_class = AsesorAdminSerializer

    def get_permissions(self):
        # Ver la "Paleta de Vendedores" ya requiere el mismo permiso que
        # administrarla — GESTION_WEB por sí solo ya no basta, para que un
        # rol sin este permiso ni siquiera pueda listar los asesores.
        return [permissions.IsAuthenticated(), check_feature_permission('ADMINISTRAR_ASESORES_WEB')()]

    def perform_create(self, serializer):
        data = self.request.data
        nombre = data.get('nombre', 'Asesor')
        slug = data.get('slug')
        if not slug:
            slug = slugify(nombre) or 'asesor'
            base_slug = slug
            count = 1
            while AsesorPerfil.objects.filter(slug=slug).exists():
                slug = f"{base_slug}-{count}"
                count += 1

        asesor_id = str(data.get('id') or uuid.uuid4())
        serializer.save(id=asesor_id, slug=slug)

    # A propósito NO se regenera el slug al editar el nombre (a diferencia de
    # productos): el slug de un asesor puede estar impreso en tarjetas físicas
    # o codificado en un QR ya compartido — cambiarlo silenciosamente rompería
    # esos enlaces. perform_update por defecto conserva el slug existente.


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated, check_feature_permission('ADMINISTRAR_ASESORES_WEB')])
def admin_upload_asesor_foto(request):
    """
    POST /api/paginaweb/admin/asesores/upload-foto/
    Subida de foto de perfil para la tarjeta digital de un asesor.
    """
    f = request.FILES.get('foto') or request.FILES.get('file') or request.FILES.get('image')
    if not f:
        return Response({"error": "No se envió ningún archivo"}, status=status.HTTP_400_BAD_REQUEST)

    max_size = 5 * 1024 * 1024
    if f.size > max_size:
        return Response({"error": "La imagen supera el máximo de 5 MB"}, status=status.HTTP_400_BAD_REQUEST)

    file_bytes = f.read()
    try:
        ext, content_type = validate_image(file_bytes)
    except InvalidImageError:
        return Response({"error": "El archivo no es una imagen válida."}, status=status.HTTP_400_BAD_REQUEST)

    filename = f"asesores/{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}{ext}"
    try:
        url = upload_to_cloudinary(file_bytes, filename, content_type)
    except CloudinaryUploadError:
        logger.exception("Error subiendo foto de asesor a Cloudinary")
        return Response({"error": "No se pudo subir la imagen. Intenta de nuevo."}, status=status.HTTP_502_BAD_GATEWAY)

    return Response({"ok": True, "url": url})


# ============================================================
# PQRS — Peticiones, Quejas, Reclamos y Sugerencias (formulario de Contacto)
# ============================================================

class PublicCreatePqrsView(APIView):
    """
    POST /api/paginaweb/pqrs/
    Crea un ticket desde el formulario público de "Contacto" y envía el
    correo de confirmación al cliente (más una notificación interna).
    Throttle propio y bajo (ver 'pqrs_create' en settings) para que un bot no
    pueda inundar el buzón de PQRS ni el correo de un tercero con envíos
    automatizados.
    """
    permission_classes = [permissions.AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'pqrs_create'

    def post(self, request):
        serializer = PqrsPublicCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        ticket = serializer.save(id=str(uuid.uuid4()))

        pqrs_emails.send_confirmation_email(ticket)
        pqrs_emails.send_internal_notification(ticket)

        return Response({
            "ok": True,
            "radicado": ticket.radicado,
            "message": "Hemos recibido tu solicitud. Revisa tu correo para ver la confirmación.",
        }, status=status.HTTP_201_CREATED)


class PublicTrackPqrsView(APIView):
    """
    POST /api/paginaweb/pqrs/rastrear/  { "radicado": "PQRS-XXXXXXXX", "email": "..." }
    Consulta pública de seguimiento. Exige radicado + correo juntos (no solo
    el radicado) para que no cualquiera pueda leer el caso de otra persona
    adivinando/probando radicados — el correo actúa como segundo factor,
    igual que en los portales de PQRS típicos que piden radicado + documento.
    Throttle propio y bajo (ver 'pqrs_track' en settings) para frenar el
    fuerza bruta de radicados/correos.
    """
    permission_classes = [permissions.AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'pqrs_track'

    def post(self, request):
        radicado = (request.data.get('radicado') or '').strip().upper()
        email = (request.data.get('email') or '').strip().lower()
        if not radicado or not email:
            return Response(
                {"error": "Ingresa el radicado y el correo con el que lo creaste."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        prefix = radicado[5:] if radicado.startswith('PQRS-') else radicado
        if len(prefix) < 6:
            return Response({"error": "No encontramos un PQRS con esos datos."}, status=status.HTTP_404_NOT_FOUND)

        ticket = PqrsTicket.objects.filter(id__istartswith=prefix, email__iexact=email).first()
        if not ticket:
            return Response({"error": "No encontramos un PQRS con esos datos."}, status=status.HTTP_404_NOT_FOUND)

        return Response(PqrsTrackingSerializer(ticket).data)


class PqrsAdminViewSet(viewsets.ModelViewSet):
    """
    Gestión de PQRS desde "Gestión Web" → pestaña PQRS. El contenido
    enviado por el cliente es de solo lectura; el estado se puede cambiar
    libremente (PATCH) y las respuestas se agregan con la acción
    `responder`, que también envía el correo al cliente.
    """
    queryset = PqrsTicket.objects.all()
    serializer_class = PqrsAdminSerializer

    def get_permissions(self):
        # Ver los tickets PQRS ya requiere el mismo permiso que responderlos
        # — GESTION_WEB por sí solo ya no basta, para que un rol sin este
        # permiso ni siquiera pueda listarlos.
        return [permissions.IsAuthenticated(), check_feature_permission('RESPONDER_PQRS')()]

    def create(self, request, *args, **kwargs):
        return Response(
            {"error": "Los tickets PQRS solo se crean desde el formulario público de contacto."},
            status=status.HTTP_405_METHOD_NOT_ALLOWED,
        )

    def destroy(self, request, *args, **kwargs):
        return Response(
            {"error": "No se permite eliminar tickets PQRS."},
            status=status.HTTP_405_METHOD_NOT_ALLOWED,
        )

    def update(self, request, *args, **kwargs):
        # El contenido del cliente es de solo lectura (ver read_only_fields
        # del serializer); solo se admite actualización parcial de estado.
        kwargs['partial'] = True
        return super().update(request, *args, **kwargs)

    @action(detail=True, methods=['post'])
    def responder(self, request, pk=None):
        """
        POST /api/paginaweb/admin/pqrs/<id>/responder/  { "mensaje": "..." }
        Agrega una respuesta al hilo del ticket, marca el estado como
        "respondido" y envía el correo al cliente.
        """
        ticket = self.get_object()
        mensaje = (request.data.get('mensaje') or '').strip()
        if not mensaje:
            return Response({"error": "El mensaje de respuesta es obligatorio."}, status=status.HTTP_400_BAD_REQUEST)

        autor = request.user.get_full_name() or request.user.username
        ticket.respuestas = list(ticket.respuestas or []) + [{
            "mensaje": mensaje,
            "fecha": timezone.now().isoformat(),
            "autor": autor,
        }]
        ticket.estado = 'respondido'
        ticket.respondido_por = autor
        ticket.save()

        pqrs_emails.send_response_email(ticket, mensaje)

        return Response(PqrsAdminSerializer(ticket).data)
