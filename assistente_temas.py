# -*- coding: utf-8 -*-
"""Respostas locais sobre dengue: sintomas e orientação geral. Não faz diagnóstico."""
import unicodedata

AVISO_NAO_DIAGNOSTICO = (
    "Isto não é um diagnóstico.\n"
    "Só um profissional de saúde pode avaliar o caso."
)

_SINTOMAS = (
    ("vomito persistente", "Vômito persistente", True),
    ("vomitos persistentes", "Vômito persistente", True),
    ("sangramento na gengiva", "Sangramento na gengiva", True),
    ("gengiva sangrando", "Sangramento na gengiva", True),
    ("sangue na urina", "Sangue na urina", True),
    ("sangue nas fezes", "Sangue nas fezes", True),
    ("dor abdominal intensa", "Dor abdominal intensa", True),
    ("dor abdominal forte", "Dor abdominal intensa", True),
    ("dor atras dos olhos", "Dor atrás dos olhos", False),
    ("dor atras do olho", "Dor atrás dos olhos", False),
    ("dor retroorbitaria", "Dor atrás dos olhos", False),
    ("dor nas articulacoes", "Dor nas articulações", False),
    ("dor na articulacao", "Dor nas articulações", False),
    ("dor no corpo", "Dor no corpo", False),
    ("dor muscular", "Dor muscular", False),
    ("dor de cabeca", "Dor de cabeça", False),
    ("manchas na pele", "Manchas na pele", False),
    ("mal estar", "Mal-estar", False),
    ("sonolencia", "Sonolência", True),
    ("prostracao", "Prostração", True),
    ("sangramento", "Sangramento", True),
    ("confusao mental", "Confusão mental", True),
    ("dificuldade para respirar", "Dificuldade para respirar", True),
    ("febre", "Febre", False),
    ("cefaleia", "Dor de cabeça", False),
    ("mialgia", "Dor muscular", False),
    ("artralgia", "Dor nas articulações", False),
    ("mancha", "Manchas na pele", False),
    ("exantema", "Manchas na pele", False),
    ("nausea", "Náusea", False),
    ("enjoo", "Náusea", False),
    ("vomito", "Vômito", False),
    ("cansaco", "Cansaço", False),
    ("fadiga", "Cansaço", False),
)


def normalizar_texto_pergunta(valor):
    valor = unicodedata.normalize("NFKD", str(valor or ""))
    return "".join(ch for ch in valor if not unicodedata.combining(ch)).lower()


def sintomas_citados(texto):
    q = normalizar_texto_pergunta(texto)
    encontrados = []
    vistos = set()
    restantes = q
    for alias, rotulo, alerta in sorted(_SINTOMAS, key=lambda item: len(item[0]), reverse=True):
        if alias in restantes and rotulo not in vistos:
            encontrados.append({"rotulo": rotulo, "alerta": alerta})
            vistos.add(rotulo)
            restantes = restantes.replace(alias, " ")
    return encontrados


def _linhas(itens):
    if not itens:
        return "Nenhum citado na mensagem."
    return "\n".join(f"• {item}" for item in itens)


def _resposta_lista_sintomas():
    compativeis = []
    alertas = []
    for _alias, rotulo, alerta in _SINTOMAS:
        destino = alertas if alerta else compativeis
        if rotulo not in destino:
            destino.append(rotulo)
    texto = (
        "Sintomas mais citados na dengue\n"
        f"{_linhas(compativeis)}\n\n"
        "Sinais de alerta\n"
        f"{_linhas(alertas)}\n\n"
        "Quando procurar atendimento\n"
        "Procure um serviço de saúde se a febre vier com muito mal-estar, se os sintomas piorarem "
        "ou se aparecer qualquer sinal de alerta.\n\n"
        f"{AVISO_NAO_DIAGNOSTICO}"
    )
    return texto, "orientação geral sobre dengue"


