"""Reproduzir a validação complementar de 2025, sem novos tratamentos.

Ambiente: Python global 3.14.4 e Pandas 3.0.2, sem .venv.
Saída: documentacao/analises/validacao_pico_2025.csv.
Uma nova execução substitui apenas esse relatório, mantendo as bases intactas.
"""

import csv
import hashlib
import io
import json
import sys
from decimal import Decimal, localcontext
from pathlib import Path
import pandas as pd

# Informar qual valor ordena os grupos permite explicar o ranking sem uma lambda.
def valor_total_do_grupo(grupo):
    return grupo["valor_total_grupo"]


# 1. Conferir o ambiente e definir caminhos para reproduzir a análise sem .venv.
raiz = Path(__file__).resolve().parents[1]
if sys.version_info[:3] != (3, 14, 4) or pd.__version__ != "3.0.2":
    raise ValueError("Use Python global 3.14.4 e Pandas 3.0.2.")
if sys.prefix != sys.base_prefix:
    raise ValueError("Não utilize ambiente virtual.")
caminho_base = raiz / "dados/processados/BPS_20_26_Petras_Ruben_Carvalho.parquet"
caminho_saida = raiz / "documentacao/analises/validacao_pico_2025.csv"

# 2. Guardar hashes para comprovar que a base e o README não foram alterados.
hashes = {}
for caminho in (caminho_base, raiz / "README.md"):
    with caminho.open("rb") as arquivo:
        hashes[caminho] = hashlib.file_digest(arquivo, "sha256").hexdigest()

# 3. Filtrar 2025 em memória, mantendo o índice para localizar a linha no Parquet.
# O número de registro abaixo começa em 1 e não é um identificador de compra.
base = pd.read_parquet(caminho_base, engine="pyarrow", dtype_backend="pyarrow")
base_2025 = base.loc[base["ano_arquivo"].eq(2025)]
if len(base_2025) != 26214:
    raise ValueError("Contagem de 2025 inesperada.")
for campo in ("preco_total", "preco_unitario", "qtd_itens_comprados"):
    if base_2025[campo].isna().any():
        raise ValueError(f"Ausências impedem validar {campo}.")

