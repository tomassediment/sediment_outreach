from fastapi import APIRouter, HTTPException
from datetime import datetime
from typing import Optional
from pydantic import BaseModel

from config import get_settings
from database import fetch_one, fetch_all, execute
from models.outreach import PrepareRequest, PrepareResponse, CascadeRequest, CascadeResponse
from services.email_validator import build_email_cascade
from services.matrix_selector import get_message, increment_sent
from services.email_builder import build_email, build_subject
from services.cascade_service import get_next_email
from services.enrichment_service import verify_zerobounce


class MarkSentRequest(BaseModel):
    intento_id: int
    instantly_id: Optional[str] = None  # deprecated — era para Instantly. Opcional post-migración a Gmail API.


class MarkBouncesRequest(BaseModel):
    email_destinos: list[str]  # lista de emails que hicieron bounce según Gmail

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
        verify_fn=verify_zerobounce,
    )
    if not cascade:
        # Actualizar status y rechazar
        if not IS_DEV:
            execute(
                "UPDATE leads_brutos SET contacto_status = 'sin_contacto' WHERE id = %s",
                (req.lead_id,)
            )
        raise HTTPException(
            status_code=422,
            detail=f"Lead {req.lead_id} no tiene emails válidos. Marcado como sin_contacto."
        )

    email_real = cascade[0]
    # DEV SAFETY: si hay dev_email_override, redirigir todos los envíos a esa dirección
    email_destino = settings.dev_email_override if (IS_DEV and settings.dev_email_override) else email_real

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
    send_at = req.programado_para or datetime.utcnow()
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
             asunto_final, cuerpo_final, send_at)
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
        email_real=email_real if (IS_DEV and settings.dev_email_override) else None,
        asunto=asunto_final,
        cuerpo=cuerpo_final,
        matrix_id=msg['id'],
        tipo=req.tipo,
        programado_para=send_at,
        is_dry_run=IS_DEV,
    )


@router.get("/pending")
def get_pending_intentos():
    """
    Devuelve todos los intentos listos para enviar:
    - estado = 'pendiente'
    - programado_para <= NOW()
    - LEFT JOIN leads_brutos: excluye leads que respondieron; Apollo (lead_id NULL) siempre pasa.

    Usado por el Flujo B (Dispatcher) cada 30 minutos.
    """
    intentos = fetch_all(
        """
        SELECT
            oi.id AS intento_id,
            oi.lead_id,
            oi.tipo,
            oi.email_destino,
            oi.asunto,
            oi.cuerpo,
            oi.matrix_id,
            oi.programado_para
        FROM outreach_intentos oi
        LEFT JOIN leads_brutos lb ON lb.id = oi.lead_id
        WHERE oi.estado = 'pendiente'
          AND oi.programado_para <= NOW()
          AND (lb.contacto_status != 'respondio' OR oi.lead_id IS NULL)
        ORDER BY oi.programado_para ASC
        """,
        ()
    )
    return {
        "intentos": [dict(i) for i in intentos] if intentos else [],
        "total": len(intentos) if intentos else 0,
    }


@router.post("/mark_sent")
def mark_sent(req: MarkSentRequest):
    """
    Marca un intento como enviado tras confirmación de Instantly.
    Registra el instantly_id para correlacionar eventos futuros (bounces, replies).
    Incrementa el contador emails_enviados en message_matrix.

    Usado por el Flujo B (Dispatcher) después de cada envío exitoso.
    """
    intento = fetch_one(
        "SELECT id, matrix_id FROM outreach_intentos WHERE id = %s",
        (req.intento_id,)
    )
    if not intento:
        raise HTTPException(status_code=404, detail=f"Intento {req.intento_id} no encontrado")

    execute(
        """
        UPDATE outreach_intentos
        SET estado = 'enviado', enviado_at = %s, instantly_id = %s
        WHERE id = %s
        """,
        (datetime.utcnow(), req.instantly_id or '', req.intento_id)
    )

    # Incrementar contador en la versión de matrix usada
    if intento['matrix_id']:
        increment_sent(intento['matrix_id'])

    return {"status": "ok", "intento_id": req.intento_id, "instantly_id": req.instantly_id}


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


