# Prevenção Dengue — Franca/SP

Projeto acadêmico de ciência de dados e Machine Learning para apoio à prevenção de dengue em Franca/SP. Autoria: Arthur Henrique.

O sistema reúne dados por bairro, indicadores municipais, clima, análise de risco e previsão de curto prazo. **Não substitui vigilância epidemiológica nem decisão oficial de saúde pública.**

## Como executar

```bash
python -m pip install -r requirements.txt
python app.py
```

No Windows, também é possível usar `INICIAR.bat`. Depois abra [http://127.0.0.1:5000](http://127.0.0.1:5000).

Documentação completa: [LEIA-ME.txt](LEIA-ME.txt).

## Dashboard

A página inicial mostra quantos bairros estão cadastrados, quantos registros e casos existem na base local e quantos bairros estão em risco baixo, médio ou alto. O filtro por bairro muda só os gráficos; não grava nada no banco.

Os gráficos locais cobrem casos acumulados, pontuação de risco (0 a 100), incidência por 1.000 habitantes e a previsão de casos. O painel municipal, separado da base local, mostra a última semana do InfoDengue (casos acumulados, incidência por 100 mil e nível de alerta) e o clima do último mês (chuva e temperatura). Há também o ranking dos cinco bairros com maior pontuação. O botão de atualização dispara a coleta das fontes automáticas.

## Mapa e página do bairro

**Mapa / Bairros** usa Leaflet sobre o perímetro de Franca. Dá para alternar o mapa urbano do OpenStreetMap, a imagem de satélite e um mapa de calor do risco. Cada marcador usa a latitude e a longitude salvas (centroide do IBGE, coordenada de referência do cadastro ou posição ajustada no mapa). Arrastar o marcador grava a nova posição como ajuste manual. O clique abre casos, incidência por 1.000 e previsão.

A tabela ao lado lista população, casos, incidência, risco e previsão, com link para o bairro. A ordem padrão é a pontuação de risco. O endereço aceita `?ordem=risco`, `previsao`, `incidencia` ou `casos`.

A **página do bairro** mostra população, casos e focos acumulados, incidência por 1.000, tendência em relação ao período anterior (subindo, estável ou caindo), a última previsão e o histórico, com a origem de cada registro.

## IA preditiva

A tela estima os casos do próximo período de um bairro, ou de todos de uma vez.

O modelo é um Random Forest temporal. Cada exemplo tem como alvo os casos do período seguinte. As variáveis do período anterior são: casos, casos de dois períodos atrás, média móvel de até 3 períodos, chuva, temperatura média, umidade média municipal e focos, com um indicador de que o foco foi informado de fato. O corte de treino e teste é por período inteiro: cerca de 20% dos períodos mais recentes ficam só no teste, e o mesmo mês não aparece nos dois lados. O ajuste pede pelo menos 20 exemplos observados. A tela mostra MAE e RMSE de treino e de teste, e o R² de teste.

No mesmo teste, o erro do modelo é comparado com duas referências: repetir os casos do período anterior (persistência) e a média móvel de 3 períodos. A umidade vem da série municipal do Open-Meteo; quando falta, entra a mediana do treino. Chuva e temperatura do registro local também cedem lugar à série municipal quando a origem é de demonstração ou está vazia.

Registro cuja origem, ou a origem dos casos, começa com “demonstr” fica fora do treino e da entrada da previsão. Entram séries manuais, importadas e automáticas do SINAN.

Se não houver modelo ou série observada suficiente, a tela mostra só a fórmula didática de risco, de 0 a 100: casos 35%, focos 30%, chuva 20% e temperatura 15%. Sem focos observados, esses 30% saem da conta e o restante é redistribuído. A faixa é Baixo até 39,9, Médio de 40 a 69,9 e Alto a partir de 70. Com a floresta treinada, a pontuação junta 60% desse risco atual e 40% da previsão de casos. O intervalo é o quantil 10–90 das árvores. A chance de aumento é a fração das árvores que preveem mais casos do que o último período. É uma avaliação acadêmica, não uma validação epidemiológica.

O simulador da mesma página recalcula essa fórmula no navegador e não grava no banco.

## Cadastro e importação CSV

A página Dados faz o cadastro, a edição e a exclusão de bairros (nome e população) e de registros históricos (período, casos, chuva, temperatura e focos). Chuva e temperatura podem ser preenchidas pela série municipal daquele mês. Cada linha guarda a origem: demonstração, manual, importado ou SINAN/Dengue. O banco é o SQLite `banco.db`.

A importação CSV exige o cabeçalho `bairro,periodo,casos,chuva_mm,temperatura_media,focos`. O bairro já precisa existir. O arquivo aceita até 2 MB e 5.000 linhas. Uma linha válida inclui ou atualiza o par bairro/período e marca a origem como importado. As últimas importações aparecem na própria página.

## Relatórios

A página reúne o resumo por bairro, o histórico local, as previsões, a série municipal do InfoDengue e as últimas atualizações de fonte. A exportação CSV em UTF-8 oferece:

- resumo dos bairros;
- dados epidemiológicos externos;
- histórico local;
- previsões;
- cadastro de bairros.

A rota `/relatorios/exportar/ambiental` exporta também a série climática municipal (chuva, temperaturas, umidade, vento e horas de sol).

## Fontes automáticas

A coleta roda em segundo plano quando o cache vence e também pelo botão de atualizar. Se a consulta falhar, o último dado salvo permanece.

- **InfoDengue / Fiocruz** (geocódigo 3516200): semanas epidemiológicas de dengue do ano corrente e dos dois anteriores. Grava casos, casos estimados, acumulado, incidência por 100 mil, nível de alerta, Rt e probabilidade de Rt maior que 1. Cache de 6 horas. A série fica numa tabela municipal, separada dos bairros.
- **Open-Meteo**: reanálise no ponto de Franca, com chuva, temperaturas média, mínima e máxima, horas de precipitação, vento máximo, horas de sol e umidade relativa média do mês. A previsão diária do assistente usa a API de previsão nas coordenadas do bairro. Cache de 6 horas.
- **SINAN/Dengue**: microdados públicos de 2024, 2025 e 2026 (um ano ainda futuro é ignorado), filtrados pelo município de residência de Franca e pela classificação final de dengue confirmada. Os casos são somados por bairro e mês (`AAAA-MM`). O nome do arquivo só é gravado se casar com um bairro cadastrado: igualdade depois de tirar acentos e expandir abreviações (Jd, Vl, Pq, Res, Conj, Prol, Cond), ou semelhança de pelo menos 0,93 entre nomes de tamanho parecido. Nome sem casamento seguro fica numa lista à parte e não recebe casos. Cache de 24 horas.
- **IBGE Censo 2022**: população e centroide da camada de bairros de Franca, com o mesmo casamento de nome. Coordenada fora do retângulo do município é descartada. Um ajuste manual feito no mapa não é substituído. Cache de 7 dias.

Focos do mosquito não são calculados a partir das notificações. Sem uma fonte estruturada, continuam manuais ou vindos do CSV.

## Integridade

Registro manual ou importado não é sobrescrito pelo SINAN, nem na contagem de casos nem na origem. Quando o SINAN grava por cima de uma linha de demonstração, o foco sintético é zerado e a chuva e a temperatura passam a copiar a série municipal.

População com origem `nao_informada` ou `Consolidado Franca/SP` não entra na incidência. População maior que zero com origem manual, do IBGE ou de outra fonte informada entra. Na inicialização, o placeholder `Consolidado Franca/SP` é limpo: a população fica nula e a origem passa a `nao_informada`.

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

## Metodologia

A página explica a separação entre a série municipal e os registros por bairro, os pesos da fórmula de risco (casos 35%, focos 30%, chuva 20%, temperatura 15%) e o corte temporal da previsão. Também lista links de consulta: InfoDengue, a Organização Mundial da Saúde e revisões sobre clima, temperatura e *Aedes*. A fórmula não é protocolo oficial de vigilância.

## Testes

Os testes usam `unittest` e não pedem dependência além das do `requirements.txt`.

- `tests/test_regras.py` cobre a origem que pode entrar no treino, a população que entra na incidência, o casamento de nome, a proteção do cadastro manual contra o SINAN, a limpeza de foco e clima sintéticos, a série de demonstração fora do dataset, o corte temporal sem repetir período, as métricas de persistência e de média móvel, a classificação de risco, o limite de perguntas e a checagem de origem HTTP.
- `tests/test_assistente_temas.py` cobre a leitura de sintomas, a comparação que avisa que não é diagnóstico, o pedido de atendimento diante de sinal de alerta, a lista de sintomas, a transmissão, o mosquito, e o fato de perguntas de risco e de chuva ficarem com o painel de dados.

```bash
python -m unittest discover -s tests
```
