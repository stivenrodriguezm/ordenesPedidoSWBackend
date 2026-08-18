from rest_framework import viewsets, status, permissions
from rest_framework.decorators import api_view, permission_classes, action
from rest_framework.response import Response
from rest_framework.parsers import MultiPartParser, FormParser
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
    PqrsPublicCreateSerializer, PqrsAdminSerializer,
)
from .sirv import upload_to_sirv, SirvUploadError
from .image_utils import convert_raw_to_jpeg, RawConversionError, RAW_EXTENSIONS
from . import emails as pqrs_emails
from ordenes.permissions import IsAdministradorRole

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
    PaginawebSetting.objects.update_or_create(
        key="heroSubtitle",
        defaults={"value": "Cada pieza nace en nuestro estudio creativo y toma forma en manos de maestros artesanos bogotanos. Para quienes entienden que un hogar no se decora: se compone."}
    )
    PaginawebSetting.objects.update_or_create(
        key="aboutText",
        defaults={"value": "Desde hace más de 5 años, en LOTTUS entendemos que un mueble bien hecho no pasa de moda: se convierte en parte de la memoria del hogar y se hereda. Cada pieza nace en nuestro taller de Bogotá, donde maestros ebanistas combinan roble, nogal, mármol y cuero con un diseño concebido para perdurar."}
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
    permission_classes = [permissions.IsAuthenticated, IsAdministradorRole]

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
@permission_classes([permissions.IsAuthenticated, IsAdministradorRole])
def admin_settings(request):
    """
    POST /api/paginaweb/admin/settings/
    GET /api/paginaweb/admin/settings/
    """
    if request.method == 'GET':
        settings_objs = PaginawebSetting.objects.all()
        settings_dict = {obj.key: obj.value for obj in settings_objs}
        return Response({"settings": settings_dict})

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
@permission_classes([permissions.IsAuthenticated, IsAdministradorRole])
def admin_upload_image(request):
    """
    POST /api/paginaweb/upload/
    Subida de imágenes para productos o configuraciones
    """
    files = request.FILES.getlist('images') or request.FILES.getlist('file') or request.FILES.getlist('image')
    if not files:
        return Response({"error": "No se enviaron archivos"}, status=status.HTTP_400_BAD_REQUEST)

    uploaded_urls = []
    for f in files:
        ext = os.path.splitext(f.name)[1].lower()
        content_type = f.content_type
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
        elif ext not in ['.jpg', '.jpeg', '.png', '.webp', '.gif', '.avif']:
            ext = '.jpg'

        filename = f"paginaweb/{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}{ext}"
        try:
            url = upload_to_sirv(file_bytes, filename, content_type)
        except SirvUploadError:
            logger.exception("Error subiendo imagen a Sirv")
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
    permission_classes = [permissions.IsAuthenticated, IsAdministradorRole]

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
@permission_classes([permissions.IsAuthenticated, IsAdministradorRole])
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

    ext = os.path.splitext(f.name)[1].lower()
    if ext not in ['.jpg', '.jpeg', '.png', '.webp']:
        ext = '.jpg'
    filename = f"asesores/{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}{ext}"
    try:
        url = upload_to_sirv(f.read(), filename, f.content_type)
    except SirvUploadError:
        logger.exception("Error subiendo foto de asesor a Sirv")
        return Response({"error": "No se pudo subir la imagen. Intenta de nuevo."}, status=status.HTTP_502_BAD_GATEWAY)

    return Response({"ok": True, "url": url})


# ============================================================
# PQRS — Peticiones, Quejas, Reclamos y Sugerencias (formulario de Contacto)
# ============================================================

@api_view(['POST'])
@permission_classes([permissions.AllowAny])
def public_create_pqrs(request):
    """
    POST /api/paginaweb/pqrs/
    Crea un ticket desde el formulario público de "Contacto" y envía el
    correo de confirmación al cliente (más una notificación interna).
    """
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


class PqrsAdminViewSet(viewsets.ModelViewSet):
    """
    Gestión de PQRS desde "Gestión Web" → pestaña PQRS. El contenido
    enviado por el cliente es de solo lectura; el estado se puede cambiar
    libremente (PATCH) y las respuestas se agregan con la acción
    `responder`, que también envía el correo al cliente.
    """
    queryset = PqrsTicket.objects.all()
    serializer_class = PqrsAdminSerializer
    permission_classes = [permissions.IsAuthenticated, IsAdministradorRole]

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
