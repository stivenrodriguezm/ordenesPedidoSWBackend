# Generated manually for paginaweb

import uuid
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
    ]

    operations = [
        migrations.CreateModel(
            name='PaginawebProducto',
            fields=[
                ('id', models.CharField(default=uuid.uuid4, max_length=255, primary_key=True, serialize=False)),
                ('name', models.CharField(max_length=255, verbose_name='Nombre')),
                ('slug', models.SlugField(max_length=255, unique=True, verbose_name='Slug')),
                ('category', models.CharField(blank=True, default='', max_length=100, verbose_name='Categoría')),
                ('price', models.DecimalField(decimal_places=2, default=0, max_digits=12, verbose_name='Precio')),
                ('old_price', models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True, verbose_name='Precio Anterior')),
                ('price_range', models.JSONField(blank=True, null=True, verbose_name='Rango de Precios')),
                ('variants', models.JSONField(blank=True, default=list, verbose_name='Variaciones')),
                ('badge', models.CharField(blank=True, max_length=100, null=True, verbose_name='Etiqueta / Badge')),
                ('short_description', models.TextField(blank=True, default='', verbose_name='Descripción Corta')),
                ('description', models.TextField(blank=True, default='', verbose_name='Descripción Larga')),
                ('materials', models.TextField(blank=True, default='', verbose_name='Materiales')),
                ('dimensions', models.TextField(blank=True, default='', verbose_name='Dimensiones')),
                ('features', models.JSONField(blank=True, default=list, verbose_name='Características')),
                ('images', models.JSONField(blank=True, default=list, verbose_name='Imágenes')),
                ('featured', models.BooleanField(default=False, verbose_name='Destacado')),
                ('active', models.BooleanField(default=True, verbose_name='Activo')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='Fecha de Creación')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='Última Actualización')),
            ],
            options={
                'verbose_name': 'Producto Web',
                'verbose_name_plural': 'Productos Web',
                'db_table': 'paginaweb_producto',
                'ordering': ['-created_at'],
            },
        ),
        migrations.CreateModel(
            name='PaginawebSetting',
            fields=[
                ('key', models.CharField(max_length=100, primary_key=True, serialize=False, verbose_name='Clave')),
                ('value', models.JSONField(blank=True, null=True, verbose_name='Valor')),
            ],
            options={
                'verbose_name': 'Configuración Web',
                'verbose_name_plural': 'Configuraciones Web',
                'db_table': 'paginaweb_setting',
            },
        ),
    ]
