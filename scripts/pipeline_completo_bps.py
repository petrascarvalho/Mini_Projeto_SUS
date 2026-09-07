"""Pipeline didático das Sprints 1, 2 e 3, independente dos scripts 01 a 07.

Executar com Python global 3.14.4 e Pandas 3.0.2, sem .venv.
Parte dos sete CSVs originais, sem fazer downloads nem alterar os brutos.
As saídas são preparadas em pasta temporária e comparadas com as existentes.
Qualquer diferença interrompe a execução ANTES de substituir os resultados.
Os documentos narrativos e os relatórios históricos de diagnóstico são preservados.
O diagnóstico básico desta execução fica em diagnostico_pipeline_bps.csv.
"""

# 1. Importar as bibliotecas usadas na leitura, nas contas e nas verificações.
# Decimal e Arrow preservam os tipos exatos que já foram validados no projeto.
import csv
import hashlib
import json
import re
import shutil
import sys
import tempfile
from decimal import Decimal, localcontext
from pathlib import Path

import pandas as pd
import pyarrow as pa

# 2. Definir caminhos relativos à raiz e os mesmos tipos do tratamento anual.
# As 25 colunas são mantidas na ordem original, seguidas das três de rastreabilidade.
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
REGISTROS_ANTES = {2020: 84819, 2021: 83622, 2022: 88991, 2023: 31992,
                   2024: 26258, 2025: 26215, 2026: 819}
REGISTROS_DEPOIS = {2020: 84819, 2021: 83622, 2022: 88991, 2023: 31992,
                    2024: 26242, 2025: 26214, 2026: 817}
TEMPORAIS_ESPERADOS = {2020: 0, 2021: 0, 2022: 0, 2023: 1, 2024: 11, 2025: 0, 2026: 0}
NOME_BASE = "BPS_20_26_Petras_Ruben_Carvalho"

# Estas funções curtas repetem verificações específicas em cada ano.
# Elas não executam outros scripts nem corrigem formatos inesperados.
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



# 3. Conferir o ambiente e registrar hashes para proteger entradas e documentação.
# As saídas existentes serão usadas como referência, nunca como fonte de tratamento.
if sys.version_info[:3] != (3, 14, 4) or pd.__version__ != "3.0.2":
    raise ValueError("Use Python global 3.14.4 e Pandas 3.0.2.")
if sys.prefix != sys.base_prefix:
    raise ValueError("Não utilize ambiente virtual.")
print(f"Python {sys.version.split()[0]} | Pandas {pd.__version__}", flush=True)
protegidos = {}
for pasta in (BRUTOS, RAIZ / "scripts"):
    for caminho in pasta.rglob("*"):
        if caminho.is_file():
            protegidos[caminho] = hash_arquivo(caminho)
protegidos[RAIZ / "README.md"] = hash_arquivo(RAIZ / "README.md")

# Ler evidências das Sprints 1 e 2 apenas para comparar os diagnósticos.
# Quando ausentes em uma reprodução inicial, as contagens fixas continuam valendo.
referencias = {}
for nome in ("resumo_bases", "tipos_colunas_por_ano", "diagnostico_nulos",
             "diagnostico_numericos", "diagnostico_datas", "resumo_qualidade_sprint2"):
    caminho = ANALISES / f"{nome}.csv"
    referencias[nome] = {}
    if caminho.exists():
        protegidos[caminho] = hash_arquivo(caminho)
        with caminho.open(encoding="utf-8-sig", newline="") as arquivo:
            for linha in csv.DictReader(arquivo):
                campo = linha.get("campo", linha.get("nome_coluna_original", ""))
                referencias[nome][(int(linha["ano"]), campo)] = linha

