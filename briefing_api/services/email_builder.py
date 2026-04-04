def build_email(cuerpo: str, empresa: str, slot_1: str, slot_2: str) -> str:
    """
    Reemplaza los placeholders del template con los valores reales del lead.
    """
    result = cuerpo
    result = result.replace('[EMPRESA]', empresa)
    result = result.replace('[SLOT_1]', slot_1)
    result = result.replace('[SLOT_2]', slot_2)
    return result


def build_subject(asunto: str, empresa: str) -> str:
    """
    El asunto no usa [EMPRESA] actualmente, pero dejamos el reemplazo
    por si en versiones futuras se personaliza.
    """
    return asunto.replace('[EMPRESA]', empresa)
