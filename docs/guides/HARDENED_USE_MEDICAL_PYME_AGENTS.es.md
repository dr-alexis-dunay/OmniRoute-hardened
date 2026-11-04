---
title: "Hardened OmniRoute: medical use, Chilean SMEs and coordinated agents"
version: 3.8.53
lastUpdated: 2026-11-04
---

# OmniRoute endurecido: uso médico, PYMES en Chile y agentes coordinados

> Guía operativa derivada de una auditoría local (noviembre de 2026). No es asesoría legal ni clínica.
> Cada afirmación lleva su nivel de verificación. Lo no verificado figura como **PENDIENTE DE VERIFICACIÓN**.

## 0. Qué cambia en esta rama (`hardening-audit`)

| Cambio | Antes | Ahora | Verificación |
|---|---|---|---|
| Interfaz de escucha del CLI | `0.0.0.0` | `127.0.0.1` (usar `OMNIROUTE_SERVER_HOST=0.0.0.0` para abrir la red) | Prueba unitaria + ejecución en sandbox |
| `REQUIRE_API_KEY` | `false` | `true` (código y `.env.example`) | Prueba unitaria |
| `INITIAL_PASSWORD` | `CHANGEME` público | Aleatoria al crear `.env` | Prueba unitaria |
| Permisos del `.env` raíz | 664 | 600 | Prueba unitaria |
| Cuerpos de prompts/respuestas en `call_logs` | Guardados siempre | **No se guardan** salvo `OMNIROUTE_CALL_LOG_BODIES=true` | Prueba unitaria **y servidor compilado** (con la opción: 1 archivo con el prompt; por defecto: 0; clave `noLog`: 0) |
| Fallo al cifrar | Guarda en texto plano | Lanza error (falla cerrado) | Revisión de código |
| `OMNIROUTE_REQUIRE_ENCRYPTION=true` | no existía | Rechaza guardar credenciales sin clave | Prueba unitaria |
| Retardo fijo por solicitud | 350 ms | 0 (variable `OMNIROUTE_MIN_TIME_BETWEEN_REQUESTS_MS`) | Medido: mediana 350 ms → 28 ms (servidor simulado) |
| SSRF por DNS (`block-metadata`) | Solo miraba el nombre literal | Resuelve el nombre y bloquea 169.254.0.0/16 | Prueba unitaria con control negativo (falla sin el parche) |
| CSRF con sujeto anónimo | Sin comprobación de `Origin` | Se comprueba si la petición trae `Origin` | Servidor compilado con `requireLogin=false`: sin `Origin` 201, `Origin` propio 201, `Origin` cruzado **403**. Sin comparación contra una compilación del código original |
| `NO_LOG_API_KEY_IDS` | Se perdía al cargar la clave (`setNoLog(id,false)` borraba el id) | Ids de la variable en un conjunto inmutable | Servidor compilado: sin la variable 1 archivo con el prompt, con la variable 0 (también en la 2.ª solicitud). Prueba de regresión con control negativo |
| `requireLogin=false` | Acceso anónimo a cualquier par de red (LAN, Docker, CGNAT) | Solo loopback; `OMNIROUTE_ALLOW_ANONYMOUS_NON_LOOPBACK=true` restaura lo anterior | Servidor compilado (datos nuevos): loopback 200, 192.168.1.50 → 401; con la opción ambos 200. Prueba con control negativo |
| MITM (CA raíz del sistema, `/etc/hosts`, sudo) | Disponible | Desactivado salvo `OMNIROUTE_ENABLE_MITM=true` (parar/limpiar sigue disponible) | Servidor compilado: `403 MITM_DISABLED`; prueba unitaria |
| `docker-compose.ollama-local.yml` | Publicaba en `0.0.0.0` | `127.0.0.1` | Prueba de contrato existente |

Lo que **no** se corrigió: ver la sección 5.

## 1. Uso en el área médica

**Principio:** OmniRoute es un enrutador. Todo lo que le envíes se reenvía al proveedor elegido. Si el
proveedor es un servicio en la nube, el dato sale de tu equipo.

