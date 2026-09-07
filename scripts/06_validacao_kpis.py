"""Calcular e validar os seis KPIs da Sprint 3, sem alterar a base."""

import csv
import hashlib
import sys
from decimal import Decimal, localcontext
from pathlib import Path

import pandas as pd


# 1. Conferir o ambiente para reproduzir os cálculos nas versões do projeto.
# A verificação também impede executar este script em um ambiente virtual.
if sys.version_info[:3] != (3, 14, 4) or pd.__version__ != "3.0.2":
    raise ValueError("Use Python global 3.14.4 e Pandas 3.0.2.")
if sys.prefix != sys.base_prefix:
    raise ValueError("Não utilize ambiente virtual.")

# 2. Definir caminhos relativos e guardar hashes antes da análise.
# Comparar os hashes ao final comprova a preservação da base e do README.
raiz = Path(__file__).resolve().parents[1]
caminho_base = raiz / "dados/processados/BPS_20_26_Petras_Ruben_Carvalho.parquet"
pasta_analises = raiz / "documentacao/analises"
hashes_antes = {}
for caminho in (caminho_base, raiz / "README.md"):
    with caminho.open("rb") as arquivo:
        hashes_antes[caminho] = hashlib.file_digest(arquivo, "sha256").hexdigest()

# 3. Ler somente os campos necessários, preservando tipos, textos e nulos.
# Conferir os anos e campos numéricos evita somar uma base incompleta ou
# ignorar silenciosamente ausências em valores usados nos indicadores.
campos = [
    "ano_arquivo", "ano_parcial", "preco_total", "qtd_itens_comprados",
    "cnpj_instituicao", "cnpj_fornecedor",
]
base = pd.read_parquet(
    caminho_base, columns=campos, engine="pyarrow", dtype_backend="pyarrow"
)
if len(base) != 342697:
    raise ValueError("Esperados 342.697 registros na base consolidada.")
if base["ano_arquivo"].isna().any():
    raise ValueError("Ano de origem ausente.")
if set(base["ano_arquivo"]) != set(range(2020, 2027)):
    raise ValueError("Esperados somente os anos de 2020 a 2026.")
if base[["preco_total", "qtd_itens_comprados"]].isna().any().any():
    raise ValueError("Ausência em campo numérico necessário aos KPIs.")
if base["ano_parcial"].isna().any():
    raise ValueError("Marcação de período parcial ausente.")
if not base["ano_parcial"].eq(base["ano_arquivo"].eq(2026)).all():
    raise ValueError("Somente 2026 deve estar marcado como parcial.")

