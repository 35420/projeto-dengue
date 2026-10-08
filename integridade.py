# -*- coding: utf-8 -*-
"""Regras de nome de bairro, origem do registro e proteção contra mistura de fontes."""
import difflib
import re
import unicodedata
from collections import deque
from urllib.parse import urlparse

LIMIAR_CASAMENTO_BAIRRO = 0.93
LIMIAR_TAMANHO_NOME = 0.75


def normalizar_nome_bairro(valor):
    texto = unicodedata.normalize("NFKD", str(valor or "")).encode("ascii", "ignore").decode("ascii")
    texto = texto.upper().strip()
    texto = re.sub(r"[./,_-]+", " ", texto)
    for abrev, extenso in (
        ("JD", "JARDIM"),
        ("VL", "VILA"),
        ("PQ", "PARQUE"),
        ("RES", "RESIDENCIAL"),
        ("CONJ", "CONJUNTO"),
        ("PROL", "PROLONGAMENTO"),
        ("COND", "CONDOMINIO"),
    ):
        texto = re.sub(rf"\b{abrev}\.?\b", extenso, texto)
    texto = re.sub(r"[^A-Z0-9 ]+", " ", texto)
    return re.sub(r"\s+", " ", texto).strip()


def chaves_nome_bairro(valor):
    base = normalizar_nome_bairro(valor)
    sem_genericos = re.sub(
        r"\b(JARDIM|VILA|PARQUE|RESIDENCIAL|CONJUNTO|PROLONGAMENTO|CONDOMINIO|CHACARA|CHACARAS|BAIRRO)\b",
        " ",
        base,
    )
    sem_genericos = re.sub(r"\s+", " ", sem_genericos).strip()
    return {base, sem_genericos}


def _score_nome(alvo, chave):
    if not alvo or not chave or len(alvo) < 5 or len(chave) < 5:
        return 0.0
    menor, maior = sorted((len(alvo), len(chave)))
    if menor / maior < LIMIAR_TAMANHO_NOME:
        return 0.0
    return difflib.SequenceMatcher(None, alvo, chave).ratio()


def melhor_bairro_oficial(nome, indice, limiar=LIMIAR_CASAMENTO_BAIRRO):
    """Casa um nome externo com a base local. Semelhança fraca não grava caso no bairro errado."""
    chaves = chaves_nome_bairro(nome)
    for chave in chaves:
        if chave and chave in indice:
            return indice[chave]
    melhor = None
    score_max = 0.0
    for chave, registro in indice.items():
        for alvo in chaves:
            score = _score_nome(alvo, chave)
            if score > score_max:
                score_max = score
                melhor = registro
    return melhor if score_max >= limiar else None


def _texto(valor):
    return str(valor or "").strip().lower()


def origem_permite_treino(origem, casos_origem):
    """Série sintética não entra no modelo, mesmo que o rótulo geral tenha sido reescrito."""
    o = _texto(origem)
    c = _texto(casos_origem)
    if o.startswith("demonstr") or c.startswith("demonstr"):
        return False
    if c.startswith("automatico") or c in {"manual", "importado"}:
        return True
    return o in {"manual", "importado", "sinan/dengue"}


def registro_protegido_contra_fonte_automatica(origem, casos_origem):
    o = _texto(origem)
    c = _texto(casos_origem)
    return o in {"manual", "importado"} or c in {"manual", "importado"}


def focos_sao_observados(focos_origem):
    o = _texto(focos_origem)
    return o in {"manual", "importado"} or o.startswith("automatico")


def populacao_confiavel(populacao, populacao_origem):
    """O placeholder sem fonte fica de fora. Estimativa já gravada ou dado do IBGE entra na incidência."""
    try:
        if populacao is None or int(populacao) <= 0:
            return False
    except (TypeError, ValueError):
        return False
    origem = _texto(populacao_origem)
    return origem not in {"", "nao_informada", "consolidado franca/sp"}


def consumir_janela(fila, agora, limite, janela_segundos):
    """Rate limit em memória. `fila` é um deque de timestamps."""
    if not isinstance(fila, deque):
        raise TypeError("fila deve ser collections.deque")
    while fila and agora - fila[0] > janela_segundos:
        fila.popleft()
    if len(fila) >= limite:
        return False
    fila.append(agora)
    return True


def origem_http_permitida(host, origin, referer, remote_addr):
    """POST same-origin passa. Sem Origin/Referer, só o acesso local."""
    if origin:
        return urlparse(origin).netloc == host
    if referer:
        return urlparse(referer).netloc == host
    return remote_addr in ("127.0.0.1", "::1")


