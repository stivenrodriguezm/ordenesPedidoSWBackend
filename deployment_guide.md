# Guía de Despliegue en Producción - Hostinger VPS & MySQL (`api.muebleslottus.com`)

Esta guía describe el procedimiento oficial para ejecutar las migraciones y desplegar el backend en el servidor **Hostinger VPS** usando la base de datos MySQL en Hostinger (`u756180748_lottus`).

---

## 1. Respaldo de Seguridad de la Base de Datos Real (phpMyAdmin / SSH)

Antes de hacer las migraciones, realiza una copia de seguridad de la base de datos de producción `u756180748_lottus`:

### Opción A (Desde el panel phpMyAdmin de Hostinger):
1. Entra al panel de **Hostinger -> Bases de Datos MySQL -> phpMyAdmin**.
2. Selecciona la base de datos `u756180748_lottus`.
3. Haz clic en la pestaña **Exportar**.
4. Selecciona el formato **SQL** y haz clic en **Exportar** para descargar la copia en tu equipo.

### Opción B (Desde la terminal del VPS Hostinger):
```bash
mysqldump -h "$DB_HOST" -u "$DB_USER" -p "$DB_NAME" > backup_lottus_$(date +%F_%H%M%S).sql   # pide la contraseña; no la escribas en la línea de comandos
```

---

## 2. Instalación de Paquetes en Hostinger VPS (Sin Entorno Virtual)

En tu VPS de Hostinger, instala las dependencias directamente en Python global de la máquina:

```bash
# Actualizar el sistema e instalar dependencias
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3-pip git nginx certbot python3-certbot-nginx libmysqlclient-dev

# Instalar los paquetes del proyecto directamente
cd /var/www/backend  # O la ruta donde tengas clonado el repositorio en Hostinger VPS
pip3 install -r requirements.txt
```

---

## 3. Ejecución Directa de Migraciones en Producción

Con los accesos configurados en el `.env` del servidor (nunca en `settings.py` ni en este repositorio).
Desde la auditoría 2026-10-02 (H16) `DB_NAME`, `DB_USER` y `DB_PASSWORD` son **obligatorios** cuando hay `DB_HOST`:
`DJANGO_DEBUG` ya no elige la base. Las variables definidas en el proceso (systemd, shell) prevalecen sobre `.env`.
Verifica antes de reiniciar: `python3 manage.py check` debe terminar sin error.

```bash
cd /var/www/backend

# 1. Comprobar las migraciones registradas
python3 manage.py showmigrations

# 2. Aplicar las migraciones versionadas (nunca ejecutar makemigrations en el servidor:
#    las migraciones se crean y prueban en desarrollo y llegan por git)
python3 manage.py migrate

# 3. Recolectar archivos estáticos
python3 manage.py collectstatic --noinput
```

---

## 4. Configurar Gunicorn en Systemd (Directo con Python3)

Crea el archivo de servicio para Gunicorn:

```bash
sudo nano /etc/systemd/system/gunicorn.service
```

Pega la siguiente configuración:

```ini
[Unit]
Description=Gunicorn daemon for Lottus Backend API (Hostinger VPS)
After=network.target

[Service]
User=root
WorkingDirectory=/var/www/backend
ExecStart=/usr/local/bin/gunicorn --workers 3 --bind 127.0.0.1:8000 lottusPedidos.wsgi:application
Restart=always

[Install]
WantedBy=multi-user.target
```

*Pendiente (P01-03): ejecutar con un usuario de servicio sin privilegios en vez de `root`.*

*Nota: Si `gunicorn` fue instalado en `/usr/bin/gunicorn`, ajusta el `ExecStart` ejecutando previamente `which gunicorn`.*

Reinicia el servicio:

```bash
sudo systemctl daemon-reload
sudo systemctl restart gunicorn
sudo systemctl enable gunicorn
```

---

## 5. Nginx & Certificado SSL (HTTPS)

Asegúrate de que Nginx redirija las peticiones a `api.muebleslottus.com` y activa el certificado SSL:

```bash
sudo certbot --nginx -d api.muebleslottus.com
```
