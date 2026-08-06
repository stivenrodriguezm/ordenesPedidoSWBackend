from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

router = DefaultRouter()
router.register(r'admin/products', views.PaginawebProductoAdminViewSet, basename='paginaweb-admin-products')

urlpatterns = [
    # Endpoints Públicos
    path('products/', views.public_products, name='paginaweb-public-products'),
    path('products/<str:slug_or_id>/', views.public_product_detail, name='paginaweb-public-product-detail'),
    path('settings/', views.public_settings, name='paginaweb-public-settings'),

    # Endpoints Administración
    path('admin/settings/', views.admin_settings, name='paginaweb-admin-settings'),
    path('upload/', views.admin_upload_image, name='paginaweb-admin-upload'),
    path('', include(router.urls)),
]
