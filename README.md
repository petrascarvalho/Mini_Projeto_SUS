# Mini-Projeto Avaliativo - Banco de Preços em Saúde (BPS)

Projeto desenvolvido para o módulo de Visualização de Dados e Business Intelligence.

## Objetivo do projeto

Desenvolver um dashboard analítico para acompanhar as compras de medicamentos e dispositivos médicos registradas no Banco de Preços em Saúde — BPS entre 2020 e 2026, utilizando indicadores, métricas, gráficos e filtros interativos para apoiar a análise dos gastos, da distribuição das compras, dos produtos, fornecedores, instituições e das variações de preços registradas.

## Período analisado

2020 a 2026

## Tecnologias

- Python 3.14.4
- Pandas 3.0.2
- Looker Studio
- Git e GitHub

## Estrutura do projeto

- dados/brutos
- dados/processados
- documentacao/analises
- documentacao/painel
- scripts

## Histórico inicial

Estrutura inicial do projeto.

O registro acima descreve a criação do repositório. A situação atual está na seção [Status do projeto](#status-do-projeto).

## Contextualização

O projeto utiliza registros do Banco de Preços em Saúde — BPS, do Ministério da Saúde, para estudar compras de medicamentos e dispositivos médicos e preparar análises de visualização de dados e Business Intelligence. O interesse está na evolução dos valores registrados, na distribuição das aquisições e na comparação de preços de produtos comparáveis.

A Sprint 1 foi dedicada ao entendimento do problema, à obtenção e preservação das bases e à inspeção diagnóstica de sua estrutura e significado, sem qualquer transformação dos arquivos originais. A inspeção utilizou Python global 3.14.4 e Pandas 3.0.2, sem criar ou utilizar `.venv`.

## Fonte oficial e cobertura temporal

A fonte oficial é o [Banco de Preços em Saúde — BPS, no Portal de Dados Abertos do SUS](https://dadosabertos.saude.gov.br/dataset/bps), mantido pelo Ministério da Saúde. O período analisado é de **2020 a 2026**.

**A base de 2026 é parcial.** A cobertura observada no arquivo local `dados/brutos/2026/2026.csv` é:

| Campo | Significado | Data mínima | Data máxima | Valores válidos |
| --- | --- | --- | --- | ---: |
| `compra` | Data da compra informada pela instituição | 06/01/2026 | 05/03/2026 | 819 |
| `insercao` | Data de registro das informações no BPS | 21/01/2026 | 13/03/2026 | 819 |

Nenhum desses campos sustenta a afirmação de registros até agosto de 2026. A atualização ou disponibilização do arquivo no portal não deve ser confundida com a cobertura das datas internas. A parcialidade é uma característica do período, não um erro do arquivo, e deverá ser considerada nas comparações entre anos.

## Obtenção e preservação das bases

Foram obtidos exclusivamente os sete arquivos anuais oficiais em formato CSV compactado, de 2020 a 2026, seguindo o endereço oficial:

```text
https://s3.sa-east-1.amazonaws.com/ckan.saude.gov.br/BPS/csv/ANO_csv.zip
```

O procedimento realizado na Sprint 1 foi:

1. Baixar `2020_csv.zip`, `2021_csv.zip`, `2022_csv.zip`, `2023_csv.zip`, `2024_csv.zip`, `2025_csv.zip` e `2026_csv.zip` para `dados/brutos`, preservando os nomes originais.
2. Conferir os downloads, calcular os hashes SHA-256, testar a integridade interna dos ZIPs e inventariar seu conteúdo e tamanhos.
3. Após a validação dos sete ZIPs, extrair cada arquivo para `dados/brutos/ANO/`, mantendo os ZIPs originais. Cada pasta contém o CSV de mesmo ano, como `dados/brutos/2020/2020.csv`.
4. Preservar os nomes e o conteúdo dos CSVs, sem tratamento ou concatenação. Os hashes dos arquivos brutos foram conferidos durante as inspeções.

Os ZIPs e CSVs originais **não são versionados no Git**. As regras do `.gitignore` excluem `dados/brutos/*.zip` e `dados/brutos/**/*.csv`; os arquivos `.gitkeep` continuam versionados para preservar a estrutura de pastas. O inventário e os documentos de diagnóstico ficam em `documentacao/analises`.

## Inspeção estrutural e semântica

A inspeção realizada pelo script [01_inspecao_bases.py](scripts/01_inspecao_bases.py) identificou:

- 25 colunas em todos os sete anos, com nomes e ordem iguais;
- 25 colunas comuns, sem colunas exclusivas de algum ano;
- nenhuma coluna completamente vazia;
- arquivos compatíveis com UTF-8 e separador `;`;
- quantidades de nulos e tipos inferidos registrados apenas para diagnóstico, sem remover valores ou converter as bases.

Em 2020, `esfera` contém **43 ocorrências de `"0"`** junto de categorias textuais. Esse valor não tem significado explicado nas fontes oficiais consultadas e foi preservado. Sua investigação e eventual tratamento ficam para a Sprint 2, sem atribuição automática de uma categoria.

A análise documental relacionou as colunas aos dicionários oficiais e distinguiu as datas de compra, inserção e disponibilização. Também registrou lacunas e divergências documentais em `unidade_medida`, `unidade_fornecimento_capacidade` e `tipo_compra`, que deverão ser confirmadas antes de decisões de tratamento.

## Documentação produzida na Sprint 1

| Arquivo | Conteúdo |
| --- | --- |
| [inventario_arquivos_bps.csv](documentacao/analises/inventario_arquivos_bps.csv) | ZIPs, tamanhos, hashes SHA-256, integridade e caminhos de extração. |
| [resumo_bases.csv](documentacao/analises/resumo_bases.csv) | Dimensões, encoding, separador e diagnóstico inicial por ano. |
| [matriz_colunas_por_ano.csv](documentacao/analises/matriz_colunas_por_ano.csv) | Presença das colunas nos sete anos. |
| [discrepancias_estruturais.csv](documentacao/analises/discrepancias_estruturais.csv) | Diferenças de tipos inferidos e observações da inspeção inicial. |
| [tipos_colunas_por_ano.csv](documentacao/analises/tipos_colunas_por_ano.csv) | Tipos inferidos, nulos e diagnóstico de datas por coluna e ano. |
| [dicionario_colunas_bps.csv](documentacao/analises/dicionario_colunas_bps.csv) | Significados, fontes oficiais, tipos semânticos, usos potenciais e ressalvas. |
| [validacao_datas_2026.csv](documentacao/analises/validacao_datas_2026.csv) | Validação temporal de 2026, com distinção entre datas internas e atualização do portal. |
| [perguntas_negocio.md](documentacao/analises/perguntas_negocio.md) | Oito perguntas orientadoras e ressalvas de interpretação. |

Para a análise temporal de 2026, devem ser utilizados os limites observados nos próprios dados. A referência a agosto corresponde à atualização do portal e não à cobertura temporal dos registros do CSV.

## Perguntas de negócio

As [oito perguntas de negócio](documentacao/analises/perguntas_negocio.md) orientam a investigação da evolução dos valores registrados, da concentração geográfica e institucional, dos produtos, fornecedores, fabricantes, modalidades e diferenças de preços.

Diferenças de preços **não devem ser interpretadas automaticamente como economia, sobrepreço ou irregularidade**. Será necessário avaliar a comparabilidade dos produtos, apresentações, períodos e condições das aquisições.

## Sprint 2 — Preparação e concatenação das bases

A Sprint 2 foi executada com Python global 3.14.4 e Pandas 3.0.2, sem criar ou utilizar `.venv`. O trabalho foi dividido em diagnóstico, tratamento anual e consolidação. Os arquivos brutos foram preservados, com conferência de hashes SHA-256; os tratamentos foram aplicados somente às cópias destinadas a `dados/processados`.

### Diagnóstico antes do tratamento

O script [02_diagnostico_qualidade.py](scripts/02_diagnostico_qualidade.py) investigou nulos, strings vazias, espaços nos textos, duplicados, categorias, formatos numéricos, datas e a consistência entre quantidade e preços. As evidências foram registradas nos relatórios `diagnostico_*.csv` e em [resumo_qualidade_sprint2.csv](documentacao/analises/resumo_qualidade_sprint2.csv), em `documentacao/analises`.

Esse diagnóstico orientou as regras de tratamento. Os nulos foram investigados e não preenchidos indiscriminadamente: ausência de informação não equivale a zero nem autoriza inferir um valor.

### Tratamento anual e rastreabilidade

O script [03_tratamento_bases.py](scripts/03_tratamento_bases.py) preparou cada ano separadamente, mantendo os 25 nomes originais das colunas:

- `compra` e `insercao` foram convertidas para datas, preservando as ausências de `insercao` como nulos.
- `ano_compra` e `qtd_itens_comprados` foram convertidos para inteiros; `capacidade`, `preco_unitario` e `preco_total`, para tipos decimais. Quando ausente, `capacidade` permaneceu nula, sem preenchimento com zero.
- Os identificadores CNPJ da instituição, do fornecedor e do fabricante, `codigo_br` e `anvisa` foram mantidos como texto, preservando zeros à esquerda.
- Foram removidos **19 duplicados exatos excedentes**, identificados nas 25 colunas originais antes das conversões, preservando a primeira ocorrência. As cópias removidas, seus valores originais, o ano do arquivo e a posição de origem foram mantidos em [registros_duplicados_removidos.csv](documentacao/analises/registros_duplicados_removidos.csv) para auditoria.
- Os **43 registros de 2020 com `esfera = "0"`** foram classificados como `NAO_INFORMADO`, sem atribuir uma esfera administrativa não comprovada. O valor anterior foi preservado em `esfera_original`, coluna presente em todos os anos.
- `DOSE` e `DOSES` não foram unificados por falta de evidência documental suficiente. Os demais valores categóricos e nomes de instituições, fornecedores, fabricantes e produtos foram preservados.
- Foi criada `ano_arquivo` para identificar o ano do arquivo de origem, e `ano_parcial`, verdadeira somente para 2026. Com `esfera_original`, essas adições elevaram a estrutura para **28 colunas**.

As **12 inconsistências temporais da origem em que `insercao < compra` foram preservadas e sinalizadas**: 1 em 2023 e 11 em 2024. Não houve correção dessas datas sem uma regra fundamentada; essas ocorrências não representam falhas de conversão.

O campo `preco_total` foi validado contra `qtd_itens_comprados × preco_unitario`, usando decimais exatos e tolerância de **R$ 0,01**, com **zero divergências**. Também não foram encontradas inconsistências entre `ano_compra` e `ano_arquivo` após o tratamento.

Os sete arquivos tratados anuais foram armazenados como `dados/processados/por_ano/ANO_tratado.parquet`. O formato Parquet preserva os tipos de dados e os nulos para as análises locais. As contagens antes e depois e as validações constam em [resumo_tratamento_sprint2.csv](documentacao/analises/resumo_tratamento_sprint2.csv).

### Consolidação e distribuição final

O script [04_consolidacao_bps.py](scripts/04_consolidacao_bps.py) conferiu os nomes, a ordem e os tipos das 28 colunas dos sete Parquets e concatenou os registros verticalmente com Pandas. Nenhum novo tratamento foi realizado nessa etapa: nulos, categorias, `ano_arquivo`, `ano_parcial` e `esfera_original` foram preservados.

A consolidação resultou em **342.697 registros e 28 colunas**, distribuídos da seguinte forma:

| Ano | Registros finais |
| --- | ---: |
| 2020 | 84.819 |
| 2021 | 83.622 |
| 2022 | 88.991 |
| 2023 | 31.992 |
| 2024 | 26.242 |
| 2025 | 26.214 |
| 2026 | 817 |
| **Total** | **342.697** |

A conferência após a concatenação encontrou **zero duplicados exatos nas 28 colunas**, zero inconsistências de ano e zero divergências na relação de preços com a mesma tolerância de R$ 0,01. Foram confirmados os 43 registros com `esfera = "NAO_INFORMADO"` e `esfera_original = "0"`, além de `ano_parcial = True` somente nos 817 registros de 2026. O detalhamento está em [resumo_consolidacao_sprint2.csv](documentacao/analises/resumo_consolidacao_sprint2.csv).

Foram geradas duas versões da base consolidada:

- `dados/processados/BPS_20_26_Petras_Ruben_Carvalho.csv`: CSV final com separador `;`, encoding UTF-8 e sem índice do Pandas.
- `dados/processados/BPS_20_26_Petras_Ruben_Carvalho.parquet`: versão mantida para preservar os tipos de dados durante as análises locais. O CSV é uma representação textual e não armazena o esquema de tipos do Parquet.

As contagens de 819 registros de 2026 apresentadas na documentação da Sprint 1 referem-se ao arquivo bruto. Os 817 registros finais correspondem à base após a remoção de duas cópias excedentes. A cobertura parcial de 2026 continua sendo uma característica do período e deve ser considerada nas comparações.

## Status do projeto

**Sprint 1 — Entendimento do problema e dos dados: concluída.**

Foram concluídas a obtenção e preservação dos sete arquivos anuais, a validação técnica dos ZIPs, a inspeção estrutural, a análise semântica e temporal e a documentação das perguntas de negócio.

**Sprint 2 — Preparação e concatenação das bases: concluída.**

Foram concluídos o diagnóstico de qualidade, o tratamento auditável dos sete anos e a consolidação em CSV e Parquet, preservando os arquivos brutos. A documentação da Sprint 1 permanece como registro da situação anterior ao tratamento.

Não foram definidos KPIs finais. Os KPIs da Sprint 3, o dashboard, as descobertas, recomendações, limitações e instruções de reprodução serão desenvolvidos e documentados nas respectivas Sprints, sem antecipar essas entregas.
