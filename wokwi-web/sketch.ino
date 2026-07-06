/**
 * ENVASADORA DE PRODUCTOS SECOS — Proyecto Final Sistemas Operativos
 * ESP32 + FreeRTOS (framework Arduino) · Emulación: Wokwi
 *
 * Arquitectura hexagonal ejecutada como tareas FreeRTOS:
 *   nucleo (FSM + validación ± tolerancia)  →  tarea_control   (prio 5)
 *   adaptador báscula HX711                 →  tarea_bascula   (prio 4)
 *   adaptador válvula (relé)                →  tarea_valvula   (prio 4)
 *   dominio alarmas                         →  tarea_alarmas   (prio 3)
 *   adaptador telemetría MQTT               →  tarea_mqtt      (prio 2)
 *   adaptador HMI (LCD + serial)            →  tarea_hmi       (prio 1)
 *
 * Sincronización: colas (peso, válvula, telemetría, comandos),
 * mutex (estado compartido), event group (alarmas), semáforos desde ISR (botones).
 *
 * Tópicos MQTT (broker público, ver HALLAZGOS.md D3):
 *   envasadora/ENV01/peso | estado | unidad | alarma   (publica)
 *   envasadora/ENV01/cmd                               (suscribe)
 */
#include <Arduino.h>
#include <WiFi.h>
#include <PubSubClient.h>
#include <HX711.h>
#include <LiquidCrystal_I2C.h>
#include <ArduinoJson.h>

// ---------- configuración ----------
#define MODO_DEMO 1               // 1 = peso simulado por la válvula (demo autónoma en Wokwi)
                                  // 0 = peso real del HX711 (ajustar en la parte hx1 de Wokwi)
static const char* WIFI_SSID   = "Wokwi-GUEST";
static const char* WIFI_PASS   = "";
static const char* MQTT_BROKER = "broker.emqx.io";   // hivemq limita IPs de nubes (Render)
static const int   MQTT_PUERTO = 1883;
static const char* T_PESO   = "envasadora/ENV01/peso";
static const char* T_ESTADO = "envasadora/ENV01/estado";
static const char* T_UNIDAD = "envasadora/ENV01/unidad";
static const char* T_ALARMA = "envasadora/ENV01/alarma";
static const char* T_CMD    = "envasadora/ENV01/cmd";

// pines (ver diagram.json)
#define PIN_HX_DT     16
#define PIN_HX_SCK     4
#define PIN_VALVULA   26
#define PIN_LED_OK    27
#define PIN_LED_AL    14
#define PIN_BTN_INI   32
#define PIN_BTN_PARO  33

// parámetros de proceso
static const float TOLERANCIA_G   = 0.6f;   // validación: objetivo ± tolerancia
static const float ANTICIPO_G     = 0.8f;   // cierre anticipado (producto en vuelo)
static const float FACTOR_ESCALA  = 420.0f; // calibración HX711 (celda 5 kg)
static const uint32_t MS_ASENTAR  = 400;    // espera a que el peso se asiente
static const uint32_t MS_DESCARGA = 500;    // cambio de funda

// ---------- dominio: FSM ----------
enum EstadoFSM : uint8_t { ESPERA, DOSIFICANDO, ASENTANDO, VALIDANDO, DESCARGA, PARADA };
static const char* NOMBRE_FSM[] = { "ESPERA", "DOSIFICANDO", "ASENTANDO", "VALIDANDO", "DESCARGA", "PARADA" };

struct Orden {
  char producto[12];
  int  presentacionG;   // 25 | 50
  int  tamLote;         // 50 | 100
  int  unidadesOk;
  int  rechazos;
  int  numeroLote;
  bool activa;
};

enum TipoCmd : uint8_t { CMD_PARAR = 0, CMD_INICIAR, CMD_REANUDAR, CMD_REINICIAR };

struct Comando {        // llega por MQTT (backend) o botones (operador)
  uint8_t tipo;         // TipoCmd
  char producto[12];
  int  presentacionG;
  int  tamLote;
  int  numeroLote;      // 0 = autonumerar (orden local por botón)
};

