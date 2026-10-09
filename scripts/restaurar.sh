#!/bin/sh
# Restaura un respaldo en una base NUEVA para probarlo, sin tocar la base en uso.
# Uso (desde el servidor):  docker compose run --rm --entrypoint sh respaldo /restaurar.sh /respaldos/caune-AAAAMMDD-HHMMSS.dump
set -eu
ARCHIVO="$1"
PRUEBA="caune_prueba_restauracion"
dropdb -h db -U "$POSTGRES_USER" --if-exists "$PRUEBA"
createdb -h db -U "$POSTGRES_USER" "$PRUEBA"
pg_restore -h db -U "$POSTGRES_USER" -d "$PRUEBA" --no-owner "$ARCHIVO"
psql -h db -U "$POSTGRES_USER" -d "$PRUEBA" -c "SELECT count(*) AS afiliados FROM afiliados_afiliado;" \
     -c "SELECT count(*) AS movimientos, sum(monto) AS total FROM aportaciones_movimientoafiliado WHERE estado='CONFIRMADO';"
echo "Restauración de prueba completa en la base $PRUEBA. Compare los conteos con la base en uso."
