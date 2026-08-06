from rest_framework import viewsets, status, permissions
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework.parsers import MultiPartParser, FormParser
from django.db.models import Q
from django.utils.text import slugify
from django.core.files.storage import default_storage
from django.core.files.base import ContentFile
import os
import uuid
import datetime

from .models import PaginawebProducto, PaginawebSetting
from .serializers import PaginawebProductoSerializer, PaginawebSettingSerializer, CATEGORIES
from ordenes.permissions import check_feature_permission


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
    permission_classes = [permissions.IsAuthenticated, check_feature_permission('ADMINISTRAR_PAGINAWEB')]

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
@permission_classes([permissions.IsAuthenticated, check_feature_permission('ADMINISTRAR_PAGINAWEB')])
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
@permission_classes([permissions.IsAuthenticated, check_feature_permission('ADMINISTRAR_PAGINAWEB')])
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
        if ext not in ['.jpg', '.jpeg', '.png', '.webp', '.gif', '.avif']:
            ext = '.jpg'
        filename = f"paginaweb/{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}{ext}"
        saved_path = default_storage.save(filename, ContentFile(f.read()))
        uploaded_urls.append(f"/media/{saved_path}")

    return Response({
        "ok": True,
        "urls": uploaded_urls,
        "url": uploaded_urls[0] if uploaded_urls else None
    })