struct EventoTele {     // hacia tarea_mqtt
  char sufijo[8];       // "peso" | "estado" | "unidad" | "alarma"
  char json[160];
};

// bits del event group de alarmas
#define BIT_FUERA_TOL (1 << 0)
#define BIT_SENSOR    (1 << 1)

// ---------- estado compartido y primitivas ----------
static volatile EstadoFSM fsm = ESPERA;
static Orden orden = { "mani", 25, 50, 0, 0, 0, false };
static volatile bool  valvulaAbierta = false;
static volatile bool  enDescarga    = false;
static volatile float pesoActual    = 0.0f;

static SemaphoreHandle_t  mtxEstado;
static SemaphoreHandle_t  semInicio, semParo;      // desde ISR de botones
static QueueHandle_t      colaPeso;                // float, longitud 1 (última muestra)
static QueueHandle_t      colaValvula;             // bool: abrir/cerrar
static QueueHandle_t      colaTele;                // EventoTele
static QueueHandle_t      colaCmd;                 // Comando
static EventGroupHandle_t grupoAlarmas;

// métricas de determinismo (evidencia para el informe)
static volatile uint32_t peorCicloControlUs = 0;
static volatile uint32_t peorCicloBasculaUs = 0;
static volatile float    pesoAlarma = 0.0f;   // peso capturado al momento de la falla

static HX711 bascula;
static LiquidCrystal_I2C lcd(0x27, 16, 2);
static WiFiClient wifiCliente;
static PubSubClient mqtt(wifiCliente);

// ---------- ISR de botones (patrón sistema-incendio: ISR → semáforo) ----------
void IRAM_ATTR isrInicio() {
  BaseType_t despertar = pdFALSE;
  xSemaphoreGiveFromISR(semInicio, &despertar);
  portYIELD_FROM_ISR(despertar);
}
void IRAM_ATTR isrParo() {
  BaseType_t despertar = pdFALSE;
  xSemaphoreGiveFromISR(semParo, &despertar);
  portYIELD_FROM_ISR(despertar);
}

// ---------- helpers de telemetría ----------
static void teleEncolar(const char* sufijo, const char* json) {
  EventoTele ev;
  strlcpy(ev.sufijo, sufijo, sizeof(ev.sufijo));
  strlcpy(ev.json, json, sizeof(ev.json));
  xQueueSend(colaTele, &ev, 0);   // si la cola está llena se descarta: telemetría nunca bloquea el control
}

static void publicarEstado() {
  char json[160];
  snprintf(json, sizeof(json),
    "{\"fsm\":\"%s\",\"lote\":\"L-%04d\",\"unidad\":%d,\"rechazos\":%d,\"tam_lote\":%d,\"producto\":\"%s\",\"presentacion_gr\":%d}",
    NOMBRE_FSM[fsm], orden.numeroLote, orden.unidadesOk, orden.rechazos,
    orden.tamLote, orden.producto, orden.presentacionG);
  teleEncolar("estado", json);
}

// ---------- TAREA: báscula (adaptador conducido, prio 4, periodo 50 ms) ----------
static void tarea_bascula(void*) {
  TickType_t ultimo = xTaskGetTickCount();
#if MODO_DEMO
  float pesoSim = 0.0f;
  float enVuelo = 0.0f;      // producto que ya cayó de la válvula pero no llegó a la funda
  bool valvulaPrev = false;
#endif
  for (;;) {
    uint32_t t0 = micros();
    float peso = pesoActual;
#if MODO_DEMO
    // modelo físico simple: flujo ~12 g/s con ruido + material en vuelo al cerrar
    if (enDescarga) { pesoSim = 0.0f; enVuelo = 0.0f; }
    else {
      if (valvulaAbierta) pesoSim += 12.0f * 0.050f + (esp_random() % 100) / 500.0f;
      if (valvulaPrev && !valvulaAbierta) enVuelo = 0.30f + (esp_random() % 50) / 100.0f;
      if (!valvulaAbierta && enVuelo > 0.0f) {
        float d = fminf(0.35f, enVuelo);
        pesoSim += d; enVuelo -= d;
      }
    }
    valvulaPrev = valvulaAbierta;
    peso = pesoSim + (esp_random() % 100) / 1000.0f;   // ruido de lectura ±0.1 g
#else
    if (bascula.wait_ready_timeout(40)) {
      peso = bascula.get_units(1);
    } else {
      xEventGroupSetBits(grupoAlarmas, BIT_SENSOR);
    }
#endif
    pesoActual = peso;
    xQueueOverwrite(colaPeso, &peso);   // cola de longitud 1: siempre la muestra más fresca

    uint32_t dt = micros() - t0;
    if (dt > peorCicloBasculaUs) peorCicloBasculaUs = dt;
    vTaskDelayUntil(&ultimo, pdMS_TO_TICKS(50));
  }
}

