# -*- coding: utf-8 -*-
import unittest

from assistente_temas import pergunta_educativa, resposta_tema_dengue, sintomas_citados


class AssistenteTemasTest(unittest.TestCase):
    def test_sintomas_citados_nao_confundem_alerta_com_vomito_simples(self):
        citados = {item["rotulo"]: item["alerta"] for item in sintomas_citados(
            "estou com febre, dor atras dos olhos e dor no corpo"
        )}
        self.assertEqual(citados["Febre"], False)
        self.assertEqual(citados["Dor atrás dos olhos"], False)
        self.assertEqual(citados["Dor no corpo"], False)
        self.assertNotIn("Vômito persistente", citados)

    def test_comparacao_avisa_que_nao_e_diagnostico(self):
        texto, fonte = resposta_tema_dengue(
            "Estou com febre, dor atrás dos olhos e dor no corpo. Pode ser dengue?"
        )
        self.assertIn("não é um diagnóstico", texto.lower())
        self.assertIn("Febre", texto)
        self.assertIn("Dor atrás dos olhos", texto)
        self.assertIn("comparação", fonte)
        self.assertNotIn("%", texto)

    def test_sinal_de_alerta_pede_atendimento(self):
        texto, _fonte = resposta_tema_dengue("estou com febre e sangramento na gengiva")
        self.assertIn("Sangramento na gengiva", texto)
        self.assertIn("agora", texto.lower())

    def test_lista_de_sintomas_e_transmissao(self):
        lista, _fonte = resposta_tema_dengue("Quais são os sintomas da dengue e os sinais de alerta?")
        self.assertIn("Sinais de alerta", lista)
        self.assertIn("Febre", lista)
        transmissao, _fonte = resposta_tema_dengue("Como a dengue é transmitida?")
        self.assertIn("Aedes", transmissao)
        mosquito, _fonte = resposta_tema_dengue("O que é o mosquito da dengue?")
        self.assertIn("Aedes aegypti", mosquito)

    def test_risco_e_chuva_ficam_com_o_painel(self):
        self.assertIsNone(resposta_tema_dengue("Qual é o risco do bairro selecionado?"))
        self.assertIsNone(resposta_tema_dengue("Qual a probabilidade de chuva no Jardim Brasil?"))
        self.assertFalse(pergunta_educativa("Qual é o risco do bairro selecionado?"))

    def test_marcas_no_corpo_falam_de_pele_e_nao_de_risco(self):
        texto, fonte = resposta_tema_dengue("quais as marcas que a dengue deixa no corpo?")
        self.assertIsNotNone(texto)
        self.assertIn("mancha", texto.lower())
        self.assertIn("pele", texto.lower())
        self.assertIn("não é um diagnóstico", texto.lower())
        self.assertNotIn("classificação", texto.lower())
        self.assertNotIn("pontos", texto.lower())
        self.assertIn("orientação", fonte)
        self.assertTrue(pergunta_educativa("quais as marcas que a dengue deixa no corpo?"))
