CREATE TABLE usuarios (
  id          SERIAL PRIMARY KEY,
  cedula      TEXT UNIQUE NOT NULL,
  nombre      TEXT NOT NULL,
  clave_hash  TEXT NOT NULL
);

CREATE TABLE cuentas (
  id          SERIAL PRIMARY KEY,
  usuario_id  INT NOT NULL REFERENCES usuarios(id),
  saldo       NUMERIC(18,2) NOT NULL DEFAULT 0 CHECK (saldo >= 0)
);

CREATE TABLE transferencias (
  id              UUID PRIMARY KEY,
  cuenta_origen   INT NOT NULL REFERENCES cuentas(id),
  cuenta_destino  INT NOT NULL REFERENCES cuentas(id),
  banco_destino   TEXT DEFAULT 'RedSpider Bank',
  monto           NUMERIC(18,2) NOT NULL CHECK (monto > 0),
  creada_en       TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE movimientos (
  id          BIGSERIAL PRIMARY KEY,
  cuenta_id   INT NOT NULL REFERENCES cuentas(id),
  transf_id   UUID REFERENCES transferencias(id),
  monto       NUMERIC(18,2) NOT NULL,
  descripcion TEXT,
  creado_en   TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE creditos (
  id           SERIAL PRIMARY KEY,
  usuario_id   INT NOT NULL REFERENCES usuarios(id),
  monto        NUMERIC(18,2) NOT NULL CHECK (monto > 0),
  plazo_meses  INT NOT NULL,
  estado       TEXT NOT NULL DEFAULT 'pendiente',
  creado_en    TIMESTAMPTZ DEFAULT now()
);

-- Usuario de prueba: cédula 123456789, clave "1234" (ya encriptada abajo)