// ---------- TAREA: válvula (adaptador conducido, prio 4, por evento) ----------
static void tarea_valvula(void*) {
  bool abrir;
  for (;;) {
    if (xQueueReceive(colaValvula, &abrir, portMAX_DELAY) == pdTRUE) {
      digitalWrite(PIN_VALVULA, abrir ? HIGH : LOW);
      valvulaAbierta = abrir;
    }
  }
}

static inline void valvula(bool abrir) { xQueueSend(colaValvula, &abrir, 0); }

// ---------- TAREA: control (núcleo de dominio, prio 5, ciclo 25 ms) ----------
static void tarea_control(void*) {
  TickType_t ultimo = xTaskGetTickCount();
  uint32_t tMarca = 0;
  static int consecutivoLote = 0;

  auto iniciarOrden = [&](const Comando& c) {
    xSemaphoreTake(mtxEstado, portMAX_DELAY);
    strlcpy(orden.producto, c.producto, sizeof(orden.producto));
    orden.presentacionG = c.presentacionG;
    orden.tamLote       = c.tamLote;
    orden.unidadesOk    = 0;
    orden.rechazos      = 0;
    // el backend manda su numero de lote en el cmd; el boton local autonumera
    if (c.numeroLote > 0) {
      orden.numeroLote = c.numeroLote;
      if (c.numeroLote > consecutivoLote) consecutivoLote = c.numeroLote;
    } else {
      orden.numeroLote = ++consecutivoLote;
    }
    orden.activa        = true;
    xSemaphoreGive(mtxEstado);
    Serial.printf("[ORDEN] iniciada producto=%s presentacion=%dg lote=%d\n",
                  orden.producto, orden.presentacionG, orden.tamLote);
    fsm = ESPERA;
    publicarEstado();
  };

  for (;;) {
    uint32_t t0 = micros();

    // comandos: botones (ISR→semáforo) y MQTT (cola)
    if (xSemaphoreTake(semParo, 0) == pdTRUE && orden.activa) {
      valvula(false);
      fsm = PARADA;
      Serial.println("[PARO] solicitado por operador");
      publicarEstado();
    }
    if (xSemaphoreTake(semInicio, 0) == pdTRUE) {
      if (fsm == PARADA) { fsm = DOSIFICANDO; valvula(true); publicarEstado(); }
      else if (!orden.activa) {
        Comando porDefecto = { CMD_INICIAR, "mani", 25, 50, 0 };
        iniciarOrden(porDefecto);
      }
    }
    Comando cmd;
    if (xQueueReceive(colaCmd, &cmd, 0) == pdTRUE) {
      switch (cmd.tipo) {
        case CMD_PARAR:
          if (orden.activa && fsm != PARADA) {
            valvula(false); fsm = PARADA;
            Serial.println("[CMD] pausa desde la web");
            publicarEstado();
          }
          break;
        case CMD_INICIAR:
          if (!orden.activa) iniciarOrden(cmd);
          else if (fsm == PARADA) { valvula(true); fsm = DOSIFICANDO; publicarEstado(); }
          break;
        case CMD_REANUDAR:
          if (fsm == PARADA) {
            valvula(true); fsm = DOSIFICANDO;
            Serial.println("[CMD] reanudar desde la web");
            publicarEstado();
          }
          break;
        case CMD_REINICIAR:
          if (orden.activa) {
            xSemaphoreTake(mtxEstado, portMAX_DELAY);
            orden.unidadesOk = 0;
            orden.rechazos = 0;
            xSemaphoreGive(mtxEstado);
            valvula(false);
            enDescarga = true;          // vacía la funda en curso (y el peso demo)
            tMarca = millis();
            fsm = DESCARGA;             // DESCARGA reabre la válvula al terminar
            Serial.println("[CMD] reinicio de lote desde la web");
            publicarEstado();
          }
          break;
      }
    }

    float peso = 0;
    xQueuePeek(colaPeso, &peso, 0);
    const float objetivo = (float)orden.presentacionG;

    switch (fsm) {
      case ESPERA:
        if (orden.activa) { enDescarga = false; valvula(true); fsm = DOSIFICANDO; publicarEstado(); }
        break;

      case DOSIFICANDO:
        // lazo de tiempo real: cerrar ANTES del objetivo por el producto en vuelo
        if (peso >= objetivo - ANTICIPO_G) {
          valvula(false);
          tMarca = millis();
          fsm = ASENTANDO;
        }
        break;

      case ASENTANDO:
        if (millis() - tMarca >= MS_ASENTAR) { fsm = VALIDANDO; }
        break;

      case VALIDANDO: {
        bool ok = fabsf(peso - objetivo) <= TOLERANCIA_G;
        xSemaphoreTake(mtxEstado, portMAX_DELAY);
        if (ok) orden.unidadesOk++; else orden.rechazos++;
        int n = orden.unidadesOk;
        xSemaphoreGive(mtxEstado);

        char json[160];
        snprintf(json, sizeof(json),
          "{\"lote\":\"L-%04d\",\"n\":%d,\"peso\":%.2f,\"ok\":%s,\"producto\":\"%s\",\"presentacion_gr\":%d}",
          orden.numeroLote, ok ? n : orden.rechazos, peso, ok ? "true" : "false",
          orden.producto, orden.presentacionG);
        teleEncolar("unidad", json);
        publicarEstado();
        Serial.printf("[UNIDAD] n=%d peso=%.2f ok=%d\n", ok ? n : -orden.rechazos, peso, ok);

        if (ok) { digitalWrite(PIN_LED_OK, HIGH); }
        else    { pesoAlarma = peso; xEventGroupSetBits(grupoAlarmas, BIT_FUERA_TOL); }

        enDescarga = true;
        tMarca = millis();
        fsm = DESCARGA;
        break;
      }

      case DESCARGA:
        if (millis() - tMarca >= MS_DESCARGA) {
          digitalWrite(PIN_LED_OK, LOW);
          enDescarga = false;
          if (orden.unidadesOk >= orden.tamLote) {
            xSemaphoreTake(mtxEstado, portMAX_DELAY);
            orden.activa = false;
            xSemaphoreGive(mtxEstado);
            valvula(false);
            fsm = ESPERA;
            Serial.printf("[ORDEN COMPLETADA] lote=L-%04d ok=%d rechazos=%d\n",
                          orden.numeroLote, orden.unidadesOk, orden.rechazos);
            publicarEstado();
          } else {
            valvula(true);
            fsm = DOSIFICANDO;
            publicarEstado();
          }
        }
        break;

      case PARADA:
        break;   // se sale con INICIO o cmd MQTT
    }

    uint32_t dt = micros() - t0;
    if (dt > peorCicloControlUs) peorCicloControlUs = dt;
    vTaskDelayUntil(&ultimo, pdMS_TO_TICKS(25));
  }
}