# 4. Calcular primeiro o total e depois cada ano, sem modificar a base.
# Usar soma para valores e quantidades, linhas para registros e CNPJ distinto
# para entidades evita confundir nomes diferentes com organizações diferentes.
# nunique(dropna=True) exclui nulos, sem preencher ou padronizar identificadores.
resultados = []
periodos = ["TOTAL", 2020, 2021, 2022, 2023, 2024, 2025, 2026]
with localcontext() as contexto:
    # Decimal mantém os valores monetários exatos. A divisão pode produzir
    # dízima; usar 50 algarismos significativos evita arredondamento prematuro.
    contexto.prec = 50
    for periodo in periodos:
        if periodo == "TOTAL":
            recorte = base
            observacao = "2020 a 2026; inclui 2026 parcial"
        else:
            recorte = base.loc[base["ano_arquivo"].eq(periodo)]
            observacao = "Período parcial" if periodo == 2026 else "Base anual"

        valor_total = recorte["preco_total"].sum()
        quantidade_total = int(recorte["qtd_itens_comprados"].sum())
        registros = len(recorte)
        instituicoes = int(recorte["cnpj_instituicao"].nunique(dropna=True))
        fornecedores = int(recorte["cnpj_fornecedor"].nunique(dropna=True))

        # 5. Validar os totais antes da divisão, pois denominador zero impede
        # calcular o indicador. Não substituir um resultado indefinido por zero.
        if quantidade_total <= 0:
            raise ValueError(f"Quantidade total não positiva em {periodo}.")
        if not valor_total.is_finite() or valor_total <= 0:
            raise ValueError(f"Valor total inválido ou não positivo em {periodo}.")
        preco_ponderado = valor_total / Decimal(quantidade_total)

        # Conferir as somas e contagens com operações independentes ajuda a
        # detectar perda de precisão ou inclusão de nulos nas contagens distintas.
        if valor_total != sum(recorte["preco_total"], Decimal("0")):
            raise ValueError(f"Soma monetária inconsistente em {periodo}.")
        if quantidade_total != sum(int(valor) for valor in recorte["qtd_itens_comprados"]):
            raise ValueError(f"Soma de quantidades inconsistente em {periodo}.")
        if instituicoes != len(set(recorte["cnpj_instituicao"].dropna())):
            raise ValueError(f"Contagem de instituições inconsistente em {periodo}.")
        if fornecedores != len(set(recorte["cnpj_fornecedor"].dropna())):
            raise ValueError(f"Contagem de fornecedores inconsistente em {periodo}.")

        resultados.append({
            "periodo": str(periodo),
            "observacao_periodo": observacao,
            "valor_total_registrado": valor_total,
            "quantidade_total_itens_comprados": quantidade_total,
            "numero_registros_compra": registros,
            "instituicoes_compradoras": instituicoes,
            "fornecedores": fornecedores,
            "preco_unitario_medio_ponderado": preco_ponderado,
        })
        print(f"[{periodo}] {registros:,} registros; KPIs validados.", flush=True)

    # 6. Reconciliar os indicadores aditivos anuais com o total geral.
    # CNPJs distintos não são somados: uma entidade pode aparecer em vários anos.
    for campo in (
        "valor_total_registrado", "quantidade_total_itens_comprados",
        "numero_registros_compra",
    ):
        soma_anual = sum(resultado[campo] for resultado in resultados[1:])
        if soma_anual != resultados[0][campo]:
            raise ValueError(f"Total geral difere da soma anual em {campo}.")
    if sum(resultado["numero_registros_compra"] for resultado in resultados[1:]) != 342697:
        raise ValueError("A soma dos registros anuais deve ser 342.697.")

# 7. Gravar somente o relatório, mantendo decimais como texto exato no CSV.
# Reler sem inferência numérica permite conferir a gravação sem passar por float.
relatorio = pd.DataFrame(resultados)
pasta_analises.mkdir(parents=True, exist_ok=True)
caminho_resultados = pasta_analises / "resultados_kpis.csv"
relatorio.to_csv(caminho_resultados, sep=";", encoding="utf-8", index=False)
with caminho_resultados.open(encoding="utf-8", newline="") as arquivo:
    relidos = list(csv.DictReader(arquivo, delimiter=";"))
if len(relidos) != 8:
    raise ValueError("O relatório deve conter o total e sete anos.")
for esperado, relido in zip(resultados, relidos, strict=True):
    for campo, valor in esperado.items():
        if relido[campo] != str(valor):
            raise ValueError(f"Valor alterado na gravação: {campo}.")

# 8. Documentar fórmulas e limites de interpretação para que o dashboard
# utilize as agregações corretas, especialmente com filtros e produtos distintos.
definicoes = """# Definição dos KPIs — Sprint 3

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
"""
(pasta_analises / "definicao_kpis.md").write_text(definicoes, encoding="utf-8")

# 9. Conferir os arquivos protegidos e mostrar os resultados para revisão.
# Nenhuma operação acima grava na base consolidada ou no README.
for caminho, hash_antes in hashes_antes.items():
    with caminho.open("rb") as arquivo:
        hash_depois = hashlib.file_digest(arquivo, "sha256").hexdigest()
    if hash_depois != hash_antes:
        raise ValueError(f"Arquivo protegido alterado: {caminho}")
print(relatorio.to_string(index=False))
print("Base e README com hashes inalterados. Sem tratamento ou commit.")
