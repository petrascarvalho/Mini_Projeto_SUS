# Definição dos KPIs — Sprint 3

Fonte: `dados/processados/BPS_20_26_Petras_Ruben_Carvalho.parquet`.
Script: `scripts/06_validacao_kpis.py`. Ambiente: Python global 3.14.4 e Pandas 3.0.2, sem `.venv`.
Resultados: `documentacao/analises/resultados_kpis.csv`, com uma linha total e sete linhas anuais agrupadas por `ano_arquivo`.

| KPI | Objetivo | Campo utilizado | Fórmula | Tipo de agregação | Por que foi escolhida | Cuidados de interpretação |
| --- | --- | --- | --- | --- | --- | --- |
| Valor total registrado | Dimensionar o valor financeiro registrado | `preco_total` | `SUM(preco_total)` | Soma | Cada registro contribui com seu valor total | São valores registrados no BPS; não equivalem necessariamente a pagamentos realizados ou à totalidade das compras públicas. Não há correção pela inflação. |
| Quantidade total de itens comprados | Dimensionar as quantidades registradas | `qtd_itens_comprados` | `SUM(qtd_itens_comprados)` | Soma | Acumula a quantidade informada em cada linha | Produtos e unidades de fornecimento diferentes são somados; não representa uma quantidade física homogênea, doses equivalentes ou pacientes atendidos. |
| Número de registros de compra | Medir o volume de linhas da base | Todas as linhas | Quantidade de linhas do recorte | Contagem | Cada linha é um registro da base tratada | Uma compra, contrato ou licitação pode conter várias linhas; não é contagem distinta desses eventos. |
| Instituições compradoras | Medir quantos CNPJs compradores aparecem | `cnpj_instituicao` | `COUNT_DISTINCT(cnpj_instituicao)`, excluindo nulos | Contagem distinta | O identificador evita contar variações de nome como entidades diferentes | CNPJs distintos podem pertencer à mesma organização; mede identificadores presentes. Não somar contagens anuais para obter o total. |
| Fornecedores | Medir quantos CNPJs fornecedores aparecem | `cnpj_fornecedor` | `COUNT_DISTINCT(cnpj_fornecedor)`, excluindo nulos | Contagem distinta | Usa o identificador, sem depender da escrita do nome | Não confundir CNPJ com grupo econômico. Não somar contagens anuais, pois um fornecedor pode aparecer em vários anos. |
| Preço unitário médio ponderado | Relacionar o valor registrado à quantidade registrada | `preco_total` e `qtd_itens_comprados` | `SUM(preco_total) / SUM(qtd_itens_comprados)` | Razão entre somas | Considera as quantidades e evita dar peso igual a linhas de tamanhos diferentes | No total de produtos e unidades heterogêneos, é uma razão agregada influenciada pela composição das compras, não um preço comparável de um produto. Recalcular a razão sob filtros; não tirar média simples dos resultados anuais. |

## Regras de cálculo e validação

- Usar soma para valores totais e quantidades; contagem de linhas para registros; contagem distinta por CNPJ para instituições e fornecedores.
- Usar razão entre somas para o preço unitário médio ponderado. Não usar média simples de `preco_unitario` como KPI geral.
- A soma de preços unitários não possui significado adequado neste contexto: não representa gasto total nem preço médio.
- A mediana poderá ser utilizada posteriormente para comparar preços de produtos equivalentes, considerando apresentação, unidade, período e condições da aquisição.
- Os totais monetários são calculados com decimais exatos. A razão é calculada com 50 algarismos significativos; seu arredondamento é necessário quando houver dízima. A exibição pode usar menos casas sem recalcular os valores a partir dos números exibidos.
- O script exige valores e quantidades totais positivos em cada recorte e verifica o denominador antes de dividir. Ausências nos campos numéricos interrompem o cálculo, sem preenchimento.
- Nulos são excluídos das contagens distintas. Textos vazios e espaços não são transformados em nulos: os identificadores são usados como armazenados, sem tratamento adicional.
- A soma dos registros anuais deve ser exatamente 342.697 e coincidir com o total geral. Valores e quantidades anuais também são reconciliados com o total.

## Período parcial e interpretação

2026 é um período parcial, marcado por `ano_parcial`. A cobertura observada na documentação do arquivo local é de 06/01/2026 a 05/03/2026 em `compra`, e de 21/01/2026 a 13/03/2026 em `insercao`. Não comparar seus totais diretamente com anos completos como se tivessem igual cobertura; o total geral também inclui esse período parcial.

A validação prévia das chaves identificou 29 CNPJs de instituições associados a mais de um nome, reforçando o uso de CNPJ nas contagens distintas. Nenhuma padronização de nomes foi realizada nesta etapa.

Diferenças de preços não devem ser interpretadas automaticamente como economia, sobrepreço ou irregularidade. Comparações exigem produtos e unidades equivalentes e contexto das aquisições. As 12 inconsistências temporais já sinalizadas na origem permanecem preservadas.

## Nota de interpretação sobre 2025

Um único registro de penicilamina 250 mg representa **65,32% do valor registrado em 2025**, e os **10 maiores registros representam 79,75%**. Os cálculos aritméticos foram validados: em todos os registros de 2025, `preco_total` corresponde a `qtd_itens_comprados × preco_unitario`, sem divergências.

Essa concentração não comprova erro ou irregularidade. Por isso, análises de preço devem preferir comparações entre produtos equivalentes, com a mesma apresentação e unidade de fornecimento. **O preço médio ponderado geral não deve ser interpretado como o preço típico de um medicamento.**
