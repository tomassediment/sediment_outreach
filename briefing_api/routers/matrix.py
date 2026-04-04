from fastapi import APIRouter, HTTPException
from services.matrix_selector import get_message

router = APIRouter()


@router.get("/{tipo}/{vertical}/{stack}")
def get_matrix_message(tipo: str, vertical: str, stack: str, version: str = 'A'):
    """
    Devuelve el mensaje de la matriz para una combinación dada.
    Útil para preview y debugging desde n8n o Postman.
    """
    msg = get_message(tipo, vertical, stack, version)
    if not msg:
        raise HTTPException(
            status_code=404,
            detail=f"No hay mensaje para tipo={tipo}, vertical={vertical}, stack={stack}, version={version}"
        )
    return msg
