# 1. Importação das bibliotecas
import pandas as pd
from pathlib import Path
from html import unescape
import sys
import zipfile

# 2. Definição das pastas
raiz = Path(__file__).resolve().parent
pasta_brutos = raiz / "dados" / "brutos"
pasta_processados = raiz / "dados" / "processados"
arquivo_padrao = pasta_processados / "BPS_20_26_Petras_Ruben_Carvalho.csv"
arquivo_saida = Path(sys.argv[1]) if len(sys.argv) > 1 else arquivo_padrao

# 3. Leitura dos arquivos de 2020 a 2026
# Ler os identificadores como texto para preservar seus valores.
tipos = {
    "ano_compra": "int64",
    "codigo_br": "string",
    "anvisa": "string",
    "cnpj_instituicao": "string",
    "cnpj_fornecedor": "string",
    "cnpj_fabricante": "string",
}
bases = []
print("Registros originais por ano:")
for ano in range(2020, 2027):
    arquivo = pasta_brutos / f"{ano}_csv.zip"
    with zipfile.ZipFile(arquivo) as arquivo_zip:
        nomes_csv = [nome for nome in arquivo_zip.namelist()
                     if nome.lower().endswith(".csv")]
        if len(nomes_csv) != 1:
            raise ValueError(f"ZIP de {ano} deve conter um único CSV.")
        nome_csv = nomes_csv[0]
        print(f"{ano}: CSV interno = {nome_csv}")
        # Reconhecer apenas os campos vazios como valores ausentes.
        with arquivo_zip.open(nome_csv) as csv_anual:
            base_anual = pd.read_csv(
                csv_anual, sep=";", encoding="utf-8", dtype=tipos,
                keep_default_na=False, na_values=[""], low_memory=False,
            )
    bases.append(base_anual)
    print(f"{ano}: {len(base_anual)} registros")

# 4. Junção das bases anuais
# Empilhar as sete tabelas e criar uma sequência única de índices.
base = pd.concat(bases, ignore_index=True)
registros_originais = len(base)

# 5. Verificação e remoção dos duplicados
# Comparar as 25 colunas originais antes de tratar os dados.
duplicados_removidos = int(base.duplicated().sum())
base = base.drop_duplicates(keep="first")

# 6. Seleção das colunas utilizadas no projeto
# Manter os campos necessários às análises e comparações no Power BI.
colunas_projeto = [
    "ano_compra",
    "compra",
    "nome_instituicao",
    "cnpj_instituicao",
    "municipio_instituicao",
    "uf",
    "codigo_br",
    "descricao_catmat",
    "unidade_fornecimento",
    "unidade_fornecimento_capacidade",
    "modalidade_compra",
    "cnpj_fornecedor",
    "fornecedor",
    "fabricante",
    "qtd_itens_comprados",
    "preco_unitario",
    "preco_total",
]
base = base[colunas_projeto]

# 7. Tratamento e definição dos tipos de dados
# Definir os tipos para facilitar a análise posterior no Power BI.
base["ano_compra"] = base["ano_compra"].astype("int64")
base["compra"] = pd.to_datetime(
    base["compra"], format="%d/%m/%Y", errors="coerce",
)

colunas_texto = [
    "nome_instituicao",
    "cnpj_instituicao",
    "municipio_instituicao",
    "uf",
    "codigo_br",
    "descricao_catmat",
    "unidade_fornecimento",
    "unidade_fornecimento_capacidade",
    "modalidade_compra",
    "cnpj_fornecedor",
    "fornecedor",
    "fabricante",
]
# Remover espaços nas extremidades e reduzir espaços consecutivos.
for coluna in colunas_texto:
    base[coluna] = (
        base[coluna].astype("string").str.strip()
        .str.replace(r"\s+", " ", regex=True)
    )

# Padronizar espaços ao redor de hífens somente nos nomes abaixo.
for coluna in ["nome_instituicao", "fornecedor", "fabricante"]:
    base[coluna] = base[coluna].str.replace(r"\s*-\s*", " - ", regex=True)

# Manter quantidades inteiras e preços sem arredondamento.
base["qtd_itens_comprados"] = base["qtd_itens_comprados"].astype("int64")
for coluna in ["preco_unitario", "preco_total"]:
    base[coluna] = pd.to_numeric(base[coluna])

# Diagnosticar HTML sem modificar a descrição técnica original.
com_tags = base["descricao_catmat"].str.contains("<", regex=False, na=False)
com_entidades = base["descricao_catmat"].str.contains("&#", regex=False, na=False)
afetados_html = com_tags | com_entidades
print("\nDiagnóstico de HTML em descricao_catmat:")
print(f"Registros contendo '<': {com_tags.sum()}")
print(f"Registros contendo '&#': {com_entidades.sum()}")
print(f"Registros afetados por pelo menos um dos padrões: {afetados_html.sum()}")

# Criar o nome para exibição, preservando descricao_catmat.
base.insert(base.columns.get_loc("descricao_catmat") + 1, "Nome_Produto",
            base["descricao_catmat"].copy())
base["Nome_Produto"] = (
    base["Nome_Produto"].map(unescape, na_action="ignore").astype("string")
)

# Se a descrição começar com HTML, preservar o texto dentro das tags.
inicia_com_tag = base["Nome_Produto"].str.match(r"^\s*<", na=False)
base.loc[inicia_com_tag, "Nome_Produto"] = (
    base.loc[inicia_com_tag, "Nome_Produto"]
    .str.replace(r"<[^>]+>", " ", regex=True)
)

# Nos demais casos, manter somente o texto anterior à primeira tag.
base.loc[~inicia_com_tag, "Nome_Produto"] = (
    base.loc[~inicia_com_tag, "Nome_Produto"]
    .str.replace(r"<.*$", "", regex=True)
)

