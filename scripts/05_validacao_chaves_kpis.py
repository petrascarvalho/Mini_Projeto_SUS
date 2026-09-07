"""Validar CNPJs e nomes antes da definição dos KPIs, sem tratar os dados."""

import hashlib
import sys
from pathlib import Path

import pandas as pd


# 1. Conferir as versões e o uso do Python global para reproduzir a análise
# no ambiente definido pelo projeto, sem criar ou utilizar ambiente virtual.
if sys.version_info[:3] != (3, 14, 4) or pd.__version__ != "3.0.2":
    raise ValueError("Use Python global 3.14.4 e Pandas 3.0.2.")
if sys.prefix != sys.base_prefix:
    raise ValueError("Não utilize ambiente virtual.")

# 2. Definir caminhos relativos à raiz para não depender do usuário do Windows.
# Guardar hashes permite conferir que a base e o README permaneceram intactos.
raiz = Path(__file__).resolve().parents[1]
caminho_base = raiz / "dados/processados/BPS_20_26_Petras_Ruben_Carvalho.parquet"
caminho_readme = raiz / "README.md"
caminho_relatorio = raiz / "documentacao/analises/validacao_chaves_kpis.csv"
hashes_antes = {}
for caminho in (caminho_base, caminho_readme):
    with caminho.open("rb") as arquivo:
        hashes_antes[caminho] = hashlib.file_digest(arquivo, "sha256").hexdigest()

# 3. Ler apenas os quatro campos necessários, preservando os tipos do Parquet.
# Nenhum texto é aparado ou padronizado; diferenças de escrita continuam distintas.
campos = ["cnpj_instituicao", "nome_instituicao", "cnpj_fornecedor", "fornecedor"]
base = pd.read_parquet(
    caminho_base, columns=campos, engine="pyarrow", dtype_backend="pyarrow"
)
print(f"Python {sys.version.split()[0]} | Pandas {pd.__version__}")
print(f"Registros examinados: {len(base):,}")

# 4. Contar valores distintos, nulos e nomes associados a cada CNPJ.
# nunique exclui nulos, enquanto isna conta as linhas com ausência real.
# Strings vazias ou espaços permanecem valores textuais, sem virar nulos.
# O agrupamento exclui CNPJs nulos e conta apenas nomes não nulos: a ausência
# de um nome não é interpretada como um segundo nome para o mesmo CNPJ.
entidades = [
    ("instituicoes", "cnpj_instituicao", "nome_instituicao"),
    ("fornecedores", "cnpj_fornecedor", "fornecedor"),
]
resultados = []
for entidade, campo_cnpj, campo_nome in entidades:
    # Agrupar pelo identificador evita confundir grafias diferentes de uma entidade.
    grupos_por_cnpj = base.groupby(campo_cnpj, dropna=True)
    nomes_por_cnpj = grupos_por_cnpj[campo_nome].nunique(dropna=True)
    cnpjs_com_varios_nomes = nomes_por_cnpj.gt(1)
    resultado = {
        "entidade": entidade,
        "campo_cnpj": campo_cnpj,
        "campo_nome": campo_nome,
        "cnpjs_distintos": int(base[campo_cnpj].nunique(dropna=True)),
        "nomes_distintos": int(base[campo_nome].nunique(dropna=True)),
        "cnpjs_nulos": int(base[campo_cnpj].isna().sum()),
        "nomes_nulos": int(base[campo_nome].isna().sum()),
        "cnpjs_com_mais_de_um_nome": int(cnpjs_com_varios_nomes.sum()),
    }
    resultados.append(resultado)

# 5. Gravar somente o relatório e reler para conferir as contagens registradas.
# Essa saída documenta a validação sem modificar ou gerar outra versão da base.
relatorio = pd.DataFrame(resultados)
caminho_relatorio.parent.mkdir(parents=True, exist_ok=True)
relatorio.to_csv(caminho_relatorio, sep=";", encoding="utf-8", index=False)
relatorio_relido = pd.read_csv(caminho_relatorio, sep=";", encoding="utf-8")
pd.testing.assert_frame_equal(relatorio_relido, relatorio, check_exact=True)

# 6. Comparar hashes após a análise para comprovar a preservação dos arquivos.
# Mostrar o resultado encerra esta etapa, sem calcular KPIs finais ou fazer commit.
for caminho, hash_antes in hashes_antes.items():
    with caminho.open("rb") as arquivo:
        hash_depois = hashlib.file_digest(arquivo, "sha256").hexdigest()
    if hash_depois != hash_antes:
        raise ValueError(f"Arquivo protegido alterado: {caminho}")
print(relatorio.to_string(index=False))
print("Base consolidada e README com hashes inalterados. Sem tratamento ou commit.")
