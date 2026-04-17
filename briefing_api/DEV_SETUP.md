# Setup de desarrollo local — briefing_api

## Primera vez (solo se hace una vez)

### 1. Instalar Python 3.12
Descargar de: https://www.python.org/downloads/release/python-31210/
Marcar "Add Python to PATH" durante la instalación.

### 2. Crear entorno virtual
```powershell
cd "D:\Dokumente\Laboral\Sediment Data\4. Github Sediment\sediment_outreach\briefing_api"
py -3.12 -m venv venv
```

### 3. Instalar dependencias
```powershell
venv\Scripts\activate
pip install -r requirements.txt
```

### 4. Configurar variables de entorno
```powershell
copy .env.example .env
notepad .env
```
Completar `.env` con:
```
ENVIRONMENT=development
API_PORT=8002
DATABASE_URL=postgresql://usuario:password@187.77.234.205:5432/nombre_db
API_KEY=sediment-dev-2026
DEV_EMAIL_OVERRIDE=tomas@sedimentdata.com   ← tu correo real
TWENTY_API_URL=http://187.77.234.205:8347
TWENTY_API_TOKEN=                            ← dejar vacío en dev
```

---

## Cada vez que querés desarrollar o testear

```powershell
cd "D:\Dokumente\Laboral\Sediment Data\4. Github Sediment\sediment_outreach\briefing_api"
venv\Scripts\activate
uvicorn main:app --reload --port 8002
```

Swagger UI disponible en: **http://localhost:8002/docs**

Para detener: **Ctrl+C** en la terminal.

---

## Garantías de seguridad en modo development

| Riesgo | Protección |
|---|---|
| Escribir intentos reales en la BD | `ENVIRONMENT=development` → dry-run, no escribe en `outreach_intentos` |
| Enviar email a un prospecto real | `DEV_EMAIL_OVERRIDE` → todos los emails se redirigen a tu correo |
| Crear leads en Twenty CRM | Solo se ejecuta si `ENVIRONMENT=production` |
| Subir credenciales al repo | `.env` está en `.gitignore`, nunca se sube |

**Con estas protecciones puedes testear cualquier flujo desde n8n → briefing_api sin riesgo de contactar a nadie ni corromper datos de producción.**

La respuesta del endpoint en dev incluye:
- `is_dry_run: true`
- `email_destino`: tu correo (override)
- `email_real`: el email del lead real (para verificar que el cascade funciona)

---

## Leads de prueba en la BD

Para testear sin depender de leads reales, ejecutar este SQL en DBeaver:

```sql
-- Leads dummy para desarrollo — no tocar en producción
INSERT INTO leads_brutos (
    timestamp_levante, fuente, nombre, ciudad, pais,
    vertical_consolidada, stack_categoria, stack_score,
    score, emails_sitio, email_fuente, web_url,
    contacto_status, enrichment_status, sheets_exported
) VALUES
(NOW(), 'dev_test', 'Clínica Demo Salud', 'Bogotá', 'Colombia',
 'salud', 'ecommerce', 40,
 78, 'contacto@clinica-demo.co', 'admin@clinica-demo.co', 'https://clinica-demo.co',
 'pendiente', 'done', FALSE),

(NOW(), 'dev_test', 'Manufactura Demo SAS', 'Medellín', 'Colombia',
 'manufactura', 'erp', 20,
 72, 'ventas@manufactura-demo.com', NULL, 'https://manufactura-demo.com',
 'pendiente', 'done', FALSE),

(NOW(), 'dev_test', 'Retail Demo Ltda', 'Cali', 'Colombia',
 'retail', 'analytics', 25,
 68, 'info@retaildemo.co', NULL, 'https://retaildemo.co',
 'pendiente', 'done', FALSE);

-- Verificar
SELECT id, nombre, vertical_consolidada, stack_categoria, score, contacto_status
FROM leads_brutos
WHERE fuente = 'dev_test';
```

Para limpiar los leads de prueba después:
```sql
DELETE FROM leads_brutos WHERE fuente = 'dev_test';
```

---

## Subir cambios a GitHub

```powershell
git add .
git commit -m "descripción del cambio"
git push
```

Coolify hace redeploy automático al detectar el push (si está configurado el webhook de GitHub).

---

## Variables de entorno en Coolify (producción)

Ir a Coolify → Servicio `briefing_api` → Environment Variables y verificar:

| Variable | Valor |
|---|---|
| `ENVIRONMENT` | `production` |
| `DATABASE_URL` | URL real de PostgreSQL |
| `API_KEY` | Clave compartida con n8n |
| `DEV_EMAIL_OVERRIDE` | *(vacío)* |
| `TWENTY_API_URL` | `http://187.77.234.205:8347` |
| `TWENTY_API_TOKEN` | Token generado en Twenty → Settings → API |
