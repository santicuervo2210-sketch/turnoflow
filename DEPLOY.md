# Deploy demo de TurnoFlow

Esta guia deja el proyecto listo para conectar un servidor con PostgreSQL.

## Costos aproximados

Precios revisados el 31 de julio de 2026. Pueden cambiar.

### Opcion recomendada para demo rapida: Railway

- Trial: USD 0 con USD 5 de creditos por 30 dias.
- Hobby: USD 5/mes minimo, incluye USD 5 de uso.
- Si el consumo supera esos USD 5, se paga la diferencia.

Para una demo chica de TurnoFlow, lo esperable es arrancar alrededor de USD 5/mes si el uso es bajo.

### Opcion simple con capa gratuita: Render

- Web service free: USD 0, pero duerme tras 15 minutos sin trafico y puede tardar alrededor de 1 minuto en despertar.
- Postgres free: USD 0 con limites y expiracion; sirve para probar, no para produccion.
- Para demo mas seria, conviene pasar a planes pagos cuando no quieras que duerma ni perder datos.

### Opcion mas tecnica: Fly.io

- Uso por recursos.
- Una maquina chica puede arrancar en pocos dolares mensuales, pero con base de datos y almacenamiento el costo suele ser menos predecible.

## Variables de entorno necesarias

```text
APP_NAME=TurnoFlow
ENVIRONMENT=production
DATABASE_URL=postgres://...
AUTO_CREATE_TABLES=false
AUTH_ENABLED=true
ADMIN_USERNAME=admin
ADMIN_PASSWORD=usar-una-clave-real
SESSION_SECRET=usar-un-texto-largo-aleatorio
BOT_WEBHOOK_SECRET=usar-un-secreto-aleatorio-de-32-caracteres-o-mas
BOT_AI_PROVIDER=rules
ERROR_ALERT_WEBHOOK_URL=
LOGIN_RATE_LIMIT_PER_MINUTE=30
BOT_WEBHOOK_RATE_LIMIT_PER_MINUTE=120
```

Notas:

- `DATABASE_URL` puede venir como `postgres://`, `postgresql://` o `postgresql+psycopg://`.
- La app lo normaliza internamente para SQLAlchemy.
- No uses SQLite en deploy.
- No actives `AUTO_CREATE_TABLES` en produccion; usa Alembic.
- `SESSION_SECRET` debe tener minimo 32 caracteres y no debe compartirse.
- `ERROR_ALERT_WEBHOOK_URL` es opcional. Si lo configuras con un webhook HTTPS de un servicio externo, TurnoFlow enviara una alerta breve cuando ocurra un error 500. No se envian cookies, body, telefono ni query string; solo ambiente, metodo, path y tipo de excepcion.
- `LOGIN_RATE_LIMIT_PER_MINUTE` y `BOT_WEBHOOK_RATE_LIMIT_PER_MINUTE` deben ser mayores a 0.

## Comandos de build y arranque

Build:

```bash
pip install -e .
```

Migraciones:

```bash
python -m alembic upgrade head
```

Confirmar revision aplicada:

```bash
python -m alembic current
```

La revision esperada para esta version es `20260809_0010`. En Postgres tambien debe existir el constraint `ex_appointments_no_active_overlap`, creado por la migracion `20260801_0007`.

Crear tu usuario owner inicial:

```bash
python -m app.create_owner
```

Chequeo antes de exponer la demo:

```bash
python -m app.check_production
```

Este chequeo valida configuracion sensible, conexion a Postgres, revision Alembic, constraint anti doble-reserva y existencia del usuario owner.

Start:

