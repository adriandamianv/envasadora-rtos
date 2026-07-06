# HALLAZGOS — Investigación de stacks maduros para forkear

**Fecha:** 2026-07-05 · **Objetivo:** no empezar de 0. 15 repos clonados en `vendor/`, revisados uno a uno.
**Destino de despliegue:** Render · **Emulador:** Wokwi (confirmado como estándar correcto).

---

## 1. Decisiones que salen de esta investigación

| # | Decisión | Fundamento |
|---|----------|------------|
| D1 | **Emulador: Wokwi** (el manager tiene razón) | HX711 es parte nativa de Wokwi (variantes 5kg/50kg, docs oficiales `docs.wokwi.com/parts/wokwi-hx711`); WiFi virtual con salida a internet (MQTT a brokers públicos); `wokwi-cli` permite tests de escenarios YAML en CI. Renode/QEMU son para ARM/RISC-V profesional, sin catálogo de sensores. |
| D2 | **Firmware: Arduino framework sobre ESP32** (no ESP-IDF) | El HX711 de Wokwi se integra con la lib Arduino de bogde; FreeRTOS viene embebido en el core Arduino-ESP32 (xTaskCreate, colas, mutex, semáforos disponibles → cumple rúbrica "multitarea real"); PlatformIO como build (patrón de `sistema-incendio-str-esp32`). |
| D3 | **Broker MQTT: público (HiveMQ / test.mosquitto.org), NO en Render** | Render no expone puertos TCP arbitrarios al público — solo HTTP(S)/WSS. El ESP32 emulado publica al broker público; el backend en Render se suscribe como cliente (TCP saliente sí está permitido). |
| D4 | **Base de datos: PostgreSQL** (no MySQL) | Es la BD gestionada de Render (entrega `DATABASE_URL`); la rúbrica la acepta explícitamente. El esqueleto que forkeamos ya es PostgreSQL. |
| D5 | **Backend: Flask 3 + SQLAlchemy 2 + gunicorn** forkeando `automotive-repair-management-system` | Mismo stack objetivo, capas planas (models/services/views), roles+permisos e inventario con transacciones ya resueltos, MIT, deploy con Procfile listo para Render. |
| D6 | **Telemetría en dashboard: Flask-MQTT + SocketIO** | Su ejemplo oficial (`example/app.py`) es exactamente MQTT→WebSocket→navegador en vivo. ⚠️ Requiere **1 solo worker** de gunicorn. |
| D7 | **HMI industrial: FUXA como pieza opcional** | SCADA web MIT con cliente MQTT nativo y editor visual — cubre "interfaz industrial funcional" + "SCADA" de la rúbrica casi gratis. Riesgo: filesystem efímero de Render (exportar el proyecto JSON y versionarlo). |
| D8 | **Arquitectura: hexagonal con capas PLANAS, monorepo sin anidamiento** | Ver §4. |

---

## 2. Veredicto por repo (los 15 de `vendor/`)

### FORKEAR (licencia limpia, código que usamos como base)

| Repo | ⭐ | Lic. | Qué tomamos |
|------|----|------|-------------|
| `automotive-repair-management-system` | 29 | MIT | **Esqueleto del backend.** App factory, `models/` (adaptar `Job`→OrdenProduccion/Lote, `inventory.py` casi tal cual — `InventoryTransaction` con trazabilidad es exactamente nuestro histórico de materia prima), `utils/decorators.py` (`role_required`, `permission_required`), blueprints, `Procfile` + `wsgi.py` + normalización `postgres://`→`postgresql://` para Render. **Quitar:** Stripe, billing, multi-tenant (aplana aún más). |
| `weightech` | 0 | MIT | **Patrones del firmware de báscula.** Calibración HX711 (`HX711_Calibrate_ESP32.ino`), estabilización con `get_units(3)`/`get_units(10)` + % estabilidad, `publishData()` con esquema de tópicos `<app>/<device>/<área>/{weight,estado,data}` y payload JSON con timestamp; secuencia tara→pesar→estabilizar→publicar. |
| `HX711_ADC` (olkal) | 292 | MIT | **Librería de pesaje preferida:** tara no bloqueante (`tareNoDelay`), media móvil, `updateAsync()`, calibración por masa conocida, offset persistente. Ideal dentro de una tarea FreeRTOS sin bloquear el scheduler. |
| `HX711` (bogde) | 984 | MIT | Alternativa simple; es la lib que referencia la parte HX711 de Wokwi. Tener ambas y decidir en integración. |
| `pubsubclient` (knolleary) | 4013 | MIT | Cliente MQTT Arduino de referencia. Clave: `examples/mqtt_reconnect_nonblocking/` (reconexión sin bloquear) y `mqtt_auth/`. |
| `Flask-MQTT` (stlehmann) | 219 | MIT | Dependencia del backend. `@mqtt.on_topic()` por tópico, `MQTT_TRANSPORT` tcp/websockets, TLS. ⚠️ **Limitación documentada: 1 worker, sin reloader.** |

