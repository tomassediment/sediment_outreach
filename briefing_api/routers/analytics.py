from fastapi import APIRouter
from database import fetch_all, fetch_one

router = APIRouter()


@router.get("/outreach_summary")
def outreach_summary():
    """
    Métricas de performance por versión de mensaje en message_matrix.
    Muestra solo versiones con al menos 1 envío.
    Ordena por tipo y tasa de respuesta DESC → identifica qué combinaciones funcionan mejor.
    Útil para decidir qué mensajes mejorar o reemplazar (informa la Matriz 3).
    """
    rows = fetch_all(
        """
        SELECT
            m.id,
            m.tipo,
            m.vertical,
            m.stack_categoria,
            m.version,
            m.fecha_desde,
            m.emails_enviados,
            m.emails_respondidos,
            m.tasa_respuesta
        FROM message_matrix m
        WHERE m.emails_enviados > 0
          AND m.activo = TRUE
        ORDER BY m.tipo, m.tasa_respuesta DESC NULLS LAST, m.emails_enviados DESC
        """,
        ()
    )

    if not rows:
        return {"mensaje": "Aún no hay envíos registrados.", "data": []}

    return {
        "data": [dict(r) for r in rows],
        "total_versiones": len(rows),
        "total_enviados": sum(r['emails_enviados'] for r in rows),
        "total_respondidos": sum(r['emails_respondidos'] for r in rows),
    }


@router.get("/weekly_progress")
def weekly_progress():
    """
    Devuelve X: cantidad de leads que ya tienen un primer_contacto enviado esta semana
    y cuyo contacto_status NO es 'sin_contacto'.

    Usado por el Flujo A (Planner Diario) para calcular N = min(ceil((30-X)/D), 15).

    'sin_contacto' se excluye porque ese lead falló el cascade completo —
    no contabiliza como contacto real, y al día siguiente el planner compensa.
    """
    result = fetch_one(
        """
        SELECT COUNT(DISTINCT oi.lead_id) AS x
        FROM outreach_intentos oi
        JOIN leads_brutos lb ON lb.id = oi.lead_id
        WHERE oi.tipo = 'primer_contacto'
          AND oi.estado IN ('pendiente', 'enviado', 'respondio', 'bounce_hard', 'bounce_soft')
          AND oi.creado_at >= date_trunc('week', NOW())
          AND lb.contacto_status != 'sin_contacto'
        """,
        ()
    )
    x = result['x'] if result else 0
    return {
        "x": x,
        "description": "Leads con primer_contacto esta semana (excluye sin_contacto)",
        "semana_inicio": "lunes de la semana actual (date_trunc week)",
    }