// ---------- TAREA: alarmas (dominio, prio 3, por evento) ----------
static void tarea_alarmas(void*) {
  for (;;) {
    EventBits_t bits = xEventGroupWaitBits(grupoAlarmas, BIT_FUERA_TOL | BIT_SENSOR,
                                           pdTRUE, pdFALSE, portMAX_DELAY);
    digitalWrite(PIN_LED_AL, HIGH);
    char json[120];
    if (bits & BIT_FUERA_TOL) {
      snprintf(json, sizeof(json), "{\"tipo\":\"FUERA_TOLERANCIA\",\"peso\":%.2f}", pesoAlarma);
      teleEncolar("alarma", json);
      Serial.printf("[ALARMA] fuera de tolerancia peso=%.2f\n", pesoAlarma);
    }
    if (bits & BIT_SENSOR) {
      snprintf(json, sizeof(json), "{\"tipo\":\"SENSOR_SIN_RESPUESTA\"}");
      teleEncolar("alarma", json);
      Serial.println("[ALARMA] sensor sin respuesta");
    }
    vTaskDelay(pdMS_TO_TICKS(800));
    digitalWrite(PIN_LED_AL, LOW);
  }
}

// ---------- TAREA: MQTT (adaptador conducido, prio 2) ----------
static void mqttCallback(char* topico, byte* payload, unsigned int largo) {
  JsonDocument doc;
  if (deserializeJson(doc, payload, largo) != DeserializationError::Ok) return;
  Comando c = { CMD_PARAR, "mani", 25, 50, 0 };
  const char* accion = doc["accion"] | "";
  if (strcmp(accion, "iniciar") == 0) {
    c.tipo = CMD_INICIAR;
    strlcpy(c.producto, doc["producto"] | "mani", sizeof(c.producto));
    c.presentacionG = doc["presentacion_gr"] | 25;
    c.tamLote       = doc["tam_lote"] | 50;
    const char* lote = doc["lote"] | "";
    if (strlen(lote) > 2) c.numeroLote = atoi(lote + 2);   // "L-0007" -> 7
  } else if (strcmp(accion, "parar") == 0 || strcmp(accion, "pausar") == 0) {
    c.tipo = CMD_PARAR;
  } else if (strcmp(accion, "reanudar") == 0) {
    c.tipo = CMD_REANUDAR;
  } else if (strcmp(accion, "reiniciar") == 0) {
    c.tipo = CMD_REINICIAR;
  } else {
    return;
  }
  xQueueSend(colaCmd, &c, 0);
}