def _resposta_comparacao(citados):
    compativeis = [item["rotulo"] for item in citados if not item["alerta"]]
    alertas = [item["rotulo"] for item in citados if item["alerta"]]
    if alertas:
        conduta = (
            "Conduta\n"
            "Há sinal de alerta na sua descrição. Procure atendimento de saúde agora. "
            "Não espere piorar para ser avaliado."
        )
    else:
        conduta = (
            "Conduta\n"
            "Esses sinais podem aparecer na dengue e também em outras doenças. "
            "Procure um serviço de saúde, principalmente se a febre continuar, se o mal-estar aumentar "
            "ou se surgir vômito persistente, dor abdominal intensa, sangramento ou sonolência."
        )
    texto = (
        "O que você descreveu\n"
        f"{_linhas([item['rotulo'] for item in citados])}\n\n"
        "Compatível com quadros de dengue\n"
        f"{_linhas(compativeis) if compativeis else 'Nenhum sintoma comum foi reconhecido além dos sinais de alerta.'}\n\n"
        "Sinais de alerta na mensagem\n"
        f"{_linhas(alertas) if alertas else 'Nenhum dos sinais de alerta mais citados apareceu na mensagem.'}\n\n"
        f"{conduta}\n\n"
        f"{AVISO_NAO_DIAGNOSTICO}"
    )
    return texto, "comparação de sintomas"


def _resposta_o_que_e():
    return (
        "O que é\n"
        "A dengue é uma doença viral transmitida pela picada do mosquito Aedes aegypti.\n\n"
        "Como se espalha\n"
        "O mosquito se infecta ao picar uma pessoa doente e pode transmitir o vírus em picadas seguintes. "
        "Não passa de pessoa para pessoa pelo ar.\n\n"
        "O que este sistema faz\n"
        "O painel estima risco por bairro com dados do projeto. Isso não diz se uma pessoa está doente.\n\n"
        f"{AVISO_NAO_DIAGNOSTICO}"
    ), "orientação geral sobre dengue"


def _resposta_mosquito():
    return (
        "O mosquito\n"
        "O principal transmissor da dengue é o Aedes aegypti. "
        "Ele é escuro e tem manchas brancas no corpo e nas pernas.\n\n"
        "Como ele vive\n"
        "Pica sobretudo de dia e se cria em água parada limpa, dentro e perto de casa.\n\n"
        "O que ele pode transmitir\n"
        "Além da dengue, o mesmo mosquito pode transmitir zika e chikungunya.\n\n"
        f"{AVISO_NAO_DIAGNOSTICO}"
    ), "orientação geral sobre dengue"


def _resposta_transmissao():
    return (
        "Transmissão\n"
        "A dengue é transmitida pela picada do mosquito Aedes aegypti infectado.\n\n"
        "Onde o mosquito se cria\n"
        "Ele usa água parada limpa: caixas d’água, calhas, vasos, pneus e recipientes no quintal.\n\n"
        "O que não transmite\n"
        "A doença não passa pelo abraço, pela fala nem pelo ar.\n\n"
        f"{AVISO_NAO_DIAGNOSTICO}"
    ), "orientação geral sobre dengue"


def _resposta_incubacao():
    return (
        "Incubação\n"
        "Em geral, os sintomas começam alguns dias depois da picada, com frequência entre 4 e 10 dias. "
        "O prazo varia de pessoa para pessoa.\n\n"
        "O que observar\n"
        "Febre, dor no corpo, dor atrás dos olhos, dor de cabeça, manchas, náusea ou cansaço.\n\n"
        f"{AVISO_NAO_DIAGNOSTICO}"
    ), "orientação geral sobre dengue"


def _resposta_gripe():
    return (
        "Dengue e resfriado\n"
        "Os dois podem causar febre, cansaço e dor no corpo. A dengue costuma cursar com febre mais alta, "
        "dor atrás dos olhos, dor intensa no corpo ou nas juntas e, às vezes, manchas na pele.\n\n"
        "Limite desta comparação\n"
        "Esses sinais também aparecem em outras doenças. A diferença não se fecha por uma lista de sintomas.\n\n"
        f"{AVISO_NAO_DIAGNOSTICO}"
    ), "orientação geral sobre dengue"


