# -*- coding: utf-8 -*-
"""
Projeto acadêmico: Inteligência Preditiva e Ciência de Dados Aplicadas
à Prevenção de Surtos Epidemiológicos de Dengue — Franca/SP.
Autoria: Arthur Henrique
"""
import csv
import io
import json
import os
import re
import secrets
import sqlite3
import tempfile
import threading
import time
import zipfile
from collections import defaultdict, deque
from datetime import date, datetime, timedelta
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pandas as pd
from flask import Flask, Response, abort, flash, g, redirect, render_template, request, session, url_for

from integridade import (
    chaves_nome_bairro as _chaves_nome_bairro,
    consumir_janela,
    gravar_casos_sinan,
    melhor_bairro_oficial as _melhor_bairro_oficial,
    normalizar_nome_bairro,
    origem_http_permitida,
    origem_permite_treino,
    populacao_confiavel,
    registrar_nomes_ignorados,
    sanear_historico_misto,
)
from modelo import (
    FEATURES,
    MINIMO_REGISTROS_MODELO,
    NOMES_FATORES,
    PESO_CASOS,
    PESO_CHUVA,
    PESO_FOCOS,
    PESO_TEMPERATURA,
    ajustar_modelo,
    calcular_risco_formula,
    carregar_ambiental,
    classificar_risco,
    construir_dataset_temporal,
    montar_entrada,
    periodo_ordem as _periodo_ordem,
    texto_baselines,
)

try:
    from bairros_oficiais import BAIRROS_OFICIAIS_FRANCA, BAIRROS_COM_COORDENADAS
except ImportError:
    BAIRROS_COM_COORDENADAS = {
        'Centro': (-20.5386, -47.4008),
        'Cidade Nova': (-20.5350, -47.4120),
        'Estação': (-20.5320, -47.4080),
        'São Joaquim': (-20.5430, -47.4200),
        'Jardim Dermínio': (-20.5510, -47.4260),
        'Jardim Aeroporto': (-20.5650, -47.3850),
        'Parque Vicente Leporace': (-20.5080, -47.4120),
        'Jardim Brasilândia': (-20.5300, -47.3750),
        'Jardim Ângela Rosa': (-20.5250, -47.3800),
        'Parque das Esmeraldas': (-20.5550, -47.4300),
        'Vila Santa Cruz': (-20.5500, -47.4150),
        'Jardim Vera Cruz': (-20.5150, -47.3950),
        'Jardim Portinari': (-20.4980, -47.3850),
        'Recanto Elimar': (-20.5600, -47.3980),
        'Vila Rezende': (-20.5480, -47.4050),
        'Bairro Higienópolis': (-20.5420, -47.3920),
        'Jardim Paulistano': (-20.5400, -47.3700),
        'Parque Progresso': (-20.5520, -47.3850),
        'Vila Chico Júlio': (-20.5260, -47.4100),
        'Jardim Piratininga': (-20.5350, -47.3880),
        'Vila Aparecida': (-20.5300, -47.3920),
        'Vila São Sebastião': (-20.5420, -47.4150),
        'Jardim Planalto': (-20.5220, -47.3810),
        'Jardim Dr. Antonio Petraglia': (-20.5460, -47.3790),
        'Jardim Integração': (-20.5510, -47.3810),
        'Parque Franville': (-20.5540, -47.3820),
        'Jardim Noêmia': (-20.5440, -47.3850),
        'Jardim Seminário': (-20.5310, -47.3950),
        'Miramontes': (-20.4950, -47.4050),
        'Jardim Palma': (-20.5150, -47.3720),
        'Jardim Alvorada': (-20.5220, -47.4080),
        'Vila Imperador': (-20.5260, -47.4080),
        'Jardim Guanabara': (-20.5290, -47.3810),
        'Vila Hípica': (-20.5500, -47.3980),
        'Jardim Paraty': (-20.5560, -47.3750),
        'Parque Universitário': (-20.5580, -47.3720),
        'Vila Industrial': (-20.5700, -47.4100),
        'Vila Raycos': (-20.5390, -47.4150),
        'Jardim Panorama': (-20.5280, -47.3880),
        'Jardim América': (-20.5360, -47.4090),
        'Jardim Palestina': (-20.5280, -47.4180),
        'Residencial Zanetti': (-20.5200, -47.3650),
        'Jardim Brasil': (-20.5310, -47.4220),
        'Jardim Luiza': (-20.5050, -47.4020),
        'Jardim Santa Lúcia': (-20.5480, -47.3980)
    }
    BAIRROS_OFICIAIS_FRANCA = list(BAIRROS_COM_COORDENADAS.keys())

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "banco.db")

def _carregar_secret_key():
    env = os.environ.get("DENGUE_SECRET_KEY", "").strip()
    if env:
        return env
    caminho = os.path.join(BASE_DIR, ".secret_key")
    if os.path.isfile(caminho):
        with open(caminho, "r", encoding="utf-8") as f:
            salvo = f.read().strip()
            if salvo:
                return salvo
    chave = secrets.token_urlsafe(32)
    try:
        with open(caminho, "w", encoding="utf-8") as f:
            f.write(chave)
    except OSError:
        return "chave-local-projeto-dengue-2026"
    return chave


app = Flask(__name__)
app.config["SECRET_KEY"] = _carregar_secret_key()
app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024

ATUALIZACAO_AUTOMATICA_HORAS = 6
ATUALIZACAO_SINAN_HORAS = 24
ATUALIZACAO_IBGE_HORAS = 24 * 7
INFO_DENGUE_GEOCODE = 3516200
INFO_DENGUE_API = "https://info.dengue.mat.br/api/alertcity"
OPEN_METEO_ARCHIVE_API = "https://archive-api.open-meteo.com/v1/archive"
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
OPENAI_RESPONSES_API = "https://api.openai.com/v1/responses"
OPENAI_CHAT_API = "https://api.openai.com/v1/chat/completions"
OPEN_METEO_FORECAST_API = "https://api.open-meteo.com/v1/forecast"
IBGE_ARCGIS_BAIRROS_API = "https://services8.arcgis.com/5BwCrbm6qPzGdhUo/ArcGIS/rest/services/Censo%20IBGE%202022%20Bairros/FeatureServer/0/query"
SINAN_DENGUE_CSV_TEMPLATE = "https://s3.sa-east-1.amazonaws.com/ckan.saude.gov.br/SINAN/Dengue/csv/DENGBR{yy:02d}.csv.zip"
SINAN_ANOS_AUTOMATICOS = (2024, 2025, 2026)
CODIGO_MUNICIPIO_FRANCA = "351620"
FRANCA_LAT = -20.5386
FRANCA_LON = -47.4008
FRANCA_LAT_MIN, FRANCA_LAT_MAX = -20.64, -20.45
FRANCA_LON_MIN, FRANCA_LON_MAX = -47.48, -47.31
AUTO_WEATHER_TIMEOUT = 20
SQLITE_BUSY_TIMEOUT_MS = 30000
FONTES_AUTOMATICAS = (
    "InfoDengue / Fiocruz",
    "Open-Meteo / reanálise meteorológica",
    "SINAN/Dengue - Ministério da Saúde",
    "IBGE Censo 2022 / camada de bairros",
)

AUTOMATIC_COLLECT_LOCK = threading.Lock()
_MODEL_LOCK = threading.Lock()
MODELO_VERSAO = "2026-10-serie-observada"
ASSISTENTE_LIMITE = 20
ASSISTENTE_JANELA_S = 600
_ASSISTENTE_HITS = defaultdict(deque)

_MODEL_CACHE = {
    "modelo": None,
    "features": FEATURES,
    "df": None,
    "timestamp": None,
    "metrica": None,
    "preenchimento": {},
    "versao": None,
}

# ---------------------------------------------------------------------------
# BANCO DE DADOS
# ---------------------------------------------------------------------------

def _configurar_conexao(conn):
    conn.row_factory = sqlite3.Row
    conn.execute(f"PRAGMA busy_timeout = {SQLITE_BUSY_TIMEOUT_MS}")
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        conn.execute("PRAGMA journal_mode = WAL")
    except sqlite3.DatabaseError:
        pass
    return conn


def get_db():
    if "db" not in g:
        g.db = _configurar_conexao(sqlite3.connect(DB_PATH, timeout=30))
    return g.db