static void tarea_mqtt(void*) {
  char clientId[32];
  snprintf(clientId, sizeof(clientId), "envasadora-ENV01-%06X", (uint32_t)(ESP.getEfuseMac() & 0xFFFFFF));
  mqtt.setServer(MQTT_BROKER, MQTT_PUERTO);
  mqtt.setCallback(mqttCallback);

  uint32_t ultimoIntento = 0, ultimoPeso = 0;
  for (;;) {
    // conexión WiFi + broker, reintento no bloqueante (patrón pubsubclient/mqtt_reconnect_nonblocking)
    if (WiFi.status() != WL_CONNECTED) {
      if (millis() - ultimoIntento > 5000) {
        ultimoIntento = millis();
        WiFi.begin(WIFI_SSID, WIFI_PASS, 6);
        Serial.println("[WIFI] conectando...");
      }
    } else if (!mqtt.connected()) {
      if (millis() - ultimoIntento > 3000) {
        ultimoIntento = millis();
        if (mqtt.connect(clientId)) {
          mqtt.subscribe(T_CMD);
          Serial.println("[MQTT] conectado y suscrito a cmd");
        }
      }
    } else {
      mqtt.loop();

      EventoTele ev;
      while (xQueueReceive(colaTele, &ev, 0) == pdTRUE) {
        char topico[48];
        snprintf(topico, sizeof(topico), "envasadora/ENV01/%s", ev.sufijo);
        mqtt.publish(topico, ev.json, strcmp(ev.sufijo, "estado") == 0);  // estado: retained
      }

      if (millis() - ultimoPeso >= 500) {          // telemetría de peso a 2 Hz
        ultimoPeso = millis();
        char json[64];
        snprintf(json, sizeof(json), "{\"g\":%.2f,\"ts\":%lu}", pesoActual, (unsigned long)millis());
        mqtt.publish(T_PESO, json, false);
      }
    }
    vTaskDelay(pdMS_TO_TICKS(50));
  }
}

