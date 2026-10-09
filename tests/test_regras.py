# -*- coding: utf-8 -*-
import sqlite3
import unittest
from collections import deque

import pandas as pd

from integridade import (
    chaves_nome_bairro,
    consumir_janela,
    gravar_casos_sinan,
    melhor_bairro_oficial,
    origem_http_permitida,
    origem_permite_treino,
    populacao_confiavel,
    sanear_historico_misto,
)
from modelo import (
    ajustar_modelo,
    calcular_risco_formula,
    classificar_risco,
    construir_dataset_temporal,
    dividir_treino_teste_temporal,
    probabilidade_aumento_recente,
)


def _conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE bairros (
            id INTEGER PRIMARY KEY,
            nome TEXT UNIQUE,
            populacao INTEGER,
            populacao_origem TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE dados_historicos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            bairro_id INTEGER NOT NULL,
            periodo TEXT NOT NULL,
            casos_dengue INTEGER NOT NULL DEFAULT 0,
            chuva_mm REAL NOT NULL DEFAULT 0,
            temperatura_media REAL NOT NULL DEFAULT 0,
            focos_mosquito INTEGER NOT NULL DEFAULT 0,
            origem TEXT,
            casos_origem TEXT,
            focos_origem TEXT,
            chuva_origem TEXT,
            temperatura_origem TEXT,
            UNIQUE(bairro_id, periodo)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE dados_ambientais_franca (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            periodo TEXT,
            chuva_mm REAL,
            temperatura_media REAL,
            umidade_media REAL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE sinan_nomes_ignorados (
            nome TEXT PRIMARY KEY,
            motivo TEXT,
            ocorrencias INTEGER,
            atualizado_em TEXT
        )
        """
    )
    return conn


class RegrasOrigemTest(unittest.TestCase):
    def test_demonstracao_fica_fora_do_treino(self):
        self.assertFalse(origem_permite_treino("demonstração", "demonstração"))
        self.assertFalse(origem_permite_treino("SINAN/Dengue", "demonstração"))
        self.assertTrue(origem_permite_treino("SINAN/Dengue", "automatico - SINAN/Dengue"))
        self.assertTrue(origem_permite_treino("manual", "manual"))
        self.assertTrue(origem_permite_treino("importado", "importado"))

    def test_populacao_placeholder_nao_gera_incidencia(self):
        self.assertFalse(populacao_confiavel(8000, "Consolidado Franca/SP"))
        self.assertFalse(populacao_confiavel(None, "nao_informada"))
        self.assertTrue(populacao_confiavel(12000, "manual"))
        self.assertTrue(populacao_confiavel(9800, "automatico - IBGE Censo 2022"))
        self.assertTrue(populacao_confiavel(6500, "Estimativa Urbana Franca/SP"))

    def test_casamento_exato_e_recusa_nome_distante(self):
        indice = {}
        for chave in chaves_nome_bairro("Jardim Dermínio"):
            indice[chave] = {"id": 7, "nome": "Jardim Dermínio"}
        self.assertEqual(melhor_bairro_oficial("Jd. Derminio", indice)["id"], 7)
        self.assertIsNone(melhor_bairro_oficial("Nucleo Habitacional Inexistente", indice))

    def test_sinan_nao_sobrescreve_manual(self):
        conn = _conn()
        conn.execute("INSERT INTO bairros (id, nome) VALUES (1, 'Centro')")
        conn.execute(
            """
            INSERT INTO dados_historicos
            (bairro_id, periodo, casos_dengue, origem, casos_origem, focos_origem, chuva_origem, temperatura_origem)
            VALUES (1, '2025-01', 4, 'manual', 'manual', 'manual', 'manual', 'manual')
            """
        )
        self.assertEqual(gravar_casos_sinan(conn, 1, "2025-01", 99, "SINAN/Dengue - Ministério da Saúde"), 0)
        casos = conn.execute("SELECT casos_dengue, origem FROM dados_historicos").fetchone()
        self.assertEqual(casos["casos_dengue"], 4)
        self.assertEqual(casos["origem"], "manual")

    def test_sinan_limpa_foco_sintetico_e_saneamento_copia_clima(self):
        conn = _conn()
        conn.execute("INSERT INTO bairros (id, nome) VALUES (1, 'Centro')")
        conn.execute(
            """
            INSERT INTO dados_historicos (
                bairro_id, periodo, casos_dengue, chuva_mm, temperatura_media, focos_mosquito,
                origem, casos_origem, focos_origem, chuva_origem, temperatura_origem
            ) VALUES (1, '2025-03', 8, 120, 30, 9, 'demonstração', 'demonstração', 'demonstração', 'demonstração', 'demonstração')
            """
        )
        conn.execute(
            "INSERT INTO dados_ambientais_franca (periodo, chuva_mm, temperatura_media, umidade_media) VALUES ('2025-03', 40, 24, 70)"
        )
        gravar_casos_sinan(conn, 1, "2025-03", 15, "SINAN/Dengue - Ministério da Saúde")
        sanear_historico_misto(conn)
        row = conn.execute("SELECT * FROM dados_historicos").fetchone()
        self.assertEqual(row["casos_dengue"], 15)
        self.assertEqual(row["casos_origem"], "automatico - SINAN/Dengue")
        self.assertEqual(row["focos_origem"], "ausente")
        self.assertEqual(row["focos_mosquito"], 0)
        self.assertEqual(row["chuva_mm"], 40)
        self.assertEqual(row["chuva_origem"], "automatico")
        self.assertEqual(row["temperatura_media"], 24)

    def test_serie_de_demonstracao_nao_entra_no_dataset(self):
        conn = _conn()
        conn.execute("INSERT INTO bairros (id, nome) VALUES (1, 'Centro')")
        for i, periodo in enumerate(("2025-01", "2025-02", "2025-03", "2025-04")):
            conn.execute(
                """
                INSERT INTO dados_historicos
                (bairro_id, periodo, casos_dengue, chuva_mm, temperatura_media, focos_mosquito, origem, casos_origem, focos_origem, chuva_origem, temperatura_origem)
                VALUES (1, ?, ?, 10, 25, 1, 'demonstração', 'demonstração', 'demonstração', 'demonstração', 'demonstração')
                """,
                (periodo, i),
            )
        for i, periodo in enumerate(("2024-01", "2024-02", "2024-03", "2024-04")):
            conn.execute(
                """
                INSERT INTO dados_historicos
                (bairro_id, periodo, casos_dengue, chuva_mm, temperatura_media, focos_mosquito, origem, casos_origem, focos_origem, chuva_origem, temperatura_origem)
                VALUES (1, ?, ?, 10, 25, 1, 'manual', 'manual', 'manual', 'manual', 'manual')
                """,
                (periodo, i + 1),
            )
        df = construir_dataset_temporal(conn)
        self.assertTrue(set(df["periodo"]).issubset({"2024-03", "2024-04"}))
        self.assertNotIn("2025-04", set(df["periodo"]))


class ModeloTest(unittest.TestCase):
    def test_corte_temporal_nao_repete_periodo(self):
        linhas = []
        for bairro in (1, 2):
            for mes in range(1, 11):
                linhas.append({
                    "bairro_id": bairro,
                    "periodo": f"2024-{mes:02d}",
                    "casos_lag1": mes,
                    "casos_lag2": mes,
                    "media_3": mes,
                    "chuva_mm": 10,
                    "temperatura_media": 25,
                    "umidade_media": 70,
                    "focos_mosquito": 1,
                    "focos_informado": 1,
                    "target": mes + bairro,
                })
        df = pd.DataFrame(linhas)
        treino, teste = dividir_treino_teste_temporal(df)
        self.assertFalse(set(treino["periodo"]) & set(teste["periodo"]))
        self.assertLess(max(treino["periodo"]), min(teste["periodo"]))

    def test_ajuste_publica_referencias(self):
        linhas = []
        for bairro in range(1, 5):
            for mes in range(1, 13):
                linhas.append({
                    "bairro_id": bairro,
                    "periodo": f"2024-{mes:02d}",
                    "casos_lag1": float(mes),
                    "casos_lag2": float(max(mes - 1, 1)),
                    "media_3": float(mes),
                    "chuva_mm": 20.0 + mes,
                    "temperatura_media": 24.0,
                    "umidade_media": None if mes == 1 else 65.0,
                    "focos_mosquito": 0.0,
                    "focos_informado": 0.0,
                    "target": float(mes + bairro),
                })
        resultado = ajustar_modelo(pd.DataFrame(linhas), n_estimators=20, minimo_exemplos=20)
        self.assertIsNotNone(resultado["modelo"])
        self.assertIn("mae_persistencia", resultado["metrica"])
        self.assertIn("mae_media3", resultado["metrica"])
        self.assertIn("umidade_media", resultado["preenchimento"])

    def test_classificacao(self):
        self.assertEqual(classificar_risco(70)[0], "Alto")
        self.assertEqual(classificar_risco(40)[0], "Médio")
        self.assertEqual(classificar_risco(39.9)[0], "Baixo")

    def test_clima_sem_casos_nem_focos_observados_fica_baixo(self):
        """Chuva e temperatura municipais, sozinhas, não passam de Baixo."""
        sem_evidencia = calcular_risco_formula(0, 152.1, 21.94, 0, focos_disponiveis=False)
        self.assertEqual(sem_evidencia, 28.9)
        self.assertEqual(classificar_risco(sem_evidencia), ("Baixo", "verde"))
        self.assertLess(sem_evidencia, 40)

        com_casos = calcular_risco_formula(40, 152.1, 21.94, 0, focos_disponiveis=False)
        self.assertGreaterEqual(com_casos, 70)
        self.assertEqual(classificar_risco(com_casos)[0], "Alto")

        focos_observados = calcular_risco_formula(0, 152.1, 21.94, 25, focos_disponiveis=True)
        self.assertGreaterEqual(focos_observados, 40)
        self.assertEqual(classificar_risco(focos_observados)[0], "Médio")

    def test_probabilidade_mistura_subida_e_chuva(self):
        self.assertEqual(probabilidade_aumento_recente([10, 12, 15], 0), 0.6)
        self.assertEqual(probabilidade_aumento_recente([0, 0, 0], 150), 0.4)
        self.assertEqual(probabilidade_aumento_recente([0, 0, 0], 300), 0.4)
        self.assertEqual(probabilidade_aumento_recente([5], 75), 0.5)
        self.assertEqual(probabilidade_aumento_recente([10, 8, 12], 0), 0.3)


class ApiLocalTest(unittest.TestCase):
    def test_limite_de_janela(self):
        fila = deque()
        for i in range(3):
            self.assertTrue(consumir_janela(fila, 1000 + i, 3, 600))
        self.assertFalse(consumir_janela(fila, 1003, 3, 600))
        self.assertTrue(consumir_janela(fila, 1000 + 601, 3, 600))

    def test_origem_http(self):
        self.assertTrue(origem_http_permitida("127.0.0.1:5000", "http://127.0.0.1:5000", "", "127.0.0.1"))
        self.assertFalse(origem_http_permitida("127.0.0.1:5000", "http://evil.test", "", "127.0.0.1"))
        self.assertTrue(origem_http_permitida("127.0.0.1:5000", "", "", "127.0.0.1"))
        self.assertFalse(origem_http_permitida("127.0.0.1:5000", "", "", "10.0.0.8"))


if __name__ == "__main__":
    unittest.main()
