from fastapi import APIRouter, Query

from database import fetch_all, execute
from services.email_validator import build_email_cascade
from services.enrichment_service import enrich_lead

router = APIRouter()


@router.get("/batch_for_outreach")
def batch_for_outreach(
    vertical: str,
    limit: int = Query(default=35, ge=1, le=200),
    min_score: int = Query(default=65, ge=0, le=100),
):
    """
    Devuelve hasta `limit` leads elegibles para el batch semanal de outreach.

    Criterios de elegibilidad:
    - vertical_consolidada = vertical solicitado
    - contacto_status = 'pendiente'
    - score >= min_score
    - Sin intentos previos de tipo 'primer_contacto' (no cancelados)
    - Tiene al menos un email válido en su cascade

    Ordenados por (score + stack_score) DESC — los mejores leads primero.

    Se recomienda pedir un 40-50% más del target real (ej: pedir 42 para garantizar 30
    efectivos, dado que algunos leads pueden no pasar la validación de cascade).
    """
    # Candidatos: buscamos más de los necesarios porque algunos no tendrán cascade válido
    candidatos = fetch_all(
        """
        SELECT
            lb.id, lb.nombre, lb.ciudad, lb.pais,
            lb.vertical_consolidada, lb.stack_categoria,
            lb.score, lb.stack_score,
            lb.emails_sitio, lb.email_fuente, lb.web_url,
            (lb.score + COALESCE(lb.stack_score, 0)) AS score_total
        FROM leads_brutos lb
        WHERE lb.vertical_consolidada = %s
          AND lb.contacto_status = 'pendiente'
          AND lb.score >= %s
          AND NOT EXISTS (
              SELECT 1 FROM outreach_intentos oi
              WHERE oi.lead_id = lb.id
                AND oi.tipo = 'primer_contacto'
                AND oi.estado != 'cancelado'
          )
        ORDER BY COALESCE(lb.stack_score, 0) DESC
        LIMIT %s
        """,
        (vertical, min_score, limit * 2)  # buscar el doble para tener buffer de validación
    )

    if not candidatos:
        return {"leads": [], "total": 0, "vertical": vertical}

    # Filtrar solo los que tienen cascade válido (al menos 1 email utilizable)
    leads_validos = []
    for lead in candidatos:
        cascade = build_email_cascade(
            emails_sitio=lead['emails_sitio'],
            email_fuente=lead['email_fuente'],
            web_url=lead['web_url'],
        )
        if cascade:
            lead_dict = dict(lead)
            lead_dict['cascade_count'] = len(cascade)  # info útil para n8n
            lead_dict.pop('emails_sitio', None)         # no exponer emails en la respuesta
            lead_dict.pop('email_fuente', None)
            leads_validos.append(lead_dict)

        if len(leads_validos) >= limit:
            break

    return {
        "leads": leads_validos,
        "total": len(leads_validos),
        "vertical": vertical,
        "min_score": min_score,
    }


@router.post("/discover-web-extended")
def discover_web_extended(batch_size: int = Query(default=10, ge=1, le=50)):
    """
    Pipeline de enriquecimiento de emails.
    Toma leads sin email con MX válido y corre: scraping → Hunter → Snov → ZeroBounce/Abstract.
    Actualiza emails_sitio en leads_brutos si encuentra algo.
    Llamado por Flujo 2.1 cada 10 minutos.
    """
    candidatos = fetch_all(
        """
        SELECT id, web_url, score, stack_score
        FROM leads_brutos
        WHERE mx_records = 'TRUE'
          AND (emails_sitio IS NULL OR emails_sitio = '')
          AND (email_fuente IS NULL OR email_fuente = '')
          AND contacto_status = 'pendiente'
        ORDER BY score DESC NULLS LAST, stack_score DESC NULLS LAST
        LIMIT %s
        """,
        (batch_size,)
    )

    if not candidatos:
        return {"processed": 0, "found": 0, "updated": 0}

    found = 0
    updated = 0

    for lead in candidatos:
        lead_dict = dict(lead)
        email = enrich_lead(lead_dict)
        if email:
            found += 1
            result = execute(
                "UPDATE leads_brutos SET emails_sitio = %s WHERE id = %s RETURNING id",
                (email, lead_dict['id'])
            )
            if result:
                updated += 1

    return {
        "processed": len(candidatos),
        "found": found,
        "updated": updated,
    }