### USAR COMO PIEZA (se despliega, no se toca su código)

| Repo | ⭐ | Lic. | Nota |
|------|----|------|------|
| `FUXA` | 4693 | MIT | SCADA/HMI web (Node, puerto 1881, Docker oficial). Device MQTT desde la UI → mapear tags a nuestros tópicos (~30–60 min) + pantalla de envasadora en el editor visual (horas, sin código). En Render: web service HTTP+WS ✔, pero **exportar el proyecto JSON** (filesystem efímero). |
| `wokwi-cli` | 57 | MIT | Tooling: `wokwi.toml` + `*.scenario.yaml` (`wait-serial`, `expect-pin`, `set-control`, screenshots) → pruebas automatizadas del firmware = evidencia para "Emulación y pruebas". |

### EXTRAER PATRONES (sin licencia o dominio parcial — se reimplementa, no se copia)

| Repo | Lic. | Qué aprendimos |
|------|------|----------------|
| `sistema-incendio-str-esp32` | ❌ sin licencia | **La mejor plantilla estructural** — proyecto académico STR+FreeRTOS+Wokwi igual al nuestro: 7 tareas con prioridades explícitas (ISR+semáforo prio 7 → actuadores prio 3 → logger prio 1), FSM de dominio con `volatile estadoAtual`, `vTaskDelayUntil` para periodicidad, **métricas de deadlines perdidos exportadas a CSV** (oro para la sección de resultados del informe), `wokwi.toml` con `net.forward` + `diagram.json` listos, README que es casi un informe. Reimplementar el patrón, no copiar código. |
| `weighting_scale_esp_web` | ❌ sin licencia | Patrón backend mínimo peso→umbral→clasificar→persistir→`GET /last`→dashboard con polling. Nuestro flujo es el mismo cambiando REST por MQTT. |
| `ESP32-freeRTOS` (DiegoPaezA) | MIT | 35 ejemplos didácticos FreeRTOS (colas, mutex, event groups, MQTT) — pero en **ESP-IDF**, y elegimos Arduino (D2). Queda como referencia de primitivas. ⚠️ Tiene credenciales MQTT hardcodeadas en `wifi_mqtt_6/main/main.c:80-82` — no reutilizar. |
| `DIY-ESP32-Race-Scales` | ⚠️ no comercial | Calibración HX711 vía web + filtro exponencial + detección de "peso asentado". Solo referencia (licencia Source-Available Non-Commercial). |

### SOLO REFERENCIA / DESCARTAR

| Repo | Veredicto | Por qué |
|------|-----------|---------|
| `InvenTree` (7.2k⭐, MIT) | SOLO REFERENCIA | Overkill total para 6 tablas / 50 órdenes/día: Django + Postgres + Redis + worker + SPA React. Usar como diccionario de diseño (nombres de campos, estados de orden, endpoints REST). |
| `IOT-...-Bottle-Filling` | SOLO REFERENCIA | Dominio idéntico (detectar→llenar→tapar) pero Arduino UNO + relés por tiempo fijo, sin peso/MQTT/RTOS, sin licencia. Su `Project Report.pdf` sirve de modelo de informe. |
| `flask-hello-world` (Render) | SOLO REFERENCIA | Confirma el patrón de deploy: `pip install -r requirements.txt` + `gunicorn app:app` + `$PORT`. El Procfile del repo automotive es superior. |

