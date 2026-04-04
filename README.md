# sediment_outreach

Infraestructura de outreach automatizado para Sediment Data.

## Componentes

### briefing_api (puerto 8002)
API FastAPI que gestiona la lógica de outreach:
- Selección de mensajes desde `message_matrix`
- Validación y cascade de emails
- Registro de intentos y eventos
- Webhooks de Instantly

## Setup local

```bash
cd briefing_api
cp .env.example .env
# Editar .env con credenciales reales

pip install -r requirements.txt
uvicorn main:app --reload --port 8002
```

Docs disponibles en desarrollo: http://localhost:8002/docs

## Deploy en Coolify

Ver instrucciones en el Dockerfile. Variables de entorno requeridas en `.env.example`.
