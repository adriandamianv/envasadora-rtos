# Envasadora de Productos Secos — RTOS (Proyecto Final Sistemas Operativos)

Control y administración de producción de llenado de fundas de maní y pasas
(25 g / 50 g, lotes de 50 / 100) sobre **FreeRTOS/ESP32** emulado en **Wokwi**,
con telemetría **MQTT**, backend **Flask + PostgreSQL** y despliegue en **Render**.

## Estructura (plana, hexagonal)

```
firmware/    ESP32 Arduino+FreeRTOS: 6 tareas (control FSM, báscula HX711,
             válvula, alarmas, MQTT, HMI/LCD) — PlatformIO + wokwi.toml
backend/     Flask 3 + SQLAlchemy 2: dominio/ adaptadores/ vistas/ — MQTT in,
             SocketIO out, órdenes/lotes/inventario/reportes/auth por roles
db/          esquema.sql (6 tablas, PostgreSQL, claves y restricciones)
docs/        HALLAZGOS.md (investigación de stacks) + informe
vendor/      15 repos de referencia clonados (no se tocan, ver HALLAZGOS.md)
```

## Cómo correr

**Firmware (emulado):**
```bash
cd firmware && pio run          # compila
# abrir la carpeta en VS Code con la extensión Wokwi, o:
wokwi-cli . --scenario escenarios/llenado_basico.scenario.yaml
```
Botón verde INICIO = arranca orden por defecto (maní 25 g × 50). El backend
también puede iniciar órdenes publicando en `envasadora/ENV01/cmd`.

**Backend (local):**
```bash
cd backend && pip install -r requirements.txt
python seeds.py && python app.py     # http://localhost:5000  (gerente/1234)
```

**Deploy en Render:** ver `backend/render.yaml` (web service gunicorn
`--workers 1` + PostgreSQL gestionado). Broker MQTT: `broker.emqx.io:1883`
(público — Render no acepta TCP entrante, ver docs/HALLAZGOS.md §3).

## Tópicos MQTT

| Tópico | Dirección | Payload |
|---|---|---|
| `envasadora/ENV01/peso`   | ESP32 → backend | `{"g":24.7,"ts":...}` (2 Hz) |
| `envasadora/ENV01/estado` | ESP32 → backend | `{"fsm":"DOSIFICANDO","lote":"L-0001",...}` (retained) |
| `envasadora/ENV01/unidad` | ESP32 → backend | `{"lote":"L-0001","n":12,"peso":25.3,"ok":true,...}` |
| `envasadora/ENV01/alarma` | ESP32 → backend | `{"tipo":"FUERA_TOLERANCIA","peso":26.4}` |
| `envasadora/ENV01/cmd`    | backend → ESP32 | `{"accion":"iniciar","producto":"mani","presentacion_gr":25,"tam_lote":50}` |
