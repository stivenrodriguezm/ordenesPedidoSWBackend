import os
import json
from django.core.management.base import BaseCommand
from django.conf import settings
from paginaweb.models import PaginawebProducto, PaginawebSetting

class Command(BaseCommand):
    help = 'Poblar datos iniciales del catálogo web desde webLottusPrueba/data'

    def handle(self, *args, **options):
        base_dir = settings.BASE_DIR
        data_dir = os.path.join(base_dir.parent, 'webLottusPrueba', 'data')
        
        products_file = os.path.join(data_dir, 'products.json')
        settings_file = os.path.join(data_dir, 'settings.json')

        if os.path.exists(products_file):
            with open(products_file, 'r', encoding='utf-8') as f:
                products_data = json.load(f)
                count = 0
                for p in products_data:
                    PaginawebProducto.objects.update_or_create(
                        id=str(p.get('id')),
                        defaults={
                            'name': p.get('name', ''),
                            'slug': p.get('slug', ''),
                            'category': p.get('category', ''),
                            'price': p.get('price', 0),
                            'old_price': p.get('oldPrice'),
                            'price_range': p.get('priceRange'),
                            'variants': p.get('variants', []),
                            'badge': p.get('badge'),
                            'short_description': p.get('shortDescription', ''),
                            'description': p.get('description', ''),
                            'materials': p.get('materials', ''),
                            'dimensions': p.get('dimensions', ''),
                            'features': p.get('features', []),
                            'images': p.get('images', []),
                            'featured': bool(p.get('featured', False)),
                            'active': p.get('active', True) != False,
                        }
                    )
                    count += 1
                self.stdout.write(self.style.SUCCESS(f'Se importaron/actualizaron {count} productos web.'))
        else:
            self.stdout.write(self.style.WARNING(f'No se encontró {products_file}'))

        if os.path.exists(settings_file):
            with open(settings_file, 'r', encoding='utf-8') as f:
                settings_data = json.load(f)
                for key, val in settings_data.items():
                    PaginawebSetting.objects.update_or_create(
                        key=key,
                        defaults={'value': val}
                    )
                self.stdout.write(self.style.SUCCESS('Se importaron las configuraciones del sitio web.'))
        else:
            self.stdout.write(self.style.WARNING(f'No se encontró {settings_file}'))