```bash
uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

El `Procfile` ya contiene un comando compatible con hosts que leen Procfile.

## Pasos en Railway

1. Crear proyecto nuevo.
2. Conectar el repo desde GitHub.
3. Agregar un servicio PostgreSQL.
4. Copiar la variable `DATABASE_URL` del PostgreSQL al servicio web si Railway no la inyecta automaticamente.
5. Cargar las variables de entorno anteriores.
6. Configurar comando de start si no detecta el `Procfile`.
7. Ejecutar `python -m alembic upgrade head`.
8. Ejecutar `python -m app.create_owner`.
9. Ejecutar `python -m app.check_production`.
10. Abrir la URL publica y entrar con `ADMIN_USERNAME` / `ADMIN_PASSWORD`.

## Pasos en Render

1. Crear una base Render Postgres.
2. Crear un Web Service conectado al repo.
3. Build command: `pip install -e .`.
4. Start command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`.
5. Cargar variables de entorno.
6. Ejecutar migraciones con `python -m alembic upgrade head`.
7. Ejecutar `python -m app.create_owner`.
8. Ejecutar `python -m app.check_production`.

## Supabase usado para esta demo

TurnoFlow quedo conectado a Supabase como PostgreSQL gestionado, sin usar todavia Supabase Auth ni Storage.

- Proyecto: `turnoflow-prod`.
- Project ref: `fyyycgvjqfitvpalwvkn`.
- Region: `sa-east-1`.
- Dashboard: `https://supabase.com/dashboard/project/fyyycgvjqfitvpalwvkn`.
- Estado verificado por CLI: `ACTIVE_HEALTHY`.
- Revision Alembic aplicada: `20260809_0010`.

La variable `DATABASE_URL` local esta en `.env` y apunta a la conexion directa:

```text
postgresql://postgres:...@db.fyyycgvjqfitvpalwvkn.supabase.co:5432/postgres
```

Supabase indica que la conexion directa es ideal para servidores persistentes, pero usa IPv6 salvo que el proyecto tenga add-on IPv4. Si el proveedor de deploy no soporta IPv6, usar el pooler de sesion desde el panel `Connect`.

## Pasos en Vercel

Esta opcion sirve para publicar la demo rapido. Vercel corre FastAPI como funciones serverless de Python, por eso el repo incluye:

- `api/index.py`: expone `app.main.app`.
- `vercel.json`: envia todas las rutas a `api/index.py` y ejecuta las funciones en `gru1`, cerca de la base de datos de Sao Paulo.
- `requirements.txt`: dependencias que Vercel instala en build.

Variables obligatorias en Vercel:

```text
APP_NAME=TurnoFlow
ENVIRONMENT=production
DATABASE_URL=postgresql://...
AUTO_CREATE_TABLES=false
AUTH_ENABLED=true
ADMIN_USERNAME=admin
ADMIN_PASSWORD=usar-la-clave-real
SESSION_SECRET=usar-el-secret-real
BOT_WEBHOOK_SECRET=usar-otra-clave-larga-para-el-webhook
BOT_AI_PROVIDER=rules
ERROR_ALERT_WEBHOOK_URL=
LOGIN_RATE_LIMIT_PER_MINUTE=30
BOT_WEBHOOK_RATE_LIMIT_PER_MINUTE=120
```

Notas:

- No uses SQLite en Vercel.
- Cada negocio nuevo recibe 15 dias de prueba. Desde Owner se puede extender la prueba, suspender el acceso o marcarlo como pago/activo.
- El bot por reglas y el webhook pueden responder cuando alguien escribe.
- Los flujos con contexto en memoria pueden reiniciarse entre invocaciones serverless; para demo alcanza, pero para WhatsApp productivo conviene persistir el estado del bot en base de datos o usar un backend persistente.
- Las migraciones Alembic ya fueron aplicadas en Supabase; si se agregan nuevas migraciones, correrlas antes de redeployar.

## Pasos en InsForge

Estado actual de los proyectos creados desde CLI:

- Proyecto original: `TurnoFlow`.
  - Region: `us-east`.
  - ID: `5d12b4b2-2854-4ada-9515-f7ddbabd2b37`.
  - Dashboard: `https://insforge.dev/dashboard/project/5d12b4b2-2854-4ada-9515-f7ddbabd2b37`.
- Proyecto de reintento: `TurnoFlow-Prod`.
  - Region: `us-east`.
  - ID: `0b443332-3040-417d-ab98-d2831c980747`.
  - Dashboard: `https://insforge.dev/dashboard/project/0b443332-3040-417d-ab98-d2831c980747`.

