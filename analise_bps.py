# 1. Importação das bibliotecas
import pandas as pd
from pathlib import Path

# 2. Definição das pastas
raiz = Path(__file__).resolve().parent
pasta_brutos = raiz / "dados" / "brutos"
pasta_processados = raiz / "dados" / "processados"
arquivo_saida = pasta_processados / "BPS_20_26_Petras_Ruben_Carvalho.csv"

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
    arquivo = pasta_brutos / str(ano) / f"{ano}.csv"
    # Reconhecer apenas os campos vazios como valores ausentes.
    base_anual = pd.read_csv(
        arquivo, sep=";", encoding="utf-8", dtype=tipos,
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

# 6. Tratamento dos textos
# Remover somente espaços nas extremidades dos textos.
for coluna in base.select_dtypes(include=["string", "object"]).columns:
    base[coluna] = base[coluna].str.strip()

# 7. Tratamento das datas
# Interpretar dia, mês e ano sem preencher datas ausentes.
for coluna in ["compra", "insercao"]:
    base[coluna] = pd.to_datetime(
        base[coluna],
        format="%d/%m/%Y",
        errors="coerce",
    )

# 8. Tratamento dos campos numéricos
# Converter os números sem substituir valores ausentes por zero.
for coluna in ["capacidade", "qtd_itens_comprados", "preco_unitario", "preco_total"]:
    base[coluna] = pd.to_numeric(base[coluna])

# 9. Seleção das colunas utilizadas no projeto
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
    "cnpj_fabricante",
    "fabricante",
    "qtd_itens_comprados",
    "preco_unitario",
    "preco_total",
]
base = base[colunas_projeto]

# 10. Verificação dos valores nulos
# Contar as ausências sem preencher campos ou excluir linhas.
nulos_por_coluna = base.isnull().sum()

# 11. Conferência dos indicadores
valor_total = base["preco_total"].sum()
quantidade_total = base["qtd_itens_comprados"].sum()
numero_registros = len(base)
instituicoes = base["cnpj_instituicao"].nunique()
fornecedores = base["cnpj_fornecedor"].nunique()
# Dividir os totais para obter a média ponderada.
preco_medio_ponderado = valor_total / quantidade_total

# 12. Exportação do CSV consolidado para o Power BI
pasta_processados.mkdir(parents=True, exist_ok=True)
# Gravar uma única tabela, com vírgula decimal e sem o índice.
base.to_csv(
    arquivo_saida, index=False, sep=";", encoding="utf-8-sig",
    decimal=",", date_format="%d/%m/%Y",
)

# 13. Resumo final
print("\nResumo final:")
print(f"Total original das sete bases, antes do tratamento: {registros_originais}")
print(f"Duplicados removidos: {duplicados_removidos}")
print(f"Total final: {numero_registros}")
print(f"Colunas finais: {base.shape[1]}")
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
print(f"\nCSV salvo em: {arquivo_saida}")
print(f"Tamanho do CSV: {arquivo_saida.stat().st_size} bytes")