---

## 3. Restricciones de plataforma descubiertas

1. **Render no acepta TCP entrante arbitrario** → el broker MQTT NO puede vivir en Render de cara al ESP32. Solución estándar: broker público (`broker.hivemq.com:1883` / `test.mosquitto.org`) + backend suscriptor. (Fuentes: [community.render.com/mqtt](https://community.render.com/t/render-cloud-services-can-support-for-mqtt/18126), [feature request TCP](https://feedback.render.com/features/p/allow-connecting-to-non-http-services-from-outside-render), [docs web services](https://render.com/docs/web-services))
2. **Filesystem de Render es efímero** → FUXA pierde su proyecto en cada redeploy salvo Render Disk (pago) o export/import del JSON versionado en git.
3. **Flask-MQTT exige 1 worker** (`gunicorn --workers 1`) o habrá conexiones MQTT duplicadas por worker.
4. **Wokwi**: el ESP32 emulado sale a internet vía WiFi virtual `Wokwi-GUEST` → puede publicar a un broker público real desde el navegador. HX711 nativo con celda de 5 kg (nuestro rango 25/50 g funciona con la variante "gauge"/5kg).
5. **PostgreSQL gestionado en Render** entrega `DATABASE_URL` con esquema `postgres://` — el esqueleto forkeado ya lo normaliza a `postgresql://`.

---

## 4. Arquitectura objetivo (hexagonal, SIN anidamiento)

Monorepo plano — cada pieza a un nivel, sin árboles profundos:

```
adrian/
├── firmware/            # ESP32 Arduino+FreeRTOS (PlatformIO)
│   ├── src/main.cpp     #   tareas: bascula, control(FSM), valvula, alarmas, mqtt, hmi
│   ├── wokwi.toml       #   simulación (patrón sistema-incendio)
│   ├── diagram.json     #   ESP32 + HX711 + celda + relé/válvula + LCD
│   └── escenarios/      #   *.scenario.yaml para wokwi-cli (pruebas)
├── backend/             # Flask 3 + SQLAlchemy 2 + PostgreSQL (fork adaptado de automotive)
│   ├── app.py wsgi.py Procfile requirements.txt
│   ├── dominio/         #   entidades + reglas (orden, lote, validación ±tolerancia) — puro
│   ├── adaptadores/     #   mqtt_in.py (Flask-MQTT), repos SQLAlchemy, socketio_out.py
│   └── vistas/          #   blueprints: ordenes, inventario, reportes, auth
├── dashboard/           # templates+static del backend (o FUXA como servicio aparte)
├── db/                  # schema.sql + seeds (6 tablas del enunciado)
├── docs/                # HALLAZGOS.md, informe, manuales
└── vendor/              # los 15 repos clonados (referencia, no se tocan)
```

**Tópicos MQTT** (adaptando el esquema de weightech):
`envasadora/<device>/peso` · `envasadora/<device>/estado` · `envasadora/<device>/alarma` · `envasadora/<device>/unidad` (JSON: peso_final, ok/rechazo, lote, ts) · `envasadora/<device>/cmd` (backend→ESP32: iniciar/parar orden).

---

## 5. Próximos pasos (en orden)

1. `firmware/`: esqueleto PlatformIO + diagram.json (ESP32+HX711+relé) + 6 tareas FreeRTOS con FSM — patrones de sistema-incendio + weightech.
2. `backend/`: podar el fork de automotive (quitar Stripe/tenant), renombrar Job→OrdenProduccion, añadir Flask-MQTT + SocketIO.
3. `db/`: las 6 tablas sobre PostgreSQL local (docker) y Render.
4. Conectar extremo a extremo por `broker.hivemq.com` y capturar evidencia.
5. (Opcional si da el tiempo) FUXA en Docker local para la pantalla HMI industrial → export JSON al repo.
6. Deploy backend en Render (web service, 1 worker) + Postgres gestionado.