def _resposta_quando_procurar():
    return (
        "Procure atendimento\n"
        "• Febre com muito mal-estar\n"
        "• Vômito persistente\n"
        "• Dor abdominal intensa\n"
        "• Sangramento, inclusive na gengiva\n"
        "• Sonolência, confusão ou dificuldade para respirar\n"
        "• Sintomas que pioram depois de uma melhora inicial\n\n"
        "Não espere um exame caseiro\n"
        "Um serviço de saúde avalia o quadro, a hidratação e a necessidade de exame.\n\n"
        f"{AVISO_NAO_DIAGNOSTICO}"
    ), "orientação geral sobre dengue"


def _resposta_cuidado_em_casa():
    return (
        "Enquanto aguarda avaliação\n"
        "• Descanse\n"
        "• Beba líquidos com frequência, se não houver restrição médica\n"
        "• Observe febre, vômito, dor na barriga e sangramento\n\n"
        "Medicamentos\n"
        "Não use aspirina nem ibuprofeno por conta própria em suspeita de dengue. "
        "Esses remédios podem aumentar o risco de sangramento. Pergunte a um profissional o que pode tomar.\n\n"
        f"{AVISO_NAO_DIAGNOSTICO}"
    ), "orientação geral sobre dengue"


def _pergunta_pessoal(q):
    return any(x in q for x in (
        "estou", "tenho", "sinto", "senti", "comecei", "acordei", "bate", "combina",
        "pode ser", "sera dengue", "e dengue", "to com", "tou com", "ta com",
    ))


def _consulta_de_bairro(q, citados):
    if citados and _pergunta_pessoal(q):
        return False
    if citados and not any(x in q for x in ("quais", "qual o", "qual a", "lista", "o que e", "o que sao")):
        return False
    return any(x in q for x in ("risco", "casos", "tendencia", "previsao", "ranking", "bairro"))


def resposta_tema_dengue(texto):
    """Responde temas educativos. Devolve None quando a pergunta é de chuva, ranking ou risco do bairro."""
    q = normalizar_texto_pergunta(texto)
    if not q.strip():
        return None
    if any(x in q for x in ("chuva", "chover", "precipitacao", "clima")) and "sintoma" not in q and "febre" not in q:
        return None

    citados = sintomas_citados(q)
    if _consulta_de_bairro(q, citados) and not any(x in q for x in ("sintoma", "gripe", "resfriado", "incub")):
        return None

    if citados and (_pergunta_pessoal(q) or "sintoma" not in q):
        if not any(x in q for x in ("quais os sintomas", "quais sao os sintomas", "sintomas da dengue", "sintomas de dengue")):
            return _resposta_comparacao(citados)

    if any(x in q for x in ("sintoma", "sinais de alerta", "sinais da dengue")):
        return _resposta_lista_sintomas()

    if any(x in q for x in ("o que e dengue", "o que e a dengue", "definicao de dengue")):
        return _resposta_o_que_e()
    if any(x in q for x in ("o que e o mosquito", "que mosquito", "qual o mosquito", "qual mosquito", "mosquito da dengue", "aedes aegypti")):
        return _resposta_mosquito()
    if any(x in q for x in ("transmiss", "transmit", "como pega", "como transmite", "aedes", "como se pega")):
        return _resposta_transmissao()
    if "incub" in q:
        return _resposta_incubacao()
    if any(x in q for x in ("gripe", "resfriado", "diferenca", "covid")):
        return _resposta_gripe()
    if any(x in q for x in ("procurar", "pronto socorro", "pronto-socorro", "unidade de saude", "quando ir", "medico", "upa", "hospital")):
        return _resposta_quando_procurar()
    if any(x in q for x in ("aspirina", "ibuprofeno", "aas", "dipirona", "remedio", "medicamento", "hidrat", "repouso", "o que tomar")):
        return _resposta_cuidado_em_casa()
    if any(x in q for x in ("pode ser dengue", "sera dengue", "tenho dengue", "estou com dengue", "bate com")):
        return _resposta_lista_sintomas()
    return None
