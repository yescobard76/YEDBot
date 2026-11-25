# Bucle autónomo de investigación

Automatización para dejar la laptop trabajando sin supervisión. **No toca el bot
vivo**: no modifica `data/config.json`, ni `profiles/*/config.json`, ni la base
SQLite, ni reinicia el 8765. Tampoco lee el holdout.

## Qué hace

1. Evalúa una cola de variantes (una palanca por variante) sobre W1–W6
   (`2025-01-10` → `2026-06-30`, 362 sesiones, CSV `adjusted`).
2. Escribe un resultado por variante en `resultados.jsonl`.
3. Ordena por RDD (neto / drawdown) y deja `resumen_bucle.md`.
4. Combina las mejores palancas y vuelve a medirlas (fase 2).
5. Se queda vigilando hasta que aparezca `STOP`.

El informe consolidado de la misión (viva vs original, ranking, mejoras y
robustez) está en `resumen.md` y `resumen.json`, generados por
`python research/build_autoloop_report.py`. El bucle no los sobrescribe.

## Cómo pararlo

```bash
touch reports/autoloop/STOP
```

Se detiene en el siguiente punto seguro (entre ventana y ventana) y sale sin
tocar nada más. Para reanudar, borra `STOP` y vuelve a lanzar el script.

## Pausa temporal

```bash
touch reports/autoloop/PAUSA      # pausa
rm reports/autoloop/PAUSA         # reanuda
```

## Estado

- `estado.json`: latido con fase, variante y ventana actual.
- `progreso.json`: resultados parciales por ventana; permite reanudar.
- `runner.log`: registro de ejecución.
- `resultados.jsonl`: una línea por variante cerrada.
- `resumen_bucle.md`: ranking crudo del bucle.
- `resumen.md` / `resumen.json`: informe consolidado (no lo toca el bucle).

## Lanzarlo

```bash
python -u research/auto_loop.py
```

El proceso se pone a prioridad IDLE y se detiene solo si la RAM libre baja de
900 MB, para no competir con Freebuff ni con el escritorio.

## Siguiente tanda

La cola se lee de `queue.json` al arrancar. Para añadir hipótesis, edita ese
archivo (id, patch y why) y relanza el script; las variantes ya cerradas se
saltan y solo se simulan las nuevas.

## Límites

Las cifras son in-sample y elegidas sobre la misma muestra: sirven para
priorizar hipótesis, no para promocionar una configuración. Cualquier adopción
requiere forward y decisión explícita.
