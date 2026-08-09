# Escalabilidad de TurnoFlow

TurnoFlow mantiene una arquitectura multi-tenant: una aplicacion y una base PostgreSQL, con cada dato asociado a un `barber_shop_id`. Agregar clientes no requiere desplegar una copia del sistema por salon.

## Protecciones incluidas

- Vercel usa `DATABASE_POOL_MODE=serverless`: las funciones no conservan pools locales y se conectan mediante el pooler de PostgreSQL.
- Las reservas activas se protegen contra superposiciones con un constraint PostgreSQL.
- El webhook acepta `message_id` y procesa una sola vez cada evento por negocio.
- El rate limit se comparte en PostgreSQL, ocupa una fila por clave y esta aislado por negocio/remitente.
- Estados del bot, recibos del webhook y limitadores vencidos se limpian diariamente.
- Agenda pagina el historial en SQL; sus totales se calculan en la base y las listas operativas quedan acotadas.
- Cada solicitud genera `X-Request-ID`, tiempo de respuesta y log JSON sin cuerpos ni datos sensibles.

## Hitos de capacidad

Estos numeros son hitos de operacion, no garantias sin una prueba con trafico representativo.

| Salones | Infraestructura minima recomendada | Validacion antes de avanzar |
| --- | --- | --- |
| 10 | Vercel + PostgreSQL administrado con pooler | Backup restaurado, p95 menor a 1 s y error menor a 1% |
| 50 | Planes pagos, alertas y backups con retencion | Prueba sobre Agenda y webhook con concurrencia pico real |
| 100 | Base con metricas, PITR y presupuesto de conexiones revisado | Revisar consultas lentas, CPU, I/O, conexiones y crecimiento mensual |
| 1.000 | Procesamiento asincronico para mensajes/recordatorios y workers separados | Prueba de carga sostenida, cola con reintentos y guardia operativa |
| 10.000 | Capacidad dedicada, replicas/particionado segun mediciones y equipo de operacion | Ensayo de fallos, recuperacion regional y objetivos formales de disponibilidad |

## Prueba reproducible

Smoke inicial contra salud:

```powershell
python -m app.load_smoke --url https://turnoflow-five.vercel.app/health --requests 200 --concurrency 20
```

Para declarar un nuevo hito se necesita probar tambien login, Agenda, alta de turno y webhook con datos sinteticos aislados. La prueba debe ejecutarse fuera del equipo servidor y registrar p50, p95, p99, errores, conexiones, CPU e I/O de PostgreSQL.

## Indicadores de migracion

- Migrar de funciones serverless a contenedores persistentes cuando los cold starts o la duracion de procesos afecten el p95. Cambiar entonces `DATABASE_POOL_MODE=persistent`.
- Agregar una cola antes de enviar recordatorios masivos o procesar trabajo fuera de la respuesta del webhook.
- Evaluar particionado por fecha o negocio solo cuando las metricas y `EXPLAIN ANALYZE` muestren que los indices actuales no alcanzan.
- Nunca promocionar un limite de clientes basandose solo en el numero de filas: manda la concurrencia pico, la frecuencia de mensajes y el SLA contratado.
