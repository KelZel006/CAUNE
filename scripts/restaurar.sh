#!/bin/sh
# Restaura un respaldo en una base NUEVA para probarlo, sin tocar la base en uso, y la compara con la base en uso.
# Uso (desde el servidor):  docker compose run --rm --entrypoint sh respaldo /restaurar.sh /respaldos/caune-AAAAMMDD-HHMMSS.dump
# Termina con error si algún conteo o total no coincide. Si se registraron operaciones después del respaldo, la
# diferencia es esperable: restaure el respaldo más reciente.
set -eu
ARCHIVO="$1"
PRUEBA="caune_prueba_restauracion"
dropdb -h db -U "$POSTGRES_USER" --if-exists "$PRUEBA"
createdb -h db -U "$POSTGRES_USER" "$PRUEBA"
pg_restore -h db -U "$POSTGRES_USER" -d "$PRUEBA" --no-owner "$ARCHIVO"

CONSULTA="
SELECT 'afiliados', count(*)::text FROM afiliados_afiliado
UNION ALL SELECT 'movimientos confirmados', count(*) || ' / ' || coalesce(sum(monto), 0)
  FROM aportaciones_movimientoafiliado WHERE estado = 'CONFIRMADO'
UNION ALL SELECT 'préstamos', count(*) || ' / ' || coalesce(sum(monto_aprobado), 0) FROM prestamos_prestamo
UNION ALL SELECT 'pagos de préstamos', count(*) || ' / ' || coalesce(sum(monto), 0) FROM prestamos_pagoprestamo
UNION ALL SELECT 'movimientos de actividades', count(*) || ' / ' || coalesce(sum(monto), 0)
  FROM actividades_movimientoactividad
UNION ALL SELECT 'movimientos de caja', count(*) || ' / ' || coalesce(sum(monto), 0) FROM caja_movimientocaja
UNION ALL SELECT 'distribuciones', count(*)::text FROM distribucion_distribucion
UNION ALL SELECT 'entregas de ganancias', count(*) || ' / ' || coalesce(sum(monto), 0) FROM distribucion_pagoganancia
UNION ALL SELECT 'registros de auditoría', count(*)::text FROM core_historialauditoria
UNION ALL SELECT 'usuarios', count(*)::text FROM auth_user;"

psql -h db -U "$POSTGRES_USER" -d "$PRUEBA" -At -F ' : ' -c "$CONSULTA" > /tmp/restaurada.txt
psql -h db -U "$POSTGRES_USER" -d "$POSTGRES_DB" -At -F ' : ' -c "$CONSULTA" > /tmp/en_uso.txt
echo "Base restaurada ($PRUEBA):"
cat /tmp/restaurada.txt
if diff /tmp/en_uso.txt /tmp/restaurada.txt > /dev/null; then
  echo "CORRECTO: la base restaurada coincide con la base en uso."
else
  echo "DIFERENCIAS (izquierda: en uso, derecha: restaurada):"
  diff /tmp/en_uso.txt /tmp/restaurada.txt || true
  exit 1
fi
