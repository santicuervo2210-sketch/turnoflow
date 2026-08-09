# Categorias y vocabulario del bot

TurnoFlow usa el mismo flujo de turnos para todos los negocios. El rubro solo define las palabras que ayudan a reconocer un servicio.

## Categorias incluidas

- `general`: corte, barba, unas, pestanas y claritos como compatibilidad inicial.
- `barberia`: corte, barba, afeitado, claritos, mechas y reflejos.
- `unas`: manicura, semipermanente, esculpidas y soft gel.
- `pestanas`: lifting, extensiones y volumen ruso.
- `masajes`: descontracturante, relajante y deportivo.
- `tatuajes`: sesion, retoque y cover up.

Los nombres y precios reales siempre salen de los servicios cargados en el negocio. Los defaults no crean servicios ni inventan precios.

## Configuracion

En `Panel > Configuracion > Bot y vocabulario` se puede:

1. Elegir el rubro del negocio.
2. Personalizar el saludo y el menu inicial.
3. Asociar una frase propia a un servicio, por ejemplo `espalda cargada` a `Masaje descontracturante`.
4. Ocultar una palabra incluida por el rubro.
5. Quitar un alias propio o restaurar un default oculto.

Los alias propios del negocio tienen prioridad. Nunca se consultan alias ni servicios de otro negocio.

## WhatsApp

La configuracion ya es usada por el simulador y por `POST /bot/webhook`. Para WhatsApp real solo falta que el proveedor entregue el mensaje entrante al webhook y envie al cliente los textos de la respuesta.
