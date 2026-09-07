"""Consolidação da Sprint 2, sem novos tratamentos.

Executar com Python global 3.14.4 e Pandas 3.0.2, sem ambiente virtual.
Os sete Parquets anuais são somente lidos. As saídas consolidadas são
substituídas em uma nova execução, após as validações abaixo.
O CSV é um formato textual; o Parquet preserva os tipos para análise local.
"""

import csv
import hashlib
import sys
import tempfile
from decimal import Decimal, localcontext
from pathlib import Path

import pandas as pd


# Definir caminhos a partir do script, para executar em qualquer máquina
# sem fixar o usuário do Windows. As contagens vêm da etapa de tratamento.
RAIZ = Path(__file__).resolve().parents[1]
PROCESSADOS = RAIZ / "dados" / "processados"
POR_ANO = PROCESSADOS / "por_ano"
ANALISES = RAIZ / "documentacao" / "analises"
NOME_BASE = "BPS_20_26_Petras_Ruben_Carvalho"
REGISTROS_ESPERADOS = {
    2020: 84819,
    2021: 83622,
    2022: 88991,
    2023: 31992,
    2024: 26242,
    2025: 26214,
    2026: 817,
}
TOTAL_ESPERADO = 342697
TOLERANCIA = Decimal("0.01")


# Calcular uma assinatura do conteúdo sem escrever no arquivo.
# Comparar essa assinatura antes e depois comprova que a entrada foi preservada.
def calcular_hash(caminho):
    with caminho.open("rb") as arquivo:
        return hashlib.file_digest(arquivo, "sha256").hexdigest()


