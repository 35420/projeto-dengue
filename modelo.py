# -*- coding: utf-8 -*-
"""Previsão temporal de casos. A avaliação compara o modelo com duas referências simples."""
import re

import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

from integridade import focos_sao_observados, origem_permite_treino

PESO_CASOS = 0.35
PESO_FOCOS = 0.30
PESO_CHUVA = 0.20
PESO_TEMPERATURA = 0.15
MINIMO_REGISTROS_MODELO = 20
MIN_SAMPLES_LEAF = 3
# Chuva de referência da pontuação de risco: acima disto o fator de chuva satura.
CHUVA_REFERENCIA_MM = 150.0
PESO_SUBIDA_PROB = 0.60
PESO_CHUVA_PROB = 0.40

FEATURES = [
    "casos_lag1",
    "casos_lag2",
    "media_3",
    "chuva_mm",
    "temperatura_media",
    "umidade_media",
    "focos_mosquito",
    "focos_informado",
]
COLUNAS_MEDIANA = ["chuva_mm", "temperatura_media", "umidade_media"]
NOMES_FATORES = {
    "casos_dengue": "Casos atuais",
    "focos_mosquito": "Focos do mosquito",
    "focos_informado": "Focos informados",
    "chuva_mm": "Chuva",
    "temperatura_media": "Temperatura média",
    "umidade_media": "Umidade média",
    "casos_lag1": "Casos do período anterior",
    "casos_lag2": "Casos de dois períodos atrás",
    "media_3": "Média móvel de 3 períodos",
}


def calcular_risco_formula(casos, chuva, temp, focos, focos_disponiveis=True, num=None):
    def _num(value, default=0.0):
        if num:
            return num(value, default)
        try:
            if value is None or value == "":
                return default
            return float(value)
        except (TypeError, ValueError):
            return default

    casos = max(0.0, _num(casos))
    chuva = max(0.0, _num(chuva))
    temp = _num(temp, 25)
    score_casos = min(100.0, (casos / 40.0) * 100)
    score_chuva = min(100.0, (chuva / 150.0) * 100)
    score_temp = max(0.0, 100 - abs(27 - temp) * 8)
    bruto = (
        score_casos * PESO_CASOS
        + score_chuva * PESO_CHUVA
        + score_temp * PESO_TEMPERATURA
    )
    if focos_disponiveis:
        focos = max(0.0, _num(focos))
        score_focos = min(100.0, (focos / 25.0) * 100)
        risco = bruto + score_focos * PESO_FOCOS
    elif casos > 0:
        peso_disponivel = PESO_CASOS + PESO_CHUVA + PESO_TEMPERATURA
        risco = bruto / peso_disponivel
    else:
        # Casos zerados e focos sem evidência observada: o clima municipal
        # entra com o próprio peso e não herda a fatia dos focos ausentes.
        risco = bruto
    return round(max(0.0, min(100.0, risco)), 1)


def probabilidade_aumento_recente(casos, chuva_mm):
    """Chance de os casos subirem no próximo período, entre 0 e 1.

    60% vem da fração de subidas nos últimos passos (até 3 períodos).
    40% vem da chuva recente: água parada favorece o mosquito.
    Sem par de períodos, usa só a chuva.
    """
    serie = [float(v or 0) for v in (casos or [])][-3:]
    chuva = float(chuva_mm or 0)
    score_chuva = min(1.0, max(0.0, chuva) / CHUVA_REFERENCIA_MM)
    if len(serie) < 2:
        return round(score_chuva, 4)
    subidas = sum(1 for anterior, atual in zip(serie, serie[1:]) if atual > anterior)
    fracao = subidas / (len(serie) - 1)
    valor = PESO_SUBIDA_PROB * fracao + PESO_CHUVA_PROB * score_chuva
    return round(min(1.0, max(0.0, valor)), 4)


def classificar_risco(pontuacao):
    if pontuacao >= 70:
        return "Alto", "vermelho"
    if pontuacao >= 40:
        return "Médio", "amarelo"
    return "Baixo", "verde"


def periodo_ordem(valor):
    texto = str(valor or "")
    m = re.match(r"^(\d{4})[-/](\d{1,2})$", texto)
    if m:
        return int(m.group(1)) * 100 + int(m.group(2))
    nums = [int(x) for x in re.findall(r"\d+", texto)]
    return nums[-1] if nums else 0


