from fastapi import APIRouter, HTTPException
from datetime import datetime

from config import get_settings
from database import fetch_one, execute
from models.outreach import PrepareRequest, PrepareResponse, CascadeRequest, CascadeResponse
from services.email_validator import build_email_cascade
from services.matrix_selector import get_message, increment_sent
from services.email_builder import build_email, build_subject
from services.cascade_service import get_next_email

router = APIRouter()
settings = get_settings()
IS_DEV = settings.environment == "development"


@router.post("/prepare", response_model=PrepareResponse)
def prepare_outreach(req: PrepareRequest):
    """
    Endpoint principal. Recibe lead_id + tipo + slots (de n8n vía Google Calendar).
    1. Busca el lead en la BD
    2. Valida y arma el cascade de emails
    3. Selecciona el mensaje correcto de message_matrix
    4. Ensambla el email reemplazando placeholders
    5. Registra el intento en outreach_intentos (salvo dry_run en dev)
    6. Devuelve el payload listo para que n8n lo envíe por Instantly
    """
    # 1. Obtener lead
    lead = fetch_one(
        """
        SELECT id, nombre, ciudad, vertical_consolidada, stack_categoria,
               emails_sitio, email_fuente, web_url, contacto_status, score
        FROM leads_brutos WHERE id = %s
        """,
        (req.lead_id,)
    )
    if not lead:
        raise HTTPException(status_code=404, detail=f"Lead {req.lead_id} no encontrado")

    # 2. Cascade de emails — usar primero disponible
    cascade = build_email_cascade(
        emails_sitio=lead['emails_sitio'],
        email_fuente=lead['email_fuente'],
        web_url=lead['web_url'],
    )
    if not cascade:
        # Actualizar status y rechazar
        execute(
            "UPDATE leads_brutos SET contacto_status = 'sin_contacto' WHERE id = %s",
            (req.lead_id,)
        )
        raise HTTPException(
            status_code=422,
            detail=f"Lead {req.lead_id} no tiene emails válidos. Marcado como sin_contacto."
        )

    email_destino = cascade[0]

    # 3. Seleccionar mensaje de la matriz
    vertical = lead['vertical_consolidada'] or 'sin_clasificar'
    stack = lead['stack_categoria'] or 'sin_stack'
    msg = get_message(req.tipo, vertical, stack)

    if not msg:
        raise HTTPException(
            status_code=404,
            detail=f"No hay mensaje en matrix para tipo={req.tipo}, vertical={vertical}, stack={stack}"
        )

    # 4. Ensamblar email con placeholders
    empresa = lead['nombre'] or 'su empresa'
    cuerpo_final = build_email(msg['cuerpo'], empresa, req.slot_1, req.slot_2)
    asunto_final = build_subject(msg['asunto'], empresa)

    # 5. Registrar intento en BD (solo en producción)
    intento_id = -1
    if not IS_DEV:
        result = execute(
            """
            INSERT INTO outreach_intentos
                (lead_id, matrix_id, tipo, email_destino, asunto, cuerpo, estado, programado_para)
            VALUES (%s, %s, %s, %s, %s, %s, 'pendiente', %s)
            RETURNING id
            """,
            (req.lead_id, msg['id'], req.tipo, email_destino,
             asunto_final, cuerpo_final, datetime.utcnow())
        )
        intento_id = result['id']

        # Actualizar contacto_status del lead
        execute(
            "UPDATE leads_brutos SET contacto_status = 'activo' WHERE id = %s AND contacto_status = 'pendiente'",
            (req.lead_id,)
        )

        # Incrementar contador en matrix
        increment_sent(msg['id'])
    else:
        intento_id = 0  # dry-run

    return PrepareResponse(
        lead_id=req.lead_id,
        intento_id=intento_id,
        email_destino=email_destino,
        asunto=asunto_final,
        cuerpo=cuerpo_final,
        matrix_id=msg['id'],
        tipo=req.tipo,
        is_dry_run=IS_DEV,
    )


@router.post("/cascade", response_model=CascadeResponse)
def handle_bounce_cascade(req: CascadeRequest):
    """
    Cuando Instantly reporta un bounce_hard, n8n llama este endpoint.
    Devuelve el siguiente email disponible en el cascade para ese lead.
    """
    siguiente, razon = get_next_email(req.lead_id, req.email_fallido)

    # Registrar el bounce en el intento original
    if not IS_DEV and req.intento_id > 0:
        execute(
            "UPDATE outreach_intentos SET estado = 'bounce_hard', bounce_at = %s WHERE id = %s",
            (datetime.utcnow(), req.intento_id)
        )

    if siguiente is None:
        # Sin más opciones — marcar lead como sin_contacto
        if not IS_DEV:
            execute(
                "UPDATE leads_brutos SET contacto_status = 'sin_contacto' WHERE id = %s",
                (req.lead_id,)
            )

    return CascadeResponse(
        lead_id=req.lead_id,
        siguiente_email=siguiente,
        hay_siguiente=siguiente is not None,
        razon=razon,
    )


@router.get("/lead/{lead_id}/status")
def get_lead_outreach_status(lead_id: int):
    """
    Devuelve el estado de outreach de un lead: todos sus intentos y eventos.
    Útil para debugging y revisión manual.
    """
    lead = fetch_one(
        "SELECT id, nombre, contacto_status, score FROM leads_brutos WHERE id = %s",
        (lead_id,)
    )
    if not lead:
        raise HTTPException(status_code=404, detail=f"Lead {lead_id} no encontrado")

    from database import fetch_all
    intentos = fetch_all(
        """
        SELECT id, tipo, email_destino, asunto, estado,
               programado_para, enviado_at, bounce_at, respondio_at
        FROM outreach_intentos
        WHERE lead_id = %s
        ORDER BY creado_at DESC
        """,
        (lead_id,)
    )

    return {
        "lead": dict(lead),
        "intentos": [dict(i) for i in intentos] if intentos else [],
    }