# 4. Usar Decimal para somar e multiplicar sem aproximações de ponto flutuante.
# Valores altos serão descritos por sua participação, sem julgamento de validade.
linhas = []
resumos_terminal = []
with localcontext() as contexto:
    contexto.prec = 60
    total = sum(base_2025["preco_total"], Decimal("0"))
    if total != Decimal("34930896708.4730"):
        raise ValueError("Total diferente do KPI anteriormente calculado.")
    divergencias = 0
    diferencas_nao_zero = 0
    maior_diferenca = Decimal("0")
    for quantidade, unitario, valor in zip(
        base_2025["qtd_itens_comprados"], base_2025["preco_unitario"], base_2025["preco_total"], strict=True
    ):
        diferenca = abs(valor - Decimal(quantidade) * unitario)
        maior_diferenca = max(maior_diferenca, diferenca)
        diferencas_nao_zero += int(diferenca != 0)
        divergencias += int(diferenca > Decimal("0.01"))

    # 5. Ordenar registros pelas três medidas para examinar valores e quantidades.
    # Cada lista tem dez linhas; as mesmas linhas podem aparecer em listas diferentes.
    for campo in ("preco_total", "preco_unitario", "qtd_itens_comprados"):
        maiores = base_2025.sort_values(campo, ascending=False, kind="stable").head(10)
        posicao = 0
        for indice, registro in maiores.iterrows():
            posicao += 1
            linha = registro.to_dict()
            linha.update({
                "ano": 2025,
                "secao": "maiores_registros_" + campo,
                "posicao": posicao,
                "registro_parquet_1_base": int(indice) + 1,
                "criterio_ordenacao": campo,
                "valor_criterio": registro[campo],
                "valor_total_grupo": registro["preco_total"],
                "registros_grupo": 1,
                "participacao_total_2025_pct": registro["preco_total"] / total * 100,
                "total_2025": total,
                "diferenca_preco_total": abs(
                    registro["preco_total"]
                    - Decimal(registro["qtd_itens_comprados"]) * registro["preco_unitario"]
                ),
                "observacao": "Ranking diagnóstico; nenhuma linha removida ou corrigida.",
            })
            linhas.append(linha)
        primeiro = maiores.iloc[0]
        resumos_terminal.append({
            "ranking": campo,
            "maior_valor": str(primeiro[campo]),
            "preco_total_da_linha": str(primeiro["preco_total"]),
            "participacao_pct": str(primeiro["preco_total"] / total * 100),
            "produto": primeiro["descricao_catmat"],
            "instituicao": primeiro["nome_instituicao"],
            "fornecedor": primeiro["fornecedor"],
            "quantidade": str(primeiro["qtd_itens_comprados"]),
            "preco_unitario": str(primeiro["preco_unitario"]),
        })

    # 6. Agrupar por identificadores, preservando todas as grafias observadas.
    # Produtos agrupados por código podem incluir apresentações distintas:
    # somar o valor é válido para concentração, mas não compara preços equivalentes.
    for secao, chave, nome in (
        ("produtos", "codigo_br", "descricao_catmat"),
        ("instituicoes", "cnpj_instituicao", "nome_instituicao"),
        ("fornecedores", "cnpj_fornecedor", "fornecedor"),
    ):
        grupos = []
        for identificador, grupo in base_2025.groupby(chave, dropna=False, sort=False):
            valor_grupo = sum(grupo["preco_total"], Decimal("0"))
            nomes = list(grupo[nome].dropna().unique())
            grupos.append({
                "ano": 2025,
                "secao": "maiores_" + secao,
                "chave_agrupamento": chave,
                "identificador_grupo": identificador,
                "nomes_observados_json": json.dumps(nomes, ensure_ascii=False),
                "unidades_observadas_json": json.dumps(
                    list(grupo["unidade_fornecimento"].dropna().unique()), ensure_ascii=False
                ),
                "criterio_ordenacao": "soma(preco_total)",
                "valor_criterio": valor_grupo,
                "valor_total_grupo": valor_grupo,
                "registros_grupo": len(grupo),
                "participacao_total_2025_pct": valor_grupo / total * 100,
                "total_2025": total,
                "observacao": "Agrupamento por identificador, sem padronizar nomes; nulos não excluídos.",
            })
        # Somar todos os grupos confere se nenhuma parcela ficou fora da análise.
        total_dos_grupos = 0
        for grupo in grupos:
            total_dos_grupos += grupo["valor_total_grupo"]
        if total_dos_grupos != total:
            raise ValueError(f"Grupos de {secao} não reconciliam com o total.")
        grupos.sort(key=valor_total_do_grupo, reverse=True)
        for posicao, grupo in enumerate(grupos[:10], start=1):
            grupo["posicao"] = posicao
            linhas.append(grupo)
        total_dez_maiores = 0
        for grupo in grupos[:10]:
            total_dez_maiores += grupo["valor_total_grupo"]
        resumos_terminal.append({
            "ranking": secao,
            "primeiros_tres": grupos[:3],
            "participacao_top10_pct": str(
                total_dez_maiores / total * 100
            ),
        })

    # 7. Medir a concentração sem excluir os extremos da base.
    # O restante é apenas uma subtração diagnóstica, não uma nova base ou KPI tratado.
    maiores_totais = base_2025.sort_values("preco_total", ascending=False, kind="stable")
    maior = maiores_totais.iloc[0]["preco_total"]
    total_top10 = sum(maiores_totais.head(10)["preco_total"], Decimal("0"))
    medidas = {
        "registros_2025": len(base_2025),
        "total_2025": total,
        "valor_maior_registro": maior,
        "participacao_maior_registro_pct": maior / total * 100,
        "valor_top10_registros": total_top10,
        "participacao_top10_registros_pct": total_top10 / total * 100,
        "valor_restante_sem_maior_apenas_diagnostico": total - maior,
        "registros_reconciliados": len(base_2025),
        "divergencias_acima_tolerancia": divergencias,
        "diferencas_nao_zero": diferencas_nao_zero,
        "maior_diferenca_absoluta": maior_diferenca,
        "tolerancia_reais": Decimal("0.01"),
    }
    for medida, valor in medidas.items():
        linhas.append({
            "ano": 2025,
            "secao": "resumo_validacao",
            "medida": medida,
            "valor_medida": valor,
            "total_2025": total,
            "observacao": "Concentração não comprova erro, sobrepreço ou irregularidade.",
        })

# 8. Gravar somente o CSV solicitado e conferir a serialização sem inferir tipos.
# Seções de rankings se sobrepõem e não devem ser somadas entre si.
relatorio = pd.DataFrame(linhas)
caminho_saida.parent.mkdir(parents=True, exist_ok=True)
relatorio.to_csv(caminho_saida, sep=";", encoding="utf-8", index=False)
relido = pd.read_csv(caminho_saida, sep=";", encoding="utf-8", dtype=str, keep_default_na=False)
esperado = relatorio.to_csv(sep=";", index=False)
linhas_esperadas = list(csv.reader(io.StringIO(esperado), delimiter=";"))
with caminho_saida.open(encoding="utf-8", newline="") as arquivo:
    if list(csv.reader(arquivo, delimiter=";")) != linhas_esperadas:
        raise ValueError("Relatório gravado difere do esperado.")

# 9. Confirmar preservação dos arquivos e imprimir evidências, sem fazer commit.
for caminho, antes in hashes.items():
    with caminho.open("rb") as arquivo:
        depois = hashlib.file_digest(arquivo, "sha256").hexdigest()
    if depois != antes:
        raise ValueError(f"Arquivo protegido alterado: {caminho}")
print("RESUMO 2025")
print(json.dumps(medidas, ensure_ascii=False, default=str, indent=2))
for resumo in resumos_terminal:
    print(json.dumps(resumo, ensure_ascii=False, default=str, indent=2))
print("Base e README com hashes inalterados. Somente validacao_pico_2025.csv gerado.")

