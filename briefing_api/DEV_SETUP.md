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

### 4. Configurar credenciales
```powershell
copy .env.example .env
notepad .env
```
Completar con los valores reales (ver credenciales en Coolify o DBeaver):
```
ENVIRONMENT=development
API_PORT=8002
DATABASE_URL=postgresql://usuario:password@187.77.234.205:5432/nombre_db
API_KEY=sediment-dev-2026
```

---

## Cada vez que querés desarrollar o testear

```powershell
cd "D:\Dokumente\Laboral\Sediment Data\4. Github Sediment\sediment_outreach\briefing_api"
venv\Scripts\activate
uvicorn main:app --reload --port 8002
```

Swagger UI disponible en: http://localhost:8002/docs

Para detener: **Ctrl+C** en la terminal.

---

## Notas importantes

- `ENVIRONMENT=development` → el endpoint `/outreach/prepare` NO escribe en la BD (dry-run seguro)
- `ENVIRONMENT=production` → escribe en la BD real (solo en Coolify)
- El archivo `.env` nunca se sube a GitHub (está en `.gitignore`)
- La BD es siempre la real en Coolify — no hay BD local separada
- El `--reload` reinicia automáticamente cuando cambiás archivos `.py`, pero NO cuando cambiás `.env` → para eso hacé Ctrl+C y volvé a correr

---

## Subir cambios a GitHub

```powershell
git add .
git commit -m "descripción del cambio"
git push
```
