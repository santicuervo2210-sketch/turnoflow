# TurnoFlow

TurnoFlow es un MVP educativo y comercial para gestionar reservas de turnos en barberias, unas, pestanas y servicios de belleza.

## Objetivo de esta etapa

La etapa actual crea un MVP funcional:

- Aplicacion FastAPI.
- Endpoint `/health` para comprobar que el servidor responde.
- Configuracion inicial con Pydantic Settings.
- Configuracion inicial de base de datos con SQLAlchemy.
- Alembic preparado para migraciones.
- Modelos iniciales del negocio.
- API JSON para gestion y reservas.
- Panel HTML simple.
- Simulador de bot sin IA ni WhatsApp.
- Motor conversacional basico por reglas para probar servicios, horarios y reservas.
- Modo IA local opcional compatible con Ollama.
- Gestion manual de estados de turno: pendiente, confirmado, cancelado, completado y ausente.
- Marca manual de pago por turno.
- Registro simple de insumos vendidos.
- Control SaaS basico por barberia: active/suspended.
- Bloqueo de disponibilidad, turnos y ventas cuando una barberia esta suspendida.
- Diseno general mas pulido con CSS propio.
- Login configurable por variables de entorno para proteger la demo online.
- Panel de gestion sin chatbot visible; el negocio solo configura el saludo inicial.
- Primer test automatico con Pytest.

Todavia no incluye WhatsApp, procesamiento real de pagos, facturacion ni deploy productivo completo.
El bot se construira sobre la misma logica de turnos que use el panel de gestion.
La interpretacion con IA local es opcional mediante Ollama; el flujo principal funciona por reglas y botones guiados.

## Variables importantes para deploy demo

```text
ENVIRONMENT=production
DATABASE_URL=postgresql+psycopg://...
AUTO_CREATE_TABLES=false
AUTH_ENABLED=true
ADMIN_USERNAME=...
ADMIN_PASSWORD=...
SESSION_SECRET=...
BOT_AI_PROVIDER=rules
```

`SESSION_SECRET` debe ser un texto largo y aleatorio. No uses los valores de ejemplo en internet.

## Comandos utiles

Crear el entorno virtual:

```powershell
& 'C:\Users\santi\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m venv .venv
```

Instalar dependencias:

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

Ejecutar tests:

```powershell
.\.venv\Scripts\python.exe -m pytest
```

Verificar historial de migraciones:

```powershell
.\.venv\Scripts\python.exe -m alembic history
```

Verificar configuracion de produccion:

```powershell
.\.venv\Scripts\python.exe -m app.check_production
```

Levantar el servidor local:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

Ejecutar migraciones en deploy:

```powershell
.\.venv\Scripts\python.exe -m alembic upgrade head
```

Crear usuario owner inicial:

```powershell
.\.venv\Scripts\python.exe -m app.create_owner
```

Luego abrir:

```text
http://127.0.0.1:8000/admin
http://127.0.0.1:8000/bot-simulator
http://127.0.0.1:8000/docs
```

Cargar datos de demo:

```powershell
.\.venv\Scripts\python.exe -m app.seed_demo
```

Para conectar un servidor, ver [DEPLOY.md](DEPLOY.md).
