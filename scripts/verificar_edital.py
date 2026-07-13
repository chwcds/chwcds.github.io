#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Vigia Edital Centec
===================
Verifica diariamente se a Funec (Fundação de Ensino de Contagem) publicou
novo edital de processo seletivo de ESTUDANTES para cursos técnicos
SUBSEQUENTES (pós-médio) na unidade Centec — Análises Clínicas, Farmácia
e/ou Química — com ingresso a partir de 2026/2 ou 2027.

Grava o resultado em vigia-centec/status.json. Nunca lança exceção fatal:
falhas de rede geram status "ERRO" sem quebrar o workflow.
"""

import json
import re
import sys
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urljoin

import requests
import urllib3
from bs4 import BeautifulSoup

# America/Sao_Paulo (UTC-3, sem horário de verão desde 2019)
TZ_SAO_PAULO = timezone(timedelta(hours=-3))

ARQUIVO_STATUS = Path(__file__).resolve().parent.parent / "vigia-centec" / "status.json"

PORTAL_EDITAIS = "https://portal.contagem.mg.gov.br/portal/editais/3"

FONTES = [
    ("Portal de Editais de Contagem", PORTAL_EDITAIS),
    ("Estuda Contagem (Funec)", "https://ww2.contagem.mg.gov.br/estudacontagem/"),
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.5",
}
TIMEOUT = 30

# ---------------------------------------------------------------------------
# Termos (comparados sempre em minúsculas e sem acentos)

TERMOS_CENTEC = ["centec", "psefuneccentecposmed"]
TERMOS_CURSO = ["analises clinicas", "farmacia", "quimica"]
TERMOS_MODALIDADE = ["pos-medio", "pos medio", "posmedio", "subsequente"]
TERMOS_SELETIVO = ["processo seletivo", "selecao de estudantes", "inscricoes"]
TERMOS_PUBLICO = ["estudante", "aluno", "candidato"]

# Editais que NÃO interessam: servidores, instrutores, FIC/Pronatec, integrado
TERMOS_EXCLUSAO = [
    "instrutor",
    "professor",
    "docente",
    "servidor",
    "seletivo simplificado",
    "pronatec",
    "mulheres mil",
    "cursos fic",
    "curso fic",
    " fic ",
    "integrado",
    "concurso",
    "estagio",
    "mave",
    "mostra audiovisual",
    "pibic",
    "iniciacao cientifica",
    "obras literarias",
    "seguranca do trabalho",  # pós-médio de outra unidade (Inconfidentes)
    "inconfidentes",
]

# Edital antigo já encerrado (ingresso 2024) — nunca deve disparar alerta
MARCAS_EDITAL_ANTIGO = [
    "03/2023",
    "psefuneccentecposmed0323",
    "tecnicos 2024",
    "cursos tecnicos 2024",
]

ANO_MINIMO = 2026


def normalizar(texto: str) -> str:
    """minúsculas, sem acentos, espaços colapsados."""
    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", texto.lower()).strip()


def contem(texto_norm: str, termos) -> list:
    return [t for t in termos if t in texto_norm]


def anos_no_texto(texto: str) -> list:
    return sorted({int(a) for a in re.findall(r"\b(20\d{2})\b", texto)})


def avaliar_item(texto: str) -> dict | None:
    """Avalia o texto de um item (título + entorno). Retorna dict com os
    termos casados se o item indicar edital novo do Centec pós-médio,
    senão None."""
    norm = " " + normalizar(texto) + " "

    if contem(norm, MARCAS_EDITAL_ANTIGO):
        return None
    if contem(norm, TERMOS_EXCLUSAO):
        return None

    centec = contem(norm, TERMOS_CENTEC)
    cursos = contem(norm, TERMOS_CURSO)
    modalidade = contem(norm, TERMOS_MODALIDADE)
    seletivo = contem(norm, TERMOS_SELETIVO)
    publico = contem(norm, TERMOS_PUBLICO)

    # Precisa apontar para o Centec ou para os cursos-alvo...
    if not (centec or cursos):
        return None
    # ...e ser pós-médio/subsequente OU um processo seletivo de estudantes.
    if not (modalidade or (seletivo and publico) or (centec and seletivo)):
        return None

    # Só é edital NOVO se citar ano >= 2026.
    anos = anos_no_texto(texto)
    if not anos or max(anos) < ANO_MINIMO:
        return None

    return {
        "termos": sorted(set(centec + cursos + modalidade + seletivo + publico)),
        "anos": anos,
    }


def extrair_itens(html: str, url_base: str) -> list:
    """Extrai (texto, link) de cada bloco com link da página."""
    soup = BeautifulSoup(html, "html.parser")
    itens = []
    vistos = set()
    for a in soup.find_all("a", href=True):
        titulo = a.get_text(" ", strip=True)
        if len(titulo) < 12:
            continue
        bloco = a.find_parent(["article", "li", "tr", "div"]) or a
        texto = " ".join(bloco.stripped_strings)[:800]
        link = urljoin(url_base, a["href"])
        chave = (normalizar(titulo)[:120], link)
        if chave in vistos:
            continue
        vistos.add(chave)
        itens.append({"titulo": titulo, "texto": texto, "link": link})
    return itens


def verificar() -> dict:
    achados = []
    fontes_ok = []
    fontes_erro = []

    for nome, url in FONTES:
        try:
            resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
            resp.raise_for_status()
        except requests.exceptions.SSLError:
            # Certificado quebrado em site do governo: tenta sem verificação
            # (página pública, somente leitura).
            try:
                urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
                resp = requests.get(
                    url, headers=HEADERS, timeout=TIMEOUT, verify=False
                )
                resp.raise_for_status()
            except requests.RequestException as exc:
                fontes_erro.append(f"{nome}: {exc.__class__.__name__}")
                continue
        except requests.RequestException as exc:
            fontes_erro.append(f"{nome}: {exc.__class__.__name__}")
            continue

        fontes_ok.append(nome)
        for item in extrair_itens(resp.text, url):
            resultado = avaliar_item(item["titulo"] + " " + item["texto"])
            if resultado:
                achados.append(
                    {
                        "fonte": nome,
                        "titulo": item["titulo"],
                        "link": item["link"],
                        "termos": resultado["termos"],
                        "anos": resultado["anos"],
                    }
                )

    agora = datetime.now(TZ_SAO_PAULO).isoformat(timespec="seconds")

    if not fontes_ok:
        return {
            "status": "ERRO",
            "resumo": (
                "Falha ao acessar as fontes de verificação: "
                + "; ".join(fontes_erro)
                + ". Nova tentativa na próxima execução."
            ),
            "link": PORTAL_EDITAIS,
            "verificado_em": agora,
            "trechos_encontrados": [],
        }

    if achados:
        principal = achados[0]
        return {
            "status": "PUBLICADO",
            "resumo": (
                f"Possível novo edital encontrado: \"{principal['titulo']}\" "
                f"({principal['fonte']}). Termos: {', '.join(principal['termos'])}. "
                "Confira o link e confirme unidade Centec, modalidade subsequente "
                "(pós-médio) e ingresso 2026/2 ou 2027."
            ),
            "link": principal["link"],
            "verificado_em": agora,
            "trechos_encontrados": [
                f"[{a['fonte']}] {a['titulo']} — {a['link']}" for a in achados[:10]
            ],
        }

    obs = ""
    if fontes_erro:
        obs = f" (fonte indisponível: {'; '.join(fontes_erro)})"
    return {
        "status": "NAO_PUBLICADO",
        "resumo": (
            "Nenhum edital novo (2026+) de processo seletivo de estudantes para "
            "cursos técnicos subsequentes (pós-médio) no Centec — Análises "
            "Clínicas, Farmácia ou Química. Fontes verificadas: "
            + ", ".join(fontes_ok)
            + "."
            + obs
        ),
        "link": PORTAL_EDITAIS,
        "verificado_em": agora,
        "trechos_encontrados": [],
    }


def main() -> int:
    try:
        resultado = verificar()
    except Exception as exc:  # nunca quebrar o workflow
        resultado = {
            "status": "ERRO",
            "resumo": f"Erro inesperado na verificação: {exc.__class__.__name__}: {exc}",
            "link": PORTAL_EDITAIS,
            "verificado_em": datetime.now(TZ_SAO_PAULO).isoformat(timespec="seconds"),
            "trechos_encontrados": [],
        }

    ARQUIVO_STATUS.parent.mkdir(parents=True, exist_ok=True)
    ARQUIVO_STATUS.write_text(
        json.dumps(resultado, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"[vigia-centec] {resultado['status']} — {resultado['resumo']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
