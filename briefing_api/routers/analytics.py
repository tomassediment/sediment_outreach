from fastapi import APIRouter
from database import fetch_all

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
