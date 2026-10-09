# CAUNE · Caja de Ahorro Unión y Esfuerzo

<img src="static/img/logo-caune-192.png" alt="Sello de CAUNE" width="120">

Sistema de gestión administrativa y financiera

Aplicación web en Django 5.2 + PostgreSQL 16 para administrar afiliados, aportaciones, depósitos, préstamos,
actividades económicas y distribución de ganancias. **Estado actual: Fase 2 (préstamos y actividades económicas).**
Ver [docs/FASE1.md](docs/FASE1.md) y [docs/FASE2.md](docs/FASE2.md) para el alcance, las decisiones y los resultados de pruebas.

## Estructura

```
caune/
├── config/              Configuración (settings, urls, formatos L 1,250.00 y DD/MM/AAAA)
├── apps/
│   ├── core/            Auditoría, parámetros, numeración, cajas/cuentas, usuarios y roles, panel
│   ├── afiliados/       Afiliados, cambios de estado, estado de cuenta
│   ├── aportaciones/    Tipos de movimiento, aportaciones/depósitos/retiros, recibos, anulación
│   ├── prestamos/       Préstamos, cuadro de amortización, desembolsos, pagos y abonos
│   ├── actividades/     Actividades económicas, subactividades, ingresos, gastos y resultados
│   └── reportes/        Reportes 1-9 con exportación PDF y Excel
├── templates/           Interfaz (HTML) y plantillas PDF
├── static/css/          Estilos (paleta del sello: azul marino, azul Unión, naranja Esfuerzo, dorado)
├── static/img/          Logo oficial y derivados (favicon, PDF)
├── tests/               Pruebas automatizadas (datos sintéticos)
├── scripts/             Respaldo y restauración de PostgreSQL
├── docs/                Documentación por fase
├── PRODUCT.md, DESIGN.md  Contexto de producto y sistema visual
├── Dockerfile, docker-compose.yml, .env.example
```

La lógica financiera vive en `apps/*/services.py`. Las vistas, los reportes y las pruebas usan esas mismas funciones.

## Desarrollo local (Windows)

> En Windows, cree el entorno virtual en una ruta corta (por ejemplo `C:\caune-venv`). Si la ruta es muy larga,
> Pillow, que se usa para generar los PDF, no carga su DLL.

```bash
python -m venv C:\caune-venv
```
```bash
C:\caune-venv\Scripts\pip install -r requirements.txt
```

Cree un archivo `.env` con `DJANGO_DEBUG=true`. Sin `DATABASE_URL`, el sistema usa SQLite, que solo sirve para desarrollo. Luego:

```bash
C:\caune-venv\Scripts\python manage.py migrate
```
```bash
C:\caune-venv\Scripts\python manage.py inicializar_caune
```
```bash
C:\caune-venv\Scripts\python manage.py createsuperuser
```
```bash
C:\caune-venv\Scripts\python manage.py runserver
```

Datos de demostración **ficticios**, opcionales y solo con `DJANGO_DEBUG=true`:
`python manage.py cargar_demo`. Crea los usuarios `demo.admin`, `demo.tesorero` y `demo.supervisor`; la clave está en
`apps/core/management/commands/cargar_demo.py`. Nunca los cargue en producción: el comando se niega a ejecutarse con
DEBUG desactivado.

## Pruebas

```bash
C:\caune-venv\Scripts\python -m pytest
```

Por defecto corren en SQLite en memoria. Para correrlas contra PostgreSQL (obligatorio antes de producción):

```bash
TEST_DATABASE_URL=postgres://caune:CLAVE@localhost:5432/caune python -m pytest
```

## Producción (Docker + PostgreSQL)

1. Copie `.env.example` como `.env` y complete `DJANGO_SECRET_KEY`, `POSTGRES_PASSWORD`, `DATABASE_URL`,
   `DJANGO_ALLOWED_HOSTS` y `DJANGO_CSRF_TRUSTED_ORIGINS`.
2. `docker compose up -d --build`. Al iniciar se aplican las migraciones y la configuración inicial (es idempotente).
3. Cree el primer administrador: `docker compose exec web python manage.py createsuperuser`. Después, cree los
   usuarios reales desde **Configuración → Usuarios** y asígneles un rol.
4. Publique el puerto 8000 solo detrás de un proxy inverso con HTTPS, como Caddy o nginx.

### Respaldos

- El servicio `respaldo` ejecuta `pg_dump` cada 24 horas en `./respaldos`, verifica que el archivo se pueda leer y
  conserva `RESPALDO_DIAS_RETENCION` días.
- **Copie `./respaldos` fuera del servidor** (otro disco o una nube cifrada).
- Haga una prueba de restauración mensual en una base aparte, sin tocar la base en uso:
  `docker compose run --rm --entrypoint sh respaldo /restaurar.sh /respaldos/<archivo>.dump`

## Roles iniciales

| Rol | Puede |
|---|---|
| Tesorero | **Acceso total**: afiliados, movimientos, recibos, reportes, auditoría, configuración, usuarios y roles |
| Presidente | Consultar el panel financiero, afiliados, estados de cuenta, préstamos, actividades y reportes. No registra ni modifica nada |
| Administrador | Acceso total (soporte técnico) |
| Contador o supervisor | Consultar todo, anular operaciones, auditoría y reportes. No registra movimientos |
| Encargado de préstamos | Registrar préstamos (sin excepciones de tasa), desembolsos y pagos; consultar afiliados y reportes |
| Encargado de actividades | Crear actividades y subactividades, registrar ingresos y gastos, consultar reportes |

> Para anular una operación hace falta una persona distinta a la que la registró (parámetro
> `movimientos.anulacion_requiere_otro_usuario`). Con el tesorero como usuario principal, ese segundo usuario puede ser
> un Administrador o un Contador/supervisor.

Los roles se editan en **Configuración → Roles y permisos**. Todos los permisos se verifican en el servidor.