// ---------- TAREA: HMI (adaptador conductor, prio 1, periodo 200 ms) ----------
static void tarea_hmi(void*) {
  TickType_t ultimo = xTaskGetTickCount();
  uint32_t ultimaMetrica = 0;
  char linea[17];
  for (;;) {
    xSemaphoreTake(mtxEstado, portMAX_DELAY);
    int n = orden.unidadesOk, tam = orden.tamLote, rech = orden.rechazos;
    xSemaphoreGive(mtxEstado);

    lcd.setCursor(0, 0);
    snprintf(linea, sizeof(linea), "%-9.9s %3d/%-3d", NOMBRE_FSM[fsm], n, tam);
    lcd.print(linea);
    lcd.setCursor(0, 1);
    snprintf(linea, sizeof(linea), "P:%6.2fg  R:%-3d", pesoActual, rech);
    lcd.print(linea);

    if (millis() - ultimaMetrica >= 10000) {       // evidencia de determinismo cada 10 s
      ultimaMetrica = millis();
      Serial.printf("[METRICA] peor_ciclo_control=%luus peor_ciclo_bascula=%luus heap_libre=%u\n",
                    (unsigned long)peorCicloControlUs, (unsigned long)peorCicloBasculaUs,
                    (unsigned)ESP.getFreeHeap());
    }
    vTaskDelayUntil(&ultimo, pdMS_TO_TICKS(200));
  }
}

// ---------- arranque ----------
void setup() {
  Serial.begin(115200);
  pinMode(PIN_VALVULA, OUTPUT);
  pinMode(PIN_LED_OK, OUTPUT);
  pinMode(PIN_LED_AL, OUTPUT);
  pinMode(PIN_BTN_INI, INPUT_PULLUP);
  pinMode(PIN_BTN_PARO, INPUT_PULLUP);

  lcd.init();
  lcd.backlight();
  lcd.print("Envasadora ENV01");

  bascula.begin(PIN_HX_DT, PIN_HX_SCK);
  bascula.set_scale(FACTOR_ESCALA);
  bascula.tare();

  mtxEstado    = xSemaphoreCreateMutex();
  semInicio    = xSemaphoreCreateBinary();
  semParo      = xSemaphoreCreateBinary();
  colaPeso     = xQueueCreate(1,  sizeof(float));
  colaValvula  = xQueueCreate(4,  sizeof(bool));
  colaTele     = xQueueCreate(16, sizeof(EventoTele));
  colaCmd      = xQueueCreate(4,  sizeof(Comando));
  grupoAlarmas = xEventGroupCreate();

  attachInterrupt(PIN_BTN_INI, isrInicio, FALLING);
  attachInterrupt(PIN_BTN_PARO, isrParo, FALLING);

  // núcleo 1: lazo de control determinista · núcleo 0: red (junto al stack WiFi)
  xTaskCreatePinnedToCore(tarea_control, "control", 4096, nullptr, 5, nullptr, 1);
  xTaskCreatePinnedToCore(tarea_bascula, "bascula", 4096, nullptr, 4, nullptr, 1);
  xTaskCreatePinnedToCore(tarea_valvula, "valvula", 2048, nullptr, 4, nullptr, 1);
  xTaskCreatePinnedToCore(tarea_alarmas, "alarmas", 3072, nullptr, 3, nullptr, 1);
  xTaskCreatePinnedToCore(tarea_mqtt,    "mqtt",    6144, nullptr, 2, nullptr, 0);
  xTaskCreatePinnedToCore(tarea_hmi,     "hmi",     3072, nullptr, 1, nullptr, 1);

  Serial.println("[BOOT] envasadora lista");
}

void loop() { vTaskDelay(portMAX_DELAY); }   // todo vive en tareas