# 4. Preparar saídas isoladas para não substituir resultados se houver diferença.
# A limpeza automática atinge apenas esta pasta temporária criada pela execução.
PROCESSADOS.mkdir(parents=True, exist_ok=True)
ANALISES.mkdir(parents=True, exist_ok=True)
POR_ANO.mkdir(parents=True, exist_ok=True)
with tempfile.TemporaryDirectory(prefix=".pipeline_", dir=PROCESSADOS) as temporario:
    preparo = Path(temporario).resolve()
    if not preparo.is_relative_to(PROCESSADOS.resolve()):
        raise ValueError("Pasta temporária fora de processados.")
    publicacoes = []
    bases_tratadas = []
    resumos_tratamento = []
    removidos = []
    diagnosticos = []
    tipos_anteriores = {}
    total_antes = 0

    # 5. Ler, inspecionar e diagnosticar um ano de cada vez antes de tratá-lo.
    # UTF-8 estrito e csv.reader preservam identificadores, espaços e campos vazios.
    for ano in ANOS:
        caminho_original = BRUTOS / str(ano) / f"{ano}.csv"
        base_original = ler_original(caminho_original)
        total_antes += len(base_original)
        if len(base_original) != REGISTROS_ANTES[ano]:
            raise ValueError(f"Contagem original diferente em {ano}.")
        print(f"[{ano}] Original: {len(base_original):,} registros; 25 colunas iguais.", flush=True)
        referencia = referencias["resumo_bases"].get((ano, ""))
        if referencia is not None:
            if int(referencia["numero_registros"]) != len(base_original):
                raise ValueError(f"Inspeção anterior difere em {ano}.")
            if json.loads(referencia["nomes_colunas_originais"]) != list(base_original.columns):
                raise ValueError(f"Estrutura diferente da Sprint 1 em {ano}.")

        # Nulo diagnóstico significa campo vazio; espaços e textos como NA ficam
        # separados. Inferir tipos não converte nem padroniza o conteúdo original.
        total_nulos = 0
        datas_diagnostico = {}
        numeros_diagnostico = {}
        tipos_do_ano = {}
        for campo in COLUNAS:
            serie = base_original[campo]
            preenchidos = serie.loc[serie.ne("")]
            nulos = int(serie.eq("").sum())
            total_nulos += nulos
            tipo = "texto"
            if preenchidos.empty:
                tipo = "indeterminado (sem valores)"
            elif preenchidos.str.fullmatch(r"[+-]?\d+").all():
                tipo = "inteiro"
            elif preenchidos.str.fullmatch(r"[+-]?(?:\d+(?:[.,]\d*)?|[.,]\d+)(?:[eE][+-]?\d+)?").all():
                tipo = "decimal"
            elif preenchidos.isin(["True", "False", "true", "false"]).all():
                tipo = "booleano"
            elif preenchidos.str.fullmatch(r"[+-]?(?:\d+(?:[.,]\d*)?|[.,]\d+)(?:[eE][+-]?\d+)?").any():
                tipo = "misto (numero/texto)"
            detalhe = {
                "ano": ano, "campo": campo, "registros": len(base_original),
                "colunas": len(COLUNAS), "encoding": "utf-8", "separador": ";",
                "nulos_campos_vazios": nulos, "percentual_nulos": round(100 * nulos / len(serie), 6),
                "strings_apenas_espacos": int(serie.str.fullmatch(r"\s+").sum()),
                "espacos_nas_bordas": int(serie.ne(serie.str.strip()).sum()),
                "distintos_textuais": int(serie.nunique(dropna=True)),
                "dtype_leitura": str(serie.dtype),
            }

            # Interpretar datas somente em séries auxiliares para obter limites.
            # Formatos inválidos interrompem o pipeline, sem virar nulos silenciosos.
            if campo in DATAS:
                datas = datas_originais(serie)
                datas_diagnostico[campo] = datas
                tipo = "data" if len(preenchidos) else tipo
                detalhe["datas_validas"] = int(datas.notna().sum())
                detalhe["datas_invalidas"] = int((serie.ne("") & datas.isna()).sum())
                detalhe["data_minima"] = datas.min().strftime("%Y-%m-%d")
                detalhe["data_maxima"] = datas.max().strftime("%Y-%m-%d")
                referencia_data = referencias["diagnostico_datas"].get((ano, campo))
                if referencia_data is not None:
                    for atual, antigo in (("datas_validas", "valores_validos"),
                                          ("datas_invalidas", "valores_invalidos_nao_vazios")):
                        if detalhe[atual] != int(referencia_data[antigo]):
                            raise ValueError(f"Diagnóstico de datas diferente: {ano}/{campo}.")
                    for limite in ("data_minima", "data_maxima"):
                        if detalhe[limite] != referencia_data[limite]:
                            raise ValueError(f"Limite de data diferente: {ano}/{campo}.")

            # Interpretar números em listas auxiliares para diagnosticar sinais,
            # zeros e conversibilidade, sem preencher capacidade nem corrigir textos.
            if campo in (*INTEIROS, *DECIMAIS):
                valores = []
                for valor in serie:
                    valores.append(numero_original(valor, campo))
                numeros_diagnostico[campo] = valores
                negativos = zeros = positivos = 0
                for valor in valores:
                    if valor is not None:
                        negativos += int(valor < 0)
                        zeros += int(valor == 0)
                        positivos += int(valor > 0)
                detalhe["negativos"] = negativos
                detalhe["zeros"] = zeros
                detalhe["positivos"] = positivos
                detalhe["numeros_invalidos"] = 0
                detalhe["padrao_numerico"] = "Inteiro, ponto decimal ou notação científica; sem correção."
                referencia_numero = referencias["diagnostico_numericos"].get((ano, campo))
                if referencia_numero is not None:
                    for sinal in ("negativos", "zeros", "positivos"):
                        if detalhe[sinal] != int(referencia_numero[sinal]):
                            raise ValueError(f"Diagnóstico numérico diferente: {ano}/{campo}/{sinal}.")
                    if int(referencia_numero["valores_nao_vazios_nao_conversiveis"]) != 0:
                        raise ValueError(f"Conversibilidade diferente: {ano}/{campo}.")

            detalhe["tipo_inferido"] = tipo
            tipos_do_ano[campo] = tipo
            detalhe["tipo_diferente_ano_anterior"] = campo in tipos_anteriores and tipos_anteriores[campo] != tipo
            referencia_tipo = referencias["tipos_colunas_por_ano"].get((ano, campo))
            if referencia_tipo is not None and referencia_tipo["tipo_inferido"] != tipo:
                raise ValueError(f"Tipo inferido diferente da Sprint 1: {ano}/{campo}.")
            referencia_nulo = referencias["diagnostico_nulos"].get((ano, campo))
            if referencia_nulo is not None and int(referencia_nulo["quantidade_nulos"]) != nulos:
                raise ValueError(f"Nulos diferentes da Sprint 2: {ano}/{campo}.")
            diagnosticos.append(detalhe)
        tipos_anteriores = tipos_do_ano

        # Conferir os preços antes do tratamento para não ocultar inconsistências.
        # Decimal e tolerância absoluta de R$ 0,01 repetem a regra já validada.
        divergencias_origem = 0
        with localcontext() as contexto:
            contexto.prec = 60
            for quantidade, unitario, total in zip(
                numeros_diagnostico["qtd_itens_comprados"],
                numeros_diagnostico["preco_unitario"],
                numeros_diagnostico["preco_total"], strict=True,
            ):
                divergencias_origem += int(abs(total - quantidade * unitario) > TOLERANCIA)
        duplicados_origem = int(base_original.duplicated(keep="first").sum())
        if divergencias_origem != 0:
            raise ValueError(f"Divergência de preço na origem em {ano}.")
        referencia_qualidade = referencias["resumo_qualidade_sprint2"].get((ano, ""))
        if referencia_qualidade is not None:
            for campo, valor in (("total_nulos", total_nulos),
                                 ("duplicados_exatos_excedentes", duplicados_origem),
                                 ("divergencias_preco_total", divergencias_origem)):
                if int(referencia_qualidade[campo]) != valor:
                    raise ValueError(f"Qualidade diferente da Sprint 2: {ano}/{campo}.")
        print(f"[{ano}] Diagnóstico: {total_nulos:,} nulos; {duplicados_origem} cópias excedentes.", flush=True)

        # 6. Aplicar as mesmas regras do script 03 em uma cópia anual.
        # O bloco é explícito para permitir acompanhar cada transformação.
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

        base_tratada = base_tratada.reset_index(drop=True)
        if len(base_tratada) != REGISTROS_DEPOIS[ano]:
            raise ValueError(f"Contagem tratada diferente em {ano}.")
        if resumo["insercao_anterior_compra"] != TEMPORAIS_ESPERADOS[ano]:
            raise ValueError(f"Inconsistências temporais diferentes em {ano}.")
        if resumo["compra_fora_ano_arquivo"] != 0:
            raise ValueError(f"Ano das datas de compra diferente em {ano}.")

        # 7. Gravar o Parquet anual temporário e reler para conferir valores e tipos.
        # A comparação com o arquivo existente ocorre antes da publicação de tudo.
        nome = f"{ano}_tratado.parquet"
        arquivo_temporario = preparo / nome
        base_tratada.to_parquet(arquivo_temporario, engine="pyarrow", index=False, compression="snappy")
        relida = pd.read_parquet(arquivo_temporario, engine="pyarrow", dtype_backend="pyarrow")
        pd.testing.assert_frame_equal(relida, base_tratada, check_exact=True)
        if (POR_ANO / nome).exists():
            anterior = pd.read_parquet(POR_ANO / nome, engine="pyarrow", dtype_backend="pyarrow")
            pd.testing.assert_frame_equal(base_tratada, anterior, check_exact=True, obj=f"Base anual {ano}")
        resumo["arquivo_origem"] = caminho_original.relative_to(RAIZ).as_posix()
        resumo["sha256_origem"] = hash_arquivo(caminho_original)
        resumo["arquivo_tratado"] = (POR_ANO / nome).relative_to(RAIZ).as_posix()
        resumo["sha256_tratado"] = hash_arquivo(arquivo_temporario)
        resumos_tratamento.append(resumo)
        removidos.extend(auditoria)
        bases_tratadas.append(base_tratada)
        publicacoes.append((arquivo_temporario, POR_ANO / nome))
        print(f"[{ano}] Tratado: {len(base_tratada):,}; conteúdo igual ao anterior quando disponível.", flush=True)

    # Registrar as cópias removidas e os resumos com o formato histórico.
    # Não substituir documentos narrativos nem os relatórios antigos de inspeção.
    for nome, linhas, campos in (
        ("registros_duplicados_removidos.csv", removidos, [*COLUNAS, "ano_arquivo", "numero_registro_origem"]),
        ("resumo_tratamento_sprint2.csv", resumos_tratamento, list(resumos_tratamento[0])),
    ):
        caminho = preparo / nome
        with caminho.open("w", encoding="utf-8-sig", newline="") as arquivo:
            escritor = csv.DictWriter(arquivo, fieldnames=campos)
            escritor.writeheader()
            escritor.writerows(linhas)
        publicacoes.append((caminho, ANALISES / nome))
    caminho_diagnostico = preparo / "diagnostico_pipeline_bps.csv"
    pd.DataFrame(diagnosticos).to_csv(caminho_diagnostico, sep=";", encoding="utf-8", index=False)
    publicacoes.append((caminho_diagnostico, ANALISES / caminho_diagnostico.name))

    # 8. Concatenar verticalmente sem novo tratamento e sem remover registros.
    # Comparar cada trecho garante que nenhuma coluna, tipo, texto ou nulo mudou.
    base = pd.concat(bases_tratadas, axis=0, ignore_index=True)
    if len(base) != 342697 or list(base.columns) != [*COLUNAS, *ADICIONAIS]:
        raise ValueError("Esperados 342.697 registros e as mesmas 28 colunas.")
    if total_antes != 342716 or len(removidos) != 19:
        raise ValueError("Contagem inicial ou duplicados removidos diferente.")
    inicio = 0
    for anual in bases_tratadas:
        fim = inicio + len(anual)
        pd.testing.assert_frame_equal(base.iloc[inicio:fim].reset_index(drop=True), anual, check_exact=True)
        inicio = fim
    if base.duplicated(keep="first").any():
        raise ValueError("Duplicados após concatenação; nenhuma nova remoção autorizada.")
    if base["ano_compra"].isna().any() or not base["ano_compra"].eq(base["ano_arquivo"]).all():
        raise ValueError("ano_compra diferente de ano_arquivo.")
    if base["ano_parcial"].isna().any() or not base["ano_parcial"].eq(base["ano_arquivo"].eq(2026)).all():
        raise ValueError("Marcação parcial incorreta.")
    esfera_convertida = base["esfera"].eq("NAO_INFORMADO") & base["esfera_original"].eq("0")
    if int(esfera_convertida.sum()) != 43 or int(base["esfera"].eq("NAO_INFORMADO").sum()) != 43:
        raise ValueError("Substituição de esfera diferente.")
    if not base.loc[esfera_convertida, "ano_arquivo"].eq(2020).all():
        raise ValueError("Substituição de esfera fora de 2020.")
    with localcontext() as contexto:
        contexto.prec = 60
        for quantidade, unitario, total in zip(base["qtd_itens_comprados"], base["preco_unitario"], base["preco_total"], strict=True):
            if abs(total - Decimal(quantidade) * unitario) > TOLERANCIA:
                raise ValueError("Divergência de preço após concatenação.")

    # 9. Preparar CSV UTF-8 com ponto e vírgula e Parquet, ambos sem índice.
    # O Parquet também é comparado célula a célula e por tipo com o consolidado atual.
    arquivo_csv = preparo / f"{NOME_BASE}.csv"
    arquivo_parquet = preparo / f"{NOME_BASE}.parquet"
    base.to_csv(arquivo_csv, sep=";", encoding="utf-8", index=False)
    base.to_parquet(arquivo_parquet, engine="pyarrow", index=False)
    relida = pd.read_parquet(arquivo_parquet, engine="pyarrow", dtype_backend="pyarrow")
    pd.testing.assert_frame_equal(relida, base, check_exact=True)
    if (PROCESSADOS / arquivo_parquet.name).exists():
        anterior = pd.read_parquet(PROCESSADOS / arquivo_parquet.name, engine="pyarrow", dtype_backend="pyarrow")
        pd.testing.assert_frame_equal(base, anterior, check_exact=True, obj="Consolidado anterior")
    publicacoes.append((arquivo_csv, PROCESSADOS / arquivo_csv.name))
    publicacoes.append((arquivo_parquet, PROCESSADOS / arquivo_parquet.name))

    # 10. Validar CNPJs e nomes sem padronizar textos ou contar nulos como entidade.
    # As contagens esperadas foram estabelecidas antes da definição dos KPIs.
    entidades = [
        ("instituicoes", "cnpj_instituicao", "nome_instituicao"),
        ("fornecedores", "cnpj_fornecedor", "fornecedor"),
    ]
    resultados = []
    for entidade, campo_cnpj, campo_nome in entidades:
        nomes_por_cnpj = base.groupby(campo_cnpj, dropna=True)[campo_nome].nunique(dropna=True)
        resultado = {
            "entidade": entidade,
            "campo_cnpj": campo_cnpj,
            "campo_nome": campo_nome,
            "cnpjs_distintos": int(base[campo_cnpj].nunique(dropna=True)),
            "nomes_distintos": int(base[campo_nome].nunique(dropna=True)),
            "cnpjs_nulos": int(base[campo_cnpj].isna().sum()),
            "nomes_nulos": int(base[campo_nome].isna().sum()),
            "cnpjs_com_mais_de_um_nome": int(nomes_por_cnpj.gt(1).sum()),
        }
        resultados.append(resultado)


    relatorio_chaves = pd.DataFrame(resultados)
    chaves_esperadas = [(831, 664, 0, 0, 29), (3502, 3294, 0, 0, 0)]
    for resultado, esperado in zip(resultados, chaves_esperadas, strict=True):
        atual = (resultado["cnpjs_distintos"], resultado["nomes_distintos"],
                 resultado["cnpjs_nulos"], resultado["nomes_nulos"],
                 resultado["cnpjs_com_mais_de_um_nome"])
        if atual != esperado:
            raise ValueError(f"Chaves diferentes: {resultado['entidade']}: {atual}.")
    caminho = preparo / "validacao_chaves_kpis.csv"
    relatorio_chaves.to_csv(caminho, sep=";", encoding="utf-8", index=False)
    publicacoes.append((caminho, ANALISES / caminho.name))

    # 11. Calcular os seis KPIs no total e por ano com as mesmas fórmulas.
    # Não somar preços unitários nem usar média simples para o indicador geral.
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


    totais = resultados[0]
    if totais["valor_total_registrado"] != Decimal("78557477974.0877"):
        raise ValueError("Valor total diferente do esperado.")
    if totais["quantidade_total_itens_comprados"] != 57127143721:
        raise ValueError("Quantidade total diferente do esperado.")
    if totais["instituicoes_compradoras"] != 831 or totais["fornecedores"] != 3502:
        raise ValueError("Contagens distintas diferentes do esperado.")
    if totais["preco_unitario_medio_ponderado"].quantize(Decimal("0.0001")) != Decimal("1.3751"):
        raise ValueError("Preço ponderado diferente do esperado.")
    caminho = preparo / "resultados_kpis.csv"
    pd.DataFrame(resultados).to_csv(caminho, sep=";", encoding="utf-8", index=False)
    publicacoes.append((caminho, ANALISES / caminho.name))

    # 12. Repetir os rankings e a validação descritiva de 2025.
    # Concentração não comprova erro, sobrepreço ou irregularidade.
    ano = base.loc[base["ano_arquivo"].eq(2025)]
    if len(ano) != 26214:
        raise ValueError("Contagem de 2025 inesperada.")
    for campo in ("preco_total", "preco_unitario", "qtd_itens_comprados"):
        if ano[campo].isna().any():
            raise ValueError(f"Ausências impedem validar {campo}.")

    # 4. Usar Decimal para somar e multiplicar sem aproximações de ponto flutuante.
    # Valores altos serão descritos por sua participação, sem julgamento de validade.
    linhas = []
    resumos_terminal = []
    with localcontext() as contexto:
        contexto.prec = 60
        total = sum(ano["preco_total"], Decimal("0"))
        if total != Decimal("34930896708.4730"):
            raise ValueError("Total diferente do KPI anteriormente calculado.")
        divergencias = 0
        diferencas_nao_zero = 0
        maior_diferenca = Decimal("0")
        for quantidade, unitario, valor in zip(
            ano["qtd_itens_comprados"], ano["preco_unitario"], ano["preco_total"], strict=True
        ):
            diferenca = abs(valor - Decimal(quantidade) * unitario)
            maior_diferenca = max(maior_diferenca, diferenca)
            diferencas_nao_zero += int(diferenca != 0)
            divergencias += int(diferenca > Decimal("0.01"))

        # 5. Ordenar registros pelas três medidas para examinar valores e quantidades.
        # Cada lista tem dez linhas; as mesmas linhas podem aparecer em listas diferentes.
        for campo in ("preco_total", "preco_unitario", "qtd_itens_comprados"):
            maiores = ano.sort_values(campo, ascending=False, kind="stable").head(10)
            posicao = 0
            for indice, registro in maiores.iterrows():
                posicao += 1
                linha = registro.to_dict()
                linha.update({
                    "ano": 2025, "secao": "maiores_registros_" + campo,
                    "posicao": posicao, "registro_parquet_1_base": int(indice) + 1,
                    "criterio_ordenacao": campo, "valor_criterio": registro[campo],
                    "valor_total_grupo": registro["preco_total"], "registros_grupo": 1,
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
            for identificador, grupo in ano.groupby(chave, dropna=False, sort=False):
                valor_grupo = sum(grupo["preco_total"], Decimal("0"))
                nomes = list(grupo[nome].dropna().unique())
                grupos.append({
                    "ano": 2025, "secao": "maiores_" + secao,
                    "chave_agrupamento": chave, "identificador_grupo": identificador,
                    "nomes_observados_json": json.dumps(nomes, ensure_ascii=False),
                    "unidades_observadas_json": json.dumps(
                        list(grupo["unidade_fornecimento"].dropna().unique()), ensure_ascii=False
                    ),
                    "criterio_ordenacao": "soma(preco_total)",
                    "valor_criterio": valor_grupo, "valor_total_grupo": valor_grupo,
                    "registros_grupo": len(grupo),
                    "participacao_total_2025_pct": valor_grupo / total * 100,
                    "total_2025": total,
                    "observacao": "Agrupamento por identificador, sem padronizar nomes; nulos não excluídos.",
                })
            if sum(grupo["valor_total_grupo"] for grupo in grupos) != total:
                raise ValueError(f"Grupos de {secao} não reconciliam com o total.")
            grupos.sort(key=lambda grupo: grupo["valor_total_grupo"], reverse=True)
            for posicao, grupo in enumerate(grupos[:10], start=1):
                grupo["posicao"] = posicao
                linhas.append(grupo)
            resumos_terminal.append({
                "ranking": secao,
                "primeiros_tres": grupos[:3],
                "participacao_top10_pct": str(
                    sum(grupo["valor_total_grupo"] for grupo in grupos[:10]) / total * 100
                ),
            })

        # 7. Medir a concentração sem excluir os extremos da base.
        # O restante é apenas uma subtração diagnóstica, não uma nova base ou KPI tratado.
        maiores_totais = ano.sort_values("preco_total", ascending=False, kind="stable")
        maior = maiores_totais.iloc[0]["preco_total"]
        top10 = sum(maiores_totais.head(10)["preco_total"], Decimal("0"))
        medidas = {
            "registros_2025": len(ano),
            "total_2025": total,
            "valor_maior_registro": maior,
            "participacao_maior_registro_pct": maior / total * 100,
            "valor_top10_registros": top10,
            "participacao_top10_registros_pct": top10 / total * 100,
            "valor_restante_sem_maior_apenas_diagnostico": total - maior,
            "registros_reconciliados": len(ano),
            "divergencias_acima_tolerancia": divergencias,
            "diferencas_nao_zero": diferencas_nao_zero,
            "maior_diferenca_absoluta": maior_diferenca,
            "tolerancia_reais": Decimal("0.01"),
        }
        for medida, valor in medidas.items():
            linhas.append({
                "ano": 2025, "secao": "resumo_validacao", "medida": medida,
                "valor_medida": valor, "total_2025": total,
                "observacao": "Concentração não comprova erro, sobrepreço ou irregularidade.",
            })


    if medidas["divergencias_acima_tolerancia"] != 0 or medidas["diferencas_nao_zero"] != 0:
        raise ValueError("Consistência de 2025 diferente.")
    if medidas["participacao_maior_registro_pct"].quantize(Decimal("0.01")) != Decimal("65.32"):
        raise ValueError("Participação do maior registro diferente.")
    if medidas["participacao_top10_registros_pct"].quantize(Decimal("0.01")) != Decimal("79.75"):
        raise ValueError("Participação dos dez maiores diferente.")
    caminho = preparo / "validacao_pico_2025.csv"
    pd.DataFrame(linhas).to_csv(caminho, sep=";", encoding="utf-8", index=False)
    publicacoes.append((caminho, ANALISES / caminho.name))

    # 13. Comparar todas as saídas antes de substituir qualquer arquivo existente.
    # SHA-256 igual comprova igualdade byte a byte, além das comparações de valores.
    # Se qualquer resultado diferir, parar sem ajustar dados nem publicar saídas.
    comparados = 0
    for origem, destino in publicacoes:
        if destino.exists():
            if hash_arquivo(origem) != hash_arquivo(destino):
                raise ValueError(f"Resultado diferente do existente: {destino}. Nenhuma saída publicada.")
            comparados += 1
    for caminho, antes in protegidos.items():
        if hash_arquivo(caminho) != antes:
            raise ValueError(f"Arquivo protegido alterado: {caminho}.")

    # 14. Copiar somente as saídas validadas para seus destinos explícitos.
    # Não apagar arquivos existentes nem gravar em brutos, scripts ou README.
    for origem, destino in publicacoes:
        if not destino.resolve().is_relative_to(PROCESSADOS.resolve()) and not destino.resolve().is_relative_to(ANALISES.resolve()):
            raise ValueError(f"Destino fora do escopo: {destino}.")
        shutil.copyfile(origem, destino)
        if hash_arquivo(origem) != hash_arquivo(destino):
            raise ValueError(f"Falha de preservação na gravação: {destino}.")

# 15. Confirmar preservação e mostrar um resumo para apresentação.
# Os valores monetários só são arredondados na exibição, não no cálculo.
for caminho, antes in protegidos.items():
    if hash_arquivo(caminho) != antes:
        raise ValueError(f"Arquivo protegido alterado: {caminho}.")
print("\nRESUMO DO PIPELINE")
print(f"Registros antes: {total_antes:,}; duplicados removidos: {len(removidos)}.")
print(f"Registros finais: {len(base):,}; colunas: {len(base.columns)}.")
print(f"NAO_INFORMADO: {int(base['esfera'].eq('NAO_INFORMADO').sum())}; 2026 parcial: {int(base['ano_parcial'].sum())}.")
print("Inconsistências temporais preservadas: 12 (1 em 2023; 11 em 2024).")
for campo, valor in totais.items():
    print(f"{campo}: {valor}")
print(f"2025: total {medidas['total_2025']}; maior {medidas['participacao_maior_registro_pct']:.2f}%; top 10 {medidas['participacao_top10_registros_pct']:.2f}%.")
print(f"Todas as validações passaram. {comparados} saídas idênticas às existentes.")
print("Brutos, README e scripts 01 a 07 preservados por hash. Sem commit.")