def clima_observado(row, ambiental, campo, origem_campo):
    origem = str(row[origem_campo] or "").strip().lower()
    sintetico = origem.startswith("demonstr") or origem in {"", "ausente"}
    if not sintetico and row[campo] is not None:
        return float(row[campo])
    amb = ambiental.get(row["periodo"]) or {}
    valor = amb.get(campo)
    return float(valor) if valor is not None else None


def carregar_ambiental(conn):
    rows = conn.execute(
        """
        SELECT periodo, chuva_mm, temperatura_media, umidade_media
        FROM dados_ambientais_franca
        WHERE periodo IS NOT NULL
        ORDER BY id
        """
    ).fetchall()
    mapa = {}
    for row in rows:
        mapa[row["periodo"]] = {
            "chuva_mm": row["chuva_mm"],
            "temperatura_media": row["temperatura_media"],
            "umidade_media": row["umidade_media"],
        }
    return mapa


def construir_dataset_temporal(conn):
    rows = conn.execute(
        """
        SELECT id, bairro_id, periodo, casos_dengue, chuva_mm, temperatura_media,
               focos_mosquito, origem, casos_origem, chuva_origem, temperatura_origem, focos_origem
        FROM dados_historicos
        """
    ).fetchall()
    ambiental = carregar_ambiental(conn)
    grupos = {}
    for row in rows:
        if not origem_permite_treino(row["origem"], row["casos_origem"]):
            continue
        grupos.setdefault(row["bairro_id"], []).append(row)

    exemplos = []
    for bairro_id, itens in grupos.items():
        itens.sort(key=lambda x: (periodo_ordem(x["periodo"]), x["id"]))
        for i in range(2, len(itens)):
            prev1 = itens[i - 1]
            prev2 = itens[i - 2]
            if i >= 3:
                media3 = (
                    itens[i - 1]["casos_dengue"]
                    + itens[i - 2]["casos_dengue"]
                    + itens[i - 3]["casos_dengue"]
                ) / 3
            else:
                media3 = (itens[i - 1]["casos_dengue"] + itens[i - 2]["casos_dengue"]) / 2
            amb = ambiental.get(prev1["periodo"]) or {}
            umidade = amb.get("umidade_media")
            focos_ok = focos_sao_observados(prev1["focos_origem"])
            exemplos.append({
                "bairro_id": bairro_id,
                "periodo": itens[i]["periodo"],
                "casos_lag1": float(prev1["casos_dengue"]),
                "casos_lag2": float(prev2["casos_dengue"]),
                "media_3": float(media3),
                "chuva_mm": clima_observado(prev1, ambiental, "chuva_mm", "chuva_origem"),
                "temperatura_media": clima_observado(prev1, ambiental, "temperatura_media", "temperatura_origem"),
                "umidade_media": float(umidade) if umidade is not None else None,
                "focos_mosquito": float(prev1["focos_mosquito"]) if focos_ok else 0.0,
                "focos_informado": 1.0 if focos_ok else 0.0,
                "target": float(itens[i]["casos_dengue"]),
            })
    colunas = FEATURES + ["target", "periodo", "bairro_id"]
    if not exemplos:
        return pd.DataFrame(columns=colunas)
    return pd.DataFrame(exemplos, columns=colunas)


def dividir_treino_teste_temporal(df, fracao_teste=0.2):
    """O corte é por período fechado: o mesmo mês não aparece nos dois lados."""
    if df is None or df.empty:
        vazio = df.iloc[0:0] if df is not None else pd.DataFrame()
        return vazio, vazio
    periodos = sorted(df["periodo"].unique(), key=periodo_ordem)
    if len(periodos) < 2:
        return df.iloc[0:0].copy(), df.iloc[0:0].copy()
    n_teste = max(1, int(round(len(periodos) * fracao_teste)))
    if n_teste >= len(periodos):
        n_teste = len(periodos) - 1
    teste_periodos = set(periodos[-n_teste:])
    teste = df[df["periodo"].isin(teste_periodos)].copy()
    treino = df[~df["periodo"].isin(teste_periodos)].copy()
    return treino, teste


def preencher_mediana(treino, teste, colunas):
    valores = {}
    for col in colunas:
        serie = pd.to_numeric(treino[col], errors="coerce").dropna()
        mediana = float(serie.median()) if len(serie) else 0.0
        valores[col] = mediana
        treino[col] = pd.to_numeric(treino[col], errors="coerce").fillna(mediana)
        teste[col] = pd.to_numeric(teste[col], errors="coerce").fillna(mediana)
    return valores


