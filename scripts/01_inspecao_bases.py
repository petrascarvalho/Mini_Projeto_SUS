"""Sprint 1: inspeção diagnóstica dos CSVs do BPS, sem tratamento.

Execução, na raiz do projeto: py -3.14 scripts/01_inspecao_bases.py
Requisitos: Python global 3.14.4 e Pandas 3.0.2 (sem ambiente virtual).

CSV não armazena tipos nativos. Todos os campos são lidos como texto original;
os tipos relatados são hipóteses lexicais, nunca conversões das bases. Datas
são interpretadas somente em séries temporárias para calcular limites válidos.
Nulo significa campo CSV vazio (inclusive ""); espaços e marcadores como NA,
NULL e NaN são contados separadamente, sem substituição. Nenhuma linha é
eliminada, nem mesmo duplicadas ou linhas vazias. Registros com largura
inconsistente interrompem a inspeção, em vez de serem descartados.

Encoding é inferido por BOM e decodificação estrita de TODO o arquivo. Sem
BOM, compatibilidade não prova a codificação de origem; ambiguidades ficam
documentadas. O separador é detectado e a largura de cada registro é validada.
Somente os quatro relatórios de documentação são escritos/sobrescritos.
"""

from __future__ import annotations

import codecs
import csv
import hashlib
import io
import json
import re
import sys
from collections import Counter, defaultdict
from difflib import SequenceMatcher
from pathlib import Path

import pandas as pd


