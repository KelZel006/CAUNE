#!/bin/sh
# Respaldo comprimido de PostgreSQL. Se ejecuta a diario desde el servicio "respaldo" de docker-compose.
# Copie periódicamente la carpeta ./respaldos FUERA del servidor (otro disco, nube cifrada).
set -eu
FECHA=$(date +%Y%m%d-%H%M%S)
DESTINO="/respaldos/caune-${FECHA}.dump"
pg_dump -h db -U "$POSTGRES_USER" -d "$POSTGRES_DB" --format=custom --file="$DESTINO"
pg_restore --list "$DESTINO" > /dev/null   # verifica que el archivo sea legible
find /respaldos -name 'caune-*.dump' -mtime +"${RESPALDO_DIAS_RETENCION:-30}" -delete
echo "Respaldo creado: $DESTINO"
