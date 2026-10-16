#!/usr/bin/env bash
# Despliegue del backend por commit (P01-03 / P07-04, auditoría 2026-10-02).
#
# Reemplaza a ../deploy_backend_vps.sh de la raíz, que usaba contraseña en texto
# plano (sshpass) y ocultaba fallos de pip/migrate detrás del éxito de `tail`.
#
# Requisitos (se preparan una sola vez; ver docs/auditoria-2026-10-02/operacion.md):
#   * Llave SSH del operador autorizada para DEPLOY_USER (sin contraseña en scripts).
#   * DEPLOY_USER con sudo SIN contraseña limitado a: systemctl restart|is-active gunicorn.
#   * ~/.my.cnf del DEPLOY_USER (modo 600) con las credenciales de respaldo, o
#     LOTTUS_SKIP_BACKUP=1 solo si se acaba de verificar un respaldo externo.
#
# Uso:
#   DEPLOY_HOST=... DEPLOY_USER=... ./scripts/deploy/deploy_backend.sh <commit|rama>
#   DEPLOY_HOST=... DEPLOY_USER=... ./scripts/deploy/deploy_backend.sh --status
#
# Cualquier fallo detiene el despliegue con código distinto de cero. Si la salud
# falla después de reiniciar, el código vuelve al commit anterior; las migraciones
# NO se revierten automáticamente: deben ser compatibles hacia atrás (expansivas).
set -euo pipefail

: "${DEPLOY_HOST:?Define DEPLOY_HOST}"
: "${DEPLOY_USER:?Define DEPLOY_USER}"
REPO_PATH="${REPO_PATH:-/home/$DEPLOY_USER/ordenesPedidoSWBackend}"
BACKUP_DIR="${BACKUP_DIR:-/home/$DEPLOY_USER/backups}"
HEALTH_URL="${HEALTH_URL:-https://$DEPLOY_HOST/api/health/}"
SSH=(ssh -o BatchMode=yes -o StrictHostKeyChecking=yes "$DEPLOY_USER@$DEPLOY_HOST")

remote() {
  # El script remoto corre en su propio bash con errexit+pipefail: un fallo de
  # pip o migrate no puede quedar oculto por un `tail` posterior.
  "${SSH[@]}" "bash -euo pipefail -s" -- "$@"
}

if [ "${1:-}" = "--status" ]; then
  remote "$REPO_PATH" <<'EOS'
cd "$1"
sudo -n systemctl is-active gunicorn
git log --oneline -1
EOS
  exit 0
fi

TARGET="${1:?Indica el commit o la rama a desplegar}"
TARGET_SHA=$(git rev-parse --verify "$TARGET^{commit}")
echo "== Desplegando $TARGET_SHA en $DEPLOY_HOST =="

PREV_SHA=$(remote "$REPO_PATH" <<'EOS'
cd "$1"
git rev-parse HEAD
EOS
)
echo "Commit actual en el servidor: $PREV_SHA"

remote "$REPO_PATH" "$TARGET_SHA" "$BACKUP_DIR" "${LOTTUS_SKIP_BACKUP:-0}" <<'EOS'
REPO="$1"; SHA="$2"; BACKUP_DIR="$3"; SKIP_BACKUP="$4"
cd "$REPO"
if [ -n "$(git status --porcelain --untracked-files=no)" ]; then
  echo "El árbol del servidor tiene cambios locales; revisar antes de desplegar." >&2
  exit 10
fi
git fetch --quiet origin
git checkout --quiet --detach "$SHA"

if [ "$SKIP_BACKUP" != "1" ]; then
  mkdir -p "$BACKUP_DIR"; chmod 700 "$BACKUP_DIR"
  set -a; . ./.env; set +a
  FILE="$BACKUP_DIR/pre_${SHA:0:8}_$(date +%F_%H%M%S).sql.gz"
  # Credenciales desde ~/.my.cnf (no aparecen en la línea de comandos ni en ps).
  mysqldump --single-transaction --routines -h "$DB_HOST" "$DB_NAME" | gzip > "$FILE"
  gzip -t "$FILE"
  echo "Respaldo verificado: $FILE"
fi

./venv/bin/pip install --quiet -r requirements.txt
./venv/bin/python manage.py check --deploy --fail-level ERROR
./venv/bin/python manage.py migrate --noinput
./venv/bin/python manage.py collectstatic --noinput --verbosity 0
sudo -n systemctl restart gunicorn
sleep 2
sudo -n systemctl is-active gunicorn
EOS

echo "== Verificando salud: $HEALTH_URL =="
ok=0
for _ in 1 2 3 4 5; do
  body=$(curl -fsS --max-time 10 "$HEALTH_URL" || true)
  if printf '%s' "$body" | grep -q '"status": *"ok"'; then ok=1; break; fi
  sleep 3
done

if [ "$ok" != 1 ]; then
  echo "La salud falló; volviendo el código a $PREV_SHA (las migraciones aplicadas se conservan)." >&2
  remote "$REPO_PATH" "$PREV_SHA" <<'EOS'
cd "$1"
git checkout --quiet --detach "$2"
sudo -n systemctl restart gunicorn
EOS
  exit 20
fi
echo "Despliegue de $TARGET_SHA verificado."