RAIZ = Path(__file__).resolve().parents[1]
SAIDA = RAIZ / "documentacao" / "analises"
ANOS = tuple(range(2020, 2027))
POLITICA_NULOS = "Campo CSV vazio; espacos e marcadores textuais preservados."
PERIODO_2026 = (
    "Base parcial. Periodo informado pelo solicitante: ate agosto de 2026. "
    "Parcialidade e caracteristica do periodo, nao erro. "
    "As datas observadas sao reportadas separadamente, sem presumir cobertura mensal."
)
FORMATOS_DATA = (
    (r"\d{1,2}/\d{1,2}/\d{4}", "%d/%m/%Y"),
    (r"\d{4}-\d{2}-\d{2}", "%Y-%m-%d"),
    (r"\d{1,2}/\d{1,2}/\d{4} \d{2}:\d{2}:\d{2}", "%d/%m/%Y %H:%M:%S"),
    (r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", "%Y-%m-%d %H:%M:%S"),
    (r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", "%Y-%m-%dT%H:%M:%S"),
)
INTEIRO = r"[+-]?\d+"
NUMERO = r"[+-]?(?:\d+(?:[.,]\d*)?|[.,]\d+)(?:[eE][+-]?\d+)?"


def texto_json(valor: object) -> str:
    return json.dumps(valor, ensure_ascii=False, separators=(",", ":"))


def sha256(caminho: Path) -> str:
    with caminho.open("rb") as arquivo:
        return hashlib.file_digest(arquivo, "sha256").hexdigest()


def detectar_encoding(conteudo: bytes) -> tuple[str, str, str]:
    """Retorna encoding, evidência e texto sem reparar bytes inválidos."""
    for marca, encoding in (
        (codecs.BOM_UTF32_LE, "utf-32"),
        (codecs.BOM_UTF32_BE, "utf-32"),
        (codecs.BOM_UTF8, "utf-8-sig"),
        (codecs.BOM_UTF16_LE, "utf-16"),
        (codecs.BOM_UTF16_BE, "utf-16"),
    ):
        if conteudo.startswith(marca):
            return encoding, "BOM identificado; arquivo inteiro decodificado estritamente.", conteudo.decode(encoding)
    try:
        texto = conteudo.decode("utf-8", errors="strict")
        evidencia = "Compativel com UTF-8; validacao estrita de todos os bytes, sem BOM."
        if conteudo.isascii():
            evidencia = "Apenas ASCII; UTF-8 adotado, mas codificacao de origem indeterminada."
        return "utf-8", evidencia, texto
    except UnicodeDecodeError:
        try:
            return "cp1252", "Inferencia ambigua: compativel com CP1252 e Latin-1; CP1252 adotado.", conteudo.decode("cp1252")
        except UnicodeDecodeError:
            return "latin-1", "Fallback Latin-1; compatibilidade de bytes nao confirma codificacao de origem.", conteudo.decode("latin-1")


def ler_base(caminho: Path) -> tuple[pd.DataFrame, dict]:
    conteudo = caminho.read_bytes()
    encoding, evidencia, texto = detectar_encoding(conteudo)
    # A amostra serve apenas ao separador. Encoding, largura, contagens e
    # diagnósticos são avaliados no arquivo inteiro, não em amostragem.
    try:
        separador = csv.Sniffer().sniff(texto[:65536], delimiters=";,\t|").delimiter
    except csv.Error:
        # Cabeçalho completo, respeitando campos entre aspas.
        possibilidades = []
        for candidato in ";,\t|":
            cab = next(csv.reader(io.StringIO(texto, newline=""), delimiter=candidato, strict=True), [])
            if len(cab) > 1:
                possibilidades.append((len(cab), candidato))
        possibilidades.sort(reverse=True)
        if not possibilidades or (len(possibilidades) > 1 and possibilidades[0][0] == possibilidades[1][0]):
            raise ValueError(f"Separador ambiguo em {caminho.name}; nenhuma linha foi descartada.")
        separador = possibilidades[0][1]
    leitor = csv.reader(io.StringIO(texto, newline=""), delimiter=separador, strict=True)
    cabecalho = next(leitor, None)
    if not cabecalho:
        raise ValueError(f"Arquivo sem cabecalho: {caminho}")
    registros = []
    linhas_vazias = 0
    for numero, registro in enumerate(leitor, start=1):
        if not registro:
            # Mantém a linha como registro vazio e documenta sua ocorrência.
            linhas_vazias += 1
            registro = [""] * len(cabecalho)
        elif len(registro) != len(cabecalho):
            raise ValueError(
                f"{caminho.name}: registro {numero}, linha fisica final {leitor.line_num}: "
                f"{len(registro)} campos; esperado {len(cabecalho)}. Inspecao interrompida."
            )
        registros.append(registro)
    # csv.reader preserva rótulos repetidos/vazios e valores textuais. O acesso
    # por posição abaixo evita renomeação automática de cabeçalhos duplicados.
    quadro = pd.DataFrame(registros, columns=cabecalho, dtype=object)
    metadados = {
        "arquivo": caminho.relative_to(RAIZ).as_posix(),
        "encoding": encoding, "evidencia_encoding": evidencia,
        "separador": separador, "linhas_fisicas_vazias": linhas_vazias,
        "sha256_csv": hashlib.sha256(conteudo).hexdigest(),
    }
    return quadro, metadados


def diagnosticar_datas(serie: pd.Series, nome: str) -> dict:
    preenchidos = serie[serie.ne("") & serie.notna()]
    padrao_data = "(?:" + "|".join(p for p, _ in FORMATOS_DATA) + ")"
    formatos = preenchidos.str.fullmatch(padrao_data, na=False)
    nome_indica = bool(re.search(r"(^|_)(data|date|dt)(_|$)", nome.casefold())) or nome.casefold() in {"compra", "insercao"}
    candidato = nome_indica or (len(preenchidos) > 0 and float(formatos.mean()) >= 0.8)
    resultado = {
        "possivel_campo_data": candidato, "datas_validas": 0,
        "valores_nao_vazios_invalidos_como_data": 0,
        "data_minima": "", "data_maxima": "", "formatos_data_validos": "[]",
    }
    if not candidato:
        return resultado
    limites_min, limites_max, usados = [], [], []
    for padrao, formato in FORMATOS_DATA:
        mascara = preenchidos.str.fullmatch(padrao, na=False)
        if not mascara.any():
            continue
        # Resultado temporário: nunca atribuído à série nem ao quadro original.
        datas = pd.to_datetime(preenchidos[mascara], format=formato, errors="coerce")
        validas = int(datas.notna().sum())
        resultado["datas_validas"] += validas
        if validas:
            limites_min.append(datas.min())
            limites_max.append(datas.max())
            usados.append(formato)
    resultado["valores_nao_vazios_invalidos_como_data"] = len(preenchidos) - resultado["datas_validas"]
    if limites_min:
        resultado["data_minima"] = min(limites_min).isoformat(sep=" ")
        resultado["data_maxima"] = max(limites_max).isoformat(sep=" ")
    resultado["formatos_data_validos"] = texto_json(usados)
    return resultado


def inferir_tipo(serie: pd.Series, datas: dict) -> str:
    valores = serie[serie.ne("") & serie.notna()]
    if valores.empty:
        return "indeterminado (sem valores)"
    if datas["datas_validas"] == len(valores):
        return "data"
    if datas["datas_validas"]:
        return "misto (data/texto)"
    inteiros = valores.str.fullmatch(INTEIRO, na=False)
    numericos = valores.str.fullmatch(NUMERO, na=False)
    if inteiros.all():
        return "inteiro"
    if numericos.all():
        return "decimal"
    if valores.isin(["True", "False", "true", "false"]).all():
        return "booleano"
    if numericos.any():
        return "misto (numero/texto)"
    return "texto"


def inspecionar_ano(ano: int) -> tuple[dict, list[dict]]:
    caminho = RAIZ / "dados" / "brutos" / str(ano) / f"{ano}.csv"
    print(f"[{ano}] Inspecionando {caminho.relative_to(RAIZ)}...", flush=True)
    quadro, meta = ler_base(caminho)
    detalhes = []
    for posicao, nome in enumerate(quadro.columns, start=1):
        serie = quadro.iloc[:, posicao - 1]
        nulos = int((serie.isna() | serie.eq("")).sum())
        datas = diagnosticar_datas(serie, nome)
        detalhes.append({
            "ano": ano, "posicao_coluna": posicao, "nome_coluna_original": nome,
            "tipo_inferido": inferir_tipo(serie, datas),
            "criterio_tipo": "Inferencia lexical em todos os valores nao vazios; sem conversao da base.",
            "dtype_leitura": str(serie.dtype), "quantidade_nulos": nulos,
            "percentual_nulos": round(100 * nulos / len(quadro), 4) if len(quadro) else "",
            "completamente_vazia": len(quadro) > 0 and nulos == len(quadro),
            "quantidade_apenas_espacos": int(serie.str.fullmatch(r"\s+", na=False).sum()),
            "marcadores_textuais_nao_convertidos": int(serie.isin(["NA", "N/A", "NULL", "null", "NaN", "nan", "None", "<NA>"]).sum()),
            "valores_inteiros_com_zero_inicial": int(serie.str.fullmatch(r"[+-]?0\d+", na=False).sum()),
            **datas,
        })
    campos_data = [d for d in detalhes if d["datas_validas"]]
    referencia = next((d for d in campos_data if d["nome_coluna_original"] == "compra"), campos_data[0] if campos_data else {})
    resumo = {
        "ano": ano, **meta, "numero_registros": len(quadro), "numero_colunas": len(quadro.columns),
        "nomes_colunas_originais": texto_json(list(quadro.columns)),
        "politica_nulos": POLITICA_NULOS,
        "quantidade_colunas_vazias": sum(d["completamente_vazia"] for d in detalhes),
        "colunas_completamente_vazias": texto_json([d["nome_coluna_original"] for d in detalhes if d["completamente_vazia"]]),
        "campos_data_validos": texto_json([d["nome_coluna_original"] for d in campos_data]),
        "campo_data_referencia": referencia.get("nome_coluna_original", ""),
        "data_minima": referencia.get("data_minima", ""), "data_maxima": referencia.get("data_maxima", ""),
        "limites_por_campo_data": texto_json([{k: d[k] for k in ("nome_coluna_original", "data_minima", "data_maxima", "datas_validas", "valores_nao_vazios_invalidos_como_data")} for d in detalhes if d["possivel_campo_data"]]),
        "periodo_parcial": ano == 2026,
        "observacao_periodo": PERIODO_2026 if ano == 2026 else "Limites observados nao comprovam completude de cobertura.",
    }
    if sha256(caminho) != meta["sha256_csv"]:
        raise RuntimeError(f"O arquivo mudou durante a inspecao: {caminho}")
    print(f"[{ano}] OK: {len(quadro):,} registros; {len(quadro.columns)} colunas; {meta['encoding']}; separador {meta['separador']!r}.", flush=True)
    return resumo, detalhes


def comparar(resumos: list[dict], detalhes: list[dict]) -> tuple[list[dict], list[dict], int]:
    cabecalhos = {r["ano"]: json.loads(r["nomes_colunas_originais"]) for r in resumos}
    uniao = sorted(set().union(*(set(c) for c in cabecalhos.values())))
    comuns = set.intersection(*(set(c) for c in cabecalhos.values()))
    matriz, discrepancias = [], []

    def registrar(categoria: str, anos: object, coluna: str, descricao: str) -> None:
        discrepancias.append({"categoria": categoria, "anos": texto_json(anos), "coluna": coluna, "descricao": descricao})

    for nome in uniao:
        presentes = [a for a in ANOS if nome in cabecalhos[a]]
        matriz.append({"nome_coluna_original": nome, **{str(a): nome in cabecalhos[a] for a in ANOS}, "quantidade_anos_presente": len(presentes), "comum_a_todos": nome in comuns})
        if len(presentes) != len(ANOS):
            registrar("coluna_presente_em_alguns_anos", presentes, nome, f"Ausente nos anos {sorted(set(ANOS) - set(presentes))}.")
    for anterior, atual in zip(ANOS, ANOS[1:]):
        antes, depois = cabecalhos[anterior], cabecalhos[atual]
        if len(antes) != len(depois):
            registrar("quantidade_colunas", [anterior, atual], "", f"{len(antes)} -> {len(depois)} colunas.")
        if set(antes) == set(depois) and antes != depois:
            registrar("ordem_ou_multiplicidade_colunas", [anterior, atual], "", "Nomes iguais como conjunto, mas ordem ou repeticoes diferentes.")
        retiradas, adicionadas = set(antes) - set(depois), set(depois) - set(antes)
        for retirada in sorted(retiradas):
            for adicionada in sorted(adicionadas):
                if SequenceMatcher(None, retirada.casefold(), adicionada.casefold()).ratio() >= 0.8:
                    registrar("possivel_variacao_nome", [anterior, atual], retirada, f"Nome semelhante adicionado: {adicionada!r}; hipotese, sem renomeacao ou equivalencia confirmada.")
    por_nome = defaultdict(list)
    for detalhe in detalhes:
        por_nome[detalhe["nome_coluna_original"]].append(detalhe)
        if detalhe["completamente_vazia"]:
            registrar("coluna_completamente_vazia", [detalhe["ano"]], detalhe["nome_coluna_original"], "Todos os campos vazios; coluna preservada.")
        if detalhe["valores_nao_vazios_invalidos_como_data"]:
            registrar("campo_data_com_valores_nao_interpretados", [detalhe["ano"]], detalhe["nome_coluna_original"], f"{detalhe['valores_nao_vazios_invalidos_como_data']} valores nao interpretados nos formatos suportados; conteudo preservado.")
    for nome, itens in por_nome.items():
        tipos = {d["tipo_inferido"] for d in itens}
        if len(tipos) > 1:
            evidencia = [{"ano": d["ano"], "posicao": d["posicao_coluna"], "tipo": d["tipo_inferido"]} for d in itens]
            registrar("diferenca_tipo_inferido", sorted({d["ano"] for d in itens}), nome, texto_json(evidencia))
    for ano, nomes in cabecalhos.items():
        for nome, quantidade in Counter(nomes).items():
            if quantidade > 1 or nome == "":
                registrar("cabecalho_repetido_ou_vazio", [ano], nome, f"{quantidade} ocorrencias; nomes originais preservados por posicao.")
    for atributo in ("encoding", "separador"):
        if len({r[atributo] for r in resumos}) > 1:
            registrar(f"diferenca_{atributo}", ANOS, "", texto_json({r["ano"]: r[atributo] for r in resumos}))
    for resumo in resumos:
        if resumo["linhas_fisicas_vazias"]:
            registrar("linhas_fisicas_vazias", [resumo["ano"]], "", f"{resumo['linhas_fisicas_vazias']} linhas vazias contabilizadas como registros vazios; nao descartadas.")
    if not discrepancias:
        registrar("sem_discrepancia_estrutural_detectada", ANOS, "", "Mesmos nomes, ordem, quantidade de colunas, tipos inferidos, encoding e separador nos sete anos.")
    registrar("caracteristica_periodo_parcial", [2026], "", PERIODO_2026)
    parcial = next(r for r in resumos if r["ano"] == 2026)
    registrar("cobertura_observada_2026", [2026], parcial["campo_data_referencia"], f"Datas observadas: {parcial['data_minima']} a {parcial['data_maxima']}. {parcial['limites_por_campo_data']} A referencia a agosto nao implica presenca de registros em todos os meses.")
    return matriz, discrepancias, len(comuns)


def gravar_relatorio(nome: str, linhas: list[dict]) -> None:
    # Estes são metadados diagnósticos; nenhum DataFrame das bases é exportado.
    with (SAIDA / nome).open("w", encoding="utf-8-sig", newline="") as arquivo:
        escritor = csv.DictWriter(arquivo, fieldnames=list(linhas[0]))
        escritor.writeheader()
        escritor.writerows(linhas)


def main() -> None:
    if sys.version_info[:3] != (3, 14, 4) or pd.__version__ != "3.0.2":
        raise RuntimeError(f"Requer Python 3.14.4 e Pandas 3.0.2; encontrados {sys.version.split()[0]} e {pd.__version__}.")
    if sys.prefix != sys.base_prefix:
        raise RuntimeError("Execute com Python global; ambientes virtuais nao sao permitidos.")
    print(f"Python {sys.version.split()[0]} | Pandas {pd.__version__} | raiz: {RAIZ}", flush=True)
    resumos, detalhes = [], []
    # Cada DataFrame anual sai de escopo ao terminar sua inspeção. Apenas os
    # metadados são reunidos; as bases nunca são concatenadas.
    for ano in ANOS:
        resumo, colunas = inspecionar_ano(ano)
        resumos.append(resumo)
        detalhes.extend(colunas)
    matriz, discrepancias, comuns = comparar(resumos, detalhes)
    for resumo in resumos:
        resumo["quantidade_colunas_comuns"] = comuns
        if sha256(RAIZ / resumo["arquivo"]) != resumo["sha256_csv"]:
            raise RuntimeError(f"CSV modificado durante a execucao: {resumo['arquivo']}")
    SAIDA.mkdir(parents=True, exist_ok=True)
    gravar_relatorio("resumo_bases.csv", resumos)
    gravar_relatorio("matriz_colunas_por_ano.csv", matriz)
    gravar_relatorio("discrepancias_estruturais.csv", discrepancias)
    gravar_relatorio("tipos_colunas_por_ano.csv", detalhes)
    print(f"\nConcluido: {comuns} colunas comuns; quatro relatorios em {SAIDA.relative_to(RAIZ)}.")
    print("SHA-256 dos CSVs conferidos antes e depois. Bases preservadas; nenhuma concatenacao.")
    print("2026: " + PERIODO_2026)


if __name__ == "__main__":
    main()
