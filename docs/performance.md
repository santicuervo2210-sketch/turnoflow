# Rendimiento

## Resultados

Antes de la optimizacion inicial, el panel ejecutaba 18 consultas y la produccion tardaba aproximadamente 3,7 segundos por carga autenticada. La eliminacion de N+1 y el cambio de Vercel a `gru1` redujeron la carga caliente de produccion a 0,11-0,31 segundos.

La auditoria final agrega un benchmark reproducible con 500 turnos y 50 clientes:

| Medicion local | Antes de paginar historial | Despues |
| --- | ---: | ---: |
| Mediana | 54,0 ms | 29,2 ms |
| HTML transferido | 696.697 bytes | 144.175 bytes |
| Consultas por request | 10 | 10 |

La reduccion de HTML es de aproximadamente 79%. Los totales de caja e historial siguen usando todos los registros; solo las filas visibles se limitan a la pagina solicitada.

## Repetir la prueba

```bash
python scripts/benchmark_dashboard.py
```

El script crea una base SQLite temporal en memoria, carga 500 turnos y ejecuta cinco solicitudes calientes al panel.
