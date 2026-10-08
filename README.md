# Prevenção Dengue — Franca/SP

Projeto acadêmico de ciência de dados e Machine Learning para apoio à prevenção de dengue em Franca/SP. Autoria: Arthur Henrique.

O sistema reúne dados por bairro, indicadores municipais, clima, análise de risco e previsão de curto prazo. **Não substitui vigilância epidemiológica nem decisão oficial de saúde pública.**

## Como executar

```bash
python -m pip install -r requirements.txt
python app.py
```

No Windows, também é possível usar `INICIAR.bat`. Depois abra [http://127.0.0.1:5000](http://127.0.0.1:5000).

## Publicar no GitHub

Não envie a pasta `venv/` nem arquivos de segredo (`.env`, `.secret_key`). O `.gitignore` já cobre isso.

Variáveis opcionais:

- `DENGUE_SECRET_KEY` — chave de sessão (gerada localmente se ausente)
- `OPENAI_API_KEY` — só se quiser o assistente com modelo de linguagem
- `DENGUE_DEBUG=1` — apenas em desenvolvimento

Documentação completa: [LEIA-ME.txt](LEIA-ME.txt).