@router.post("/prepare_apollo")
def prepare_outreach_apollo(req: dict):
    """
    Versión de /prepare para leads Apollo.
    Si recibe email_cuerpo: el cuerpo viene generado por Gemini (prompt maestro).
    Asunto sigue saliendo de message_matrix (solo el subject, no el body).
    Registra en outreach_intentos y actualiza el apollo_lead.
    """
    apollo_lead_id = req.get("apollo_lead_id")
    tipo = req.get("tipo", "primer_contacto")
    email_cuerpo = req.get("email_cuerpo")

    lead = fetch_one(
        "SELECT * FROM apollo_leads WHERE id = %s AND estado = 'pendiente'",
        (apollo_lead_id,)
    )
    if not lead:
        raise HTTPException(status_code=404, detail=f"Apollo lead {apollo_lead_id} no encontrado o ya procesado")

    empresa = lead['empresa'] or 'su empresa'
    vertical = lead['vertical'] or 'sin_clasificar'
    stack = lead['stack_categoria'] or 'sin_stack'

    # Asunto: siempre desde matrix
    msg = get_message(tipo, vertical, stack) or get_message(tipo, 'sin_clasificar', 'sin_stack')
    if not msg:
        raise HTTPException(status_code=404, detail=f"Sin plantilla de asunto en matrix para {tipo}/{vertical}/{stack}")
    asunto_gemini_override = req.get("asunto_gemini")
    if asunto_gemini_override and len(asunto_gemini_override.strip()) > 10:
        asunto_final = asunto_gemini_override.strip()
    else:
        asunto_final = build_subject(msg['asunto'], empresa)

    # Cuerpo: Gemini (email_cuerpo) o fallback a intro+matrix para retrocompatibilidad
    if email_cuerpo and len(email_cuerpo.strip()) > 50:
        cuerpo_final = email_cuerpo.strip()
    else:
        nombre = lead['nombre_decisor'] or ''
        saludo = f"{nombre.split()[0]}," if nombre else "Hola,"
        intro = req.get("mensaje_intro") or lead.get('mensaje_intro') or ''
        slot_1 = req.get("slot_1", "")
        slot_2 = req.get("slot_2", "")
        cuerpo_matrix = build_email(msg['cuerpo'], empresa, slot_1, slot_2)
        cuerpo_final = f"{saludo}\n\n{intro}\n\n{cuerpo_matrix}" if intro else f"{saludo}\n\n{cuerpo_matrix}"

    # Registrar en outreach_intentos (lead_id NULL — Apollo es fuente separada)
    ahora = datetime.utcnow()
    result = execute(
        """
        INSERT INTO outreach_intentos
            (lead_id, matrix_id, tipo, email_destino, asunto, cuerpo, estado, programado_para)
        VALUES (NULL, %s, %s, %s, %s, %s, 'pendiente', %s)
        RETURNING id
        """,
        (msg['id'], tipo, lead['email'], asunto_final, cuerpo_final, ahora)
    )
    intento_id = result['id']

    execute(
        "UPDATE apollo_leads SET outreach_intento_id = %s, estado = 'enviado', contactado_at = %s WHERE id = %s",
        (intento_id, ahora, apollo_lead_id)
    )
    increment_sent(msg['id'])

    return {
        "apollo_lead_id": apollo_lead_id,
        "intento_id": intento_id,
        "email_destino": lead['email'],
        "asunto": asunto_final,
        "cuerpo": cuerpo_final,
        "matrix_id": msg['id'],
    }


@router.post("/mark_bounces")
def mark_bounces(req: MarkBouncesRequest):
    """
    Recibe una lista de emails que hicieron bounce según Gmail.
    1. Marca outreach_intentos como bounce_hard.
    2. Para leads Apollo: si tiene email_secundario → crea nuevo intento; si no → sin_contacto.
    """
    if not req.email_destinos:
        return {"status": "ok", "marcados": 0}

    marcados = 0
    reintentos_apollo = 0
    ahora = datetime.utcnow()

    for email in req.email_destinos:
        email_clean = email.strip().lower()

        execute(
            """
            UPDATE outreach_intentos
            SET estado = 'bounce_hard', bounce_at = %s
            WHERE email_destino = %s
              AND estado = 'enviado'
              AND bounce_at IS NULL
            """,
            (ahora, email_clean)
        )

        # Cascade Apollo: buscar si este email pertenece a un apollo_lead
        apollo_lead = fetch_one(
            "SELECT id, email_secundario, vertical, stack_categoria, empresa, nombre_decisor FROM apollo_leads WHERE email = %s AND estado IN ('enviado', 'bounce')",
            (email_clean,)
        )
        if apollo_lead:
            execute(
                "UPDATE apollo_leads SET estado = 'bounce' WHERE id = %s",
                (apollo_lead['id'],)
            )
            if apollo_lead['email_secundario']:
                # Crear nuevo intento con email secundario
                vertical = apollo_lead['vertical'] or 'sin_clasificar'
                stack = apollo_lead['stack_categoria'] or 'sin_stack'
                msg = get_message('primer_contacto', vertical, stack)
                if not msg:
                    msg = get_message('primer_contacto', 'sin_clasificar', 'sin_stack')
                if msg:
                    empresa = apollo_lead['empresa'] or 'su empresa'
                    cuerpo = build_email(msg['cuerpo'], empresa, '', '')
                    asunto = build_subject(msg['asunto'], empresa)
                    execute(
                        """
                        INSERT INTO outreach_intentos
                            (lead_id, matrix_id, tipo, email_destino, asunto, cuerpo, estado, programado_para)
                        VALUES (NULL, %s, 'primer_contacto', %s, %s, %s, 'pendiente', %s)
                        """,
                        (msg['id'], apollo_lead['email_secundario'], asunto, cuerpo, ahora)
                    )
                    execute(
                        "UPDATE apollo_leads SET email = %s, estado = 'pendiente' WHERE id = %s",
                        (apollo_lead['email_secundario'], apollo_lead['id'])
                    )
                    reintentos_apollo += 1
            else:
                execute(
                    "UPDATE apollo_leads SET estado = 'sin_contacto' WHERE id = %s",
                    (apollo_lead['id'],)
                )

        # También marcar leads_brutos sin_contacto si aplica
        execute(
            """
            UPDATE leads_brutos
            SET contacto_status = 'sin_contacto'
            WHERE id IN (
                SELECT DISTINCT lead_id
                FROM outreach_intentos
                WHERE email_destino = %s AND lead_id IS NOT NULL
            )
            AND NOT EXISTS (
                SELECT 1 FROM outreach_intentos
                WHERE lead_id = leads_brutos.id
                  AND estado NOT IN ('bounce_hard', 'sin_contacto')
            )
            """,
            (email_clean,)
        )
        marcados += 1

    return {
        "status": "ok",
        "marcados": marcados,
        "reintentos_apollo": reintentos_apollo,
        "procesados": len(req.email_destinos),
    }


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