def gravar_casos_sinan(conn, bairro_id, periodo, casos, fonte):
    """Grava casos do SINAN sem substituir cadastro manual ou CSV e sem manter foco sintético."""
    cur = conn.execute(
        """
        INSERT INTO dados_historicos (
            bairro_id, periodo, casos_dengue, chuva_mm, temperatura_media, focos_mosquito,
            origem, casos_origem, focos_origem, chuva_origem, temperatura_origem
        ) VALUES (?, ?, ?, 0, 0, 0, ?, ?, 'ausente', 'ausente', 'ausente')
        ON CONFLICT(bairro_id, periodo) DO UPDATE SET
            casos_dengue = excluded.casos_dengue,
            casos_origem = 'automatico - SINAN/Dengue',
            focos_mosquito = CASE
                WHEN lower(COALESCE(dados_historicos.focos_origem, '')) LIKE 'demonstr%' THEN 0
                ELSE dados_historicos.focos_mosquito
            END,
            focos_origem = CASE
                WHEN lower(COALESCE(dados_historicos.focos_origem, '')) LIKE 'demonstr%' THEN 'ausente'
                ELSE dados_historicos.focos_origem
            END,
            origem = CASE
                WHEN lower(COALESCE(dados_historicos.origem, '')) IN ('manual', 'importado')
                    THEN dados_historicos.origem
                ELSE 'SINAN/Dengue'
            END
        WHERE lower(COALESCE(dados_historicos.origem, '')) NOT IN ('manual', 'importado')
          AND lower(COALESCE(dados_historicos.casos_origem, '')) NOT IN ('manual', 'importado')
        """,
        (bairro_id, periodo, int(casos), fonte, "automatico - SINAN/Dengue"),
    )
    return cur.rowcount


def registrar_nomes_ignorados(conn, contagens, agora):
    for nome, qtd in contagens.items():
        conn.execute(
            """
            INSERT INTO sinan_nomes_ignorados (nome, motivo, ocorrencias, atualizado_em)
            VALUES (?, 'sem correspondência segura', ?, ?)
            ON CONFLICT(nome) DO UPDATE SET
                ocorrencias = excluded.ocorrencias,
                atualizado_em = excluded.atualizado_em
            """,
            (str(nome)[:120], int(qtd), agora),
        )


def _copiar_clima_municipal(conn, campo, origem_col):
    conn.execute(
        f"""
        UPDATE dados_historicos
        SET {campo} = (
                SELECT a.{campo}
                FROM dados_ambientais_franca a
                WHERE a.periodo = dados_historicos.periodo AND a.{campo} IS NOT NULL
                ORDER BY a.id DESC
                LIMIT 1
            ),
            {origem_col} = 'automatico'
        WHERE (
                lower(COALESCE({origem_col}, '')) IN ('ausente', '')
                OR lower(COALESCE({origem_col}, '')) LIKE 'demonstr%'
            )
          AND lower(COALESCE(casos_origem, '')) NOT LIKE 'demonstr%'
          AND lower(COALESCE(origem, '')) NOT LIKE 'demonstr%'
          AND EXISTS (
                SELECT 1 FROM dados_ambientais_franca a
                WHERE a.periodo = dados_historicos.periodo AND a.{campo} IS NOT NULL
          )
        """
    )


def sanear_historico_misto(conn):
    """Tira chuva, temperatura e foco sintéticos de linhas cujo caso já veio de fonte real."""
    conn.execute(
        """
        UPDATE dados_historicos
        SET chuva_origem = 'ausente', temperatura_origem = 'ausente'
        WHERE lower(COALESCE(origem, '')) = 'sinan/dengue'
          AND lower(COALESCE(chuva_origem, '')) = 'manual'
          AND lower(COALESCE(temperatura_origem, '')) = 'manual'
          AND COALESCE(chuva_mm, 0) = 0
          AND COALESCE(temperatura_media, 0) = 0
        """
    )
    conn.execute(
        """
        UPDATE dados_historicos
        SET focos_mosquito = 0, focos_origem = 'ausente'
        WHERE lower(COALESCE(focos_origem, '')) LIKE 'demonstr%'
          AND lower(COALESCE(casos_origem, '')) NOT LIKE 'demonstr%'
          AND lower(COALESCE(origem, '')) NOT LIKE 'demonstr%'
        """
    )
    _copiar_clima_municipal(conn, "chuva_mm", "chuva_origem")
    _copiar_clima_municipal(conn, "temperatura_media", "temperatura_origem")
    conn.execute(
        """
        UPDATE dados_historicos
        SET chuva_mm = 0, chuva_origem = 'ausente'
        WHERE lower(COALESCE(chuva_origem, '')) LIKE 'demonstr%'
          AND lower(COALESCE(casos_origem, '')) NOT LIKE 'demonstr%'
          AND lower(COALESCE(origem, '')) NOT LIKE 'demonstr%'
        """
    )
    conn.execute(
        """
        UPDATE dados_historicos
        SET temperatura_media = 0, temperatura_origem = 'ausente'
        WHERE lower(COALESCE(temperatura_origem, '')) LIKE 'demonstr%'
          AND lower(COALESCE(casos_origem, '')) NOT LIKE 'demonstr%'
          AND lower(COALESCE(origem, '')) NOT LIKE 'demonstr%'
        """
    )
