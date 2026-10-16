from django.db import migrations, models


class Migration(migrations.Migration):
    """La tela del producto se registra como en /telas: material, referencia y color."""

    dependencies = [
        ('ordenes', '0053_tela_y_gestion_venta'),
    ]

    operations = [
        migrations.RenameField(model_name='lineaventa', old_name='tela_nombre', new_name='tela_referencia'),
        migrations.AddField(
            model_name='lineaventa', name='tela_color',
            field=models.CharField(blank=True, default='', max_length=255),
        ),
        migrations.AddField(
            model_name='lineaventa', name='tela_material',
            field=models.CharField(blank=True, choices=[('tela', 'Tela'), ('cuero', 'Cuero')], default='', max_length=6),
        ),
    ]
