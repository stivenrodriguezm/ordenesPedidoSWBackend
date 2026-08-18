from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

router = DefaultRouter()
router.register(r'admin/products', views.PaginawebProductoAdminViewSet, basename='paginaweb-admin-products')
router.register(r'admin/asesores', views.AsesorPerfilAdminViewSet, basename='paginaweb-admin-asesores')
router.register(r'admin/pqrs', views.PqrsAdminViewSet, basename='paginaweb-admin-pqrs')

urlpatterns = [
    # Endpoints Públicos
    path('products/', views.public_products, name='paginaweb-public-products'),
    path('products/<str:slug_or_id>/', views.public_product_detail, name='paginaweb-public-product-detail'),
    path('settings/', views.public_settings, name='paginaweb-public-settings'),
    path('asesores/', views.public_asesores, name='paginaweb-public-asesores'),
    path('asesores/<slug:slug>/', views.public_asesor_detail, name='paginaweb-public-asesor-detail'),
    path('asesores/<slug:slug>/qr.png', views.asesor_qr_png, name='paginaweb-asesor-qr'),
    path('pqrs/', views.public_create_pqrs, name='paginaweb-public-pqrs-create'),

    # Endpoints Administración
    path('admin/settings/', views.admin_settings, name='paginaweb-admin-settings'),
    path('upload/', views.admin_upload_image, name='paginaweb-admin-upload'),
    # Debe ir antes del router: si no, "upload-foto" sería interpretado como <pk>
    path('admin/asesores/upload-foto/', views.admin_upload_asesor_foto, name='paginaweb-admin-asesores-upload-foto'),
    path('', include(router.urls)),
]
