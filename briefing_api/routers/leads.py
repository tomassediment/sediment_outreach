from fastapi import APIRouter, Query
from typing import Optional

from database import fetch_all
from services.email_validator import build_email_cascade

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