def main():
    # 1. Conferir o ambiente antes de processar os dados, pois versões diferentes
    # podem produzir comportamentos diferentes na leitura e na concatenação.
    if sys.version_info[:3] != (3, 14, 4) or pd.__version__ != "3.0.2":
        raise ValueError("Use Python global 3.14.4 e Pandas 3.0.2.")
    if sys.prefix != sys.base_prefix:
        raise ValueError("Não utilize ambiente virtual.")
    print(f"Python {sys.version.split()[0]} | Pandas {pd.__version__}", flush=True)

    # 2. Guardar hashes dos brutos, dos Parquets anuais e do README.
    # Esses arquivos não fazem parte das saídas e devem permanecer intactos.
    hashes_antes = {}
    for pasta in (RAIZ / "dados" / "brutos", POR_ANO):
        for caminho in pasta.rglob("*"):
            if caminho.is_file():
                hashes_antes[caminho] = calcular_hash(caminho)
    hashes_antes[RAIZ / "README.md"] = calcular_hash(RAIZ / "README.md")

    # 3. Ler e conferir cada ano antes de concatenar. O backend Arrow mantém
    # os decimais exatos, identificadores textuais, datas e nulos dos Parquets.
    # Comparar colunas e tipos evita alinhamentos ou conversões inesperadas.
    bases_anuais = []
    colunas_referencia = None
    tipos_referencia = None
    for ano, quantidade_esperada in REGISTROS_ESPERADOS.items():
        caminho = POR_ANO / f"{ano}_tratado.parquet"
        base_anual = pd.read_parquet(caminho, engine="pyarrow", dtype_backend="pyarrow")
        print(f"[{ano}] {caminho.name}: {len(base_anual):,} registros", flush=True)
        if len(base_anual) != quantidade_esperada:
            raise ValueError(f"Contagem inesperada em {ano}.")
        if len(base_anual.columns) != 28:
            raise ValueError(f"Esperadas 28 colunas em {ano}.")
        if colunas_referencia is None:
            colunas_referencia = list(base_anual.columns)
            tipos_referencia = base_anual.dtypes.copy()
        if list(base_anual.columns) != colunas_referencia:
            raise ValueError(f"Nomes ou ordem das colunas diferentes em {ano}.")
        if not base_anual.dtypes.equals(tipos_referencia):
            raise ValueError(f"Tipos diferentes em {ano}.")
        for campo in ("ano_arquivo", "ano_parcial", "esfera_original"):
            if campo not in base_anual.columns:
                raise ValueError(f"Campo obrigatório ausente: {campo}.")
        origem_ausente = base_anual["ano_arquivo"].isna().any()
        origem_correta = base_anual["ano_arquivo"].eq(ano).all()
        if origem_ausente or not origem_correta:
            raise ValueError(f"Origem incorreta em {ano}.")
        bases_anuais.append(base_anual)

    # 4. Empilhar os sete anos verticalmente, criando apenas um novo índice.
    # Nenhuma coluna, categoria, ausência ou repetição é alterada nesta etapa.
    consolidada = pd.concat(bases_anuais, axis=0, ignore_index=True)
    if len(consolidada) != TOTAL_ESPERADO:
        raise ValueError("O total deve ser exatamente 342.697 registros.")
    if list(consolidada.columns) != colunas_referencia:
        raise ValueError("A concatenação alterou as colunas.")
    if not consolidada.dtypes.equals(tipos_referencia):
        raise ValueError("A concatenação alterou os tipos.")

    # Comparar cada trecho consolidado com seu ano original para comprovar
    # a preservação de todos os valores, inclusive nulos e esfera_original.
    inicio = 0
    for base_anual in bases_anuais:
        fim = inicio + len(base_anual)
        trecho = consolidada.iloc[inicio:fim].reset_index(drop=True)
        pd.testing.assert_frame_equal(
            trecho, base_anual.reset_index(drop=True), check_exact=True
        )
        inicio = fim

    # 5. Contar cópias excedentes considerando as 28 colunas, sem removê-las.
    # keep='first' define apenas a contagem: todas as linhas ficam na base.
    # Essa definição difere da etapa 03, que avaliou as 25 colunas antes das
    # conversões; valores diferentes na origem podem ter se tornado iguais.
    duplicados = consolidada.duplicated(keep="first")
    total_duplicados = int(duplicados.sum())

    # 6. Validar o ano da compra e a marcação de período parcial.
    # Ausências nesses campos também são erros, não devem ser ignoradas.
    anos_inconsistentes = (
        consolidada["ano_compra"].isna()
        | consolidada["ano_arquivo"].isna()
        | consolidada["ano_compra"].ne(consolidada["ano_arquivo"])
    )
    if anos_inconsistentes.any():
        raise ValueError("ano_compra diverge de ano_arquivo ou está ausente.")
    parcial_esperado = consolidada["ano_arquivo"].eq(2026)
    if consolidada["ano_parcial"].isna().any():
        raise ValueError("ano_parcial contém nulos.")
    if not consolidada["ano_parcial"].eq(parcial_esperado).all():
        raise ValueError("ano_parcial deve ser True somente em 2026.")

    # 7. Conferir a substituição já realizada na etapa 03, sem repeti-la.
    # A combinação dos dois campos comprova a rastreabilidade dos 43 registros.
    esfera_convertida = (
        consolidada["esfera"].eq("NAO_INFORMADO")
        & consolidada["esfera_original"].eq("0")
    )
    if int(esfera_convertida.sum()) != 43:
        raise ValueError("Esperados 43 registros com esfera convertida e original 0.")
    if not consolidada.loc[esfera_convertida, "ano_arquivo"].eq(2020).all():
        raise ValueError("Substituição de esfera encontrada fora de 2020.")

    # 8. Recalcular a relação de preços apenas para validação, sem atribuir
    # resultados às colunas. Decimal evita aproximações de ponto flutuante;
    # a tolerância de um centavo aceita diferenças pequenas de arredondamento.
    divergencias = []
    with localcontext() as contexto:
        contexto.prec = 60
        for quantidade, unitario, total in zip(
            consolidada["qtd_itens_comprados"],
            consolidada["preco_unitario"],
            consolidada["preco_total"],
            strict=True,
        ):
            if pd.isna(quantidade) or pd.isna(unitario) or pd.isna(total):
                raise ValueError("Valor ausente impede validar a relação de preços.")
            diferenca = abs(total - Decimal(quantidade) * unitario)
            divergencias.append(diferenca > TOLERANCIA)
    divergencias_preco = pd.Series(divergencias, index=consolidada.index)
    if divergencias_preco.any():
        raise ValueError("Divergência de preço superior a R$ 0,01.")

    # 9. Montar uma linha de resumo por ano para tornar a validação auditável.
    # Contagens de problemas são por ano; os campos de total consolidado e
    # total de duplicados repetem os totais gerais, não devem ser somados.
    resumos = []
    for ano in REGISTROS_ESPERADOS:
        registros_do_ano = consolidada["ano_arquivo"].eq(ano)
        # Calcular separadamente as contagens facilita conferir o resumo do ano.
        esferas_do_ano = consolidada.loc[registros_do_ano, "esfera"]
        quantidade_nao_informado = int(esferas_do_ano.eq("NAO_INFORMADO").sum())
        quantidade_esfera_convertida = int(esfera_convertida.loc[registros_do_ano].sum())
        quantidade_parciais = int(consolidada.loc[registros_do_ano, "ano_parcial"].sum())
        resumos.append({
            "ano": ano,
            "registros_por_ano": int(registros_do_ano.sum()),
            "total_consolidado": len(consolidada),
            "quantidade_colunas": len(consolidada.columns),
            "duplicados_encontrados": int(duplicados.loc[registros_do_ano].sum()),
            "total_duplicados_consolidado": total_duplicados,
            "inconsistencias_ano_compra": int(anos_inconsistentes.loc[registros_do_ano].sum()),
            "divergencias_preco_total": int(divergencias_preco.loc[registros_do_ano].sum()),
            "quantidade_nao_informado": quantidade_nao_informado,
            "quantidade_esfera_original_zero_convertida": quantidade_esfera_convertida,
            "registros_ano_parcial_true": quantidade_parciais,
        })
    resumo = pd.DataFrame(resumos)

    # 10. Gravar primeiro em pasta temporária dentro de processados e reler.
    # Assim os resultados definitivos só são substituídos após conferir as saídas.
    # No CSV, nulos são representados por campos vazios; somente o Parquet
    # preserva a distinção de tipos e nulos para futuras análises locais.
    ANALISES.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".consolidacao_", dir=PROCESSADOS) as temporario:
        pasta_temporaria = Path(temporario).resolve()
        if not pasta_temporaria.is_relative_to(PROCESSADOS.resolve()):
            raise ValueError("Pasta temporária fora de processados.")
        arquivo_csv = pasta_temporaria / f"{NOME_BASE}.csv"
        arquivo_parquet = pasta_temporaria / f"{NOME_BASE}.parquet"
        arquivo_resumo = pasta_temporaria / "resumo_consolidacao_sprint2.csv"
        consolidada.to_csv(arquivo_csv, sep=";", encoding="utf-8", index=False)
        consolidada.to_parquet(arquivo_parquet, engine="pyarrow", index=False)
        resumo.to_csv(arquivo_resumo, sep=";", encoding="utf-8", index=False)

        relida = pd.read_parquet(arquivo_parquet, engine="pyarrow", dtype_backend="pyarrow")
        pd.testing.assert_frame_equal(relida, consolidada, check_exact=True)
        with arquivo_csv.open(encoding="utf-8", newline="") as arquivo:
            leitor = csv.reader(arquivo, delimiter=";", strict=True)
            if next(leitor) != colunas_referencia:
                raise ValueError("Cabeçalho incorreto no CSV consolidado.")
            registros_csv = 0
            for linha in leitor:
                if len(linha) != 28:
                    raise ValueError("Registro com largura incorreta no CSV.")
                registros_csv += 1
            if registros_csv != TOTAL_ESPERADO:
                raise ValueError("Contagem incorreta no CSV consolidado.")
        resumo_relido = pd.read_csv(arquivo_resumo, sep=";", encoding="utf-8")
        pd.testing.assert_frame_equal(resumo_relido, resumo, check_exact=True)

        # 11. Conferir a preservação das entradas antes de publicar as três saídas.
        # Somente os destinos explícitos abaixo recebem os arquivos gerados.
        for caminho, hash_antes in hashes_antes.items():
            if calcular_hash(caminho) != hash_antes:
                raise ValueError(f"Arquivo protegido alterado: {caminho}")
        arquivo_csv.replace(PROCESSADOS / arquivo_csv.name)
        arquivo_parquet.replace(PROCESSADOS / arquivo_parquet.name)
        arquivo_resumo.replace(ANALISES / arquivo_resumo.name)

    # 12. Confirmar os hashes ao final e apresentar as contagens no terminal.
    # Isso documenta o resultado da execução sem fazer commit ou novo tratamento.
    for caminho, hash_antes in hashes_antes.items():
        if calcular_hash(caminho) != hash_antes:
            raise ValueError(f"Arquivo protegido alterado: {caminho}")
    print(resumo.to_string(index=False))
    print(f"Total: {len(consolidada):,} registros; 28 colunas.")
    print(f"Duplicados exatos encontrados e mantidos: {total_duplicados}.")
    print("Brutos, Parquets anuais e README com hashes inalterados. Sem commit.")


if __name__ == "__main__":
    main()