1. **No enviar datos identificables de pacientes a proveedores en la nube** (nombre, RUT, fechas exactas,
   direcciones, imágenes con rostro, números de ficha). La depuración por expresiones regulares del
   orquestador (`--scrub`) solo quita RUT, correos y teléfonos; **no es desidentificación**.
2. **Preferir modelos locales** (Ollama aparece como proveedor de primera clase en el README): el texto
   no sale de la máquina. Requiere hardware adecuado y validar la calidad del modelo; **no evaluado aquí**.
3. Dejar la **compresión de tokens desactivada** (es el valor por defecto). Caveman elimina calificadores
   como "somewhat/a bit" y no protege números, unidades ni negaciones (según un revisor de código sobre
   `open-sse/services/compression/*`; no lo reverifiqué personalmente).
4. Registro: con esta rama los cuerpos no se guardan por defecto. Si necesitas auditar, activa
   `OMNIROUTE_CALL_LOG_BODIES=true` **solo** en entornos sin datos clínicos. Para una clave concreta,
   crear la API key con `{"noLog": true}` (comportamiento verificado en sandbox: 0 copias del prompt en disco).
5. Ejecutar en un equipo propio, con cifrado de disco, solo en loopback, con clave de API obligatoria.
6. Salida clínica: las respuestas de un LLM **no sustituyen el juicio clínico**. Exigir fuentes
   verificables (PMID/DOI) y comprobarlas en PubMed antes de usarlas. Esta guía no evalúa eficacia clínica
   de ningún modelo (**EVIDENCIA NO REVISADA** en esta auditoría).

### Marco normativo chileno (fuentes SECUNDARIAS; no se pudo abrir bcn.cl ni leychile.cl)

