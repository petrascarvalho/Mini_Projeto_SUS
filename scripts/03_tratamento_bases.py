"""Tratamento anual autorizado da Sprint 2, sem concatenar bases.

Requisitos: Python global 3.14.4, Pandas 3.0.2 e pyarrow para Parquet.
Execução: py -3.14 scripts/03_tratamento_bases.py

Saídas: dados/processados/por_ano/ANO_tratado.parquet e dois CSVs de auditoria
em documentacao/analises. Parquet conserva tipos de datas, nulos, identificadores
textuais e valores decimais exatos; não são geradas cópias CSV dos tratados.
Os arquivos gerados com esses nomes são substituídos em uma nova execução.

Duplicação é avaliada sobre as 25 colunas originais, ANTES de qualquer conversão
ou substituição. A primeira ocorrência é preservada. As cópias excedentes vão
para auditoria com seus valores originais e o número do registro de origem
(primeiro registro de dados = 1, sem contar o cabeçalho).

Nenhum texto é aparado, normalizado ou preenchido. A única substituição textual
é esfera='0' -> 'NAO_INFORMADO', exclusivamente em 2020. esfera_original é
acrescentada em todos os anos para preservar o esquema e a rastreabilidade.
Campos textuais vazios continuam strings vazias; vazios de capacidade e datas
tornam-se nulos tipados. Não há preenchimento de capacidade com zero.

Valores monetários usam decimal128, não float. As escalas (capacidade: 2;
preços: 4) comportam os valores diagnosticados. Uma futura entrada que exija
arredondamento ou exceda a precisão interrompe o script, sem coerção silenciosa.

Validação temporal separa falhas de conversão de incoerências já existentes.
Inserção anterior à compra é preservada e sinalizada: não há autorização para
corrigir essas datas. Novas incoerências introduzidas pelo tratamento são erro.
Todas as saídas são preparadas e relidas antes da publicação. Os brutos e o
README são conferidos por SHA-256 antes e depois, sem qualquer escrita neles.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
import sys
import tempfile
from decimal import Decimal, localcontext
from pathlib import Path

import pandas as pd
import pyarrow as pa


# -----------------------------------------------------------------------------
# Configuração: definir caminhos relativos e o esquema já validado na Sprint 1.
# Isso permite executar o projeto em outra máquina sem mudar caminhos ou colunas.
# -----------------------------------------------------------------------------
RAIZ = Path(__file__).resolve().parents[1]
BRUTOS = RAIZ / "dados" / "brutos"
PROCESSADOS = RAIZ / "dados" / "processados"
POR_ANO = PROCESSADOS / "por_ano"
ANALISES = RAIZ / "documentacao" / "analises"
ANOS = range(2020, 2027)
COLUNAS = (
    "ano_compra", "nome_instituicao", "esfera", "cnpj_instituicao",
    "municipio_instituicao", "uf", "compra", "insercao", "codigo_br",
    "descricao_catmat", "unidade_fornecimento", "generico", "anvisa",
    "modalidade_compra", "tipo_compra", "capacidade", "unidade_medida",
    "unidade_fornecimento_capacidade", "cnpj_fornecedor", "fornecedor",
    "cnpj_fabricante", "fabricante", "qtd_itens_comprados", "preco_unitario",
    "preco_total",
)
ADICIONAIS = ("ano_arquivo", "ano_parcial", "esfera_original")
DATAS = ("compra", "insercao")
INTEIROS = ("ano_compra", "qtd_itens_comprados")
# Definir tipos decimais com precisão e escala explícitas evita aproximações
# de ponto flutuante. Por exemplo, decimal128(12, 2) aceita 12 dígitos no total,
# sendo 2 depois do ponto. Arrow permite manter esses tipos e nulos no Parquet.
DECIMAIS = {
    "capacidade": pa.decimal128(12, 2),
    "preco_unitario": pa.decimal128(14, 4),
    "preco_total": pa.decimal128(24, 4),
}
TEXTO = pd.ArrowDtype(pa.string())
INTEIRO = pd.ArrowDtype(pa.int64())
DATA = pd.ArrowDtype(pa.timestamp("us"))
BOOLEANO = pd.ArrowDtype(pa.bool_())
TOLERANCIA = Decimal("0.01")
# Aceitar apenas a representação numérica já diagnosticada: ponto decimal,
# sinal opcional e possível notação científica; não corrigir vírgulas ou textos.
NUMERO_CANONICO = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?\Z")


# -----------------------------------------------------------------------------
# Calcular uma assinatura SHA-256 sem escrever no arquivo.
# A comparação dessas assinaturas comprova a preservação dos arquivos brutos.
# -----------------------------------------------------------------------------
def hash_arquivo(caminho: Path) -> str:
    with caminho.open("rb") as arquivo:
        return hashlib.file_digest(arquivo, "sha256").hexdigest()


# -----------------------------------------------------------------------------
# Ler cada CSV como texto, usando UTF-8 e ponto e vírgula.
# Isso preserva zeros à esquerda em CNPJs, codigo_br e anvisa, além de espaços,
# strings vazias e textos como NA, que não devem virar nulos automaticamente.
# -----------------------------------------------------------------------------
def ler_original(caminho: Path) -> pd.DataFrame:
    with caminho.open(encoding="utf-8", errors="strict", newline="") as arquivo:
        # Conferir cabeçalho e largura de cada registro antes de criar a tabela.
        # Uma estrutura inesperada deve interromper a leitura, sem descartar linhas.
        leitor = csv.reader(arquivo, delimiter=";", strict=True)
        if next(leitor, None) != list(COLUNAS):
            raise ValueError(f"Cabeçalho inesperado: {caminho}")
        linhas = []
        for numero, linha in enumerate(leitor, start=1):
            if len(linha) != len(COLUNAS):
                raise ValueError(f"Registro {numero} de {caminho} tem largura irregular; nada descartado.")
            linhas.append(linha)
    return pd.DataFrame(linhas, columns=COLUNAS, dtype=TEXTO)


# -----------------------------------------------------------------------------
# Interpretar um número original como Decimal antes de escolher seu tipo final.
# Assim podemos conferir o valor exato e impedir conversões com perda silenciosa.
# -----------------------------------------------------------------------------
def numero_original(valor: str, campo: str) -> Decimal | None:
    # Manter capacidade ausente como nulo, pois ausência não significa zero.
    # Nos outros campos numéricos, uma ausência inesperada interrompe a execução.
    if valor == "":
        if campo != "capacidade":
            raise ValueError(f"Nulo inesperado no campo numérico obrigatório {campo}.")
        return None
    if NUMERO_CANONICO.fullmatch(valor) is None:
        raise ValueError(f"Formato numérico não autorizado: {campo}={valor!r}")
    numero = Decimal(valor)
    if not numero.is_finite():
        raise ValueError(f"Valor não finito: {campo}={valor!r}")
    return numero


# -----------------------------------------------------------------------------
# Converter datas no formato dia/mês/ano e manter valores ausentes como nulos.
# Validar o formato e o calendário evita interpretar mês e dia ao contrário ou
# esconder uma data preenchida inválida por meio de conversão silenciosa para nulo.
# -----------------------------------------------------------------------------
def datas_originais(serie: pd.Series) -> pd.Series:
    preenchidos = serie.ne("")
    if not (bool(serie.loc[preenchidos].str.fullmatch(r"[0-9]{2}/[0-9]{2}/[0-9]{4}").all())):
        raise ValueError(f"Formato de data não autorizado em {serie.name}.")
    # Somente ausência literal vira nulo. Datas preenchidas inválidas são erro.
    return pd.to_datetime(serie.mask(~preenchidos), format="%d/%m/%Y", errors="raise")


# -----------------------------------------------------------------------------
# Tratar e validar um ano por vez, trabalhando somente em cópias na memória.
# Essa separação preserva os CSVs originais e evita concatenar os sete anos.
# -----------------------------------------------------------------------------
def tratar_quadro(base_original: pd.DataFrame, ano: int) -> tuple[pd.DataFrame, list[dict], dict]:
    if list(base_original.columns) != list(COLUNAS):
        raise ValueError("Esperadas as 25 colunas originais, na ordem validada.")
    # 1. Identificar repetições exatas nas 25 colunas ANTES das conversões.
    # Valores originalmente diferentes não devem virar duplicados por conversão.
    # Guardar as cópias excedentes e a posição original permite auditar a remoção.
    duplicados = base_original.duplicated(subset=list(COLUNAS), keep="first")
    auditoria = []
    for indice in base_original.index[duplicados]:
        registro_removido = base_original.loc[indice].to_dict()
        registro_removido["ano_arquivo"] = ano
        registro_removido["numero_registro_origem"] = int(indice) + 1
        auditoria.append(registro_removido)
    # Preservar a primeira ocorrência e remover somente as cópias já auditadas.
    # Manter outra cópia dos registros permite comparar os valores antes e depois.
    registros_mantidos = base_original.loc[~duplicados].copy(deep=True)
    base_tratada = registros_mantidos.copy(deep=True)

    # 2. Registrar o ano do arquivo para manter a origem de cada registro.
    # Ele será comparado com ano_compra e não depende da conversão das datas.
    base_tratada["ano_arquivo"] = pd.Series(ano, index=base_tratada.index, dtype=INTEIRO)

    # 3. Marcar somente 2026 como parcial, pois sua cobertura é incompleta.
    # Essa informação evita interpretar o período como um ano completo depois.
    base_tratada["ano_parcial"] = pd.Series(ano == 2026, index=base_tratada.index, dtype=BOOLEANO)

    # 4. Preservar esfera_original em TODOS os anos antes de qualquer substituição.
    # Isso mantém o mesmo esquema e permite rastrear os 43 valores 0 de 2020.
    # Apenas esses valores recebem NAO_INFORMADO; os demais textos ficam intactos.
    base_tratada["esfera_original"] = registros_mantidos["esfera"].copy(deep=True)
    substituir = registros_mantidos["esfera"].eq("0") & (ano == 2020)
    base_tratada.loc[substituir, "esfera"] = "NAO_INFORMADO"


    # 5. Converter compra e insercao e guardar referências para validar o resultado.
    # As ausências continuam nulas, especialmente em insercao, sem preenchimento.
    referencias_datas = {}
    for campo in DATAS:
        referencias_datas[campo] = datas_originais(registros_mantidos[campo])
    for campo in DATAS:
        base_tratada[campo] = pd.Series(pd.array(referencias_datas[campo], dtype=DATA), index=base_tratada.index)

    # 6. Converter ano_compra e quantidade para inteiros; capacidade e preços
    # para decimais exatos. Recusar frações nos inteiros evita truncar valores.
    # Guardar os números de referência permite provar que nada foi arredondado.
    referencias_numericas = {}
    for campo in (*INTEIROS, *DECIMAIS):
        valores = []
        for valor in registros_mantidos[campo]:
            valores.append(numero_original(valor, campo))
        referencias_numericas[campo] = valores
        if campo in INTEIROS:
            valores_inteiros = []
            for valor in valores:
                if valor is None or valor != valor.to_integral_value():
                    raise ValueError(f"Valor não inteiro em {campo}; nenhuma truncagem autorizada.")
                valores_inteiros.append(int(valor))
            convertido = pd.array(valores_inteiros, dtype=INTEIRO)
        else:
            convertido = pd.array(valores, dtype=pd.ArrowDtype(DECIMAIS[campo]))
        base_tratada[campo] = pd.Series(convertido, index=base_tratada.index)

    # 7. Conferir esquema, textos e origem após as conversões.
    # Essas comparações protegem os identificadores, nomes, DOSE/DOSES e demais
    # categorias contra alterações não autorizadas. São 25 colunas mais 3 novas.
    if list(base_tratada.columns) != [*COLUNAS, *ADICIONAIS]:
        raise ValueError("Esquema de saída inesperado.")
    # Confere cada valor textual, incluindo identificadores e strings vazias.
    for campo in COLUNAS:
        if campo not in (*DATAS, *INTEIROS, *DECIMAIS, "esfera"):
            pd.testing.assert_series_equal(base_tratada[campo], registros_mantidos[campo])
    esfera_esperada = registros_mantidos["esfera"].copy(deep=True)
    esfera_esperada.loc[substituir] = "NAO_INFORMADO"
    pd.testing.assert_series_equal(base_tratada["esfera"], esfera_esperada)
    if base_tratada["esfera_original"].tolist() != registros_mantidos["esfera"].tolist():
        raise ValueError("esfera_original não preservada.")
    ano_arquivo_correto = bool(base_tratada["ano_arquivo"].eq(ano).all())
    ano_parcial_correto = bool(base_tratada["ano_parcial"].eq(ano == 2026).all())
    if not ano_arquivo_correto or not ano_parcial_correto:
        raise ValueError("Proveniência incorreta.")

    # 8. Comparar datas e números convertidos com suas referências originais.
    # Conferir também os nulos garante que nenhuma ausência tenha virado zero
    # e que nenhum valor positivo tenha se perdido durante a conversão.
    for campo, referencia in referencias_datas.items():
        if base_tratada[campo].isna().tolist() != registros_mantidos[campo].eq("").tolist():
            raise ValueError(f"Nulos de {campo} alterados.")
        esperado = pd.Series(pd.array(referencia, dtype=DATA), index=base_tratada.index, name=campo)
        pd.testing.assert_series_equal(base_tratada[campo], esperado)
    positivos_invalidos = 0
    for campo, antes in referencias_numericas.items():
        for referencia, depois in zip(antes, base_tratada[campo], strict=True):
            if referencia is None:
                if not pd.isna(depois):
                    raise ValueError(f"Nulo preenchido indevidamente: {campo}")
                continue
            perdeu_positivo = referencia > 0 and (pd.isna(depois) or depois <= 0)
            positivos_invalidos += int(perdeu_positivo)
            if pd.isna(depois) or Decimal(depois) != referencia:
                raise ValueError(f"Conversão alterou o valor de {campo}: {referencia} -> {depois}")

    # 9. Comparar ano_compra com o ano do arquivo para validar a proveniência.
    # Uma divergência interrompe a execução, pois não há regra para corrigi-la.
    inconsistencias_ano = int(base_tratada["ano_compra"].ne(base_tratada["ano_arquivo"]).sum())
    if inconsistencias_ano != 0:
        raise ValueError("ano_compra diverge de ano_arquivo.")

    # 10. Conferir preco_total = quantidade × preco_unitario com Decimal.
    # A tolerância de R$ 0,01 aceita pequenas diferenças de arredondamento.
    # Precisão de 60 dígitos evita que o próprio cálculo gere uma divergência.
    divergencias_preco = 0
    maior_diferenca = Decimal(0)
    with localcontext() as contexto:
        contexto.prec = 60
        for quantidade, unitario, total in zip(
            base_tratada["qtd_itens_comprados"],
            base_tratada["preco_unitario"],
            base_tratada["preco_total"],
            strict=True,
        ):
            diferenca = abs(total - Decimal(quantidade) * unitario)
            maior_diferenca = max(maior_diferenca, diferenca)
            divergencias_preco += int(diferenca > TOLERANCIA)
    if divergencias_preco != 0:
        raise ValueError("A relação entre quantidade e preços diverge além de R$ 0,01.")
    if positivos_invalidos != 0:
        raise ValueError("Um valor positivo tornou-se inválido.")

    # 11. Comparar a coerência temporal antes e depois do tratamento.
    # Datas incoerentes já existentes são registradas, não corrigidas.
    # fillna(False) atua apenas nas máscaras de diagnóstico, nunca nas datas.
    cronologia_antes = referencias_datas["insercao"].lt(referencias_datas["compra"]).fillna(False)
    cronologia_depois = base_tratada["insercao"].lt(base_tratada["compra"]).fillna(False)
    if cronologia_antes.tolist() != cronologia_depois.tolist():
        raise ValueError("Tratamento alterou a coerência temporal.")
    fora_ano_antes = referencias_datas["compra"].notna() & referencias_datas["compra"].dt.year.ne(ano)
    fora_ano_depois = (base_tratada["compra"].notna() & base_tratada["compra"].dt.year.ne(ano)).fillna(False)
    if fora_ano_antes.tolist() != fora_ano_depois.tolist():
        raise ValueError("Tratamento alterou o ano das compras.")
    erros_temporais = int((cronologia_depois | fora_ano_depois).sum())

    # 12. Registrar contagens e validações para permitir a comparação antes/depois.
    # O resumo distingue problemas da origem de erros introduzidos no tratamento.
    registros_com_incoerencia = []
    for indice in base_tratada.index[cronologia_depois | fora_ano_depois]:
        registros_com_incoerencia.append(int(indice) + 1)
    tipos_saida = {}
    for coluna, tipo in base_tratada.dtypes.items():
        tipos_saida[coluna] = str(tipo)
    resumo = {
        "ano": ano, "registros_antes": len(base_original), "registros_depois": len(base_tratada),
        "duplicados_removidos": int(duplicados.sum()),
        "esfera_zero_antes": int(base_original["esfera"].eq("0").sum()),
        "nao_informado_depois": int(base_tratada["esfera"].eq("NAO_INFORMADO").sum()),
        "substituicoes_esfera_realizadas": int(substituir.sum()),
        "nulos_capacidade": int(base_tratada["capacidade"].isna().sum()),
        "nulos_insercao": int(base_tratada["insercao"].isna().sum()),
        "erros_datas": erros_temporais,
        "erros_conversao_datas": 0,
        "insercao_anterior_compra": int(cronologia_depois.sum()),
        "compra_fora_ano_arquivo": int(fora_ano_depois.sum()),
        "novas_incoerencias_temporais": 0,
        "registros_origem_com_incoerencia_temporal_json": json.dumps(registros_com_incoerencia),
        "inconsistencias_ano_compra": inconsistencias_ano,
        "divergencias_preco_total": divergencias_preco,
        "maior_diferenca_preco_total": str(maior_diferenca), "tolerancia_preco_total": str(TOLERANCIA),
        "positivos_tornados_invalidos": positivos_invalidos,
        "nulos_capacidade_antes": int(base_original["capacidade"].eq("").sum()),
        "nulos_insercao_antes": int(base_original["insercao"].eq("").sum()),
        "ano_parcial": ano == 2026,
        "tipos_saida_json": json.dumps(tipos_saida, ensure_ascii=False),
        "status": "CONCLUIDO_COM_RESSALVAS_DA_ORIGEM" if erros_temporais else "VALIDADO",
        "observacoes": (
            "Erros de datas contam registros com incoerência temporal já presente: "
            "inserção anterior à compra ou compra fora do ano. Nenhuma data inválida "
            "foi ocultada; falhas de conversão interrompem a execução. Incoerências "
            "da origem preservadas, sem correção autorizada. Duplicação definida "
            "antes das conversões, sobre as 25 colunas originais."
        ),
    }
    if len(base_original) != len(base_tratada) + len(auditoria):
        raise ValueError("Contagem antes/depois não fecha.")
    return base_tratada.reset_index(drop=True), auditoria, resumo


# -----------------------------------------------------------------------------
# Gravar os relatórios de auditoria e reler seu conteúdo.
# Essa conferência garante que as evidências gravadas correspondem à memória.
# -----------------------------------------------------------------------------
def gravar_csv(caminho: Path, linhas: list[dict], campos: list[str]) -> None:
    with caminho.open("w", encoding="utf-8-sig", newline="") as arquivo:
        escritor = csv.DictWriter(arquivo, fieldnames=campos)
        escritor.writeheader()
        escritor.writerows(linhas)
    with caminho.open(encoding="utf-8-sig", newline="") as arquivo:
        leitor = csv.DictReader(arquivo)
        if leitor.fieldnames != campos:
            raise ValueError(f"Cabeçalho de auditoria incorreto: {caminho}")
        dados_relidos = list(leitor)
    esperado = []
    for linha in linhas:
        linha_textual = {}
        for coluna in campos:
            linha_textual[coluna] = str(linha[coluna])
        esperado.append(linha_textual)
    if dados_relidos != esperado:
        raise ValueError(f"Auditoria alterada na serialização: {caminho}")


# -----------------------------------------------------------------------------
# Conferir a lista de arquivos brutos, suas assinaturas e a assinatura do README.
# Esses arquivos estão fora do tratamento e precisam permanecer intactos.
# -----------------------------------------------------------------------------
def conferir_protegidos(hashes_brutos: dict[Path, str], hash_readme: str) -> None:
    atuais = set()
    for caminho in BRUTOS.rglob("*"):
        if caminho.is_file():
            atuais.add(caminho)
    if atuais != set(hashes_brutos):
        raise ValueError("Inventário dos arquivos brutos mudou.")
    for caminho, hash_esperado in hashes_brutos.items():
        if hash_arquivo(caminho) != hash_esperado:
            raise ValueError("Arquivo bruto modificado.")
    if hash_arquivo(RAIZ / "README.md") != hash_readme:
        raise ValueError("README modificado.")


# -----------------------------------------------------------------------------
# Executar as etapas na ordem: conferir ambiente, tratar, validar e gravar saídas.
# Só publicar os arquivos depois de validar todos os anos reduz o risco de
# substituir resultados anteriores por saídas ainda não conferidas.
# -----------------------------------------------------------------------------
def main() -> None:
    if sys.version_info[:3] != (3, 14, 4) or pd.__version__ != "3.0.2":
        raise ValueError("Requer Python 3.14.4 e Pandas 3.0.2.")
    if sys.prefix != sys.base_prefix:
        raise ValueError("Execute com Python global, sem ambiente virtual.")
    print(f"Python {sys.version.split()[0]} | Pandas {pd.__version__} | Parquet com tipos preservados", flush=True)
    # Guardar hashes antes da leitura para comprovar a preservação ao final.
    # Verificar as sete entradas antecipadamente evita iniciar com ano ausente.
    hashes_brutos = {}
    for caminho in BRUTOS.rglob("*"):
        if caminho.is_file():
            hashes_brutos[caminho] = hash_arquivo(caminho)
    for ano in ANOS:
        if not (BRUTOS / str(ano) / f"{ano}.csv" in hashes_brutos):
            raise ValueError(f"Base de {ano} ausente.")
    hash_readme = hash_arquivo(RAIZ / "README.md")
    PROCESSADOS.mkdir(parents=True, exist_ok=True)
    resumos, removidos = [], []
    # Preparar as saídas em pasta temporária dentro de processados.
    # Isso permite reler os resultados antes de substituir as saídas definitivas.
    # Conferir o caminho também mantém a limpeza temporária dentro dessa pasta.
    with tempfile.TemporaryDirectory(prefix=".tratamento_", dir=PROCESSADOS) as temporario:
        pasta_temporaria = Path(temporario).resolve()
        if not (pasta_temporaria.is_relative_to(PROCESSADOS.resolve())):
            raise ValueError("Pasta temporária fora de processados.")
        arquivos_para_publicar = []
        for ano in ANOS:
            caminho_original = BRUTOS / str(ano) / f"{ano}.csv"
            print(f"[{ano}] Tratando cópia de {caminho_original.relative_to(RAIZ)}...", flush=True)
            # Ler e tratar apenas o ano atual para preservar a separação anual.
            # Nenhum comando desta etapa escreve em dados/brutos.
            base_original = ler_original(caminho_original)
            base_tratada, auditoria, resumo = tratar_quadro(base_original, ano)
            nome = f"{ano}_tratado.parquet"
            arquivo_temporario = pasta_temporaria / nome
            # Gravar Parquet sem índice e com os tipos explicitamente definidos.
            # Reler e comparar valores e tipos comprova que a gravação preservou
            # datas, decimais, nulos e identificadores textuais.
            base_tratada.to_parquet(arquivo_temporario, engine="pyarrow", index=False, compression="snappy")
            dados_relidos = pd.read_parquet(arquivo_temporario, engine="pyarrow", dtype_backend="pyarrow")
            pd.testing.assert_frame_equal(dados_relidos, base_tratada, check_exact=True)
            # Acrescentar caminhos e hashes para rastrear entrada e saída.
            # Acumular somente os resumos e cópias removidas para a auditoria.
            resumo["arquivo_origem"] = caminho_original.relative_to(RAIZ).as_posix()
            resumo["sha256_origem"] = hashes_brutos[caminho_original]
            resumo["arquivo_tratado"] = (POR_ANO / nome).relative_to(RAIZ).as_posix()
            resumo["sha256_tratado"] = hash_arquivo(arquivo_temporario)
            resumos.append(resumo)
            removidos.extend(auditoria)  # Apenas cópias removidas para a auditoria solicitada.
            arquivos_para_publicar.append((arquivo_temporario, POR_ANO / nome))
            print(
                f"[{ano}] {len(base_original):,} -> {len(base_tratada):,}; "
                f"removidos: {len(auditoria)}; "
                f"ressalvas de datas: {resumo['erros_datas']}.",
                flush=True,
            )
            del base_original, base_tratada, dados_relidos
        # Gravar e conferir os dois relatórios após concluir os sete anos.
        # Eles documentam as remoções e validações sem juntar as bases tratadas.
        arquivo_duplicados = pasta_temporaria / "registros_duplicados_removidos.csv"
        arquivo_resumo = pasta_temporaria / "resumo_tratamento_sprint2.csv"
        gravar_csv(arquivo_duplicados, removidos, [*COLUNAS, "ano_arquivo", "numero_registro_origem"])
        gravar_csv(arquivo_resumo, resumos, list(resumos[0]))
        arquivos_para_publicar.append((arquivo_duplicados, ANALISES / arquivo_duplicados.name))
        arquivos_para_publicar.append((arquivo_resumo, ANALISES / arquivo_resumo.name))
        # Publicar somente saídas validadas nos diretórios autorizados.
        # Conferir hashes antes e depois assegura a preservação na transferência.
        conferir_protegidos(hashes_brutos, hash_readme)
        POR_ANO.mkdir(parents=True, exist_ok=True)
        ANALISES.mkdir(parents=True, exist_ok=True)
        for origem, destino in arquivos_para_publicar:
            if not (destino.resolve().is_relative_to(POR_ANO.resolve()) or destino.resolve().is_relative_to(ANALISES.resolve())):
                raise ValueError("Destino de publicação fora do escopo.")
            hash_esperado = hash_arquivo(origem)
            origem.replace(destino)
            if hash_arquivo(destino) != hash_esperado:
                raise ValueError(f"Saída mudou na publicação: {destino}")
    # Repetir a proteção ao final para confirmar que toda a execução respeitou
    # os arquivos brutos e o README, incluindo a publicação dos resultados.
    conferir_protegidos(hashes_brutos, hash_readme)
    print(f"Concluído: 7 bases anuais separadas; {len(removidos)} cópias excedentes auditadas. Sem concatenação ou commit.")
    print("Brutos e README preservados por SHA-256. Datas cronologicamente inconsistentes da origem foram mantidas e sinalizadas.")


if __name__ == "__main__":
    main()
