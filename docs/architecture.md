# Arquitectura operativa de TurnoFlow

## Una sola fuente de verdad

El panel HTML y el bot son dos entradas distintas al mismo dominio:

- Crear: `create_appointment(...)`.
- Reprogramar: `reschedule_appointment(...)`.
- Cancelar: `cancel_appointment(...)`.
- Disponibilidad: `get_available_slots(...)`.

El panel obtiene los datos desde formularios. El bot los obtiene desde una conversacion. Ninguno reimplementa reglas de horarios, servicios compatibles, bloqueos, superposiciones o acceso comercial.

## Persistencia

Los turnos, clientes, servicios, profesionales y configuraciones se guardan inmediatamente en PostgreSQL. El contexto incompleto de una conversacion tambien se persiste en `bot_conversation_states`, identificado por negocio y telefono. Esto permite que una conversacion continue aunque Vercel atienda el siguiente mensaje desde otra instancia.

El rate limiting usa `rate_limit_events` en PostgreSQL. No depende de la memoria temporal de una funcion serverless.

## Aislamiento multi-tenant

Cada recurso operativo pertenece a un `barber_shop_id`. Las rutas del panel validan el negocio permitido y el bot recibe el negocio resuelto por el numero receptor. Los alias personalizados tambien incluyen `barber_shop_id`.

## Caminos de carga

- Manual: una persona crea o modifica un turno desde Agenda.
- Bot: el cliente escribe, el bot identifica servicio, fecha y horario, y llama al mismo servicio de dominio.

El resultado final tiene la misma estructura y las mismas validaciones en ambos caminos.