# Finalizar a limpeza e manter somente o texto antes da primeira vírgula.
base["Nome_Produto"] = (
    base["Nome_Produto"]
    .str.replace(r"<[^>]+>", " ", regex=True)
    .str.replace(r"\s+", " ", regex=True)
    .str.strip()
    .str.split(",", n=1).str[0]
    .str.strip()
)
base["Nome_Produto"] = base["Nome_Produto"].astype("string")

print("\nValidação de Nome_Produto:")
print(f"Valores distintos: {base['Nome_Produto'].nunique()}")
print(f"Valores nulos: {base['Nome_Produto'].isna().sum()}")
print(f"Valores vazios: {base['Nome_Produto'].eq('').sum()}")
tags_restantes = base["Nome_Produto"].str.contains("<", regex=False, na=False).sum()
entidades_restantes = base["Nome_Produto"].str.contains("&#", regex=False, na=False).sum()
print(f"Valores ainda contendo '<': {tags_restantes}")
print(f"Valores ainda contendo '&#': {entidades_restantes}")
if tags_restantes > 0 or entidades_restantes > 0:
    raise ValueError("Limpeza de Nome_Produto incompleta. Exportação interrompida.")

print("\nExemplos corrigidos:")
exemplos = base.loc[afetados_html, ["descricao_catmat", "Nome_Produto"]]
for exemplo in exemplos.drop_duplicates().head(3).itertuples(index=False):
    print(f"Original: {exemplo.descricao_catmat}")
    print(f"Nome_Produto: {exemplo.Nome_Produto}\n")

# 8. Verificação dos valores nulos
# Contar as ausências sem preencher campos ou excluir linhas.
nulos_por_coluna = base.isnull().sum()

# 9. Conferência dos indicadores
valor_total = base["preco_total"].sum()
quantidade_total = base["qtd_itens_comprados"].sum()
numero_registros = len(base)
instituicoes = base["cnpj_instituicao"].nunique()
fornecedores = base["cnpj_fornecedor"].nunique()
# Dividir os totais para obter a média ponderada.
preco_medio_ponderado = valor_total / quantidade_total

# 10. Conferência antes da exportação
print("\nTipos de dados antes da exportação:")
print(base.dtypes)
print("\nResumo final:")
print(f"Total original das sete bases, antes do tratamento: {registros_originais}")
print(f"Duplicados removidos: {duplicados_removidos}")
print(f"Total final: {numero_registros}")
print(f"Nomes distintos de instituições: {base['nome_instituicao'].nunique()}")
print(f"Nomes distintos de fornecedores: {base['fornecedor'].nunique()}")
print(f"Nomes distintos de fabricantes: {base['fabricante'].nunique()}")
print(f"Colunas finais: {base.shape[1]}")
print("Nomes das colunas:")
print(base.columns.tolist())
print(f"Intervalo de ano_compra: {base['ano_compra'].min()} a {base['ano_compra'].max()}")
print("\nValores nulos por coluna:")
print(nulos_por_coluna.to_string())
print("\nIndicadores para conferência no Power BI:")
print(f"Valor total: {valor_total:.4f}")
print(f"Quantidade total: {quantidade_total}")
print(f"Número de registros: {numero_registros}")
print(f"Instituições: {instituicoes}")
print(f"Fornecedores: {fornecedores}")
print(f"Preço médio ponderado: {preco_medio_ponderado:.10f}")

# Conferir os KPIs na precisão informada antes de gravar o arquivo.
if (
    numero_registros != 342697
    or f"{valor_total:.4f}" != "78557477974.0877"
    or quantidade_total != 57127143721
    or instituicoes != 831
    or fornecedores != 3502
    or f"{preco_medio_ponderado:.10f}" != "1.3751340056"
):
    raise ValueError("KPIs diferentes dos esperados. Exportação interrompida.")
print("KPIs conferidos: todos permanecem iguais aos valores esperados.")

# 11. Exportação do CSV consolidado para o Power BI
pasta_processados.mkdir(parents=True, exist_ok=True)
# Gravar uma única tabela, com vírgula decimal e sem o índice.
base.to_csv(
    arquivo_saida, index=False, sep=";", encoding="utf-8-sig",
    decimal=",", date_format="%d/%m/%Y",
)
print(f"\nCSV salvo em: {arquivo_saida}")
print(f"Tamanho do CSV: {arquivo_saida.stat().st_size} bytes")

# 12. Releitura simples do CSV gerado
# Conferir a estrutura sem criar outro arquivo.
base_conferida = pd.read_csv(
    arquivo_saida, sep=";", encoding="utf-8-sig", dtype="string",
    keep_default_na=False, na_values=[""],
)
print("\nConferência do CSV gerado:")
print(f"Linhas: {len(base_conferida)}")
print(f"Colunas: {base_conferida.shape[1]}")
print("Nomes das colunas:")
print(base_conferida.columns.tolist())
print(f"Presença de Nome_Produto: {'Nome_Produto' in base_conferida.columns}")
if base_conferida.shape != (342697, 18) or "Nome_Produto" not in base_conferida.columns:
    raise ValueError("Estrutura do CSV diferente da esperada.")
tags_csv = base_conferida["Nome_Produto"].str.contains("<", regex=False, na=False).sum()
entidades_csv = base_conferida["Nome_Produto"].str.contains("&#", regex=False, na=False).sum()
print(f"Nome_Produto contendo '<' no CSV: {tags_csv}")
print(f"Nome_Produto contendo '&#' no CSV: {entidades_csv}")
if tags_csv > 0 or entidades_csv > 0:
    raise ValueError("O CSV contém HTML não tratado em Nome_Produto.")