| Tema | Lo reportado | Estado de verificación |
|---|---|---|
| Ley 21.719 (datos personales) | Publicada 13-12-2024; vigencia según su art. 1° transitorio: 1-12-2026. A la fecha de consulta (2026-11-04) aún no vigente. Hay un proyecto para postergarla a 1-12-2027, sin evidencia de aprobación | Secundaria (diarioconstitucional.cl, 12-06-2026). Datos de salud, transferencias internacionales y sanciones: **PENDIENTE DE VERIFICACIÓN** |
| Ley 19.628 | Rige hasta que entre en vigor la 21.719 | **PENDIENTE DE VERIFICACIÓN** en texto |
| Ley 20.584, arts. 12–13 | La ficha clínica contiene datos sensibles, reserva frente a terceros y conservación mínima de 15 años | Secundaria; numeración de incisos **a confirmar en BCN** (https://www.bcn.cl/leychile/navegar?i=1046753 — no abierta) |
| Ley 21.663 (ciberseguridad) | Alcanza a servicios esenciales y operadores de importancia vital; la atención de salud figuraría entre los esenciales | Secundaria; si aplica a una consulta individual o PYME: **PENDIENTE DE VERIFICACIÓN** |
| Software/IA como dispositivo médico | D.S. 825/1998; el Decreto Exento 25 (2026) incluyó dos tipos de SaMD de imágenes oncológicas. No se encontró norma específica de IA clínica | Secundaria; "no encontrada" **no equivale** a "no existe" |
| Proyecto de ley de IA (boletín 16821-19) | Sin evidencia de que sea ley; las fuentes discrepan sobre su trámite | Secundaria, discrepante |
| Código de Ética del Colegio Médico (2021) | Contiene título de secreto profesional; no se halló referencia específica a IA | PDF oficial no abierto: https://www.colegiomedico.cl/wp-content/uploads/2022/04/codigo-de-etica_FINAL-2021.pdf |

**Acción pendiente (tuya):** abrir con tu acceso las URL de BCN/Diario Oficial y confirmar el texto vigente antes
de decidir. Consultar a un abogado especialista en datos de salud.

## 2. Uso en PYMES chilenas

OmniRoute aporta infraestructura, no procesos de negocio:

- **Una API key por área o empleado**, con modelos y cuotas distintos (control de costos y trazabilidad).
- **Enrutamiento por costo** (`auto/thrifty`, `cost-optimized`) y cuota gratuita para tareas de bajo riesgo.
- **Un solo punto** para herramientas de marketing, soporte y análisis.

Casos de uso con un orquestador (sección 3): plan comercial, análisis de competencia, borradores de
propuestas, guiones de atención al cliente, revisión de contratos como **borrador a validar por una
persona**, conciliación y resúmenes de ventas con datos agregados.

Reglas mínimas:
1. No cargar datos personales de clientes (RUT, correos) salvo base legal y proveedor evaluado; revisar la
   Ley 21.719 cuando entre en vigor (ver tabla).
2. Todo texto con consecuencias legales, tributarias o de salud lo aprueba una persona.
3. Facturación electrónica, SII y obligaciones laborales: **no evaluados aquí**; no hay integración verificada.
4. Límite de gasto: los proveedores de pago cobran por token; fijar cuotas por clave.

## 3. Agentes coordinados

OmniRoute ya trae piezas: combos `fusion` (panel + juez) y `pipeline`, servidor A2A, 110 herramientas MCP,
memoria y *skills*. Para un flujo propio hay un orquestador mínimo y auditable:

```bash
export OMNIROUTE_API_KEY=<tu-clave>      # nunca por argumento
python3 examples/multi-agent/orchestrator.py \
  --goal "Plan comercial 90 días para una pastelería en Temuco" \
  --base-url http://127.0.0.1:20128/v1 --model auto \
  --require-approval --max-calls 30 --trace /tmp/traza.jsonl
```

Patrón: **planificador → trabajadores en paralelo por nivel de dependencia → crítico (hasta N revisiones) →
sintetizador**. Controles: presupuesto duro de llamadas, tiempo de espera, aprobación humana del plan,
traza solo con metadatos, depuración opcional de RUT/correo/teléfono.

Pruebas: `python3 -I examples/multi-agent/test_orchestrator.py` (12/12 contra un servidor simulado).
**Límite:** se probó el control de flujo, no la calidad de las respuestas de modelos reales.

Para tareas largas con herramientas reales (ejecutar código, escribir archivos) añade aislamiento
(contenedor, usuario sin privilegios, sin red) y aprobación humana por acción.

## 4. Configuración recomendada

Ver `omniroute-hardened.env`. Mínimo: `OMNIROUTE_SERVER_HOST=127.0.0.1`, `REQUIRE_API_KEY=true`,
contraseña propia, `STORAGE_ENCRYPTION_KEY`, `OMNIROUTE_REQUIRE_ENCRYPTION=true`,
`OMNIROUTE_CALL_LOG_BODIES` sin definir.

## 5. Riesgos que siguen abiertos

- **Cobertura de pruebas parcial.** Se ejecutaron 1737 de 7777 archivos de prueba (613 elegidos por tocar lo
  modificado, 524 importadores directos de los módulos cambiados y 600 al azar del resto). Quedan ~6000 sin ejecutar;
  una ejecución completa no fue viable en este equipo. Fallan 15 archivos distintos, todos ya presentes en el código original
  (entorno de sandbox, interfaz y red); ninguno es nuevo.
- **Vulnerabilidades de dependencias:** producción 0; 69 en herramientas de desarrollo (11 altas: promptfoo, extract-zip,
  basic-ftp, etc.). `npm audit fix` no puede resolverlas sin forzar (conflictos ERESOLVE) y exigiría subidas mayores.
  No afectan al servidor empaquetado, pero sí a quien desarrolle o ejecute esas herramientas.
- **Con `requireLogin=false` y acceso desde loopback**, cualquier proceso local (o una página web que logre
  una petición sin `Origin`, por ejemplo con DNS rebinding) puede administrar el gateway. No desactivar el login.
- **Proveedores reales y calidad de respuestas:** no se probaron.
- **Docker/Fly y Electron:** no verificados (salvo el compose de Ollama).
- **Marco legal chileno:** de fuentes secundarias; verificar en bcn.cl y con un abogado.
