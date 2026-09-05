# Digimon World (PS1) — Randomizer de Archipelago (proyecto de rescate)

Objetivo: NO empezar de cero. Existe una implementación muy avanzada y
casi jugable (cliente compatible con BizHawk y DuckStation) construida
sobre un decomp parcial comunitario y un randomizer previo. Este
proyecto consiste en DESBLOQUEAR lo que quedó sin resolver, con la
técnica adecuada:

- Localizar las rutinas de las tiendas (inventario/precios) para
  randomizarlas.
- Implementar bloqueo de acceso a regiones por código, desbloqueable
  con items de Archipelago.
- Completar el mapa de memoria pendiente.

Idioma con el usuario: español.

## REGLAS DE ORO — AUTONOMÍA (prioridad máxima)

1. **NUNCA pidas al usuario trabajo técnico manual.** Prohibido
   explícitamente (ya ocurrió y es la razón de este documento): "ve a la
   zona A, muévete a la zona B y hazme capturas de memoria", RAM Search
   manual, snapshots paso a paso para trazar rutinas.
2. **La técnica que sustituye todo eso es el watchpoint.** Para
   encontrar CÓDIGO que toca un dato conocido no se difean snapshots:
   se pone un watchpoint sobre el dato, se provoca el evento UNA vez
   (por script, con savestates), y el emulador entrega el PC exacto de
   la instrucción. Ghidra decompila esa función. Fin.
3. **Lo único que puedes pedir al usuario** (en lote): acceso al repo y
   documentación de su implementación actual; su imagen del juego en
   `roms/` si no está ya; decisiones de diseño; playtests de UNA pasada;
   como máximo UNA sesión de savestates jugando normal por hito.
4. Bloqueado → otra vía automatizada → `docs/BLOCKERS.md` → siguiente
   tarea. Nunca degradar a petición manual.

## BANCO DE TRABAJO: PCSX-Redux (solo para RE)

El cliente del usuario seguirá en BizHawk/DuckStation: PCSX-Redux es tu
laboratorio, no un cambio de emulador. Es un emulador orientado
explícitamente a desarrollo e ingeniería inversa de PS1, con debugger,
**GDB server**, servidor web y **motor Lua**, arrancable con flags de
CLI (`-interpreter -debugger -gdb`, más flags para cargar Lua desde
fichero/cadena). Ghidra (≥10.3) puede conectarse a su GDB server como
debugger vía `gdb-multiarch` — doc oficial:
https://pcsx-redux.consoledev.net/Debugging/ghidra/

Docs generales: https://pcsx-redux.consoledev.net
Repo: https://github.com/grumpycoders/pcsx-redux

## DOCTRINA TÉCNICA aplicada a los bloqueos concretos

- **Tiendas**: el inventario/precios de una tienda vive en algún sitio
  al abrirla. Ruta A (datos→código): encontrar la lista en RAM con
  dump+diff al abrir la tienda, luego watchpoint de LECTURA sobre ella
  → rutina que la consume; xrefs → dónde se define (tabla en disco/EXE).
  Ruta B (efecto→código): watchpoint de ESCRITURA sobre el dinero,
  comprar por script → rutina de compra → subir por el call stack.
- **Bloqueo de regiones**: el ID de mapa/zona actual seguramente ya está
  localizado en el proyecto existente. Watchpoint de ESCRITURA sobre él,
  cruzar una transición por script → función de cambio de zona →
  decompilar → decidir el gate. Dos implementaciones válidas, discutir
  con el usuario: (a) parche en el binario que consulta un flag propio,
  (b) puramente en cliente: el watcher detecta transición a zona
  bloqueada y revierte/teletransporta — funciona sin tocar el juego y
  puede ser el MVP de hoy mismo.
- **Truco de navegación**: comprueba pronto si ESCRIBIR el ID de mapa
  teletransporta de forma estable. Si sí, tienes navegación autónoma
  gratis para todos los experimentos.
- **Dato desconocido**: savestate + dump + evento + dump + diff, con tu
  propio `ram_diff` de filtros encadenados.
- **Anclas gratis**: el mapa de memoria del proyecto existente (primera
  fuente), el decomp parcial comunitario (símbolos → impórtalos a
  Ghidra), trucos publicados (gamehacking.org) y code notes de
  RetroAchievements si el juego tiene set.

## PS1, mapa mental mínimo

- 2 MiB de RAM principal, little-endian, CPU MIPS R3000A.
- La RAM se ve en 0x00000000 / 0x80000000 (KSEG0) / 0xA0000000 (espejos):
  cuidado al traducir direcciones entre PCSX-Redux, BizHawk (dominios) y
  DuckStation — documenta la convención elegida en `docs/TOOLING.md`.
- Referencia de hardware: psx-spx (https://problemkaputt.de/psx-spx.htm).
- Ghidra: investiga el loader de PS1 actual (p. ej. `ghidra_psx_ldr` de
  lab313ru) y aplica firmas de PsyQ: las funciones de librería salen con
  nombre y dejan a la vista el código propio del juego.

## FASE 0 — BOOTSTRAP (lista de setup)

1. Estructura: `roms/ saves/ work/experiments/ docs/ poc/` + `.gitignore`
   (roms, saves, work, .venv).
2. **Inventario antes que nada**: pide al usuario (una sola vez, en
   lote) el repo de su implementación, su mapa de memoria y el enlace al
   decomp parcial y al randomizer previo. Resume el estado en
   `docs/ESTADO_ACTUAL.md`: qué está resuelto, qué falta, direcciones
   conocidas.
3. Investiga versiones actuales e instala: PCSX-Redux (builds
   oficiales), `gdb-multiarch`, Ghidra + loader PS1. Anota en
   `docs/TOOLING.md`.
4. Construye tu harness sobre PCSX-Redux (Lua/CLI/GDB) con capacidades
   verificadas: cargar imagen, savestates, avanzar frames, inputs,
   leer/escribir memoria, volcar regiones, captura, breakpoints y
   watchpoints por GDB.
5. Smoke test: título de Digimon World en captura verificada por ti +
   savestate reproducible.
6. Validación cruzada: reproduce 3–5 direcciones YA conocidas del
   proyecto existente leyéndolas con tu harness (así calibras espejos de
   direcciones y confirmas que todo el stack funciona).

## FASES SIGUIENTES (resumen)

1. Tiendas: rutina localizada, tabla de origen identificada, PoC de
   tienda con inventario modificado.
2. Gates de región: MVP en cliente → si procede, parche en binario.
3. Completar mapa de memoria pendiente del proyecto.
4. Integración en la implementación existente del usuario (respetando
   su arquitectura BizHawk/DuckStation) + playtest de una pasada.

## CONVENCIONES

- `docs/memory_map.md` con estado HIPÓTESIS/VERIFICADO y experimento
  reproducible en `work/experiments/`; direcciones nuevas se aportan de
  vuelta al proyecto del usuario en su formato.
- Al repo público jamás van la imagen del juego, volcados ni assets.
