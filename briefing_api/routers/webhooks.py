from fastapi import APIRouter, HTTPException, Header
from datetime import datetime
from typing import Optional

from config import get_settings
from database import execute, fetch_one
from models.webhook import InstantlyWebhook
from services.matrix_selector import increment_replied

router = APIRouter()
settings = get_settings()


def verify_api_key(x_api_key: Optional[str] = Header(None)):
    if x_api_key != settings.api_key:
        raise HTTPException(status_code=401, detail="API key inválida")


@router.post("/instantly")
def handle_instantly_webhook(payload: InstantlyWebhook, x_api_key: Optional[str] = Header(None)):
    """
    Recibe eventos de Instantly vía webhook y actualiza la BD.
    Eventos manejados:
      - email_sent    → estado = 'enviado'
      - email_bounced → estado = 'bounce_hard'
      - email_replied → estado = 'respondio', actualiza contacto_status del lead
    n8n debe pasar el header X-API-Key con el valor configurado en .env
    """
    verify_api_key(x_api_key)

    # Buscar el intento por instantly_id o email_destino
    intento = fetch_one(
        """
        SELECT id, lead_id, matrix_id, tipo
        FROM outreach_intentos
        WHERE instantly_id = %s OR email_destino = %s
        ORDER BY creado_at DESC
        LIMIT 1
        """,
        (payload.instantly_id, payload.lead_email)
    )

    if not intento:
        # Registrar el evento igual aunque no encontremos el intento (para auditoría)
        execute(
            """
            INSERT INTO outreach_eventos (lead_id, tipo, payload, procesado_at)
            VALUES (0, %s, %s, %s)
            """,
            (payload.event_type, payload.model_dump(), datetime.utcnow())
        )
        return {"status": "evento_sin_intento", "event_type": payload.event_type}

    intento_id = intento['id']
    lead_id = intento['lead_id']

    # Registrar evento
    execute(
        """
        INSERT INTO outreach_eventos (lead_id, intento_id, tipo, payload, procesado_at)
        VALUES (%s, %s, %s, %s, %s)
        """,
        (lead_id, intento_id, payload.event_type, payload.model_dump(), datetime.utcnow())
    )

    # Actualizar intento según tipo de evento
    if payload.event_type == "email_sent":
        execute(
            "UPDATE outreach_intentos SET estado = 'enviado', enviado_at = %s, instantly_id = %s WHERE id = %s",
            (datetime.utcnow(), payload.instantly_id, intento_id)
        )

    elif payload.event_type == "email_bounced":
        execute(
            "UPDATE outreach_intentos SET estado = 'bounce_hard', bounce_at = %s WHERE id = %s",
            (datetime.utcnow(), intento_id)
        )

    elif payload.event_type == "email_replied":
        execute(
            "UPDATE outreach_intentos SET estado = 'respondio', respondio_at = %s WHERE id = %s",
            (datetime.utcnow(), intento_id)
        )
        # Actualizar lead a respondio
        execute(
            "UPDATE leads_brutos SET contacto_status = 'respondio' WHERE id = %s",
            (lead_id,)
        )
        # Cancelar todos los intentos pendientes de este lead (no enviar seguimiento)
        execute(
            """
            UPDATE outreach_intentos
            SET estado = 'cancelado'
            WHERE lead_id = %s AND estado = 'pendiente'
            """,
            (lead_id,)
        )
        # Incrementar contador de respuestas en la matriz
        if intento['matrix_id']:
            increment_replied(intento['matrix_id'])

        # Crear registro en Twenty CRM (solo en producción)
        if settings.environment == "production":
            try:
                import httpx as _httpx
                _httpx.post(
                    f"http://localhost:{settings.api_port}/twenty/create_lead_record",
                    json={"lead_id": lead_id, "intento_id": intento_id},
                    headers={"X-API-Key": settings.api_key},
                    timeout=10.0,
                )
            except Exception as e:
                # No bloquear el webhook si Twenty falla — loguear y seguir
                import logging
                logging.getLogger(__name__).error(f"Error creando lead en Twenty: {e}")

    return {"status": "ok", "event_type": payload.event_type, "intento_id": intento_id}
