CREATE TABLE IF NOT EXISTS enrichment_quota (
    servicio VARCHAR(50) PRIMARY KEY,
    mes      INTEGER NOT NULL,
    año      INTEGER NOT NULL,
    usados   INTEGER DEFAULT 0,
    limite   INTEGER NOT NULL
);

INSERT INTO enrichment_quota (servicio, mes, año, usados, limite) VALUES
    ('hunter',      EXTRACT(MONTH FROM NOW())::int, EXTRACT(YEAR FROM NOW())::int, 0, 50),
    ('snov',        EXTRACT(MONTH FROM NOW())::int, EXTRACT(YEAR FROM NOW())::int, 0, 50),
    ('zerobounce',  EXTRACT(MONTH FROM NOW())::int, EXTRACT(YEAR FROM NOW())::int, 0, 100),
    ('abstract',    EXTRACT(MONTH FROM NOW())::int, EXTRACT(YEAR FROM NOW())::int, 0, 100)
ON CONFLICT (servicio) DO NOTHING;
