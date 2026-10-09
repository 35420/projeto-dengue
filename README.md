# Prevenção Dengue — Franca/SP

Projeto acadêmico de ciência de dados e Machine Learning para apoio à prevenção de dengue em Franca/SP. Autoria: Arthur Henrique.

O sistema reúne dados por bairro, indicadores municipais, clima, análise de risco e previsão de curto prazo. **Não substitui vigilância epidemiológica, diagnóstico nem decisão oficial de saúde pública.**

A base local inicial é de demonstração. Os números por bairro com origem `demonstração` não são casos oficiais. A série do InfoDengue fica numa tabela municipal, separada desses registros.

## Como executar

```bash
python -m pip install -r requirements.txt
python app.py
```

No Windows, `INICIAR.bat` confere as bibliotecas, instala o que faltar e sobe o servidor. Depois abra [http://127.0.0.1:5000](http://127.0.0.1:5000).

O debug fica desligado. Para o modo de desenvolvimento: `DENGUE_DEBUG=1`. A chave de sessão sai de `DENGUE_SECRET_KEY` ou do arquivo local `.secret_key`, que não entra no Git. A chave de linguagem, se for usada, fica só em `OPENAI_API_KEY`.

Documentação operacional complementar: [LEIA-ME.txt](LEIA-ME.txt).

## O que o sistema faz

- Dashboard com totais locais, painel municipal da semana e do mês, gráficos e ranking.
- Mapa de Franca com marcadores por risco, tabela e página de cada bairro.
- Fórmula didática de risco, de 0 a 100, e previsão de curto prazo.
- Cadastro, edição, exclusão e importação CSV.
- Relatórios e exportação.
- Coleta automática do InfoDengue, do Open-Meteo, do SINAN/Dengue e do IBGE.
- Assistente em português, com respostas locais e, se houver chave, redação por modelo de linguagem.

## Dashboard

A página inicial mostra quantos bairros estão cadastrados, quantos registros e casos existem na base local e quantos bairros estão em risco baixo, médio ou alto. O filtro por bairro muda só os gráficos. Não grava nada no banco.

O painel municipal fica separado da base local.

**Monitoramento da semana.** Última semana epidemiológica do InfoDengue/Fiocruz: rótulo da semana, casos daquela semana e incidência por 100 mil. A data da fonte vem em milissegundos. A ordenação usa essa data em UTC, não o `date()` do SQLite, que lia a primeira linha em vez da última.

**Monitoramento do mês.** Soma os `casos_semana` das semanas cuja data de início cai naquele mês civil, com a média por semana. O cartão mostra o mês da última semana disponível. Um mês seguinte só entra quando alguma semana epidemiológica começa nele.

A faixa abaixo traz o acumulado no ano informado pela fonte, o nível de alerta municipal (1 verde, 2 amarelo, 3 laranja, 4 vermelho), a chuva do último mês e a temperatura média municipal.

Os gráficos locais, desenhados em canvas, cobrem casos acumulados, pontuação de risco (0 a 100) e incidência por 1.000 habitantes. O histórico municipal é a série semanal de casos notificados. As datas do eixo também estão em UTC, para o dia coincidir com o início da semana epidemiológica. O ranking lista os cinco bairros com maior pontuação e, quando existe, a previsão do próximo período e a probabilidade de aumento. O botão de atualização dispara a coleta das fontes automáticas.

## Mapa e página do bairro

**Mapa / Bairros** usa Leaflet sobre o perímetro de Franca. Dá para alternar o mapa urbano do OpenStreetMap, a imagem de satélite e um mapa de calor do risco. Cada marcador usa a latitude e a longitude salvas: centroide do IBGE, coordenada de referência do cadastro ou posição ajustada no mapa. Arrastar o marcador grava a nova posição como ajuste manual e essa posição não é substituída pela coleta. O clique abre casos acumulados, população, incidência por 1.000, previsão do próximo período e probabilidade de aumento.

A tabela lista população, casos, incidência, risco e previsão, com link para o bairro. A ordem padrão é a pontuação de risco. O endereço aceita `?ordem=risco`, `previsao`, `incidencia` ou `casos`.

A **página do bairro** mostra população, casos e focos acumulados, incidência por 1.000, tendência em relação ao período anterior (subindo, estável ou caindo), a última previsão e o histórico, com a origem de cada registro.

## IA preditiva

A tela estima os casos do próximo período de um bairro, ou de todos de uma vez.

O modelo é um Random Forest temporal. Cada exemplo tem como alvo os casos do período seguinte. As variáveis do período anterior são: casos, casos de dois períodos atrás, média móvel de até 3 períodos, chuva, temperatura média, umidade média municipal e focos, com um indicador de que o foco foi informado de fato. O corte de treino e teste é por período inteiro: cerca de 20% dos períodos mais recentes ficam só no teste, e o mesmo mês não aparece nos dois lados. O ajuste pede pelo menos 20 exemplos observados e usa `min_samples_leaf` maior que 1. A tela mostra MAE e RMSE de treino e de teste, e o R² de teste.

No mesmo teste, o erro do modelo é comparado com duas referências: repetir os casos do período anterior (persistência) e a média móvel de 3 períodos. A umidade vem da série municipal do Open-Meteo. Quando falta, entra a mediana do treino. Chuva e temperatura do registro local também cedem lugar à série municipal quando a origem é de demonstração ou está vazia.

Registro cuja origem, ou a origem dos casos, começa com “demonstr” fica fora do treino e da entrada da previsão. Entram séries manuais, importadas e automáticas do SINAN. Enquanto a base local for só demonstração, a floresta não treina e o MAE de teste permanece em branco.

Sem modelo ou sem série observada suficiente, a previsão de casos é a média dos últimos períodos daquele bairro, até 3. A probabilidade de aumento, nesse caso, mistura 60% da fração de subidas recentes com 40% da chuva recente (a chuva satura em 150 mm, porque a água favorece o mosquito). Não é probabilidade clínica. O mesmo percentual aparece na IA, no histórico de previsões, nos relatórios e no mapa.

A pontuação de risco é a fórmula didática de 0 a 100:

- casos: 35%, saturando em 40 casos;
- focos: 30%, saturando em 25 focos;
- chuva: 20%, saturando em 150 mm;
- temperatura: 15%, com o fator mais alto perto de 27 °C.

A faixa é Baixo até 39,9, Médio de 40 a 69,9 e Alto a partir de 70.

Focos só entram quando a origem é manual, importada ou automática. Sem essa evidência, o peso de 30% sai da conta. Se o período tem casos, o restante é redistribuído. Se os casos também são zero, chuva e temperatura ficam com o próprio peso e não herdam a fatia dos focos. Clima municipal, sozinho, não classifica o bairro como Médio ou Alto.

Com a floresta treinada, a pontuação junta 60% do risco atual e 40% da previsão de casos. O intervalo é o quantil 10–90 das árvores. A chance de aumento passa a ser a fração das árvores que preveem mais casos do que o último período. É uma avaliação acadêmica, não uma validação epidemiológica.

O simulador da mesma página recalcula a fórmula no navegador e não grava no banco.

## Cadastro e importação CSV

A página Dados faz o cadastro, a edição e a exclusão de bairros (nome e população) e de registros históricos (período, casos, chuva, temperatura e focos). Chuva e temperatura podem ser preenchidas pela série municipal daquele mês. Cada linha guarda a origem: demonstração, manual, importado ou SINAN/Dengue. O banco é o SQLite `banco.db`.

A importação CSV exige o cabeçalho `bairro,periodo,casos,chuva_mm,temperatura_media,focos`. O bairro já precisa existir. O arquivo aceita até 2 MB e 5.000 linhas. Uma linha válida inclui ou atualiza o par bairro/período e marca a origem como importado. As últimas importações aparecem na própria página.

```csv
bairro,periodo,casos,chuva_mm,temperatura_media,focos
Centro,2026-09,12,85,24.8,7
Cidade Nova,2026-09,25,112,26.2,14
```

## Relatórios

A página reúne o resumo por bairro, o histórico local, as previsões (com a probabilidade de aumento), a série municipal do InfoDengue e as últimas atualizações de fonte. A exportação CSV em UTF-8 oferece:

- resumo dos bairros;
- dados epidemiológicos externos;
- histórico local;
- previsões;
- cadastro de bairros.

A rota `/relatorios/exportar/ambiental` exporta também a série climática municipal (chuva, temperaturas, umidade, vento e horas de sol).

## Fontes automáticas

A coleta roda em segundo plano quando o cache vence e também pelo botão de atualizar. Se a consulta falhar, o último dado salvo permanece. O sistema não reparte o total municipal entre os bairros.

- **InfoDengue / Fiocruz** (geocódigo 3516200): semanas epidemiológicas de dengue do ano corrente e dos dois anteriores. Grava casos, casos estimados, acumulado, incidência por 100 mil, nível de alerta, Rt e probabilidade de Rt maior que 1. Cache de 6 horas. A série fica numa tabela municipal. Semanas recentes podem ser revisadas pela fonte. Consulta: [https://info.dengue.mat.br/](https://info.dengue.mat.br/).
- **Open-Meteo**: reanálise no ponto de Franca, com chuva, temperaturas média, mínima e máxima, horas de precipitação, vento máximo, horas de sol e umidade relativa média do mês. A previsão diária do assistente usa a API de previsão nas coordenadas do bairro. Cache de 6 horas. Documentação: [Open-Meteo Historical Weather API](https://open-meteo.com/en/docs/historical-weather-api).
- **SINAN/Dengue**: microdados públicos de 2024, 2025 e 2026. Um ano ainda futuro é ignorado. O filtro é o município de residência de Franca e a classificação final de dengue confirmada. Os casos são somados por bairro e mês (`AAAA-MM`). O nome do arquivo só é gravado se casar com um bairro cadastrado: igualdade depois de tirar acentos e expandir abreviações (Jd, Vl, Pq, Res, Conj, Prol, Cond), ou semelhança de pelo menos 0,93 entre nomes de tamanho parecido. Nome sem casamento seguro fica numa lista à parte e não recebe casos. Se o arquivo do ano não tiver coluna de bairro, a coleta não inventa distribuição: os cadastros manuais e importados permanecem, e a base de demonstração também. O primeiro download pode demorar. Cache de 24 horas.
- **IBGE Censo 2022**: população e centroide da camada de bairros de Franca, com o mesmo casamento de nome. Coordenada fora do retângulo do município é descartada. Um ajuste manual feito no mapa não é substituído. Cache de 7 dias. Estimativas municipais do IBGE não são rateadas para fabricar população de bairro.

Focos do mosquito não são calculados a partir das notificações. Sem uma fonte estruturada, continuam manuais ou vindos do CSV.

## Integridade

Registro manual ou importado não é sobrescrito pelo SINAN, nem na contagem de casos nem na origem. Quando o SINAN grava por cima de uma linha de demonstração, o foco sintético é zerado e a chuva e a temperatura passam a copiar a série municipal.

População com origem `nao_informada` ou `Consolidado Franca/SP` não entra na incidência. População maior que zero com origem manual, do IBGE, estimativa informada ou ajuste de mapa entra. Na inicialização, o placeholder `Consolidado Franca/SP` é limpo: a população fica nula e a origem passa a `nao_informada`.

As consultas usam SQL parametrizado. Os formulários que alteram dados enviam token CSRF. Upload acima de 2 MB é recusado. Erros HTTP 400, 404, 413 e 500 têm página própria.

## Assistente

O assistente responde em português com os dados do próprio sistema. Sem a variável `OPENAI_API_KEY`, a resposta é local. Com a chave, um modelo de linguagem pode redigir a partir do mesmo contexto, e a resposta local continua como reserva. Há limite de 20 perguntas a cada 10 minutos por endereço. **Isto não é um diagnóstico.**

Ele responde sobre:

- previsão de chuva do bairro (Open-Meteo, próximos dias);
- risco do bairro selecionado ou citado na pergunta;
- ranking dos bairros com maior pontuação;
- prevenção do mosquito, pela eliminação de água parada;
- lista dos sintomas mais citados e dos sinais de alerta;
- comparação do que a pessoa descreve com esses sinais, pedindo atendimento quando há alerta;
- transmissão pela picada do *Aedes aegypti*, e não pelo ar;
- o mosquito, os hábitos e o que mais pode transmitir;
- incubação em termos gerais, com frequência entre 4 e 10 dias;
- quando procurar atendimento.

Os atalhos da tela, na ordem em que aparecem, são estes:

- Probabilidade de chuva
- Bairro com maior tendência
- Risco do bairro
- Cuidados para a casa
- Sintomas da dengue

Pergunta de risco ou de chuva continua no painel de dados do sistema. A comparação de sintomas deixa explícito que não é diagnóstico.

## Metodologia

A página explica a separação entre a série municipal e os registros por bairro, os pesos da fórmula de risco e o corte temporal da previsão. A fórmula não é protocolo oficial de vigilância.

Links de consulta usados na tela:

- [InfoDengue / Fiocruz](https://info.dengue.mat.br/)
- [Organização Mundial da Saúde — Dengue](https://www.who.int/en/news-room/fact-sheets/detail/dengue-and-severe-dengue)
- [Li et al. (2020) — temperatura e precipitação](https://pubmed.ncbi.nlm.nih.gov/32810500/)
- [Revisão sobre dengue e clima](https://pubmed.ncbi.nlm.nih.gov/36561711/)
- [Revisão sobre temperatura e transmissão por Aedes](https://pubmed.ncbi.nlm.nih.gov/37719233/)

## Estrutura

```text
projeto_dengue/
├── app.py                  # rotas, banco, coleta e telas
├── modelo.py               # fórmula de risco e Random Forest temporal
├── integridade.py          # nome de bairro, origem e população
├── assistente_temas.py     # temas do assistente
├── bairros_oficiais.py     # cadastro de referência dos bairros
├── banco.db                # SQLite local
├── requirements.txt
├── INICIAR.bat
├── LEIA-ME.txt
├── templates/              # dashboard, mapa, dados, previsão, relatórios, assistente
├── static/                 # estilo e gráficos em canvas
└── tests/
```

## Limitações

- O mapa usa marcadores e o perímetro do município. Não desenha o polígono oficial de cada bairro.
- Casos, focos e parte da população da base local podem ser de demonstração ou estimativa. Isso fica na coluna de origem.
- O InfoDengue é municipal. Ele não vira caso de bairro por rateio.
- Sem coluna de bairro no SINAN, não há série observada por bairro e a Random Forest não é treinada.
- A probabilidade de aumento e a pontuação de risco são indicadores do projeto, não probabilidade clínica nem alerta oficial.
- O modelo precisaria de séries reais, mais longas e de validação externa antes de qualquer uso operacional.

## Testes

Os testes usam `unittest` e não pedem dependência além das do `requirements.txt` (Flask, pandas e scikit-learn).

- `tests/test_regras.py` cobre a origem que pode entrar no treino, a população que entra na incidência, o casamento de nome, a proteção do cadastro manual contra o SINAN, a limpeza de foco e clima sintéticos, a série de demonstração fora do dataset, o corte temporal sem repetir período, as métricas de persistência e de média móvel, a classificação de risco, o clima sem casos nem focos observados (permanece Baixo), a probabilidade que mistura subida recente e chuva, o limite de perguntas e a checagem de origem HTTP.
- `tests/test_assistente_temas.py` cobre a leitura de sintomas, a comparação que avisa que não é diagnóstico, o pedido de atendimento diante de sinal de alerta, a lista de sintomas, a transmissão, o mosquito, e o fato de perguntas de risco e de chuva ficarem com o painel de dados.

```bash
python -m unittest discover -s tests
```