Nota del 1 de agosto de 2026: ambos proyectos figuraban `active`, pero `metadata` y `db query "SELECT 1"` devolvian `OSS request failed: 503`, con `service_version`, `postgres_version` y `postgrest_version` en `null`. Se reporto a InsForge con feedback ID `af82a8cd-bd37-4b28-a465-ff5236c639b4`.

InsForge puede usarse como PostgreSQL gestionado para TurnoFlow porque el sistema usa SQLAlchemy + Alembic contra una URL Postgres estandar.

Cuando el backend del proyecto responda correctamente:

```bash
npx @insforge/cli db query "SELECT 1 AS ok;" --json
```

Despues, obtener o configurar `DATABASE_URL` para el servidor FastAPI y ejecutar:

```bash
DATABASE_URL=postgresql+psycopg://... ENVIRONMENT=production AUTO_CREATE_TABLES=false AUTH_ENABLED=true python -m alembic upgrade head
DATABASE_URL=postgresql+psycopg://... ENVIRONMENT=production AUTO_CREATE_TABLES=false AUTH_ENABLED=true python -m app.create_owner
DATABASE_URL=postgresql+psycopg://... ENVIRONMENT=production AUTO_CREATE_TABLES=false AUTH_ENABLED=true python -m app.check_production
```

Para desplegar el servidor FastAPI en InsForge compute, este repo incluye `Dockerfile`. La CLI documenta dos caminos:

```bash
npx @insforge/cli compute deploy . --name turnoflow-api
```

o con una imagen ya publicada:

```bash
npx @insforge/cli compute deploy --image ghcr.io/USUARIO/turnoflow:TAG --name turnoflow-api
```

Antes de usarlo con clientes reales, confirmar desde el dashboard que el plan elegido mantiene el compute activo y que la base no se pausa por inactividad.

## Checklist antes de pasar el link

- [ ] `AUTH_ENABLED=true`.
- [ ] `AUTO_CREATE_TABLES=false`.
- [ ] `DATABASE_URL` apunta a PostgreSQL, no SQLite.
- [ ] `ADMIN_PASSWORD` no usa valor de ejemplo.
- [ ] `SESSION_SECRET` tiene al menos 32 caracteres aleatorios.
- [ ] `BOT_WEBHOOK_SECRET` tiene al menos 32 caracteres aleatorios y se envia en `X-TurnoFlow-Webhook-Secret`.
- [ ] `LOGIN_RATE_LIMIT_PER_MINUTE` y `BOT_WEBHOOK_RATE_LIMIT_PER_MINUTE` configurados.
- [ ] `python -m alembic upgrade head` ejecutado.
- [ ] `python -m alembic current` muestra `20260809_0010`.
- [ ] `python -m app.create_owner` ejecutado.
- [ ] `python -m app.check_production` devuelve OK.
- [ ] Datos demo o datos reales iniciales cargados.
- [ ] Saludo inicial configurado por negocio.
- [ ] Probado desde celular real.
- [ ] Probado crear, cancelar, reprogramar, cobrar turno y registrar insumo.
- [ ] Probado webhook local `POST /bot/webhook` con el numero del negocio.
- [ ] Backup generado y restore probado en base separada.

## Restore de backup de prueba

Antes de cobrarle a un cliente real, hace una restauracion de prueba. No alcanza con "tener backup"; hay que comprobar que vuelve.

Ejemplo con `pg_dump`/`pg_restore`:

```bash
pg_dump "$DATABASE_URL" --format=custom --file=turnoflow_backup.dump
createdb turnoflow_restore_test
pg_restore --dbname=turnoflow_restore_test --clean --if-exists turnoflow_backup.dump
DATABASE_URL=postgresql+psycopg://USER:PASS@HOST:5432/turnoflow_restore_test python -m app.check_production
```

Si tu proveedor tiene backups automaticos, usa su panel para restaurar en una base nueva de prueba y despues corre:

```bash
DATABASE_URL=postgresql+psycopg://...restore_test python -m alembic current
DATABASE_URL=postgresql+psycopg://...restore_test python -m app.check_production
```

No uses la base de produccion para ensayar restore.
