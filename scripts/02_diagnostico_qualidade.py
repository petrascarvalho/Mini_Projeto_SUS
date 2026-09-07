"""Sprint 2: evidências de qualidade, sem tratamento ou concatenação.

Execução: py -3.14 scripts/02_diagnostico_qualidade.py
Requer Python global 3.14.4 e Pandas 3.0.2. Caminhos partem deste projeto.

Os campos CSV permanecem strings exatas em DataFrames anuais independentes.
Nulos são campos vazios, inclusive campos entre aspas sem conteúdo. Espaços
e marcadores literais (NA, NULL etc.) são diagnosticados separadamente, sem
serem substituídos. Nulos e strings vazias são a mesma contagem, não somáveis.
Uma linha física vazia é mantida como registro vazio e explicitamente contada.
Cabeçalhos repetidos e registros com largura irregular interrompem a leitura.

Duplicados exatos comparam todos os campos lidos, sem normalização, e contam
repetições além da primeira. Isso não prova duplicidade de transações reais.

Decimal e datas interpretadas existem SOMENTE como valores auxiliares para
testar conversibilidade, sinais, limites e a relação de preços. Não há
conversão/atribuição de tipos nas bases. Números canônicos aceitos: inteiros,
ponto decimal e notação científica, sem espaços, moeda ou agrupamento de
milhares. Outros formatos são identificados, mas não corrigidos/conversos.
Valores não canônicos não são declarados economicamente inválidos por isso.

Compatibilidade de preços: abs(total - quantidade * unitário) <= Decimal('0.01').
A tolerância é absoluta, inclusiva e aplicada ao valor do item, sem tolerância
relativa. Casos de arredondamento do preço unitário exigem investigação futura.
Zeros/negativos são sinalizados separadamente mesmo quando a relação confere.
Nulos/não conversíveis ficam como não avaliáveis; nunca como compatíveis.

Somente sete CSVs de diagnóstico são escritos em documentacao/analises.
Relatórios anteriores com esses sete nomes são substituídos em nova execução.
Dados brutos, README e demais documentos nunca são escritos por este script.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
import sys
from collections import Counter
from decimal import Decimal, localcontext
from pathlib import Path

import pandas as pd


RAIZ = Path(__file__).resolve().parents[1]
BRUTOS = RAIZ / "dados" / "brutos"
SAIDA = RAIZ / "documentacao" / "analises"
ANOS = range(2020, 2027)
NUMERICOS = ("capacidade", "qtd_itens_comprados", "preco_unitario", "preco_total")
DATAS = ("compra", "insercao")
ESPECIAIS = ("esfera", "tipo_compra", "modalidade_compra", "generico", "unidade_medida", "unidade_fornecimento", "unidade_fornecimento_capacidade")
IDENTIFICADORES = {"cnpj_instituicao", "cnpj_fornecedor", "cnpj_fabricante", "codigo_br", "anvisa"}
TOLERANCIA = Decimal("0.01")
MARCADORES = {"NA", "N/A", "NULL", "null", "NaN", "nan", "None", "<NA>"}
DOMINIOS = {
    "esfera": {"MUNICIPAL", "ESTADUAL", "FEDERAL"},
    "tipo_compra": {"ADMINISTRATIVA", "JUDICIAL"},
}
CANONICO = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?\Z")
PADRAO_DATA = r"[0-9]{2}/[0-9]{2}/[0-9]{4}"
NOMES_RELATORIOS = (
    "diagnostico_nulos", "diagnostico_duplicados", "diagnostico_numericos",
    "diagnostico_categoricos", "diagnostico_datas",
    "diagnostico_consistencia_preco_total", "resumo_qualidade_sprint2",
)


def texto_json(valor: object) -> str:
    return json.dumps(valor, ensure_ascii=False, separators=(",", ":"))


def percentual(quantidade_frequencia: int, total: int) -> float | str:
    return round(100 * quantidade_frequencia / total, 6) if total else ""


def hash_arquivo(caminho: Path) -> str:
    with caminho.open("rb") as origem:
        return hashlib.file_digest(origem, "sha256").hexdigest()


def exemplos(serie: pd.Series, mascara: pd.Series, limite: int = 8) -> str:
    registros_exemplo = []
    for indice in serie.index[mascara][:limite]:
        registros_exemplo.append({
            "registro": int(indice) + 1,
            "valor_original": serie.loc[indice],
        })
    return texto_json(registros_exemplo)


# Ler sem converter campos preserva identificadores e permite diagnosticar a escrita original.
def ler_base(caminho: Path) -> tuple[pd.DataFrame, int]:
    with caminho.open(encoding="utf-8", errors="strict", newline="") as arquivo:
        leitor = csv.reader(arquivo, delimiter=";", strict=True)
        cabecalho = next(leitor, None)
        if not cabecalho or len(set(cabecalho)) != len(cabecalho):
            raise ValueError(f"Cabeçalho ausente ou repetido em {caminho}; não renomear automaticamente.")
        faltantes = set(NUMERICOS + DATAS + ESPECIAIS + ("ano_compra",)) - set(cabecalho)
        if faltantes:
            raise ValueError(f"Campos obrigatórios ausentes em {caminho}: {sorted(faltantes)}")
        registros, linhas_vazias = [], 0
        for numero, registro in enumerate(leitor, start=1):
            if not registro:
                linhas_vazias += 1
                registro = [""] * len(cabecalho)
            elif len(registro) != len(cabecalho):
                raise ValueError(f"{caminho}: registro {numero} tem {len(registro)} campos, esperado {len(cabecalho)}; nada descartado.")
            registros.append(registro)
    return pd.DataFrame(registros, columns=cabecalho, dtype=object), linhas_vazias


def classificar_numero(valor: str) -> tuple[str, Decimal | None]:
    """Classifica o literal intacto; interpreta apenas o padrão canônico."""
    if valor == "":
        return "vazio", None
    if valor.isspace():
        return "apenas_espacos", None
    if valor != valor.strip():
        interno = classificar_numero(valor.strip())[0]
        return "espacos_nas_bordas/" + interno, None
    if CANONICO.fullmatch(valor):
        numero = Decimal(valor)
        if not numero.is_finite() or abs(numero.adjusted()) > 100:
            return "expoente_fora_limite_diagnostico", None
        if "e" in valor.lower():
            padrao = "notacao_cientifica"
        elif "." in valor:
            padrao = "decimal_ponto"
        else:
            padrao = "inteiro"
        return padrao, numero
    if re.search(r"R\$|US\$|BRL|USD|EUR|[$€£]", valor):
        return "simbolo_ou_codigo_monetario", None
    if re.fullmatch(r"[+-]?[0-9]{1,3}(?:\.[0-9]{3})+,[0-9]+", valor):
        return "milhar_ponto_decimal_virgula", None
    if re.fullmatch(r"[+-]?[0-9]{1,3}(?:,[0-9]{3})+\.[0-9]+", valor):
        return "milhar_virgula_decimal_ponto", None
    if re.fullmatch(r"[+-]?[0-9]+,[0-9]+", valor):
        return "virgula_decimal_ou_agrupamento_a_confirmar", None
    if re.fullmatch(r"[+-]?[0-9]{1,3}(?:[., ][0-9]{3})+", valor):
        return "agrupamento_milhar_a_confirmar", None
    if valor.lower() in {"nan", "inf", "+inf", "-inf", "infinity", "+infinity", "-infinity"}:
        return "literal_nao_finito", None
    if re.fullmatch(r"\([0-9., ]+\)", valor):
        return "parenteses_contabeis_a_confirmar", None
    return "nao_reconhecido", None


# Separar vazios, espaços e marcadores evita confundir ausência com texto válido.
def diagnosticar_nulos(quadro: pd.DataFrame, ano: int) -> list[dict]:
    linhas = []
    for campo in quadro:
        serie = quadro[campo]
        vazios = serie.eq("")
        espacos = serie.str.fullmatch(r"\s+", na=False)
        bordas = serie.ne(serie.str.strip())
        linhas.append({
            "ano": ano,
            "campo": campo,
            "registros": len(quadro),
            "quantidade_nulos": int(vazios.sum()),
            "percentual_nulos": percentual(int(vazios.sum()), len(quadro)),
            "strings_vazias": int(vazios.sum()),
            "strings_apenas_espacos": int(espacos.sum()),
            "espacos_antes": int(serie.str.match(r"\s", na=False).sum()),
            "espacos_depois": int(serie.str.contains(r"\s\Z", regex=True, na=False).sum()),
            "valores_com_espacos_nas_bordas": int(bordas.sum()),
            "textos_nao_vazios_com_espacos_nas_bordas": int((bordas & ~espacos).sum()),
            "marcadores_textuais_preservados": int(serie.isin(MARCADORES).sum()),
            "completamente_vazia": len(quadro) > 0 and bool(vazios.all()),
            "exemplos_espacos_json": exemplos(serie, bordas),
            "criterio": "Nulo = campo vazio; strings_vazias repete essa contagem. Espaços e marcadores literais não são nulos. Contagens de espaços nas bordas podem se sobrepor.",
        })
    return linhas


# Contar cópias excedentes e grupos repetidos sem remover linhas gera evidência para tratamento.
def diagnosticar_duplicados(quadro: pd.DataFrame, ano: int) -> dict:
    excedentes = quadro.duplicated(keep="first")
    todos = quadro.duplicated(keep=False)
    grupos = len(quadro.loc[todos].value_counts(dropna=False)) if todos.any() else 0
    return {
        "ano": ano,
        "registros": len(quadro),
        "duplicados_exatos_excedentes": int(excedentes.sum()),
        "percentual_duplicados_excedentes": percentual(int(excedentes.sum()), len(quadro)),
        "registros_em_grupos_duplicados": int(todos.sum()),
        "quantidade_grupos_duplicados": grupos,
        "exemplos_registros_excedentes_json": texto_json([int(indice) + 1 for indice in quadro.index[excedentes][:10]]),
        "criterio": "Igualdade de todos os campos CSV decodificados, sem normalizar; excedentes além da primeira ocorrência. Registro numerado a partir de 1 após o cabeçalho; nenhuma linha removida.",
    }


# Examinar formato, sinal e conversibilidade sem atribuir números à base mantém o diagnóstico separado.
def diagnosticar_numericos(quadro: pd.DataFrame, ano: int) -> tuple[list[dict], dict]:
    linhas, auxiliares = [], {}
    for campo in NUMERICOS:
        serie = quadro[campo]
        frequencias = serie.value_counts(dropna=False)
        # Interpretar cada escrita distinta uma vez evita repetir o mesmo diagnóstico.
        interpretacao = {}
        for valor in frequencias.index:
            interpretacao[valor] = classificar_numero(valor)
        # Guardar apenas números auxiliares; os campos originais continuam strings.
        auxiliares[campo] = []
        for valor in serie:
            auxiliares[campo].append(interpretacao[valor][1])
        padroes = Counter()
        negativos = zeros = positivos = conversiveis = fracionarios = 0
        validos = []
        for valor, frequencia in frequencias.items():
            padrao, numero = interpretacao[valor]
            quantidade_frequencia = int(frequencia)
            padroes[padrao] += quantidade_frequencia
            if numero is not None:
                conversiveis += quantidade_frequencia
                negativos += quantidade_frequencia if numero < 0 else 0
                zeros += quantidade_frequencia if numero == 0 else 0
                positivos += quantidade_frequencia if numero > 0 else 0
                fracionarios += quantidade_frequencia if numero != numero.to_integral_value() else 0
                validos.append(numero)
        # Marcar as linhas que precisam de investigação sem corrigir seus valores.
        lista_falhas = []
        lista_especiais = []
        for valor in serie:
            numero = interpretacao[valor][1]
            lista_falhas.append(valor != "" and numero is None)
            lista_especiais.append(numero is not None and numero <= 0)
        falhas = pd.Series(lista_falhas, index=serie.index)
        especiais = pd.Series(lista_especiais, index=serie.index)
        separadores = Counter()
        simbolos = Counter()
        for valor, frequencia in frequencias.items():
            quantidade_frequencia = int(frequencia)
            if "." in valor and "," in valor:
                separadores["ponto_e_virgula"] += quantidade_frequencia
            elif "," in valor:
                separadores["virgula"] += quantidade_frequencia
            elif "." in valor:
                separadores["ponto"] += quantidade_frequencia
            elif valor != "":
                separadores["sem_ponto_ou_virgula"] += quantidade_frequencia
            for simbolo in set(re.findall(r"R\$|US\$|BRL|USD|EUR|[$€£]", valor)):
                simbolos[simbolo] += quantidade_frequencia
        linhas.append({
            "ano": ano,
            "campo": campo,
            "registros": len(quadro),
            "nulos": int(serie.eq("").sum()),
            "valores_conversiveis_sem_tratamento": conversiveis,
            "valores_nao_vazios_nao_conversiveis": int(falhas.sum()),
            "percentual_nao_conversiveis_nao_vazios": percentual(int(falhas.sum()), int(serie.ne("").sum())),
            "negativos": negativos,
            "zeros": zeros,
            "positivos": positivos,
            "valores_fracionarios": fracionarios,
            "quantidades_fracionarias_a_investigar": fracionarios if campo == "qtd_itens_comprados" else 0,
            "minimo_auxiliar": str(min(validos)) if validos else "",
            "maximo_auxiliar": str(max(validos)) if validos else "",
            "padroes_observados_json": texto_json(dict(sorted(padroes.items()))),
            "pontuacao_observada_json": texto_json(dict(sorted(separadores.items()))),
            "simbolos_monetarios_json": texto_json(dict(simbolos)),
            "exemplos_nao_conversiveis_json": exemplos(serie, falhas),
            "exemplos_zero_ou_negativo_json": exemplos(serie, especiais),
            "criterio": "Inteiro/ponto decimal/científico sem moeda, espaços ou milhares: Decimal auxiliar. Vírgula e demais formatos são identificados, não corrigidos. Sinais e zeros requerem regra de negócio futura; literais originais preservados.",
        })
    return linhas, auxiliares


# Contar cada categoria e registrar variações documentais permite investigar sem padronizar.
def diagnosticar_categoricos(quadro: pd.DataFrame, ano: int) -> tuple[list[dict], list[dict]]:
    linhas, problemas = [], []
    campos = []
    for campo in quadro:
        if campo not in NUMERICOS + DATAS + ("ano_compra",):
            campos.append(campo)
    for campo in campos:
        contagem = quadro[campo].value_counts(dropna=False)
        fora = {}
        for valor, quantidade in contagem.items():
            dominio = DOMINIOS.get(campo)
            avaliacao = "não avaliado: domínio não fixado nesta etapa"
            if dominio is not None:
                if valor == "":
                    avaliacao = "vazio"
                elif valor in dominio:
                    avaliacao = "documentado"
                else:
                    avaliacao = "fora do domínio documental; investigar"
                if valor != "" and valor not in dominio:
                    fora[valor] = int(quantidade)
            linhas.append({
                "ano": ano,
                "campo": campo,
                "valor_original": valor,
                "quantidade": int(quantidade),
                "percentual_registros": percentual(int(quantidade), len(quadro)),
                "quantidade_valores_distintos_coluna": len(contagem),
                "tipo_semantico": "identificador nominal" if campo in IDENTIFICADORES else "categoria ou descrição textual",
                "campo_prioritario": campo in ESPECIAIS,
                "string_vazia": valor == "",
                "apenas_espacos": bool(valor) and valor.isspace(),
                "espacos_nas_bordas": valor != valor.strip(),
                "avaliacao_dominio": avaliacao,
            })
        if fora:
            problemas.append({
                "campo": campo,
                "valores_fora_dominio": fora,
            })
        if campo in {"unidade_medida", "unidade_fornecimento"}:
            # Detecta somente a coexistência literal de X e X+S. Não transforma
            # valores nem presume equivalência semântica entre as categorias.
            pares = []
            for valor in sorted(contagem.index):
                if valor and valor + "S" in contagem.index:
                    pares.append({
                        "valor_1": valor,
                        "quantidade_1": int(contagem[valor]),
                        "valor_2": valor + "S",
                        "quantidade_2": int(contagem[valor + "S"]),
                    })
            if pares:
                problemas.append({
                    "campo": campo,
                    "variacao_textual_singular_plural_a_confirmar": pares,
                })
        bordas = {}
        for valor, quantidade in contagem.items():
            if valor != valor.strip():
                bordas[valor] = int(quantidade)
        if bordas:
            problemas.append({
                "campo": campo,
                "ocorrencias_com_espacos_nas_bordas": sum(bordas.values()),
                "distintos_com_espacos": len(bordas),
            })
    return linhas, problemas


# Conferir formato e calendário em séries auxiliares mantém as datas originais intactas.
def diagnosticar_datas(quadro: pd.DataFrame, ano: int) -> tuple[list[dict], int, int]:
    linhas, invalidos_total = [], 0
    for campo in DATAS:
        serie = quadro[campo]
        formato = serie.str.fullmatch(PADRAO_DATA, na=False)
        # Série auxiliar separada, nenhuma atribuição às bases.
        datas = pd.to_datetime(serie.where(formato), format="%d/%m/%Y", errors="coerce")
        invalidos = serie.ne("") & datas.isna()
        invalidos_total += int(invalidos.sum())
        linhas.append({
            "ano": ano,
            "campo": campo,
            "registros": len(quadro),
            "nulos": int(serie.eq("").sum()),
            "valores_validos": int(datas.notna().sum()),
            "valores_invalidos_nao_vazios": int(invalidos.sum()),
            "formato_invalido_nao_vazio": int((serie.ne("") & ~formato).sum()),
            "calendario_invalido": int((formato & datas.isna()).sum()),
            "data_minima": datas.min().strftime("%Y-%m-%d") if datas.notna().any() else "",
            "data_maxima": datas.max().strftime("%Y-%m-%d") if datas.notna().any() else "",
            "ano_diferente_arquivo": int((datas.notna() & datas.dt.year.ne(ano)).sum()),
            "inconsistencias_ano_compra": "",
            "exemplos_invalidos_json": exemplos(serie, invalidos),
            "criterio": "DD/MM/AAAA e calendário válido; comparação auxiliar. Ano de inserção diferente do arquivo não é, por si só, erro. 2026 é parcial; sem presumir cobertura até agosto.",
        })
    serie = quadro["ano_compra"]
    formato = serie.str.fullmatch(r"[0-9]{4}", na=False)
    inconsistentes = serie.ne(str(ano))
    linhas.append({
        "ano": ano,
        "campo": "ano_compra",
        "registros": len(quadro),
        "nulos": int(serie.eq("").sum()),
        "valores_validos": int(formato.sum()),
        "valores_invalidos_nao_vazios": int((serie.ne("") & ~formato).sum()),
        "formato_invalido_nao_vazio": int((serie.ne("") & ~formato).sum()),
        "calendario_invalido": "",
        "data_minima": "",
        "data_maxima": "",
        "ano_diferente_arquivo": int((formato & inconsistentes).sum()),
        "inconsistencias_ano_compra": int(inconsistentes.sum()),
        "exemplos_invalidos_json": exemplos(serie, inconsistentes),
        "criterio": "Ano literal de quatro dígitos; inconsistência = valor diferente do ano do arquivo, incluindo vazios ou formato inadequado. Não é data completa.",
    })
    return linhas, invalidos_total, int(inconsistentes.sum())


def verificar_preco(quantidade: Decimal, unitario: Decimal, total: Decimal) -> tuple[Decimal, Decimal, bool]:
    # Precisão suficiente para o produto e a subtração, inclusive escala decimal.
    numeros = (quantidade, unitario, total)
    digitos_necessarios = 0
    for numero in numeros:
        representacao = numero.as_tuple()
        digitos_necessarios += len(representacao.digits) + abs(representacao.exponent)
    precisao = max(80, digitos_necessarios + 10)
    with localcontext() as contexto:
        contexto.prec = precisao
        esperado = quantidade * unitario
        diferenca = abs(total - esperado)
        return esperado, diferenca, diferenca <= TOLERANCIA


# Comparar o total ao produto de quantidade e preço distingue divergências de casos não avaliáveis.
def diagnosticar_consistencia(quadro: pd.DataFrame, ano: int, auxiliares: dict) -> tuple[list[dict], dict]:
    campos = ("qtd_itens_comprados", "preco_unitario", "preco_total")
    avaliaveis = compativeis = divergencias = nao_avaliaveis = 0
    maior_diferenca = Decimal(0)
    detalhes = []
    for indice, (quantidade, unitario, total) in enumerate(zip(
        auxiliares["qtd_itens_comprados"],
        auxiliares["preco_unitario"],
        auxiliares["preco_total"],
        strict=True,
    )):
        motivo, esperado, diferenca = "", "", ""
        if quantidade is None or unitario is None or total is None:
            nao_avaliaveis += 1
            motivo = "não avaliável: campo vazio ou formato não canônico"
            situacao = "nao_avaliavel"
        else:
            avaliaveis += 1
            esperado, diferenca, confere = verificar_preco(quantidade, unitario, total)
            maior_diferenca = max(maior_diferenca, diferenca)
            if confere:
                compativeis += 1
                continue
            divergencias += 1
            situacao = "divergencia"
            motivo = "diferença absoluta superior à tolerância; investigar sem corrigir"
        valores_originais = {}
        for campo in campos:
            valores_originais[campo + "_original"] = quadro[campo].iat[indice]
        detalhes.append({
            "ano": ano,
            "tipo_registro": situacao,
            "registro": indice + 1,
            **valores_originais,
            "preco_total_esperado_auxiliar": str(esperado),
            "diferenca_absoluta_auxiliar": str(diferenca),
            "tolerancia_absoluta": str(TOLERANCIA),
            "motivo": motivo,
        })
    resumo = {
        "ano": ano,
        "tipo_registro": "resumo",
        "registros": len(quadro),
        "registros_avaliaveis": avaliaveis,
        "registros_compativeis": compativeis,
        "registros_divergentes": divergencias,
        "registros_nao_avaliaveis": nao_avaliaveis,
        "percentual_divergentes_avaliaveis": percentual(divergencias, avaliaveis),
        "maior_diferenca_absoluta": str(maior_diferenca) if avaliaveis else "",
        "tolerancia_absoluta": str(TOLERANCIA),
        "motivo": "|total - quantidade * unitário| <= 0.01, inclusive; Decimal auxiliar, sem tolerância relativa. Detalhes de todas as divergências e não avaliáveis seguem em linhas próprias. Não somar novamente as linhas-resumo.",
    }
    assert len(quadro) == avaliaveis + nao_avaliaveis and avaliaveis == compativeis + divergencias
    return [resumo, *detalhes], resumo


# Executar os diagnósticos de um ano e reunir apenas relatórios evita concatenar as bases.
def analisar_ano(ano: int, relatorios: dict) -> None:
    caminho = BRUTOS / str(ano) / f"{ano}.csv"
    print(f"[{ano}] Lendo {caminho.relative_to(RAIZ)} (UTF-8; separador ';')...", flush=True)
    quadro, linhas_vazias = ler_base(caminho)
    nulos = diagnosticar_nulos(quadro, ano)
    duplicados = diagnosticar_duplicados(quadro, ano)
    numericos, auxiliares = diagnosticar_numericos(quadro, ano)
    categorias, problemas_categoricos = diagnosticar_categoricos(quadro, ano)
    datas, datas_invalidas, ano_inconsistente = diagnosticar_datas(quadro, ano)
    precos, resumo_precos = diagnosticar_consistencia(quadro, ano, auxiliares)
    problemas_numericos = []
    for diagnostico in numericos:
        problema = {}
        for campo in ("campo", "valores_nao_vazios_nao_conversiveis", "negativos",
                      "zeros", "quantidades_fracionarias_a_investigar"):
            problema[campo] = diagnostico[campo]
        problemas_numericos.append(problema)
    resumo = {
        "ano": ano,
        "registros": len(quadro),
        "colunas": len(quadro.columns),
        "linhas_fisicas_vazias": linhas_vazias,
        "total_nulos": sum(diagnostico["quantidade_nulos"] for diagnostico in nulos),
        "total_strings_apenas_espacos": sum(diagnostico["strings_apenas_espacos"] for diagnostico in nulos),
        "total_valores_com_espacos_nas_bordas": sum(diagnostico["valores_com_espacos_nas_bordas"] for diagnostico in nulos),
        "duplicados_exatos_excedentes": duplicados["duplicados_exatos_excedentes"],
        "registros_em_grupos_duplicados": duplicados["registros_em_grupos_duplicados"],
        "inconsistencias_ano_compra": ano_inconsistente,
        "valores_invalidos_datas": datas_invalidas,
        "valores_nulos_datas": sum(diagnostico["nulos"] for diagnostico in datas if diagnostico["campo"] in DATAS),
        "problemas_numericos_json": texto_json(problemas_numericos),
        "discrepancias_categoricas_json": texto_json(problemas_categoricos),
        "esfera_literal_zero": int(quadro["esfera"].eq("0").sum()),
        "divergencias_preco_total": resumo_precos["registros_divergentes"],
        "preco_total_nao_avaliavel": resumo_precos["registros_nao_avaliaveis"],
        "tolerancia_preco_total": str(TOLERANCIA),
        "arquivo_origem": caminho.relative_to(RAIZ).as_posix(),
        "sha256_csv": hash_arquivo(caminho),
        "observacoes": "Nulos contam células vazias; não somar novamente strings_vazias. Bases permanecem textuais, sem correção ou concatenação. Tipos/datas/Decimal auxiliares apenas para diagnóstico." + (" 2026 é parcial; datas internas não presumidas até agosto." if ano == 2026 else ""),
    }
    for chave, valores in (
        ("diagnostico_nulos", nulos), ("diagnostico_duplicados", [duplicados]),
        ("diagnostico_numericos", numericos), ("diagnostico_categoricos", categorias),
        ("diagnostico_datas", datas), ("diagnostico_consistencia_preco_total", precos),
        ("resumo_qualidade_sprint2", [resumo]),
    ):
        relatorios[chave].extend(valores)
    print(f"[{ano}] OK: {len(quadro):,} registros; {resumo['total_nulos']:,} nulos; {resumo['duplicados_exatos_excedentes']:,} duplicados excedentes; {resumo['divergencias_preco_total']:,} divergências de preço.", flush=True)


def main() -> None:
    if sys.version_info[:3] != (3, 14, 4) or pd.__version__ != "3.0.2":
        raise RuntimeError(f"Requer Python 3.14.4/Pandas 3.0.2; encontrados {sys.version.split()[0]}/{pd.__version__}.")
    if sys.prefix != sys.base_prefix:
        raise RuntimeError("Ambiente virtual não permitido; utilize Python global.")
    print(f"Python {sys.version.split()[0]} | Pandas {pd.__version__} | diagnóstico sem tratamento", flush=True)
    entradas = []
    for ano in ANOS:
        entradas.append(BRUTOS / str(ano) / f"{ano}.csv")
    for entrada in entradas:
        if not entrada.is_file():
            raise FileNotFoundError(entrada)
    # Inclui ZIPs, CSVs e .gitkeep: nenhuma escrita dentro de dados/brutos.
    originais = {}
    for caminho in BRUTOS.rglob("*"):
        if caminho.is_file():
            originais[caminho] = hash_arquivo(caminho)
    readme_antes = hash_arquivo(RAIZ / "README.md")
    relatorios = {}
    for nome in NOMES_RELATORIOS:
        relatorios[nome] = []
    for ano in ANOS:
        analisar_ano(ano, relatorios)
    atuais = set()
    for caminho in BRUTOS.rglob("*"):
        if caminho.is_file():
            atuais.add(caminho)
    if atuais != set(originais):
        raise RuntimeError("Arquivos brutos mudaram durante o diagnóstico; relatórios não publicados.")
    for caminho, hash_antes in originais.items():
        if hash_arquivo(caminho) != hash_antes:
            raise RuntimeError("Arquivos brutos mudaram durante o diagnóstico; relatórios não publicados.")
    if hash_arquivo(RAIZ / "README.md") != readme_antes:
        raise RuntimeError("README mudou durante o diagnóstico.")
    SAIDA.mkdir(parents=True, exist_ok=True)
    for nome, linhas in relatorios.items():
        # Preservar a ordem de aparição dos campos mantém o formato dos relatórios.
        campos = []
        for linha in linhas:
            for campo in linha:
                if campo not in campos:
                    campos.append(campo)
        assert campos[0] == "ano"
        with (SAIDA / f"{nome}.csv").open("w", encoding="utf-8-sig", newline="") as arquivo:
            escritor = csv.DictWriter(arquivo, fieldnames=campos)
            escritor.writeheader()
            escritor.writerows(linhas)
        print(f"Relatório: {nome}.csv ({len(linhas):,} linhas de diagnóstico).", flush=True)
    print("Concluído. Arquivos brutos e README preservados por SHA-256. Nenhuma base tratada, concatenação ou commit.")


if __name__ == "__main__":
    main()
