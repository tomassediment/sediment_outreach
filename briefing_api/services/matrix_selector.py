from typing import Optional
from database import fetch_one


def get_message(tipo: str, vertical: str, stack_categoria: str, version: str = 'A') -> Optional[dict]:
    """
    Busca el mensaje correcto en message_matrix.
    Fallback: si no existe la combinación exacta, busca vertical='todos' como comodín.
    """
    query = """
        SELECT id, tipo, vertical, stack_categoria, version, asunto, cuerpo
        FROM message_matrix
        WHERE tipo = %s
          AND vertical = %s
          AND stack_categoria = %s
          AND version = %s
          AND activo = TRUE
        LIMIT 1
    """
    result = fetch_one(query, (tipo, vertical, stack_categoria, version))

    if result:
        return dict(result)

    # Fallback a comodín
    result = fetch_one(query, (tipo, 'todos', 'todos', version))
    return dict(result) if result else None


def increment_sent(matrix_id: int):
    from database import execute
    execute(
        "UPDATE message_matrix SET emails_enviados = emails_enviados + 1 WHERE id = %s",
        (matrix_id,)
    )


def increment_replied(matrix_id: int):
    from database import execute
    execute(
        "UPDATE message_matrix SET emails_respondidos = emails_respondidos + 1 WHERE id = %s",
        (matrix_id,)
    )
