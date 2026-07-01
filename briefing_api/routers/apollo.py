from fastapi import APIRouter, HTTPException, Query
from typing import Optional
from pydantic import BaseModel
from datetime import datetime

from database import fetch_one, fetch_all, execute

router = APIRouter()


class ApolloLeadIn(BaseModel):
    apollo_id: str
    nombre_decisor: Optional[str] = None
    cargo: Optional[str] = None
    email: str
    linkedin_url: Optional[str] = None
    empresa: Optional[str] = None
    dominio: Optional[str] = None
    vertical: Optional[str] = None
    pais: Optional[str] = 'Colombia'
    ciudad: Optional[str] = None
    empleados: Optional[int] = None
    tech_stack_apollo: Optional[str] = None
    tech_stack_wappalyzer: Optional[str] = None
    stack_categoria: Optional[str] = None
    mensaje_intro: Optional[str] = None
    email_secundario: Optional[str] = None


@router.get("/check")
def check_apollo_lead(apollo_id: str = Query(...)):
    """
    Verifica si un apollo_id ya existe en la tabla.
    Usado por Flujo 5 para evitar duplicados.
    """
    row = fetch_one("SELECT id FROM apollo_leads WHERE apollo_id = %s", (apollo_id,))
    return {"exists": row is not None}


@router.post("/", status_code=201)
def create_apollo_lead(lead: ApolloLeadIn):
    """
    Guarda un nuevo lead de Apollo. Ignora duplicados (ON CONFLICT DO NOTHING).
    Si el dominio hace match con leads_brutos, enriquece tech_stack_wappalyzer.
    """
    # Intentar enriquecer con Wappalyzer de nuestra BD si no viene ya
    tech_wap = lead.tech_stack_wappalyzer
    stack_cat = lead.stack_categoria
    if lead.dominio and not tech_wap:
        row = fetch_one(
            "SELECT tech_stack, stack_categoria FROM leads_brutos WHERE dominio = %s AND tech_stack IS NOT NULL LIMIT 1",
            (lead.dominio,)
        )
        if row:
            tech_wap = row['tech_stack']
            stack_cat = stack_cat or row['stack_categoria']

    result = execute(
        """
        INSERT INTO apollo_leads
            (apollo_id, nombre_decisor, cargo, email, linkedin_url, empresa, dominio,
             vertical, pais, ciudad, empleados, tech_stack_apollo, tech_stack_wappalyzer,
             stack_categoria, mensaje_intro, email_secundario)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT (apollo_id) DO NOTHING
        RETURNING id
        """,
        (lead.apollo_id, lead.nombre_decisor, lead.cargo, lead.email, lead.linkedin_url,
         lead.empresa, lead.dominio, lead.vertical, lead.pais, lead.ciudad, lead.empleados,
         lead.tech_stack_apollo, tech_wap, stack_cat, lead.mensaje_intro, lead.email_secundario)
    )
    if not result:
        return {"status": "duplicate", "apollo_id": lead.apollo_id}
    return {"status": "created", "id": result['id'], "apollo_id": lead.apollo_id}


@router.get("/pending")
def get_pending_apollo(limit: int = Query(default=10, ge=1, le=50)):
    """
    Devuelve leads de Apollo listos para enviar:
    - estado = 'pendiente'
    - mensaje_intro no nulo (Gemini ya generó la intro)
    Usado por Flujo A para incluir Apollo como fuente primaria.
    """
    rows = fetch_all(
        """
        SELECT id, apollo_id, nombre_decisor, cargo, email, empresa,
               dominio, vertical, ciudad, empleados,
               stack_categoria, tech_stack_apollo, tech_stack_wappalyzer, mensaje_intro
        FROM apollo_leads
        WHERE estado = 'pendiente'
        ORDER BY importado_at ASC
        LIMIT %s
        """,
        (limit,)
    )
    return {
        "leads": [dict(r) for r in rows] if rows else [],
        "total": len(rows) if rows else 0,
    }


@router.patch("/{lead_id}/estado")
def update_apollo_estado(lead_id: int, estado: str, intento_id: Optional[int] = None):
    """
    Actualiza el estado de un lead Apollo.
    Estados válidos: pendiente | enviado | bounce | reply | sin_contacto
    """
    estados_validos = {'pendiente', 'enviado', 'bounce', 'reply', 'sin_contacto'}
    if estado not in estados_validos:
        raise HTTPException(status_code=400, detail=f"Estado inválido. Válidos: {estados_validos}")

    execute(
        """
        UPDATE apollo_leads
        SET estado = %s,
            contactado_at = CASE WHEN %s = 'enviado' THEN NOW() ELSE contactado_at END,
            outreach_intento_id = COALESCE(%s, outreach_intento_id)
        WHERE id = %s
        """,
        (estado, estado, intento_id, lead_id)
    )
    return {"status": "ok", "lead_id": lead_id, "estado": estado}


@router.get("/stats")
def apollo_stats():
    """Resumen del estado actual de la tabla apollo_leads."""
    row = fetch_one(
        """
        SELECT
            COUNT(*) FILTER (WHERE estado = 'pendiente') AS pendientes,
            COUNT(*) FILTER (WHERE estado = 'enviado') AS enviados,
            COUNT(*) FILTER (WHERE estado = 'bounce') AS bounces,
            COUNT(*) FILTER (WHERE estado = 'reply') AS replies,
            COUNT(*) FILTER (WHERE mensaje_intro IS NULL) AS sin_intro,
            COUNT(*) AS total
        FROM apollo_leads
        """, ()
    )
    return dict(row) if row else {}