def metricas_referencia(y_true, y_persistencia, y_media3):
    y_true = pd.to_numeric(y_true, errors="coerce")
    return {
        "mae_persistencia": float(mean_absolute_error(y_true, y_persistencia)),
        "rmse_persistencia": float(mean_squared_error(y_true, y_persistencia) ** 0.5),
        "mae_media3": float(mean_absolute_error(y_true, y_media3)),
        "rmse_media3": float(mean_squared_error(y_true, y_media3) ** 0.5),
    }


def texto_baselines(metrica):
    if not metrica or metrica.get("mae_persistencia") is None or metrica.get("mae_teste") is None:
        return ""
    return (
        f" No teste temporal, o MAE do modelo foi {metrica['mae_teste']:.2f}; "
        f"repetir o período anterior deu {metrica['mae_persistencia']:.2f}; "
        f"a média móvel de 3 períodos deu {metrica['mae_media3']:.2f}."
    )


def ajustar_modelo(df, n_estimators=300, min_samples_leaf=MIN_SAMPLES_LEAF, minimo_exemplos=MINIMO_REGISTROS_MODELO):
    vazio = {"modelo": None, "metrica": None, "preenchimento": {}}
    if df is None or len(df) < minimo_exemplos:
        return vazio
    treino, teste = dividir_treino_teste_temporal(df)
    if len(treino) < max(min_samples_leaf, 8) or teste.empty:
        return vazio
    treino = treino.copy()
    teste = teste.copy()
    preenchimento = preencher_mediana(treino, teste, COLUNAS_MEDIANA)
    for frame in (treino, teste):
        frame["focos_mosquito"] = pd.to_numeric(frame["focos_mosquito"], errors="coerce").fillna(0)
        frame["focos_informado"] = pd.to_numeric(frame["focos_informado"], errors="coerce").fillna(0)

    modelo = RandomForestRegressor(
        n_estimators=n_estimators,
        max_depth=8,
        min_samples_leaf=min_samples_leaf,
        random_state=42,
    )
    modelo.fit(treino[FEATURES], treino["target"])
    pred_treino = modelo.predict(treino[FEATURES])
    pred_teste = modelo.predict(teste[FEATURES])
    metrica = {
        "mae_treino": float(mean_absolute_error(treino["target"], pred_treino)),
        "rmse_treino": float(mean_squared_error(treino["target"], pred_treino) ** 0.5),
        "mae_teste": float(mean_absolute_error(teste["target"], pred_teste)),
        "rmse_teste": float(mean_squared_error(teste["target"], pred_teste) ** 0.5),
        "r2_teste": float(r2_score(teste["target"], pred_teste)) if len(teste) >= 2 else None,
        "importancias": dict(zip(FEATURES, modelo.feature_importances_)),
        "periodos_teste": sorted(teste["periodo"].unique(), key=periodo_ordem),
    }
    metrica.update(metricas_referencia(teste["target"], teste["casos_lag1"], teste["media_3"]))
    return {"modelo": modelo, "metrica": metrica, "preenchimento": preenchimento}


def montar_entrada(rows, ambiental, preenchimento=None):
    """Entrada do próximo período a partir da série observada, já em ordem cronológica."""
    reais = [r for r in rows if origem_permite_treino(r["origem"], r["casos_origem"])]
    if len(reais) < 2:
        return None
    atual = reais[-1]
    anterior = reais[-2]
    recentes = [float(r["casos_dengue"]) for r in reais[-3:]]
    preenchimento = preenchimento or {}
    chuva = clima_observado(atual, ambiental, "chuva_mm", "chuva_origem")
    temp = clima_observado(atual, ambiental, "temperatura_media", "temperatura_origem")
    amb = ambiental.get(atual["periodo"]) or {}
    umidade = amb.get("umidade_media")
    if umidade is None:
        umidade = preenchimento.get("umidade_media", 0.0)
    if chuva is None:
        chuva = preenchimento.get("chuva_mm", 0.0)
    if temp is None:
        temp = preenchimento.get("temperatura_media", 25.0)
    focos_ok = focos_sao_observados(atual["focos_origem"])
    return {
        "casos_lag1": float(atual["casos_dengue"]),
        "casos_lag2": float(anterior["casos_dengue"]),
        "media_3": sum(recentes) / len(recentes),
        "chuva_mm": float(chuva),
        "temperatura_media": float(temp),
        "umidade_media": float(umidade),
        "focos_mosquito": float(atual["focos_mosquito"]) if focos_ok else 0.0,
        "focos_informado": 1.0 if focos_ok else 0.0,
        "registro_id": atual["id"],
    }