@app.teardown_appcontext
def fechar_db(exception=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def ensure_column(conn, table, column, definition):
    existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    if column not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def init_db():
    conn = _configurar_conexao(sqlite3.connect(DB_PATH, timeout=30))
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS bairros (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL UNIQUE,
            populacao INTEGER
        )
    """)

    ensure_column(conn, "bairros", "codigo_ibge_bairro", "TEXT")
    ensure_column(conn, "bairros", "latitude", "REAL")
    ensure_column(conn, "bairros", "longitude", "REAL")
    ensure_column(conn, "bairros", "populacao_origem", "TEXT DEFAULT 'manual'")
    ensure_column(conn, "bairros", "geometria_origem", "TEXT")

    cur.execute("""
        CREATE TABLE IF NOT EXISTS dados_historicos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            bairro_id INTEGER NOT NULL,
            periodo TEXT NOT NULL,
            casos_dengue INTEGER NOT NULL DEFAULT 0,
            chuva_mm REAL NOT NULL DEFAULT 0,
            temperatura_media REAL NOT NULL DEFAULT 0,
            focos_mosquito INTEGER NOT NULL DEFAULT 0,
            origem TEXT DEFAULT 'demonstração',
            data_cadastro TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(bairro_id, periodo),
            FOREIGN KEY (bairro_id) REFERENCES bairros(id) ON DELETE CASCADE
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS dados_oficiais_franca (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            data_inicio_semana TEXT NOT NULL,
            semana_epidemiologica INTEGER,
            casos_semana INTEGER DEFAULT 0,
            casos_estimados REAL DEFAULT 0,
            casos_acumulados INTEGER DEFAULT 0,
            incidencia_100k REAL DEFAULT 0,
            nivel_alerta INTEGER DEFAULT 1,
            rt REAL,
            prob_rt_maior_1 REAL,
            receptivo INTEGER,
            transmissao INTEGER,
            fonte TEXT NOT NULL,
            atualizado_em TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(data_inicio_semana, fonte)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS atualizacoes_fontes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fonte TEXT NOT NULL,
            status TEXT NOT NULL,
            mensagem TEXT,
            registros INTEGER DEFAULT 0,
            executado_em TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS dados_ambientais_franca (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            periodo TEXT NOT NULL,
            inicio_periodo TEXT NOT NULL,
            fim_periodo TEXT NOT NULL,
            chuva_mm REAL DEFAULT 0,
            temperatura_media REAL,
            temperatura_min REAL,
            temperatura_max REAL,
            horas_precipitacao REAL DEFAULT 0,
            vento_max_kmh REAL,
            umidade_media REAL,
            horas_sol REAL DEFAULT 0,
            fonte TEXT NOT NULL,
            atualizado_em TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(periodo, fonte)
        )
    """)

    ensure_column(conn, "dados_ambientais_franca", "umidade_media", "REAL")

    cur.execute("""
        CREATE TABLE IF NOT EXISTS previsoes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            bairro_id INTEGER NOT NULL,
            data_previsao TEXT DEFAULT CURRENT_TIMESTAMP,
            pontuacao_risco REAL NOT NULL,
            classificacao TEXT NOT NULL,
            fatores_principais TEXT,
            metodo TEXT,
            mae_modelo REAL,
            rmse_modelo REAL,
            r2_modelo REAL,
            mae_teste REAL,
            rmse_teste REAL,
            r2_teste REAL,
            registro_referencia_id INTEGER,
            previsao_casos REAL,
            limite_inferior REAL,
            limite_superior REAL,
            probabilidade_aumento REAL,
            horizonte_periodos INTEGER DEFAULT 1,
            observacao TEXT,
            FOREIGN KEY (bairro_id) REFERENCES bairros(id) ON DELETE CASCADE
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS importacoes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            arquivo TEXT NOT NULL,
            status TEXT NOT NULL,
            registros INTEGER DEFAULT 0,
            mensagem TEXT,
            executado_em TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS sinan_nomes_ignorados (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL UNIQUE,
            motivo TEXT,
            ocorrencias INTEGER DEFAULT 0,
            atualizado_em TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS meta_sistema (
            chave TEXT PRIMARY KEY,
            valor TEXT
        )
    """)

    for column, definition in [
        ("origem", "TEXT DEFAULT 'demonstração'"),
        ("chuva_origem", "TEXT DEFAULT 'manual'"),
        ("temperatura_origem", "TEXT DEFAULT 'manual'"),
        ("casos_origem", "TEXT DEFAULT 'manual'"),
        ("focos_origem", "TEXT DEFAULT 'manual'"),
    ]:
        ensure_column(conn, "dados_historicos", column, definition)

    for column, definition in [
        ("mae_modelo", "REAL"),
        ("rmse_modelo", "REAL"),
        ("r2_modelo", "REAL"),
        ("mae_teste", "REAL"),
        ("rmse_teste", "REAL"),
        ("r2_teste", "REAL"),
        ("registro_referencia_id", "INTEGER"),
        ("previsao_casos", "REAL"),
        ("limite_inferior", "REAL"),
        ("limite_superior", "REAL"),
        ("probabilidade_aumento", "REAL"),
        ("horizonte_periodos", "INTEGER DEFAULT 1"),
        ("observacao", "TEXT"),
    ]:
        ensure_column(conn, "previsoes", column, definition)

    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_dados_bairro_periodo ON dados_historicos(bairro_id, periodo)")
    conn.execute("UPDATE dados_historicos SET origem='demonstração' WHERE origem IS NULL OR TRIM(origem)=''")

    for nome in BAIRROS_OFICIAIS_FRANCA:
        lat, lon = BAIRROS_COM_COORDENADAS.get(nome, (-20.5386, -47.4008))
        cur.execute("""
            INSERT INTO bairros (nome, populacao, populacao_origem, latitude, longitude, geometria_origem)
            VALUES (?, NULL, 'nao_informada', ?, ?, 'Mapeamento Oficial Franca/SP')
            ON CONFLICT(nome) DO UPDATE SET
                latitude = COALESCE(bairros.latitude, excluded.latitude),
                longitude = COALESCE(bairros.longitude, excluded.longitude)
        """, (nome, lat, lon))

    conn.execute("UPDATE dados_historicos SET casos_origem='demonstração', focos_origem='demonstração', chuva_origem='demonstração', temperatura_origem='demonstração' WHERE origem='demonstração'")
    conn.commit()

    conn.execute("""
        UPDATE bairros
        SET populacao = NULL, populacao_origem = 'nao_informada'
        WHERE populacao_origem = 'Consolidado Franca/SP'
    """)
    sanear_historico_misto(conn)
    conn.commit()
    conn.close()


def inserir_dados_demo(conn):
    """Série sintética antiga. O arranque não chama mais esta função."""
    cur = conn.cursor()
    bairros = [
        ("Centro", 15000), ("Cidade Nova", 12000), ("Jardim América", 9000),
        ("Vila Rezende", 8000), ("Jardim Zelinda", 7000), ("Jardim Piratininga", 10000),
        ("Estação", 6000), ("Jardim Brasil", 5000), ("Jardim Palestina", 4000),
        ("São José", 11000),
    ]
    cur.executemany("INSERT INTO bairros (nome, populacao) VALUES (?, ?)", bairros)
    conn.commit()
    expandir_historico_demo(conn)


def expandir_historico_demo(conn):
    existentes = conn.execute("SELECT COUNT(*) FROM dados_historicos").fetchone()[0]
    if existentes > 15:
        return

    ids = conn.execute("SELECT id, nome FROM bairros ORDER BY id").fetchall()
    if not ids:
        return

    base = {
        "Centro": 7, "Cidade Nova": 14, "Jardim América": 8, "Vila Rezende": 18,
        "Jardim Zelinda": 12, "Jardim Piratininga": 5, "Estação": 16,
        "Jardim Brasil": 9, "Jardim Palestina": 13, "São José": 6,
    }
    meses = [f"2026-{m:02d}" for m in range(1, 9)]
    for idx, row in enumerate(ids):
        for mi, periodo in enumerate(meses):
            atual = conn.execute(
                "SELECT 1 FROM dados_historicos WHERE bairro_id=? AND periodo=?",
                (row["id"], periodo),
            ).fetchone()
            if atual:
                continue
            centro = base.get(row["nome"], 8)
            sazonal = [0, 1, 2, 4, 7, 9, 6, 3][mi]
            variacao = ((idx * 3 + mi * 2) % 5) - 2
            casos = max(0, centro + sazonal + variacao)
            chuva = [32, 48, 66, 92, 120, 135, 108, 74][mi] + idx * 2
            temp = round([22.4, 23.6, 24.7, 25.2, 26.1, 26.7, 25.8, 24.1][mi] + (idx % 3) * 0.3, 1)
            focos = max(0, int(casos * 0.55) + ((idx + mi) % 3))
            conn.execute("""
                INSERT INTO dados_historicos
                (bairro_id, periodo, casos_dengue, chuva_mm, temperatura_media, focos_mosquito, origem, casos_origem, focos_origem, chuva_origem, temperatura_origem)
                VALUES (?, ?, ?, ?, ?, ?, 'demonstração', 'demonstração', 'demonstração', 'demonstração', 'demonstração')
            """, (row["id"], periodo, casos, chuva, temp, focos))
    conn.commit()


# ---------------------------------------------------------------------------
# CSRF & HELPERS
# ---------------------------------------------------------------------------

@app.context_processor
def contexto_global():
    def csrf_token():
        token = session.get("_csrf")
        if not token:
            token = secrets.token_urlsafe(32)
            session["_csrf"] = token
        return token
    return {"csrf_token": csrf_token, "status_origem_foco": status_origem_foco}


@app.before_request
def proteger_post():
    if request.method != "POST":
        return
    if request.path.startswith("/api/"):
        if not origem_http_permitida(
            request.host,
            request.headers.get("Origin", "").strip(),
            request.headers.get("Referer", "").strip(),
            request.remote_addr,
        ):
            abort(400, description="Origem da requisição não autorizada.")
        return
    enviado = request.form.get("_csrf", "")
    esperado = session.get("_csrf", "")
    if not esperado or not secrets.compare_digest(enviado, esperado):
        abort(400, description="Token de segurança inválido. Recarregue a página e tente novamente.")


BAIRROS_OFICIAIS_POR_NORM = {normalizar_nome_bairro(nome): nome for nome in BAIRROS_OFICIAIS_FRANCA}

def bairro_oficial_por_nome(valor):
    return BAIRROS_OFICIAIS_POR_NORM.get(normalizar_nome_bairro(valor))


def _requests_json(url, timeout=20, params=None):
    if params:
        url = url + ("&" if "?" in url else "?") + urlencode(params)
    return _ler_json_url(url, timeout=timeout)


def _sinan_dengue_confirmado(codigo, ano):
    try:
        c = int(float(str(codigo).strip()))
    except (TypeError, ValueError):
        return False
    if ano <= 2012:
        return c in {1, 2, 3, 4}
    return c in {10, 11, 12}


def atualizar_populacao_bairros_ibge(force=False):
    conn = get_db(); fonte = "IBGE Censo 2022 / camada de bairros"
    if not force and not precisa_atualizar_fonte(conn, fonte):
        return {"ok": True, "atualizado": False, "mensagem": "População/localização por bairro em cache."}
    try:
        payload = _requests_json(IBGE_ARCGIS_BAIRROS_API, timeout=30, params={
            "where": "CD_MUN='3516200' OR CD_MUN='351620' OR UPPER(NM_MUN)='FRANCA'",
            "outFields": "Name,SUM_v0001,centroid_x_wgs,centroid_y_wgs",
            "returnGeometry": "false",
            "f": "json",
            "resultRecordCount": 2000
        })
        features = payload.get("features") or []
        bairros_db = conn.execute("SELECT id,nome,geometria_origem FROM bairros").fetchall()
        indice = {}
        for r in bairros_db:
            for chave in _chaves_nome_bairro(r["nome"]):
                indice.setdefault(chave, r)
        atualizados = 0; sem_correspondencia = 0
        for feat in features:
            a = feat.get("attributes") or {}; nome = str(a.get("Name") or "").strip()
            if not nome: continue
            row = _melhor_bairro_oficial(nome, indice)
            if not row:
                sem_correspondencia += 1; continue
            pop = a.get("SUM_v0001")
            try: pop = int(round(float(pop))) if pop is not None else None
            except (TypeError, ValueError): pop = None
            lat = a.get("centroid_y_wgs"); lon = a.get("centroid_x_wgs")
            
            if lat is not None and lon is not None:
                try:
                    lat_f, lon_f = float(lat), float(lon)
                    if not (FRANCA_LAT_MIN <= lat_f <= FRANCA_LAT_MAX and FRANCA_LON_MIN <= lon_f <= FRANCA_LON_MAX):
                        lat, lon = None, None
                except (ValueError, TypeError):
                    lat, lon = None, None

            ajuste_manual = str(row["geometria_origem"] or "").lower().startswith("ajuste manual")
            if ajuste_manual:
                conn.execute(
                    """UPDATE bairros SET populacao=COALESCE(?,populacao),
                       populacao_origem=CASE WHEN ? IS NULL THEN populacao_origem ELSE 'automatico - IBGE Censo 2022' END
                       WHERE id=?""",
                    (pop, pop, row["id"]),
                )
            else:
                conn.execute(
                    """UPDATE bairros SET populacao=COALESCE(?,populacao), populacao_origem='automatico - IBGE Censo 2022',
                       latitude=COALESCE(?,latitude), longitude=COALESCE(?,longitude), geometria_origem=?
                       WHERE id=?""",
                    (pop, lat, lon, fonte, row["id"]),
                )
            atualizados += 1
        msg = f"População/localização de {atualizados} bairro(s) sincronizada(s)."
        if sem_correspondencia: msg += f" {sem_correspondencia} registros do IBGE não tiveram correspondência territorial segura e foram ignorados."
        conn.execute("INSERT INTO atualizacoes_fontes (fonte,status,mensagem,registros) VALUES (?,?,?,?)", (fonte, "sucesso", msg, atualizados)); conn.commit()
        return {"ok": True, "atualizado": bool(atualizados), "mensagem": msg, "registros": atualizados}
    except Exception as exc:
        conn.rollback()
        try:
            conn.execute("INSERT INTO atualizacoes_fontes (fonte,status,mensagem,registros) VALUES (?,?,?,?)", (fonte, "erro", str(exc)[:500], 0)); conn.commit()
        except sqlite3.DatabaseError: pass
        return {"ok": False, "atualizado": False, "mensagem": "Não foi possível atualizar população/localização por bairro. Os últimos dados salvos foram preservados."}


def _baixar_sinan_ano(ano, timeout=90):
    url = SINAN_DENGUE_CSV_TEMPLATE.format(yy=ano % 100)
    req = Request(url, headers={"User-Agent": "ProjetoDengueFranca/4.0"})
    with urlopen(req, timeout=timeout) as resposta:
        data = resposta.read()
    temp = tempfile.NamedTemporaryFile(delete=False, suffix=f"_DENGBR{ano}.zip")
    temp.write(data)
    temp.close()
    return temp.name


def _ler_colunas_csv_sinan(zip_path, ano):
    zf = zipfile.ZipFile(zip_path)
    nomes = [n for n in zf.namelist() if n.lower().endswith((".csv", ".txt"))]
    if not nomes:
        zf.close()
        raise ValueError(f"Arquivo SINAN {ano} não contém CSV legível.")
    nome = nomes[0]
    return zf, nome


def atualizar_casos_bairro_sinan(force=False, anos=SINAN_ANOS_AUTOMATICOS):
    conn = get_db(); fonte = "SINAN/Dengue - Ministério da Saúde"
    if not force and not precisa_atualizar_fonte(conn, fonte): return {"ok": True, "atualizado": False, "mensagem": "Casos por bairro em cache."}
    total_periodos = 0; total_bairros = set(); arquivos = []; anos_sem_bairro = []; ignorados = {}
    try:
        bairros_db = conn.execute("SELECT id,nome FROM bairros").fetchall()
        indice = {}
        for r in bairros_db:
            for chave in _chaves_nome_bairro(r["nome"]): indice.setdefault(chave, r)
        agregados = {}
        for ano in anos:
            if ano > date.today().year: continue
            caminho = _baixar_sinan_ano(ano); arquivos.append(caminho)
            zf, nome = _ler_colunas_csv_sinan(caminho, ano)
            try:
                with zf.open(nome) as raw:
                    primeira = raw.read(5000); raw.seek(0); sep = ';' if primeira.count(b';') > primeira.count(b',') else ','
                    try: cols = pd.read_csv(raw, sep=sep, nrows=0, encoding='latin1').columns.tolist()
                    except UnicodeDecodeError:
                        raw.seek(0); cols = pd.read_csv(raw, sep=sep, nrows=0, encoding='utf-8').columns.tolist()
                    upper = {str(c).upper(): c for c in cols}; bairro_col = upper.get('NM_BAIRRO') or next((c for c in cols if 'BAIRRO' in str(c).upper()), None)
                    if not bairro_col or 'DT_SIN_PRI' not in cols or 'ID_MN_RESI' not in cols:
                        anos_sem_bairro.append(ano); continue
                    usar = ['ID_MN_RESI', bairro_col, 'DT_SIN_PRI'] + (['CLASSI_FIN'] if 'CLASSI_FIN' in cols else [])
                    raw.seek(0); reader = pd.read_csv(raw, sep=sep, usecols=usar, dtype=str, chunksize=50000, encoding='latin1', low_memory=False)
                    for chunk in reader:
                        ids = chunk['ID_MN_RESI'].fillna('').str.replace(r'\.0$', '', regex=True).str.strip(); chunk = chunk[ids == CODIGO_MUNICIPIO_FRANCA]
                        if chunk.empty: continue
                        chunk['DT_SIN_PRI'] = pd.to_datetime(chunk['DT_SIN_PRI'], dayfirst=True, errors='coerce'); chunk = chunk[chunk['DT_SIN_PRI'].notna()]
                        if 'CLASSI_FIN' in chunk.columns: chunk = chunk[chunk.apply(lambda r: _sinan_dengue_confirmado(r.get('CLASSI_FIN'), ano), axis=1)]
                        chunk['bairro_norm'] = chunk[bairro_col].fillna('').map(normalizar_nome_bairro)
                        chunk['periodo'] = chunk['DT_SIN_PRI'].dt.strftime('%Y-%m')
                        for (bairro_norm, periodo), qtd in chunk.groupby(['bairro_norm', 'periodo'], dropna=False).size().items():
                            if not bairro_norm or not periodo: continue
                            row = _melhor_bairro_oficial(bairro_norm, indice)
                            if not row:
                                ignorados[bairro_norm] = ignorados.get(bairro_norm, 0) + int(qtd)
                                continue
                            key = (row['id'], periodo); agregados[key] = agregados.get(key, 0) + int(qtd); total_bairros.add(row['id'])
            finally:
                zf.close()
        for (bairro_id, periodo), casos in agregados.items():
            if gravar_casos_sinan(conn, bairro_id, periodo, casos, fonte):
                total_periodos += 1
        sanear_historico_misto(conn)
        if ignorados:
            registrar_nomes_ignorados(conn, ignorados, datetime.now().isoformat(timespec="seconds"))
        aviso = f" Anos sem coluna de bairro: {', '.join(map(str, anos_sem_bairro))}." if anos_sem_bairro else ''
        if ignorados:
            aviso += f" {len(ignorados)} nome(s) sem correspondência segura ficaram de fora."
        aviso += " Cadastros manuais e importados não foram substituídos."
        if total_periodos:
            msg = (
                f"SINAN vinculado em {len(total_bairros)} bairro(s) e {total_periodos} período(s). "
                f"Bairros sem nome reconhecido no arquivo público mantiveram os registros já cadastrados.{aviso}"
            )
        else:
            msg = f"Não foi possível vincular casos do SINAN por bairro nos arquivos disponíveis.{aviso} Os registros já cadastrados foram preservados."
        conn.execute("INSERT INTO atualizacoes_fontes (fonte,status,mensagem,registros) VALUES (?,?,?,?)", (fonte, 'sucesso', msg, total_periodos)); conn.commit()
        return {"ok": True, "atualizado": bool(total_periodos), "mensagem": msg, "registros": total_periodos}
    except Exception as exc:
        conn.rollback()
        try: conn.execute("INSERT INTO atualizacoes_fontes (fonte,status,mensagem,registros) VALUES (?,?,?,?)", (fonte, 'erro', str(exc)[:500], 0)); conn.commit()
        except sqlite3.DatabaseError: pass
        return {"ok": False, "atualizado": False, "mensagem": "Não foi possível atualizar casos por bairro automaticamente. Os últimos dados salvos foram preservados."}
    finally:
        for p in arquivos:
            try: os.remove(p)
            except OSError: pass


def precisa_atualizar_fonte(conn, fonte):
    row = conn.execute(
        "SELECT executado_em, status FROM atualizacoes_fontes WHERE fonte=? ORDER BY id DESC LIMIT 1",
        (fonte,),
    ).fetchone()
    if not row or row["status"] != "sucesso":
        return True
    ultima = _ultima_atualizacao_fonte(conn, fonte)
    if ultima is None:
        return True
    horas = ATUALIZACAO_AUTOMATICA_HORAS
    if fonte == "SINAN/Dengue - Ministério da Saúde":
        horas = ATUALIZACAO_SINAN_HORAS
    elif fonte == "IBGE Censo 2022 / camada de bairros":
        horas = ATUALIZACAO_IBGE_HORAS
    return datetime.now() - ultima > timedelta(hours=horas)


def atualizar_dados_oficiais_franca(force=False):
    conn = get_db()
    fonte = "InfoDengue / Fiocruz"
    if not force and not precisa_atualizar_fonte(conn, fonte):
        return {"ok": True, "atualizado": False, "mensagem": "Dados epidemiológicos externos em cache."}

    ano_fim = date.today().year
    anos = range(ano_fim - 2, ano_fim + 1)
    try:
        gravados = 0
        falhas = []
        agora = datetime.now().isoformat(timespec="seconds")
        for ano in anos:
            params = {
                "geocode": INFO_DENGUE_GEOCODE,
                "disease": "dengue",
                "format": "json",
                "ew_start": 1, "ew_end": 53,
                "ey_start": ano, "ey_end": ano,
            }
            url = INFO_DENGUE_API + "?" + urlencode(params)
            try:
                itens = _extrair_itens(_ler_json_url(url))
            except Exception:
                falhas.append(str(ano))
                continue
            if not itens:
                falhas.append(str(ano))
                continue
            for item in itens:
                data_inicio = item.get("data_iniSE") or item.get("data") or item.get("data_inicio_semana")
                if not data_inicio:
                    continue
                se_raw = item.get("SE", item.get("se"))
                se = int(_num(se_raw, 0)) if se_raw not in (None, "") else None
                casos = int(_num(item.get("casos"), 0))
                casos_est = _num(item.get("casos_est"), 0)
                acumulados = int(_num(item.get("notif_accum_year"), 0))
                incidencia = _num(item.get("p_inc100k", item.get("inc")), 0)
                nivel = int(_num(item.get("nivel"), 1))
                rt_val = item.get("Rt", item.get("rt"))
                rt = _num(rt_val) if rt_val not in (None, "") else None
                prt = item.get("p_rt1", item.get("prt1"))
                prt = _num(prt) if prt not in (None, "") else None
                receptivo = int(_num(item.get("receptivo"), 0))
                transmissao = int(_num(item.get("transmissao"), 0))

                conn.execute("""
                    INSERT INTO dados_oficiais_franca
                    (data_inicio_semana, semana_epidemiologica, casos_semana, casos_estimados,
                     casos_acumulados, incidencia_100k, nivel_alerta, rt, prob_rt_maior_1,
                     receptivo, transmissao, fonte, atualizado_em)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(data_inicio_semana, fonte) DO UPDATE SET
                        semana_epidemiologica=excluded.semana_epidemiologica,
                        casos_semana=excluded.casos_semana,
                        casos_estimados=excluded.casos_estimados,
                        casos_acumulados=excluded.casos_acumulados,
                        incidencia_100k=excluded.incidencia_100k,
                        nivel_alerta=excluded.nivel_alerta,
                        rt=excluded.rt,
                        prob_rt_maior_1=excluded.prob_rt_maior_1,
                        receptivo=excluded.receptivo,
                        transmissao=excluded.transmissao,
                        atualizado_em=excluded.atualizado_em
                """, (data_inicio, se, casos, casos_est, acumulados, incidencia, nivel,
                      rt, prt, receptivo, transmissao, fonte, agora))
                gravados += 1

        if not gravados:
            raise ValueError("A fonte não retornou registros para Franca.")
        msg = f"Consulta concluída: {gravados} semana(s) entre {ano_fim - 2} e {ano_fim}."
        if falhas:
            msg += f" Anos sem resposta: {', '.join(falhas)}."
        conn.execute(
            "INSERT INTO atualizacoes_fontes (fonte,status,mensagem,registros) VALUES (?,?,?,?)",
            (fonte, "sucesso", msg, gravados),
        )
        conn.commit()
        return {"ok": True, "atualizado": True, "mensagem": msg}
    except Exception as exc:
        conn.rollback()
        conn.execute(
            "INSERT INTO atualizacoes_fontes (fonte,status,mensagem,registros) VALUES (?,?,?,?)",
            (fonte, "erro", str(exc)[:500], 0),
        )
        conn.commit()
        return {"ok": False, "atualizado": False, "mensagem": "Não foi possível consultar a fonte automática. O último dado salvo foi preservado."}


def resumo_oficial_franca(conn):
    ultimo = conn.execute(
        "SELECT * FROM dados_oficiais_franca ORDER BY date(data_inicio_semana) DESC, id DESC LIMIT 1"
    ).fetchone()
    serie = conn.execute("""
        SELECT data_inicio_semana, semana_epidemiologica, casos_semana, casos_acumulados,
               incidencia_100k, nivel_alerta, rt, prob_rt_maior_1
        FROM dados_oficiais_franca
        ORDER BY date(data_inicio_semana)
    """).fetchall()
    atualizacao = conn.execute(
        "SELECT * FROM atualizacoes_fontes ORDER BY id DESC LIMIT 1"
    ).fetchone()
    return {
        "ultimo": dict(ultimo) if ultimo else None,
        "serie": [dict(r) for r in serie],
        "atualizacao": dict(atualizacao) if atualizacao else None,
        "fonte_url": "https://info.dengue.mat.br/",
    }


def _parse_periodo(periodo):
    m = re.fullmatch(r"(\d{4})-(\d{2})", str(periodo or "").strip())
    if not m:
        return None, None
    ano, mes = int(m.group(1)), int(m.group(2))
    if not 1 <= mes <= 12:
        return None, None
    inicio = date(ano, mes, 1)
    if mes == 12:
        fim = date(ano + 1, 1, 1) - timedelta(days=1)
    else:
        fim = date(ano, mes + 1, 1) - timedelta(days=1)
    return inicio, fim


def periodos_necessarios_clima(conn):
    periodos = {r["periodo"] for r in conn.execute("SELECT DISTINCT periodo FROM dados_historicos WHERE periodo IS NOT NULL")}
    hoje = date.today().replace(day=1)
    for desloc in range(24):
        ano, mes = hoje.year, hoje.month - desloc
        while mes <= 0:
            ano -= 1
            mes += 12
        periodos.add(f"{ano:04d}-{mes:02d}")
    return sorted(p for p in periodos if _parse_periodo(p)[0])


def atualizar_clima_franca(force=False):
    conn = get_db()
    fonte = "Open-Meteo / reanálise meteorológica"
    if not force and not precisa_atualizar_fonte(conn, fonte):
        return {"ok": True, "atualizado": False, "mensagem": "Dados climáticos automáticos em cache."}

    periodos = periodos_necessarios_clima(conn)
    if not periodos:
        return {"ok": False, "atualizado": False, "mensagem": "Nenhum período válido para coletar clima."}

    inicio = min(_parse_periodo(p)[0] for p in periodos)
    fim = min(date.today(), max(_parse_periodo(p)[1] for p in periodos))
    params = {
        "latitude": FRANCA_LAT,
        "longitude": FRANCA_LON,
        "start_date": inicio.isoformat(),
        "end_date": fim.isoformat(),
        "daily": ",".join([
            "temperature_2m_mean", "temperature_2m_min", "temperature_2m_max",
            "precipitation_sum", "precipitation_hours", "wind_speed_10m_max",
            "sunshine_duration"
        ]),
        "hourly": "relative_humidity_2m",
        "timezone": "America/Sao_Paulo",
        "temperature_unit": "celsius",
        "wind_speed_unit": "kmh",
        "precipitation_unit": "mm",
    }
    url = OPEN_METEO_ARCHIVE_API + "?" + urlencode(params)
    try:
        payload = _ler_json_url(url, timeout=AUTO_WEATHER_TIMEOUT)
        daily = payload.get("daily") or {}
        dates = daily.get("time") or []
        if not dates:
            raise ValueError("A fonte climática não retornou datas.")

        chaves = [
            "temperature_2m_mean", "temperature_2m_min", "temperature_2m_max",
            "precipitation_sum", "precipitation_hours", "wind_speed_10m_max",
            "sunshine_duration"
        ]
        series = {k: daily.get(k) or [] for k in chaves}
        hourly = payload.get("hourly") or {}
        hourly_times = hourly.get("time") or []
        hourly_humidity = hourly.get("relative_humidity_2m") or []
        umidade_por_mes = {}
        for i, hs in enumerate(hourly_times):
            try:
                hd = datetime.fromisoformat(str(hs)).date()
            except ValueError:
                continue
            hp = hd.strftime("%Y-%m")
            if hp not in periodos or i >= len(hourly_humidity) or hourly_humidity[i] is None:
                continue
            umidade_por_mes.setdefault(hp, []).append(_num(hourly_humidity[i], 0))
        por_mes = {}
        for i, ds in enumerate(dates):
            try:
                d = datetime.fromisoformat(str(ds)).date()
            except ValueError:
                continue
            periodo = d.strftime("%Y-%m")
            if periodo not in periodos:
                continue
            item = por_mes.setdefault(periodo, {k: [] for k in chaves})
            for k in chaves:
                arr = series[k]
                if i < len(arr) and arr[i] is not None:
                    item[k].append(_num(arr[i], 0))

        if not por_mes:
            raise ValueError("A resposta climática não cobriu os períodos solicitados.")

        agora = datetime.now().isoformat(timespec="seconds")
        gravados = 0
        for periodo, vals in por_mes.items():
            p_ini, p_fim = _parse_periodo(periodo)
            fim_real = min(p_fim, date.today())
            conn.execute("""
                INSERT INTO dados_ambientais_franca
                (periodo,inicio_periodo,fim_periodo,chuva_mm,temperatura_media,temperatura_min,
                 temperatura_max,horas_precipitacao,vento_max_kmh,umidade_media,horas_sol,fonte,atualizado_em)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(periodo,fonte) DO UPDATE SET
                    inicio_periodo=excluded.inicio_periodo,
                    fim_periodo=excluded.fim_periodo,
                    chuva_mm=excluded.chuva_mm,
                    temperatura_media=excluded.temperatura_media,
                    temperatura_min=excluded.temperatura_min,
                    temperatura_max=excluded.temperatura_max,
                    horas_precipitacao=excluded.horas_precipitacao,
                    vento_max_kmh=excluded.vento_max_kmh,
                    umidade_media=excluded.umidade_media,
                    horas_sol=excluded.horas_sol,
                    atualizado_em=excluded.atualizado_em
            """, (
                periodo, p_ini.isoformat(), fim_real.isoformat(),
                round(sum(vals["precipitation_sum"]), 2),
                round(sum(vals["temperature_2m_mean"])/len(vals["temperature_2m_mean"]), 2) if vals["temperature_2m_mean"] else None,
                round(min(vals["temperature_2m_min"]), 2) if vals["temperature_2m_min"] else None,
                round(max(vals["temperature_2m_max"]), 2) if vals["temperature_2m_max"] else None,
                round(sum(vals["precipitation_hours"]), 2),
                round(max(vals["wind_speed_10m_max"]), 2) if vals["wind_speed_10m_max"] else None,
                round(sum(umidade_por_mes.get(periodo, []))/len(umidade_por_mes.get(periodo, [])), 2) if umidade_por_mes.get(periodo) else None,
                round(sum(vals["sunshine_duration"])/3600, 2),
                fonte, agora,
            ))
            gravados += 1

        conn.execute("""
            UPDATE dados_historicos
            SET chuva_mm = (SELECT a.chuva_mm FROM dados_ambientais_franca a WHERE a.periodo = dados_historicos.periodo AND a.fonte = ?),
                temperatura_media = (SELECT a.temperatura_media FROM dados_ambientais_franca a WHERE a.periodo = dados_historicos.periodo AND a.fonte = ?),
                chuva_origem = 'automatico',
                temperatura_origem = 'automatico'
            WHERE periodo IN (SELECT periodo FROM dados_ambientais_franca WHERE fonte = ?)
              AND (chuva_origem IS NULL OR chuva_origem != 'manual')
              AND (temperatura_origem IS NULL OR temperatura_origem != 'manual')
        """, (fonte, fonte, fonte))

        conn.execute(
            "INSERT INTO atualizacoes_fontes (fonte,status,mensagem,registros) VALUES (?,?,?,?)",
            (fonte, "sucesso", f"Clima agregado por mês: {gravados} período(s).", gravados),
        )
        conn.commit()
        return {"ok": True, "atualizado": True, "mensagem": f"Clima atualizado ({gravados} período(s)).", "registros": gravados}
    except Exception as exc:
        conn.rollback()
        conn.execute(
            "INSERT INTO atualizacoes_fontes (fonte,status,mensagem,registros) VALUES (?,?,?,?)",
            (fonte, "erro", str(exc)[:500], 0),
        )
        conn.commit()
        return {"ok": False, "atualizado": False, "mensagem": "Não foi possível consultar o clima automaticamente; os últimos valores salvos foram preservados."}


def _bairro_localizacao(conn, bairro_id):
    row = conn.execute(
        "SELECT id,nome,latitude,longitude FROM bairros WHERE id=?",
        (bairro_id,),
    ).fetchone()
    if not row:
        return None
    lat = row["latitude"] if row["latitude"] is not None else FRANCA_LAT
    lon = row["longitude"] if row["longitude"] is not None else FRANCA_LON
    return {"id": row["id"], "nome": row["nome"], "latitude": float(lat), "longitude": float(lon),
            "precisao": "coordenada do bairro" if row["latitude"] is not None and row["longitude"] is not None else "referência do município"}

def _extrair_itens(payload):
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("data", "items", "results"):
            if isinstance(payload.get(key), list):
                return payload[key]
    return []

def _ler_json_url(url, timeout=8):
    req = Request(url, headers={"User-Agent": "ProjetoDengueFranca/3.0"})
    with urlopen(req, timeout=timeout) as resposta:
        return json.loads(resposta.read().decode("utf-8"))

def _normalizar_texto(valor):
    valor = unicodedata.normalize("NFKD", str(valor or ""))
    return "".join(ch for ch in valor if not unicodedata.combining(ch)).lower()

def _num(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)

def _ultima_atualizacao_fonte(conn, fonte):
    row = conn.execute(
        "SELECT executado_em FROM atualizacoes_fontes WHERE fonte=? ORDER BY id DESC LIMIT 1",
        (fonte,),
    ).fetchone()
    if not row:
        return None
    try:
        texto = str(row["executado_em"]).strip()
        if texto.endswith("Z"):
            texto = texto[:-1] + "+00:00"
        dt = datetime.fromisoformat(texto)
        if dt.tzinfo is not None:
            dt = dt.replace(tzinfo=None)
        return dt
    except (ValueError, TypeError):
        return None

def detectar_bairro_pergunta(conn, pergunta):
    q = _normalizar_texto(pergunta)
    bairros = conn.execute("SELECT id,nome FROM bairros ORDER BY LENGTH(nome) DESC").fetchall()
    for b in bairros:
        nome = _normalizar_texto(b["nome"])
        if nome and nome in q:
            return dict(b)
    return None

def previsao_clima_bairro(bairro_id, dias=7):
    conn = get_db()
    local = _bairro_localizacao(conn, bairro_id)
    if not local:
        return {"ok": False, "mensagem": "Bairro não encontrado."}

    dias = max(1, min(int(dias or 7), 10))
    params = {
        "latitude": local["latitude"],
        "longitude": local["longitude"],
        "daily": ",".join([
            "precipitation_probability_max", "precipitation_probability_mean",
            "precipitation_sum", "rain_sum", "temperature_2m_max",
            "temperature_2m_min", "weather_code"
        ]),
        "forecast_days": dias,
        "timezone": "America/Sao_Paulo",
        "temperature_unit": "celsius",
        "precipitation_unit": "mm",
    }
    url = OPEN_METEO_FORECAST_API + "?" + urlencode(params)
    try:
        payload = _ler_json_url(url, timeout=AUTO_WEATHER_TIMEOUT)
        daily = payload.get("daily") or {}
        datas = daily.get("time") or []
        probs = daily.get("precipitation_probability_max") or []
        probs_mean = daily.get("precipitation_probability_mean") or []
        prec = daily.get("precipitation_sum") or []
        rain = daily.get("rain_sum") or []
        tmax = daily.get("temperature_2m_max") or []
        tmin = daily.get("temperature_2m_min") or []
        codes = daily.get("weather_code") or []
        if not datas:
            raise ValueError("A fonte climática não retornou previsão diária.")
        dias_saida = []
        for i, d in enumerate(datas):
            dias_saida.append({
                "data": d,
                "probabilidade_max": _num(probs[i], 0) if i < len(probs) and probs[i] is not None else None,
                "probabilidade_media": _num(probs_mean[i], 0) if i < len(probs_mean) and probs_mean[i] is not None else None,
                "precipitacao_mm": _num(prec[i], 0) if i < len(prec) and prec[i] is not None else 0,
                "chuva_mm": _num(rain[i], 0) if i < len(rain) and rain[i] is not None else 0,
                "temp_max": _num(tmax[i], 0) if i < len(tmax) and tmax[i] is not None else None,
                "temp_min": _num(tmin[i], 0) if i < len(tmin) and tmin[i] is not None else None,
                "codigo_tempo": int(codes[i]) if i < len(codes) and codes[i] is not None else None,
            })
        maior = max(dias_saida, key=lambda x: (x["probabilidade_max"] if x["probabilidade_max"] is not None else -1))
        acumulado = sum(d["precipitacao_mm"] for d in dias_saida)
        return {
            "ok": True,
            "fonte": "Open-Meteo / previsão meteorológica",
            "bairro": local,
            "dias": dias_saida,
            "maior_probabilidade": maior,
            "chuva_acumulada_prevista_mm": round(acumulado, 1),
            "atualizado_em": datetime.now().isoformat(timespec="seconds"),
        }
    except Exception as exc:
        return {"ok": False, "mensagem": f"Não foi possível obter a previsão do clima agora: {str(exc)[:180]}"}

def contexto_assistente(pergunta, bairro_id=None):
    conn = get_db()
    bairro = None
    if bairro_id:
        bairro = conn.execute("SELECT * FROM bairros WHERE id=?", (bairro_id,)).fetchone()
    if not bairro:
        bairro = detectar_bairro_pergunta(conn, pergunta)
    bairro_id_final = bairro["id"] if bairro else None

    resumo = buscar_resumo_bairros(conn)
    ranking = sorted([b for b in resumo if b.get("pontuacao") is not None], key=lambda b: b["pontuacao"], reverse=True)
    oficial = resumo_oficial_franca(conn)
    clima_municipal = conn.execute("SELECT * FROM dados_ambientais_franca ORDER BY date(periodo) DESC, id DESC LIMIT 1").fetchone()
    dados_bairro = next((b for b in resumo if bairro_id_final and b["id"] == bairro_id_final), None)
    previsao = previsao_clima_bairro(bairro_id_final, 7) if bairro_id_final else None

    return {
        "pergunta": pergunta,
        "bairro_selecionado": dict(bairro) if bairro else None,
        "bairro_indicadores": dados_bairro,
        "previsao_clima": previsao,
        "ranking_top5": [
            {"bairro": b["nome"], "pontuacao": b["pontuacao"], "classificacao": b["classificacao"], "previsao_casos": b.get("previsao_casos")}
            for b in ranking[:5]
        ],
        "oficial": dict(oficial["ultimo"]) if oficial.get("ultimo") else None,
        "clima_municipal": dict(clima_municipal) if clima_municipal else None,
    }

def resposta_assistente_local(pergunta, contexto):
    q = _normalizar_texto(pergunta)
    b = contexto.get("bairro_indicadores")
    p = contexto.get("previsao_clima")
    nome = contexto.get("bairro_selecionado", {}).get("nome") if contexto.get("bairro_selecionado") else None

    if any(x in q for x in ["chuva", "chover", "precipitacao", "tempo", "clima"]):
        if not p or not p.get("ok"):
            return "Não consegui consultar a previsão agora. Tente novamente em alguns instantes.", "previsão meteorológica"
        maior = p["maior_probabilidade"]
        linhas = []
        for d in p["dias"][:3]:
            if d["probabilidade_max"] is not None:
                linhas.append(f'{d["data"]}: {d["probabilidade_max"]:.0f}% de chance de precipitação e {d["precipitacao_mm"]:.1f} mm previstos')
        titulo = f"Para {nome}" if nome else "Para o bairro selecionado"
        return (f'{titulo}, a maior probabilidade de precipitação nos próximos {len(p["dias"])} dias é de '
                f'{maior["probabilidade_max"]:.0f}% em {maior["data"]}. Chuva acumulada prevista no período: '
                f'{p["chuva_acumulada_prevista_mm"]:.1f} mm.\n\n' + "\n".join(linhas)), "Open-Meteo"

    if any(x in q for x in ["qual bairro", "quais bairros", "maior tendencia", "mais casos", "mais risco", "pior bairro", "ranking"]):
        top = contexto["ranking_top5"]
        if not top:
            return "Ainda não há previsões/riscos suficientes para formar um ranking.", "base local"
        lista = "; ".join(f'{i+1}º {item["bairro"]} ({item["pontuacao"]:.1f} pts, {item["classificacao"]})' for i, item in enumerate(top[:5]))
        return f"Pelos indicadores atuais da base do site, os bairros prioritários são: {lista}. Isso é uma classificação de apoio e não uma previsão epidemiológica oficial.", "IA preditiva / base local"

    if any(x in q for x in ["proteger", "protecao", "prevencao", "casa", "quintal", "cuidado", "cuidados", "mosquito", "larvas"]):
        return ("Para reduzir criadouros do Aedes, a principal medida é eliminar água parada: mantenha caixas d’água bem tampadas, "
                "limpe calhas e ralos, vire ou guarde recipientes que possam acumular água, mantenha pratos de plantas sem água acumulada "
                "e descarte corretamente objetos sem uso no quintal. Faça uma vistoria semanal. Se encontrar um problema maior na vizinhança, "
                "comunique o serviço municipal responsável."), "orientação preventiva"

    if any(x in q for x in ["risco", "casos", "dengue", "tendencia", "tendência", "previsao", "previsão"]):
        if b:
            futura = f' A previsão registrada para o próximo período é de {b.get("previsao_casos"):.1f} caso(s).' if b.get("previsao_casos") is not None else ''
            pontos_txt = f'{b["pontuacao"]:.1f} pontos' if b.get("pontuacao") is not None else 'sem análise calculada'
            classificacao_txt = b.get("classificacao") or "Sem análise"

            origem_txt = f' Origem do último período considerado: {b.get("origem_ultimo")}.' if b.get("origem_ultimo") else ""
            return (f'{b["nome"]} está classificado como {classificacao_txt}, com {pontos_txt} no indicador atual. '
                    f'O sistema considera casos, focos, chuva e temperatura.{futura}{origem_txt} '
                    f'Chuva e temperatura usadas na previsão são da série municipal.'), "IA preditiva / base local"
        return "Selecione um bairro ou escreva o nome dele na pergunta. Assim eu consigo consultar o risco e os indicadores específicos.", "base local"

    return (
        "Posso ajudar com previsão de chuva, ranking de risco por bairro e orientações de prevenção. "
        "Inclua o nome do bairro ou selecione um na lista para respostas mais específicas.",
        "base local",
    )


def chamar_modelo_linguagem(pergunta, contexto, resposta_local):
    texto_local, fonte_local = resposta_local if isinstance(resposta_local, tuple) else (str(resposta_local), "base local")
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        return texto_local, fonte_local

    contexto_json = json.dumps(contexto, ensure_ascii=False, default=str)
    prompt = (
        "Você é o assistente do sistema acadêmico Prevenção Dengue — Franca/SP. "
        "Responda em português do Brasil, de forma clara e curta. Use SOMENTE os dados do contexto para números e rankings. "
        "Não invente probabilidade, casos ou dados epidemiológicos. Diferencie claramente previsão meteorológica de previsão de dengue. "
        "Para prevenção, dê orientações gerais e seguras de eliminação de água parada. "
        "Se os dados estiverem ausentes, diga isso. Ao citar um número, mencione a origem que está no contexto. "
        "Chuva, temperatura e umidade são municipais. Não trate registro de demonstração como caso oficial. "
        "Nunca trate o resultado como diagnóstico ou decisão oficial de saúde pública.\n\n"
        f"CONTEXTO:\n{contexto_json}\n\nPERGUNTA:\n{pergunta}\n\n"
        f"RESPOSTA DE SEGURANÇA/BASE LOCAL (use como fallback):\n{texto_local}"
    )
    try:
        payload = json.dumps({"model": OPENAI_MODEL, "input": prompt}).encode("utf-8")
        req = Request(OPENAI_RESPONSES_API, data=payload, method="POST", headers={
            "Content-Type": "application/json", "Authorization": f"Bearer {api_key}"
        })
        obj = json.loads(urlopen(req, timeout=25).read().decode("utf-8"))
        output = str(obj.get("output_text") or "").strip()
        if not output:
            for item in obj.get("output", []) or []:
                for content in item.get("content", []) or []:
                    if content.get("type") == "output_text" and content.get("text"):
                        output += content["text"]
        if output.strip():
            return output.strip(), f"OpenAI {OPENAI_MODEL} + dados do site"
    except Exception:
        pass

    try:
        messages = [
            {"role": "system", "content": "Você é um assistente de apoio à decisão em saúde pública."},
            {"role": "user", "content": prompt}
        ]
        payload = json.dumps({"model": OPENAI_MODEL, "messages": messages, "max_tokens": 500}).encode("utf-8")
        req = Request(OPENAI_CHAT_API, data=payload, method="POST", headers={
            "Content-Type": "application/json", "Authorization": f"Bearer {api_key}"
        })
        obj = json.loads(urlopen(req, timeout=25).read().decode("utf-8"))
        output = obj.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
        if output:
            return output, f"OpenAI {OPENAI_MODEL} (chat completions) + dados do site"
    except Exception:
        pass

    return texto_local, fonte_local

def clima_periodo(periodo):
    conn = get_db()
    row = conn.execute("SELECT * FROM dados_ambientais_franca WHERE periodo=? ORDER BY id DESC LIMIT 1", (periodo,)).fetchone()
    if row:
        return dict(row)
    resultado = atualizar_clima_franca(force=True)
    if resultado.get("ok"):
        row = conn.execute("SELECT * FROM dados_ambientais_franca WHERE periodo=? ORDER BY id DESC LIMIT 1", (periodo,)).fetchone()
        return dict(row) if row else None
    return None


def status_origem_foco(valor):
    valor = str(valor or "").strip().lower()
    if valor.startswith("automatico"):
        return "automático"
    if valor == "ausente" or not valor:
        return "não informado"
    if valor in ("manual", "importado"):
        return valor
    return valor


def resumo_coleta_automatica(conn):
    registros = {}
    for fonte in FONTES_AUTOMATICAS:
        row = conn.execute("SELECT * FROM atualizacoes_fontes WHERE fonte=? ORDER BY id DESC LIMIT 1", (fonte,)).fetchone()
        registros[fonte] = dict(row) if row else None
    total_clima = conn.execute("SELECT COUNT(*) FROM dados_ambientais_franca").fetchone()[0]
    return {"fontes": registros, "total_clima": total_clima}


def coletar_todos_automaticos(force=False):
    acquired = AUTOMATIC_COLLECT_LOCK.acquire(timeout=1.0)
    if not acquired:
        return {
            "ok": True,
            "pulou_por_concorrencia": True,
            "resultados": [],
            "mensagem": "Coleta automática já está em andamento; usando os dados salvos."
        }
    try:
        resultados = [
            atualizar_populacao_bairros_ibge(force=force),
            atualizar_casos_bairro_sinan(force=force),
            atualizar_dados_oficiais_franca(force=force),
            atualizar_clima_franca(force=force),
        ]
        ok = all(r.get("ok") for r in resultados)
        return {"ok": ok, "resultados": resultados}
    finally:
        AUTOMATIC_COLLECT_LOCK.release()


def agendar_coleta_automatica(force=False):
    if AUTOMATIC_COLLECT_LOCK.locked():
        return
    if not force:
        conn = get_db()
        if not any(precisa_atualizar_fonte(conn, fonte) for fonte in FONTES_AUTOMATICAS):
            return

    def _run():
        with app.app_context():
            coletar_todos_automaticos(force=force)

    threading.Thread(target=_run, daemon=True, name="dengue-coleta").start()


# ---------------------------------------------------------------------------
# RISCO E MACHINE LEARNING (XAI IMPLEMENTADO)
# ---------------------------------------------------------------------------

def recomendacao_por_classificacao(classificacao, probabilidade=None, incidencia=None):
    base = {
        "Baixo": "Manter monitoramento preventivo, ações educativas e eliminação rotineira de criadouros.",
        "Médio": "Aumentar a fiscalização, priorizar pontos estratégicos e reforçar a eliminação de criadouros.",
        "Alto": "Priorizar ações de campo, inspeções, eliminação de criadouros e comunicação preventiva no território.",
    }.get(classificacao, "Manter acompanhamento.")
    extras = []
    if probabilidade is not None and probabilidade >= 0.65:
        extras.append("A previsão indica aumento provável em relação ao último período, justificando atenção antecipada.")
    if incidencia is not None and incidencia >= 2:
        extras.append("A incidência acumulada por população reforça a prioridade relativa do bairro.")
    return base + (" " + " ".join(extras) if extras else "")


def _registros_bairro_ordenados(conn, bairro_id):
    rows = conn.execute(
        "SELECT * FROM dados_historicos WHERE bairro_id=?",
        (bairro_id,),
    ).fetchall()
    return sorted(rows, key=lambda x: (_periodo_ordem(x["periodo"]), x["id"]))


def treinar_modelo_temporal(conn, force=False):
    ultima_mod = conn.execute("SELECT MAX(data_cadastro) FROM dados_historicos").fetchone()[0]
    with _MODEL_LOCK:
        cache_pronto = (
            not force
            and _MODEL_CACHE.get("versao") == MODELO_VERSAO
            and _MODEL_CACHE.get("timestamp") == ultima_mod
            and _MODEL_CACHE.get("df") is not None
        )
        if cache_pronto:
            return _MODEL_CACHE

        df = construir_dataset_temporal(conn)
        ajustado = ajustar_modelo(df)
        _MODEL_CACHE.update({
            "modelo": ajustado["modelo"],
            "features": FEATURES,
            "df": df,
            "timestamp": ultima_mod,
            "versao": MODELO_VERSAO,
            "metrica": ajustado["metrica"],
            "preenchimento": ajustado["preenchimento"],
        })
        return _MODEL_CACHE


def ultimo_registro_bairro(conn, bairro_id):
    rows = _registros_bairro_ordenados(conn, bairro_id)
    return rows[-1] if rows else None


def preparar_entrada_temporal(conn, bairro_id, preenchimento=None):
    rows = _registros_bairro_ordenados(conn, bairro_id)
    return montar_entrada(rows, carregar_ambiental(conn), preenchimento)


def gerar_previsao(bairro_id, salvar=True):
    conn = get_db()
    bairro = conn.execute("SELECT * FROM bairros WHERE id=?", (bairro_id,)).fetchone()
    serie = _registros_bairro_ordenados(conn, bairro_id)
    observados = [r for r in serie if origem_permite_treino(r["origem"], r["casos_origem"])]
    registro = observados[-1] if observados else (serie[-1] if serie else None)
    if not bairro or not registro:
        return None

    focos_ok = str(registro["focos_origem"] or "").lower().startswith(("automatico", "importado", "manual")) and str(registro["focos_origem"] or "").lower() != "ausente"
    risco_atual = calcular_risco_formula(
        registro["casos_dengue"], registro["chuva_mm"], registro["temperatura_media"], registro["focos_mosquito"], focos_disponiveis=focos_ok
    )

    # CÁLCULO DA DECOMPOSIÇÃO DE EXPLICABILIDADE (XAI)
    casos_val = max(0.0, _num(registro["casos_dengue"]))
    chuva_val = max(0.0, _num(registro["chuva_mm"]))
    temp_val = _num(registro["temperatura_media"], 25)
    focos_val = max(0.0, _num(registro["focos_mosquito"]))

    score_casos = min(100.0, (casos_val / 40.0) * 100)
    score_chuva = min(100.0, (chuva_val / 150.0) * 100)
    score_temp = max(0.0, 100 - abs(27 - temp_val) * 8)
    score_focos = min(100.0, (focos_val / 25.0) * 100) if focos_ok else 0.0

    c_casos = score_casos * PESO_CASOS
    c_focos = score_focos * PESO_FOCOS if focos_ok else 0.0
    c_chuva = score_chuva * PESO_CHUVA
    c_temp = score_temp * PESO_TEMPERATURA
    sum_c = c_casos + c_focos + c_chuva + c_temp
    sum_ref = sum_c if sum_c > 0 else 1.0

    decomposicao = {
        "casos": {"nome": "Casos Notificados", "valor": casos_val, "unidade": "casos", "peso": int(PESO_CASOS * 100), "pontos": round(c_casos, 1), "pct": round((c_casos / sum_ref) * 100, 1)},
        "focos": {"nome": "Focos do Mosquito", "valor": focos_val, "unidade": "focos", "peso": int(PESO_FOCOS * 100), "pontos": round(c_focos, 1), "pct": round((c_focos / sum_ref) * 100, 1)},
        "chuva": {"nome": "Precipitação (Chuva)", "valor": chuva_val, "unidade": "mm", "peso": int(PESO_CHUVA * 100), "pontos": round(c_chuva, 1), "pct": round((c_chuva / sum_ref) * 100, 1)},
        "temperatura": {"nome": "Temperatura Média", "valor": temp_val, "unidade": "°C", "peso": int(PESO_TEMPERATURA * 100), "pontos": round(c_temp, 1), "pct": round((c_temp / sum_ref) * 100, 1)},
    }

    cache = treinar_modelo_temporal(conn)
    modelo = cache["modelo"]
    metodo = "formula_risco"
    previsao_casos = None
    limite_inferior = None
    limite_superior = None
    prob_aumento = None
    mae_treino = rmse_treino = mae_teste = rmse_teste = r2_teste = None
    fatores = [
        ("casos_dengue", PESO_CASOS),
        ("focos_mosquito", PESO_FOCOS),
        ("chuva_mm", PESO_CHUVA),
        ("temperatura_media", PESO_TEMPERATURA),
    ]

    entrada = preparar_entrada_temporal(conn, bairro_id, cache.get("preenchimento"))
    aviso = ""

    if modelo and entrada:
        X = pd.DataFrame([{k: entrada[k] for k in cache["features"]}], columns=cache["features"])
        X_np = X.to_numpy(dtype=float)
        arvore_preds = [float(est.predict(X_np)[0]) for est in modelo.estimators_]
        previsao_casos = max(0.0, float(modelo.predict(X)[0]))
        limite_inferior = max(0.0, float(pd.Series(arvore_preds).quantile(0.10)))
        limite_superior = max(limite_inferior, float(pd.Series(arvore_preds).quantile(0.90)))
        ultimo_caso = float(registro["casos_dengue"])
        prob_aumento = sum(1 for p in arvore_preds if p > ultimo_caso) / len(arvore_preds)

        futuro_score = min(100.0, (previsao_casos / 40.0) * 100)
        pontuacao = round(0.6 * risco_atual + 0.4 * futuro_score, 1)
        metodo = "random_forest_temporal"
        top = sorted(cache["metrica"]["importancias"].items(), key=lambda x: x[1], reverse=True)[:4]
        fatores = [(n, float(w)) for n, w in top]
        mae_treino = cache["metrica"]["mae_treino"]
        rmse_treino = cache["metrica"]["rmse_treino"]
        mae_teste = cache["metrica"]["mae_teste"]
        rmse_teste = cache["metrica"]["rmse_teste"]
        r2_teste = cache["metrica"]["r2_teste"]
        aviso = (
            f"Previsão de 1 período à frente, com {len(cache['df'])} exemplos observados "
            f"(manual, importado ou automático). Chuva, temperatura e umidade vêm da série municipal. "
            f"O intervalo é a dispersão das árvores, não uma probabilidade calibrada."
            + texto_baselines(cache.get("metrica"))
        )
    else:
        pontuacao = risco_atual
        if not observados:
            aviso = (
                "Este bairro ainda não tem série observada. Registros de demonstração ficam de fora do modelo. "
                "O número abaixo é só o indicador didático do último registro."
            )
        else:
            aviso = (
                f"Histórico observado insuficiente para treinar a previsão de casos "
                f"(necessário: {MINIMO_REGISTROS_MODELO} exemplos derivados). "
                "O sistema mostra apenas o risco didático atual."
            )

    classificacao, cor = classificar_risco(pontuacao)
    populacao = bairro["populacao"]
    incidencia = (
        registro["casos_dengue"] / populacao * 1000
        if populacao_confiavel(populacao, bairro["populacao_origem"])
        else None
    )
    recomendacao = recomendacao_por_classificacao(classificacao, prob_aumento, incidencia)

    fatores_txt = " • ".join(f"{NOMES_FATORES.get(nome, nome)} ({peso * 100:.0f}%)" for nome, peso in fatores)
    observacao = (
        "O risco combina um indicador ponderado atual com a previsão de casos quando o histórico observado é suficiente. "
        "O teste separa períodos inteiros e compara o modelo com repetir o período anterior e com a média móvel. "
        "É avaliação acadêmica, não validação clínica. Clima e umidade são municipais, não medidos dentro do bairro."
        + texto_baselines(cache.get("metrica"))
    )

    resultado = {
        "pontuacao": pontuacao,
        "classificacao": classificacao,
        "cor": cor,
        "metodo": metodo,
        "fatores": fatores_txt,
        "decomposicao": decomposicao,
        "aviso": aviso,
        "recomendacao": recomendacao,
        "entrada": dict(registro),
        "registro_id": registro["id"],
        "previsao_casos": round(previsao_casos, 1) if previsao_casos is not None else None,
        "limite_inferior": round(limite_inferior, 1) if limite_inferior is not None else None,
        "limite_superior": round(limite_superior, 1) if limite_superior is not None else None,
        "probabilidade_aumento": round(prob_aumento * 100, 1) if prob_aumento is not None else None,
        "mae_treino": round(mae_treino, 2) if mae_treino is not None else None,
        "rmse_treino": round(rmse_treino, 2) if rmse_treino is not None else None,
        "mae_teste": round(mae_teste, 2) if mae_teste is not None else None,
        "rmse_teste": round(rmse_teste, 2) if rmse_teste is not None else None,
        "r2_teste": round(r2_teste, 3) if r2_teste is not None else None,
        "total_exemplos_temporais": len(cache["df"]) if cache["df"] is not None else 0,
        "observacao": observacao + (" A variável de focos não foi usada como evidência quando não há fonte estruturada por bairro." if not focos_ok else ""),
        "cache_usado": cache["modelo"] is not None,
    }

    if salvar:
        conn.execute("""
            INSERT INTO previsoes
            (bairro_id, pontuacao_risco, classificacao, fatores_principais, metodo,
             mae_modelo, rmse_modelo, r2_modelo, mae_teste, rmse_teste, r2_teste,
             registro_referencia_id, previsao_casos, limite_inferior, limite_superior,
             probabilidade_aumento, horizonte_periodos, observacao)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            bairro_id, pontuacao, classificacao, fatores_txt, metodo,
            mae_treino, rmse_treino, None, mae_teste, rmse_teste, r2_teste,
            registro["id"], previsao_casos, limite_inferior, limite_superior,
            prob_aumento, 1, observacao,
        ))
        conn.commit()
    return resultado


def latest_previsao_por_bairro():
    conn = get_db()
    rows = conn.execute("""
        SELECT p.*
        FROM previsoes p
        INNER JOIN (
            SELECT bairro_id, MAX(id) AS max_id FROM previsoes GROUP BY bairro_id
        ) u ON p.bairro_id=u.bairro_id AND p.id=u.max_id
    """).fetchall()
    return {r["bairro_id"]: r for r in rows}


def _tendencia_de_casos(atual, anterior):
    if anterior is None:
        return {"texto": "Sem comparação", "classe": "neutro", "variacao": None}
    atual_f, anterior_f = float(atual), float(anterior)
    if anterior_f == 0:
        variacao = 100.0 if atual_f > 0 else 0.0
    else:
        variacao = (atual_f - anterior_f) / anterior_f * 100
    if variacao > 5:
        texto, classe = "Subindo", "alta"
    elif variacao < -5:
        texto, classe = "Caindo", "baixa"
    else:
        texto, classe = "Estável", "neutro"
    return {"texto": texto, "classe": classe, "variacao": round(variacao, 1)}


def _serie_para_analise(rows):
    observados = [r for r in rows if origem_permite_treino(r["origem"], r["casos_origem"])]
    return observados if observados else list(rows)


def tendencia_bairro(conn, bairro_id):
    serie = _serie_para_analise(_registros_bairro_ordenados(conn, bairro_id))
    if len(serie) < 2:
        return _tendencia_de_casos(None, None)
    return _tendencia_de_casos(serie[-1]["casos_dengue"], serie[-2]["casos_dengue"])


def buscar_resumo_bairros(conn):
    rows = conn.execute("""
        SELECT b.id, b.nome, b.populacao, b.populacao_origem,
               COUNT(d.id) qtd_registros,
               COALESCE(SUM(d.casos_dengue),0) total_casos,
               COALESCE(SUM(d.focos_mosquito),0) total_focos,
               COALESCE(AVG(d.chuva_mm),0) chuva_media,
               COALESCE(AVG(d.temperatura_media),0) temperatura_media
        FROM bairros b
        LEFT JOIN dados_historicos d ON d.bairro_id=b.id
        GROUP BY b.id, b.nome, b.populacao, b.populacao_origem
        ORDER BY b.nome
    """).fetchall()
    historico = conn.execute("""
        SELECT bairro_id, id, periodo, casos_dengue, origem, casos_origem
        FROM dados_historicos
    """).fetchall()
    por_bairro = {}
    for r in historico:
        por_bairro.setdefault(r["bairro_id"], []).append(r)
    for itens in por_bairro.values():
        itens.sort(key=lambda x: (_periodo_ordem(x["periodo"]), x["id"]))
    previsoes = latest_previsao_por_bairro()
    resultado = []
    for row in rows:
        d = dict(row)
        prev = previsoes.get(d["id"])
        d["pontuacao"] = float(prev["pontuacao_risco"]) if prev else None
        d["classificacao"] = prev["classificacao"] if prev else "Sem análise"
        d["cor"] = {"Alto": "vermelho", "Médio": "amarelo", "Baixo": "verde"}.get(d["classificacao"], "cinza")
        d["previsao_casos"] = float(prev["previsao_casos"]) if prev and prev["previsao_casos"] is not None else None
        d["probabilidade_aumento"] = float(prev["probabilidade_aumento"]) * 100 if prev and prev["probabilidade_aumento"] is not None else None
        d["incidencia_1000"] = (
            round(d["total_casos"] / d["populacao"] * 1000, 2)
            if populacao_confiavel(d["populacao"], d.get("populacao_origem"))
            else None
        )
        serie = _serie_para_analise(por_bairro.get(d["id"]) or [])
        d["ultimo_periodo"] = serie[-1]["periodo"] if serie else None
        d["origem_ultimo"] = serie[-1]["origem"] if serie else None
        if len(serie) < 2:
            d["tendencia"] = _tendencia_de_casos(None, None)
        else:
            d["tendencia"] = _tendencia_de_casos(serie[-1]["casos_dengue"], serie[-2]["casos_dengue"])
        resultado.append(d)
    return resultado


# ---------------------------------------------------------------------------
# ROTAS FLASK
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    agendar_coleta_automatica(force=False)
    conn = get_db()
    resumo = buscar_resumo_bairros(conn)
    filtro_id = request.args.get("bairro", type=int)
    filtrado = [b for b in resumo if not filtro_id or b["id"] == filtro_id]

    total_registros = conn.execute("SELECT COUNT(*) FROM dados_historicos").fetchone()[0]
    total_casos = conn.execute("SELECT COALESCE(SUM(casos_dengue),0) FROM dados_historicos").fetchone()[0]
    total_focos = conn.execute("SELECT COALESCE(SUM(focos_mosquito),0) FROM dados_historicos").fetchone()[0]
    temp_media = conn.execute("SELECT COALESCE(AVG(temperatura_media),0) FROM dados_historicos").fetchone()[0]
    alto = sum(1 for b in resumo if b["classificacao"] == "Alto")
    medio = sum(1 for b in resumo if b["classificacao"] == "Médio")
    baixo = sum(1 for b in resumo if b["classificacao"] == "Baixo")
    criticos = sorted([b for b in resumo if b["pontuacao"] is not None], key=lambda b: b["pontuacao"], reverse=True)[:5]

    oficial = resumo_oficial_franca(conn)
    clima_ultimo = conn.execute("SELECT * FROM dados_ambientais_franca ORDER BY date(periodo) DESC, id DESC LIMIT 1").fetchone()
    labels = [b["nome"] for b in filtrado]
    ultima_atualizacao = conn.execute("SELECT MAX(data_cadastro) FROM dados_historicos").fetchone()[0]
    return render_template(
        "index.html",
        bairros=resumo, filtro_id=filtro_id, total_bairros=len(resumo),
        total_registros=total_registros, total_casos=total_casos, total_focos=total_focos,
        temp_media=round(temp_media, 1), alto=alto, medio=medio, baixo=baixo, criticos=criticos,
        labels_casos=labels, dados_casos=[b["total_casos"] for b in filtrado],
        dados_risco=[b["pontuacao"] or 0 for b in filtrado],
        dados_incidencia=[b["incidencia_1000"] or 0 for b in filtrado],
        dados_futuros=[b["previsao_casos"] or 0 for b in filtrado],
        dados_reais=None, oficial=oficial, clima_ultimo=dict(clima_ultimo) if clima_ultimo else None,
        ultima_atualizacao=ultima_atualizacao,
    )


@app.route("/fontes/atualizar", methods=["POST"])
def atualizar_fontes():
    combo = coletar_todos_automaticos(force=True)
    mensagens = [r["mensagem"] for r in combo["resultados"]]
    flash(" | ".join(mensagens), "sucesso" if combo["ok"] else "erro")
    return redirect(request.referrer or url_for("index"))


@app.route("/dados/atualizar-automaticos", methods=["POST"])
def atualizar_automaticos():
    combo = coletar_todos_automaticos(force=True)
    mensagens = [r["mensagem"] for r in combo["resultados"]]
    flash(" | ".join(mensagens), "sucesso" if combo["ok"] else "erro")
    return redirect(request.referrer or url_for("cadastro"))


@app.route("/api/clima")
def api_clima():
    periodo = request.args.get("periodo", "").strip()
    if not _parse_periodo(periodo)[0]:
        return {"ok": False, "mensagem": "Informe o período no formato YYYY-MM."}, 400
    row = clima_periodo(periodo)
    if not row:
        return {"ok": False, "mensagem": "Não foi possível obter o clima para esse período."}, 503
    return {"ok": True, "dados": row}


@app.route("/assistente")
def assistente():
    conn = get_db()
    bairros = conn.execute("SELECT id,nome FROM bairros ORDER BY nome").fetchall()
    return render_template("assistente.html", bairros=bairros)

@app.route("/api/assistente", methods=["POST"])
def api_assistente():
    try:
        dados = request.get_json(silent=True) or request.form or {}
        pergunta = str(dados.get("pergunta", "")).strip()[:1200]
        raw_bairro = dados.get("bairro_id")
        bairro_id = parse_int(raw_bairro, 1) if raw_bairro else None
        if not pergunta:
            return {"ok": False, "mensagem": "Digite uma pergunta."}, 400
        fila = _ASSISTENTE_HITS[request.remote_addr or "local"]
        if not consumir_janela(fila, time.time(), ASSISTENTE_LIMITE, ASSISTENTE_JANELA_S):
            return {"ok": False, "mensagem": "Muitas perguntas em pouco tempo. Aguarde alguns minutos e tente de novo."}, 429
        contexto = contexto_assistente(pergunta, bairro_id)
        resposta_local = resposta_assistente_local(pergunta, contexto)
        resposta, fonte = chamar_modelo_linguagem(pergunta, contexto, resposta_local)
        return {
            "ok": True,
            "resposta": resposta,
            "fonte": fonte,
            "bairro": contexto.get("bairro_selecionado"),
            "previsao_clima": contexto.get("previsao_clima"),
        }
    except Exception as exc:
        return {"ok": False, "mensagem": f"Erro interno ao processar a pergunta: {str(exc)[:150]}"}, 500

@app.route("/api/clima/bairro/<int:bairro_id>")
def api_clima_bairro(bairro_id):
    return previsao_clima_bairro(bairro_id)

@app.route("/fontes")
def fontes():
    conn = get_db()
    coleta = resumo_coleta_automatica(conn)
    clima = conn.execute("SELECT * FROM dados_ambientais_franca ORDER BY periodo DESC LIMIT 12").fetchall()
    return render_template("fontes.html", coleta=coleta, clima=clima)


@app.route("/cadastro")
def cadastro():
    conn = get_db()
    bairros = conn.execute("SELECT * FROM bairros ORDER BY nome").fetchall()
    dados = conn.execute("""
        SELECT d.*, b.nome bairro_nome FROM dados_historicos d
        JOIN bairros b ON b.id=d.bairro_id
        ORDER BY d.id DESC
    """).fetchall()
    imports = conn.execute("SELECT * FROM importacoes ORDER BY id DESC LIMIT 8").fetchall()
    coleta = resumo_coleta_automatica(conn)
    clima = conn.execute("SELECT * FROM dados_ambientais_franca ORDER BY periodo DESC LIMIT 12").fetchall()
    return render_template("cadastro.html", bairros=bairros, dados=dados, imports=imports, coleta=coleta, clima=clima)


@app.route("/bairros/adicionar", methods=["POST"])
def adicionar_bairro():
    nome = request.form.get("nome", "").strip()
    raw = request.form.get("populacao", "").strip()
    try:
        populacao = int(raw) if raw else None
        if populacao is not None and populacao < 0:
            raise ValueError
    except ValueError:
        flash("A população deve ser um inteiro maior ou igual a zero.", "erro")
        return redirect(url_for("cadastro"))
    if len(nome) < 2 or len(nome) > 80:
        flash("Informe um nome de bairro entre 2 e 80 caracteres.", "erro")
        return redirect(url_for("cadastro"))
    try:
        conn = get_db()
        conn.execute(
            "INSERT INTO bairros (nome, populacao, populacao_origem) VALUES (?, ?, ?)",
            (nome, populacao, "manual" if populacao is not None else "nao_informada"),
        )
        conn.commit()
        flash(f'Bairro "{nome}" cadastrado.', "sucesso")
    except sqlite3.IntegrityError:
        flash("Esse bairro já está cadastrado.", "erro")
    return redirect(url_for("cadastro"))


@app.route("/bairros/editar/<int:bairro_id>", methods=["POST"])
def editar_bairro(bairro_id):
    nome = request.form.get("nome", "").strip()
    raw = request.form.get("populacao", "").strip()
    try:
        populacao = int(raw) if raw else None
        if populacao is not None and populacao < 0:
            raise ValueError
    except ValueError:
        flash("A população deve ser um inteiro maior ou igual a zero.", "erro")
        return redirect(url_for("cadastro"))
    if not nome:
        flash("O nome não pode ficar vazio.", "erro")
        return redirect(url_for("cadastro"))
    try:
        conn = get_db()
        atual = conn.execute("SELECT populacao, populacao_origem FROM bairros WHERE id=?", (bairro_id,)).fetchone()
        if not atual:
            flash("Bairro não encontrado.", "erro")
            return redirect(url_for("cadastro"))
        origem_pop = atual["populacao_origem"]
        if populacao != atual["populacao"]:
            origem_pop = "manual" if populacao is not None else "nao_informada"
        cur = conn.execute(
            "UPDATE bairros SET nome=?, populacao=?, populacao_origem=? WHERE id=?",
            (nome, populacao, origem_pop, bairro_id),
        )
        if not cur.rowcount:
            flash("Bairro não encontrado.", "erro")
        else:
            conn.commit()
            flash("Bairro atualizado.", "sucesso")
    except sqlite3.IntegrityError:
        flash("Já existe outro bairro com esse nome.", "erro")
    return redirect(url_for("cadastro"))


@app.route("/bairros/excluir/<int:bairro_id>", methods=["POST"])
def excluir_bairro(bairro_id):
    conn = get_db()
    cur = conn.execute("DELETE FROM bairros WHERE id=?", (bairro_id,))
    conn.commit()
    flash("Bairro excluído." if cur.rowcount else "Bairro não encontrado.", "sucesso" if cur.rowcount else "erro")
    return redirect(url_for("cadastro"))


def parse_int(value, minimum=0):
    try:
        n = int(value)
        return n if n >= minimum else None
    except (TypeError, ValueError):
        return None


def parse_float(value, minimum=None, maximum=None):
    try:
        n = float(value)
        if minimum is not None and n < minimum:
            return None
        if maximum is not None and n > maximum:
            return None
        return n
    except (TypeError, ValueError):
        return None


@app.route("/dados/adicionar", methods=["POST"])
def adicionar_dado():
    bairro_id = parse_int(request.form.get("bairro_id"), 1)
    casos = parse_int(request.form.get("casos_dengue"))
    chuva_raw = request.form.get("chuva_mm", "").strip()
    temp_raw = request.form.get("temperatura_media", "").strip()
    chuva = parse_float(chuva_raw, 0) if chuva_raw else None
    temp = parse_float(temp_raw, -20, 60) if temp_raw else None
    focos = parse_int(request.form.get("focos_mosquito"))
    periodo = request.form.get("periodo", "").strip()
    clima = clima_periodo(periodo) if periodo and (not chuva_raw or not temp_raw) else None
    if chuva is None and clima:
        chuva = clima["chuva_mm"]
    if temp is None and clima:
        temp = clima["temperatura_media"]
    if not all([bairro_id, casos is not None, chuva is not None, temp is not None, focos is not None, periodo]):
        flash("Informe casos, focos e período. Chuva e temperatura podem ser preenchidas automaticamente pelo botão de clima.", "erro")
        return redirect(url_for("cadastro"))
    chuva_origem = "manual" if chuva_raw else ("automatico" if clima else "manual")
    temp_origem = "manual" if temp_raw else ("automatico" if clima else "manual")
    conn = get_db()
    if not conn.execute("SELECT 1 FROM bairros WHERE id=?", (bairro_id,)).fetchone():
        flash("Bairro inválido.", "erro")
        return redirect(url_for("cadastro"))
    try:
        conn.execute("""
            INSERT INTO dados_historicos
            (bairro_id,periodo,casos_dengue,chuva_mm,temperatura_media,focos_mosquito,origem,casos_origem,focos_origem,chuva_origem,temperatura_origem)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
        """, (bairro_id, periodo[:30], casos, chuva, temp, focos, "manual", "manual", "manual", chuva_origem, temp_origem))
        conn.commit()
        flash("Registro histórico adicionado.", "sucesso")
    except sqlite3.IntegrityError:
        flash("Já existe um registro desse bairro para esse período.", "erro")
    return redirect(url_for("cadastro"))


@app.route("/dados/editar/<int:dado_id>", methods=["POST"])
def editar_dado(dado_id):
    periodo = request.form.get("periodo", "").strip()[:30]
    casos = parse_int(request.form.get("casos_dengue"))
    chuva = parse_float(request.form.get("chuva_mm"), 0)
    temp = parse_float(request.form.get("temperatura_media"), -20, 60)
    focos = parse_int(request.form.get("focos_mosquito"))
    if not periodo or casos is None or chuva is None or temp is None or focos is None:
        flash("Valores inválidos no registro.", "erro")
        return redirect(url_for("cadastro"))
    conn = get_db()
    try:
        conn.execute("""
            UPDATE dados_historicos
            SET periodo=?, casos_dengue=?, chuva_mm=?, temperatura_media=?, focos_mosquito=?, origem='manual',
                casos_origem='manual', focos_origem='manual', chuva_origem='manual', temperatura_origem='manual'
            WHERE id=?
        """, (periodo, casos, chuva, temp, focos, dado_id))
        conn.commit()
        flash("Registro atualizado.", "sucesso")
    except sqlite3.IntegrityError:
        flash("Já existe outro registro desse bairro com o mesmo período.", "erro")
    return redirect(url_for("cadastro"))


@app.route("/dados/excluir/<int:dado_id>", methods=["POST"])
def excluir_dado(dado_id):
    conn = get_db()
    cur = conn.execute("DELETE FROM dados_historicos WHERE id=?", (dado_id,))
    conn.commit()
    flash("Registro excluído." if cur.rowcount else "Registro não encontrado.", "sucesso" if cur.rowcount else "erro")
    return redirect(url_for("cadastro"))


@app.route("/dados/importar", methods=["POST"])
def importar_csv():
    arquivo = request.files.get("arquivo")
    if not arquivo or not arquivo.filename:
        flash("Selecione um arquivo CSV.", "erro")
        return redirect(url_for("cadastro"))
    if not arquivo.filename.lower().endswith(".csv"):
        flash("Envie um arquivo com extensão .csv.", "erro")
        return redirect(url_for("cadastro"))

    try:
        raw = arquivo.read().decode("utf-8-sig")
        df = pd.read_csv(io.StringIO(raw))
        df.columns = [str(c).strip().lower() for c in df.columns]
        obrigatorias = {"bairro", "periodo", "casos", "chuva_mm", "temperatura_media", "focos"}
        if not obrigatorias.issubset(df.columns):
            faltantes = ", ".join(sorted(obrigatorias - set(df.columns)))
            raise ValueError(f"Colunas ausentes: {faltantes}")
        if len(df) > 5000:
            raise ValueError("O arquivo pode conter no máximo 5.000 linhas.")

        conn = get_db()
        bairros = {row["nome"].strip().casefold(): row["id"] for row in conn.execute("SELECT id,nome FROM bairros")}
        inseridos = 0
        erros = []
        for idx, row in df.iterrows():
            nome = str(row["bairro"]).strip()
            bairro_id = bairros.get(nome.casefold())
            periodo = str(row["periodo"]).strip()[:30]
            casos = parse_int(row["casos"])
            chuva = parse_float(row["chuva_mm"], 0)
            temp = parse_float(row["temperatura_media"], -20, 60)
            focos = parse_int(row["focos"])
            if not bairro_id or not periodo or casos is None or chuva is None or temp is None or focos is None:
                erros.append(idx + 2)
                continue
            try:
                conn.execute("""
                    INSERT INTO dados_historicos
                    (bairro_id,periodo,casos_dengue,chuva_mm,temperatura_media,focos_mosquito,origem,casos_origem,focos_origem,chuva_origem,temperatura_origem)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(bairro_id,periodo) DO UPDATE SET
                        casos_dengue=excluded.casos_dengue,
                        chuva_mm=excluded.chuva_mm,
                        temperatura_media=excluded.temperatura_media,
                        focos_mosquito=excluded.focos_mosquito,
                        origem='importado',
                        casos_origem='importado',
                        focos_origem='importado',
                        chuva_origem='manual',
                        temperatura_origem='manual'
                """, (bairro_id, periodo, casos, chuva, temp, focos, "importado", "importado", "importado", "manual", "manual"))
                inseridos += 1
            except sqlite3.Error:
                erros.append(idx + 2)
        conn.execute(
            "INSERT INTO importacoes (arquivo,status,registros,mensagem) VALUES (?,?,?,?)",
            (arquivo.filename[:150], "sucesso" if not erros else "parcial", inseridos, f"Linhas com erro: {erros[:20]}" if erros else "Importação concluída.")
        )
        conn.commit()
        flash(f"Importação concluída: {inseridos} registro(s)." + (f" {len(erros)} linha(s) ignorada(s)." if erros else ""), "sucesso" if inseridos else "erro")
    except Exception as exc:
        conn = get_db()
        conn.execute("INSERT INTO importacoes (arquivo,status,registros,mensagem) VALUES (?,?,?,?)",
                     (arquivo.filename[:150], "erro", 0, str(exc)[:500]))
        conn.commit()
        flash(f"Não foi possível importar o arquivo: {exc}", "erro")
    return redirect(url_for("cadastro"))


@app.route("/bairros")
def bairros_page():
    agendar_coleta_automatica(force=False)
    conn = get_db()
    bairros = buscar_resumo_bairros(conn)
    ordem = request.args.get("ordem", "risco")
    if ordem == "incidencia":
        bairros.sort(key=lambda b: (b["incidencia_1000"] is not None, b["incidencia_1000"] or -1), reverse=True)
    elif ordem == "casos":
        bairros.sort(key=lambda b: b["total_casos"], reverse=True)
    elif ordem == "previsao":
        bairros.sort(key=lambda b: b["previsao_casos"] or -1, reverse=True)
    else:
        bairros.sort(key=lambda b: b["pontuacao"] if b["pontuacao"] is not None else -1, reverse=True)

    conn_map = get_db()
    coords = {}
    for r in conn_map.execute("SELECT id, nome, latitude, longitude, geometria_origem FROM bairros").fetchall():
        lat, lon = r["latitude"], r["longitude"]
        ajuste_manual = str(r["geometria_origem"] or "").lower().startswith("ajuste manual")
        dentro_mapa = (
            lat is not None and lon is not None
            and FRANCA_LAT_MIN <= float(lat) <= FRANCA_LAT_MAX
            and FRANCA_LON_MIN <= float(lon) <= FRANCA_LON_MAX
        )
        if not dentro_mapa and not ajuste_manual:
            oficial_c = BAIRROS_COM_COORDENADAS.get(r["nome"])
            if oficial_c:
                lat, lon = oficial_c
                conn_map.execute("UPDATE bairros SET latitude=?, longitude=? WHERE id=?", (lat, lon, r["id"]))
                conn_map.commit()
        coords[r["id"]] = (lat, lon)

    mapa = []
    for b in bairros:
        item = dict(b)
        item["latitude"], item["longitude"] = coords.get(b["id"], (None, None))
        mapa.append(item)
    mapa_geolocalizados = sum(1 for b in mapa if b["latitude"] is not None and b["longitude"] is not None)
    coordenadas_oficiais = {nome: [lat, lon] for nome, (lat, lon) in BAIRROS_COM_COORDENADAS.items()}
    return render_template(
        "bairros.html",
        bairros=bairros,
        mapa=mapa,
        ordem=ordem,
        total_bairros=len(bairros),
        mapa_geolocalizados=mapa_geolocalizados,
        coordenadas_oficiais=coordenadas_oficiais,
    )


@app.route("/bairro/<int:bairro_id>")
def detalhe_bairro(bairro_id):
    conn = get_db()
    bairro = conn.execute("SELECT * FROM bairros WHERE id=?", (bairro_id,)).fetchone()
    if not bairro:
        abort(404)
    registros = conn.execute("""
        SELECT * FROM dados_historicos WHERE bairro_id=? ORDER BY periodo ASC, id ASC
    """, (bairro_id,)).fetchall()
    previsao = conn.execute("""
        SELECT * FROM previsoes WHERE bairro_id=? ORDER BY id DESC LIMIT 1
    """, (bairro_id,)).fetchone()
    total_casos = sum(r["casos_dengue"] for r in registros)
    total_focos = sum(r["focos_mosquito"] for r in registros)
    incidencia = (
        total_casos / bairro["populacao"] * 1000
        if populacao_confiavel(bairro["populacao"], bairro["populacao_origem"])
        else None
    )
    tendencia = tendencia_bairro(conn, bairro_id)
    labels = [r["periodo"] for r in registros]
    casos = [r["casos_dengue"] for r in registros]
    chuva = [r["chuva_mm"] for r in registros]
    focos = [r["focos_mosquito"] for r in registros]
    return render_template(
        "bairro_detalhe.html", bairro=bairro, registros=registros, previsao=previsao,
        total_casos=total_casos, total_focos=total_focos,
        incidencia=round(incidencia, 2) if incidencia is not None else None,
        tendencia=tendencia, labels=labels, casos=casos, chuva=chuva, focos=focos,
    )


@app.route("/previsao", methods=["GET", "POST"])
def previsao():
    conn = get_db()
    bairros = conn.execute("SELECT * FROM bairros ORDER BY nome").fetchall()
    resultado = None
    bairro_selecionado = None
    if request.method == "POST":
        bairro_id = parse_int(request.form.get("bairro_id"), 1)
        bairro_selecionado = conn.execute("SELECT * FROM bairros WHERE id=?", (bairro_id,)).fetchone() if bairro_id else None
        if bairro_selecionado:
            resultado = gerar_previsao(bairro_id, salvar=True)
        else:
            flash("Selecione um bairro válido.", "erro")
    elif request.args.get("bairro", type=int):
        bairro_id = request.args.get("bairro", type=int)
        bairro_selecionado = conn.execute("SELECT * FROM bairros WHERE id=?", (bairro_id,)).fetchone()
    historico = conn.execute("""
        SELECT p.*, b.nome bairro_nome FROM previsoes p
        JOIN bairros b ON b.id=p.bairro_id ORDER BY p.id DESC LIMIT 30
    """).fetchall()
    avaliacao = None
    cache = treinar_modelo_temporal(conn)
    if cache["modelo"]:
        avaliacao = {
            "exemplos": len(cache["df"]),
            "mae_treino": cache["metrica"]["mae_treino"],
            "rmse_treino": cache["metrica"]["rmse_treino"],
            "mae_teste": cache["metrica"]["mae_teste"],
            "rmse_teste": cache["metrica"]["rmse_teste"],
            "r2_teste": cache["metrica"]["r2_teste"],
            "cache_usado": cache["timestamp"] is not None,
        }
    return render_template("previsao.html", bairros=bairros, resultado=resultado,
                           bairro_selecionado=bairro_selecionado, historico=historico, avaliacao=avaliacao)


@app.route("/previsao/gerar-todas", methods=["POST"])
def gerar_todas_previsoes():
    conn = get_db()
    bairros = conn.execute("SELECT id FROM bairros").fetchall()
    geradas = 0
    for b in bairros:
        if ultimo_registro_bairro(conn, b["id"]):
            if gerar_previsao(b["id"], salvar=True):
                geradas += 1
    flash(f"{geradas} previsão(ões) atualizada(s).", "sucesso")
    return redirect(url_for("previsao"))


@app.route("/metodologia")
def metodologia():
    return render_template("metodologia.html")


@app.route("/relatorios")
def relatorios():
    conn = get_db()
    dados = conn.execute("""
        SELECT d.*, b.nome bairro_nome FROM dados_historicos d
        JOIN bairros b ON b.id=d.bairro_id ORDER BY d.id DESC
    """).fetchall()
    previsoes = conn.execute("""
        SELECT p.*, b.nome bairro_nome FROM previsoes p
        JOIN bairros b ON b.id=p.bairro_id ORDER BY p.id DESC LIMIT 100
    """).fetchall()
    oficial = conn.execute("SELECT * FROM dados_oficiais_franca ORDER BY date(data_inicio_semana) DESC").fetchall()
    resumo = buscar_resumo_bairros(conn)
    atualizacoes = conn.execute("SELECT * FROM atualizacoes_fontes ORDER BY id DESC LIMIT 10").fetchall()
    return render_template("relatorios.html", dados=dados, previsoes=previsoes, oficial=oficial,
                           resumo=resumo, atualizacoes=atualizacoes)


@app.route("/relatorios/exportar/<tipo>")
def exportar_csv(tipo):
    conn = get_db()
    if tipo == "bairros":
        linhas = conn.execute("SELECT * FROM bairros ORDER BY nome").fetchall()
        colunas = ["id", "nome", "populacao"]
    elif tipo == "dados":
        linhas = conn.execute("""
            SELECT d.id,b.nome bairro,d.periodo,d.casos_dengue,d.chuva_mm,
                   d.temperatura_media,d.focos_mosquito,d.origem,d.chuva_origem,d.temperatura_origem,d.data_cadastro
            FROM dados_historicos d JOIN bairros b ON b.id=d.bairro_id
            ORDER BY b.nome,d.periodo
        """).fetchall()
        colunas = ["id", "bairro", "periodo", "casos_dengue", "chuva_mm", "temperatura_media", "focos_mosquito", "origem", "chuva_origem", "temperatura_origem", "data_cadastro"]
    elif tipo == "previsoes":
        linhas = conn.execute("""
            SELECT p.id,b.nome bairro,p.data_previsao,p.pontuacao_risco,p.classificacao,
                   p.fatores_principais,p.metodo,p.mae_modelo,p.rmse_modelo,p.mae_teste,
                   p.rmse_teste,p.r2_teste,p.previsao_casos,p.limite_inferior,
                   p.limite_superior,p.probabilidade_aumento,p.horizonte_periodos,p.observacao
            FROM previsoes p JOIN bairros b ON b.id=p.bairro_id ORDER BY p.id DESC
        """).fetchall()
        colunas = ["id", "bairro", "data_previsao", "pontuacao_risco", "classificacao", "fatores_principais", "metodo",
                   "mae_modelo", "rmse_modelo", "mae_teste", "rmse_teste", "r2_teste", "previsao_casos",
                   "limite_inferior", "limite_superior", "probabilidade_aumento", "horizonte_periodos", "observacao"]
    elif tipo == "ambiental":
        linhas = conn.execute("SELECT * FROM dados_ambientais_franca ORDER BY date(periodo)").fetchall()
        colunas = ["id", "periodo", "inicio_periodo", "fim_periodo", "chuva_mm", "temperatura_media", "temperatura_min", "temperatura_max", "horas_precipitacao", "vento_max_kmh", "umidade_media", "horas_sol", "fonte", "atualizado_em"]
    elif tipo == "oficial":
        linhas = conn.execute("SELECT * FROM dados_oficiais_franca ORDER BY date(data_inicio_semana)").fetchall()
        colunas = ["id", "data_inicio_semana", "semana_epidemiologica", "casos_semana", "casos_estimados",
                   "casos_acumulados", "incidencia_100k", "nivel_alerta", "rt", "prob_rt_maior_1", "receptivo", "transmissao", "fonte", "atualizado_em"]
    elif tipo == "resumo":
        linhas = buscar_resumo_bairros(conn)
        colunas = ["id", "nome", "populacao", "qtd_registros", "total_casos", "total_focos", "incidencia_1000",
                   "pontuacao", "classificacao", "previsao_casos", "probabilidade_aumento", "ultimo_periodo"]
    else:
        abort(404)

    buffer = io.StringIO()
    out = csv.writer(buffer)
    out.writerow(colunas)
    for linha in linhas:
        out.writerow([linha[c] if isinstance(linha, sqlite3.Row) else linha.get(c) for c in colunas])
    filename = f"relatorio_{tipo}_{datetime.now().strftime('%Y%m%d_%H%M')}.csv"
    return Response("\ufeff" + buffer.getvalue(), mimetype="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f"attachment; filename={filename}"})


@app.errorhandler(400)
def erro_400(exc):
    return render_template("erro.html", codigo=400, mensagem=getattr(exc, "description", "Requisição inválida.")), 400


@app.errorhandler(404)
def erro_404(exc):
    return render_template("erro.html", codigo=404, mensagem="Página ou registro não encontrado."), 404


@app.errorhandler(413)
def erro_413(exc):
    return render_template("erro.html", codigo=413, mensagem="Arquivo muito grande. O limite de importação é 2 MB."), 413


@app.errorhandler(500)
def erro_500(exc):
    return render_template("erro.html", codigo=500, mensagem="Ocorreu um erro interno. Consulte o terminal para detalhes."), 500

@app.route("/api/bairro/<int:bairro_id>/coordenadas", methods=["POST"])
def api_atualizar_coordenadas_bairro(bairro_id):
    try:
        dados = request.get_json(silent=True) or request.form or {}
        lat = parse_float(dados.get("latitude"), -90, 90)
        lon = parse_float(dados.get("longitude"), -180, 180)
        if lat is None or lon is None:
            return {"ok": False, "mensagem": "Coordenadas inválidas."}, 400

        enviado = (
            request.headers.get("X-CSRFToken")
            or dados.get("_csrf")
            or ""
        )
        esperado = session.get("_csrf", "")
        if not esperado or not secrets.compare_digest(str(enviado), esperado):
            return {"ok": False, "mensagem": "Token de segurança inválido. Recarregue a página."}, 400

        conn = get_db()
        cur = conn.execute(
            "UPDATE bairros SET latitude=?, longitude=?, geometria_origem='ajuste manual mapa' WHERE id=?",
            (lat, lon, bairro_id)
        )
        conn.commit()
        if not cur.rowcount:
            return {"ok": False, "mensagem": "Bairro não encontrado."}, 404
        return {"ok": True, "mensagem": "Coordenadas salvas com sucesso no banco."}
    except Exception as exc:
        return {"ok": False, "mensagem": str(exc)}, 500

init_db()

def agendar_recalculo_modelo():
    """Recalcula as previsões salvas uma vez quando a regra do modelo muda."""
    def _run():
        with app.app_context():
            conn = get_db()
            row = conn.execute("SELECT valor FROM meta_sistema WHERE chave='modelo_versao'").fetchone()
            if row and row["valor"] == MODELO_VERSAO:
                return
            bairros = conn.execute("SELECT id FROM bairros").fetchall()
            for bairro in bairros:
                if ultimo_registro_bairro(conn, bairro["id"]):
                    gerar_previsao(bairro["id"], salvar=True)
            conn.execute(
                """
                INSERT INTO meta_sistema (chave, valor) VALUES ('modelo_versao', ?)
                ON CONFLICT(chave) DO UPDATE SET valor=excluded.valor
                """,
                (MODELO_VERSAO,),
            )
            conn.commit()

    threading.Thread(target=_run, daemon=True, name="dengue-modelo").start()


if __name__ == "__main__":
    agendar_recalculo_modelo()
    debug = os.environ.get("DENGUE_DEBUG", "0").lower() in ("1", "true", "sim")
    print("[DENGUE] Projeto carregado com sucesso.", flush=True)
    print("[DENGUE] Banco:", DB_PATH, flush=True)
    print("[DENGUE] Servidor: http://127.0.0.1:5000", flush=True)
    app.run(host="127.0.0.1", port=5000, debug=debug, use_reloader=False)