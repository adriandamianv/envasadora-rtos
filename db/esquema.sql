-- ============================================================
-- ENVASADORA DE PRODUCTOS SECOS — Esquema PostgreSQL
-- Proyecto Final Sistemas Operativos · 6 tablas del enunciado
-- Normalizado a 3FN, con claves y restricciones (rúbrica: Diseño BD)
-- ============================================================

CREATE TABLE usuario (
    id          SERIAL PRIMARY KEY,
    nombre      VARCHAR(80)  NOT NULL,
    usuario     VARCHAR(40)  NOT NULL UNIQUE,
    clave_hash  VARCHAR(255) NOT NULL,
    rol         VARCHAR(12)  NOT NULL
                CONSTRAINT chk_rol CHECK (rol IN ('operador', 'supervisor', 'gerente'))
);

CREATE TABLE producto (
    id              SERIAL PRIMARY KEY,
    nombre          VARCHAR(40) NOT NULL,          -- 'Maní' | 'Pasas'
    presentacion_gr SMALLINT    NOT NULL
                    CONSTRAINT chk_presentacion CHECK (presentacion_gr IN (25, 50)),
    CONSTRAINT uq_producto UNIQUE (nombre, presentacion_gr)
);

CREATE TABLE inventario_materia_prima (
    id                  SERIAL PRIMARY KEY,
    materia_prima       VARCHAR(40)   NOT NULL UNIQUE,
    cantidad_disponible NUMERIC(12,2) NOT NULL DEFAULT 0
                        CONSTRAINT chk_stock_no_negativo CHECK (cantidad_disponible >= 0),
    unidad_medida       VARCHAR(10)   NOT NULL      -- 'g' | 'unidad'
);

CREATE TABLE orden_produccion (
    id                   SERIAL PRIMARY KEY,
    fecha                TIMESTAMP   NOT NULL DEFAULT NOW(),
    producto_id          INTEGER     NOT NULL REFERENCES producto(id),
    tam_lote             SMALLINT    NOT NULL
                         CONSTRAINT chk_tam_lote CHECK (tam_lote IN (50, 100)),
    cantidad_solicitada  INTEGER     NOT NULL CHECK (cantidad_solicitada > 0),
    estado               VARCHAR(12) NOT NULL DEFAULT 'pendiente'
                         CONSTRAINT chk_estado CHECK (estado IN ('pendiente', 'en_proceso', 'completada')),
    operador_id          INTEGER     REFERENCES usuario(id)
);

CREATE TABLE lote (
    id                  SERIAL PRIMARY KEY,
    numero_lote         VARCHAR(12) NOT NULL UNIQUE,    -- 'L-0001'
    orden_id            INTEGER     NOT NULL REFERENCES orden_produccion(id),
    fecha_produccion    DATE        NOT NULL DEFAULT CURRENT_DATE,
    fecha_caducidad     DATE        NOT NULL,           -- producción + 180 días
    cantidad_producida  INTEGER     NOT NULL DEFAULT 0 CHECK (cantidad_producida >= 0),
    cantidad_rechazada  INTEGER     NOT NULL DEFAULT 0 CHECK (cantidad_rechazada >= 0),
    CONSTRAINT chk_caducidad CHECK (fecha_caducidad > fecha_produccion)
);

-- un registro por funda llenada: trazabilidad unitaria (rúbrica: Reportes/Monitoreo)
CREATE TABLE historico_produccion (
    id          SERIAL PRIMARY KEY,
    lote_id     INTEGER      NOT NULL REFERENCES lote(id),
    peso_real   NUMERIC(6,2) NOT NULL,
    ok          BOOLEAN      NOT NULL,
    fecha_hora  TIMESTAMP    NOT NULL DEFAULT NOW(),
    operador_id INTEGER      REFERENCES usuario(id)
);

-- índices para los reportes (lotes/día, % error, historial por operador)
CREATE INDEX idx_historico_fecha    ON historico_produccion (fecha_hora);
CREATE INDEX idx_historico_lote     ON historico_produccion (lote_id);
CREATE INDEX idx_historico_operador ON historico_produccion (operador_id);
CREATE INDEX idx_orden_estado       ON orden_produccion (estado);
