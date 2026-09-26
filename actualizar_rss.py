import hashlib
import html
import json
import re
import sys
from datetime import datetime, timezone
from email.utils import format_datetime
from pathlib import Path
from urllib.parse import urljoin
import xml.etree.ElementTree as ET

import requests
from bs4 import BeautifulSoup, Tag


URL = "https://institutodeanalistas.com/lighthouse/informes/"
ARCHIVO_RSS = Path("feed.xml")
ARCHIVO_ESTADO = Path("estado.json")
MAXIMO_NOTICIAS = 500

MESES = {
    "01": 1,
    "02": 2,
    "03": 3,
    "04": 4,
    "05": 5,
    "06": 6,
    "07": 7,
    "08": 8,
    "09": 9,
    "10": 10,
    "11": 11,
    "12": 12,
}


def descargar_pagina():
    print("Descargando página de informes Lighthouse...", flush=True)

    cabeceras = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/136.0.0.0 Safari/537.36"
        ),
        "Accept": (
            "text/html,application/xhtml+xml,application/xml;"
            "q=0.9,image/avif,image/webp,*/*;q=0.8"
        ),
        "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    }

    respuesta = requests.get(
        URL,
        headers=cabeceras,
        timeout=60,
        allow_redirects=True,
    )

    respuesta.raise_for_status()

    if len(respuesta.text) < 1000:
        raise RuntimeError("La página descargada está vacía o incompleta.")

    print(
        f"Página descargada correctamente: {len(respuesta.text)} caracteres",
        flush=True,
    )

    return respuesta.text


def limpiar_texto(texto):
    if not texto:
        return ""

    texto = html.unescape(str(texto))
    texto = re.sub(r"\s+", " ", texto)
    return texto.strip(" \n\r\t-|")


def convertir_fecha(fecha_texto):
    coincidencia = re.search(
        r"(\d{1,2})[/-](\d{1,2})[/-](\d{4})",
        fecha_texto,
    )

    if not coincidencia:
        return datetime.now(timezone.utc)

    dia = int(coincidencia.group(1))
    mes = int(coincidencia.group(2))
    anio = int(coincidencia.group(3))

    try:
        return datetime(anio, mes, dia, 9, 0, tzinfo=timezone.utc)
    except ValueError:
        return datetime.now(timezone.utc)


def es_encabezado_valido(texto):
    texto_minusculas = texto.lower()

    descartados = (
        "informes lighthouse",
        "informes por compañías",
        "analisis fundamental",
        "análisis fundamental",
        "análisis de estados financieros",
        "sin proyecciones financieras",
        "con proyecciones financieras",
        "todos los informes",
        "compañías",
        "más información",
        "mas información",
        "la escuela",
    )

    if not texto:
        return False

    if len(texto) > 120:
        return False

    return not any(valor in texto_minusculas for valor in descartados)


def obtener_empresa(elemento_fecha):
    encabezados = ["h1", "h2", "h3", "h4", "h5", "h6"]

    anterior = elemento_fecha.find_previous(encabezados)

    while anterior:
        texto = limpiar_texto(anterior.get_text(" ", strip=True))

        if es_encabezado_valido(texto):
            return texto

        anterior = anterior.find_previous(encabezados)

    return "Lighthouse"


def obtener_contenedor(elemento_fecha):
    actual = elemento_fecha

    for _ in range(8):
        if actual is None:
            break

        if isinstance(actual, Tag):
            texto = limpiar_texto(actual.get_text(" ", strip=True))
            enlaces_pdf = actual.find_all(
                "a",
                href=re.compile(r"\.pdf(?:$|\?)", re.IGNORECASE),
            )

            contiene_fecha = bool(
                re.search(
                    r"(?:Fecha|Ficha)\s*:\s*\d{1,2}[/-]\d{1,2}[/-]\d{4}",
                    texto,
                    re.IGNORECASE,
                )
            )

            if contiene_fecha and enlaces_pdf and len(texto) <= 1500:
                return actual

        actual = actual.parent

    return elemento_fecha.parent


def obtener_enlaces_pdf(contenedor, elemento_fecha):
    enlaces = []

    if contenedor:
        candidatos = contenedor.find_all("a", href=True)
    else:
        candidatos = []

    for enlace in candidatos:
        href = enlace.get("href", "").strip()

        if ".pdf" not in href.lower():
            continue

        url_pdf = urljoin(URL, href)
        etiqueta = limpiar_texto(enlace.get_text(" ", strip=True))
        etiqueta_minusculas = etiqueta.lower()

        if "ingl" in etiqueta_minusculas or "/en/" in href.lower():
            idioma = "PDF en inglés"
        elif "españ" in etiqueta_minusculas or "espan" in etiqueta_minusculas:
            idioma = "PDF en español"
        else:
            idioma = "Descargar PDF"

        if not any(dato["url"] == url_pdf for dato in enlaces):
            enlaces.append(
                {
                    "idioma": idioma,
                    "url": url_pdf,
                }
            )

    if enlaces:
        return enlaces

    # Sistema alternativo: buscar los PDF posteriores a la fecha.
    siguiente = elemento_fecha

    for _ in range(30):
        siguiente = siguiente.find_next()

        if siguiente is None:
            break

        if not isinstance(siguiente, Tag):
            continue

        texto = limpiar_texto(siguiente.get_text(" ", strip=True))

        if re.search(
            r"(?:Fecha|Ficha)\s*:\s*\d{1,2}[/-]\d{1,2}[/-]\d{4}",
            texto,
            re.IGNORECASE,
        ):
            break

        if siguiente.name == "a" and siguiente.get("href"):
            href = siguiente.get("href", "").strip()

            if ".pdf" in href.lower():
                url_pdf = urljoin(URL, href)
                etiqueta = limpiar_texto(
                    siguiente.get_text(" ", strip=True)
                )
                etiqueta_minusculas = etiqueta.lower()

                if "ingl" in etiqueta_minusculas:
                    idioma = "PDF en inglés"
                elif "españ" in etiqueta_minusculas:
                    idioma = "PDF en español"
                else:
                    idioma = "Descargar PDF"

                if not any(dato["url"] == url_pdf for dato in enlaces):
                    enlaces.append(
                        {
                            "idioma": idioma,
                            "url": url_pdf,
                        }
                    )

    return enlaces


def obtener_asunto(texto_contenedor, fecha_texto, empresa):
    texto = limpiar_texto(texto_contenedor)

    texto = re.sub(
        r"(?:Fecha|Ficha)\s*:\s*"
        + re.escape(fecha_texto),
        " ",
        texto,
        flags=re.IGNORECASE,
    )

    texto = re.sub(
        r"N[ºo°]\s*de\s*p[aá]ginas?\s*:\s*\d+",
        " ",
        texto,
        flags=re.IGNORECASE,
    )

    texto = re.sub(
        r"PDF\s*:\s*(?:Español|Espanol|Inglés|Ingles|/|\s)+",
        " ",
        texto,
        flags=re.IGNORECASE,
    )

    texto = re.sub(
        re.escape(empresa),
        " ",
        texto,
        count=1,
        flags=re.IGNORECASE,
    )

    texto = limpiar_texto(texto)

    palabras_inutiles = (
        "Español",
        "Espanol",
        "Inglés",
        "Ingles",
        "Descargar",
        "PDF",
    )

    for palabra in palabras_inutiles:
        texto = re.sub(
            rf"\b{re.escape(palabra)}\b",
            " ",
            texto,
            flags=re.IGNORECASE,
        )

    texto = limpiar_texto(texto)

    if not texto:
        return "Nuevo informe Lighthouse"

    return texto[:300]


def extraer_informes(codigo_html):
    soup = BeautifulSoup(codigo_html, "html.parser")
    informes = []
    identificadores = set()

    patron_fecha = re.compile(
        r"(?:Fecha|Ficha)\s*:\s*"
        r"(\d{1,2}[/-]\d{1,2}[/-]\d{4})",
        re.IGNORECASE,
    )

    elementos_fecha = []

    for elemento in soup.find_all(["p", "div", "span", "li"]):
        texto = limpiar_texto(elemento.get_text(" ", strip=True))

        if patron_fecha.search(texto):
            # Evita procesar grandes contenedores que incluyen muchos informes.
            fechas_en_texto = patron_fecha.findall(texto)

            if len(fechas_en_texto) == 1 and len(texto) < 800:
                elementos_fecha.append(elemento)

    print(
        f"Bloques con fechas encontrados: {len(elementos_fecha)}",
        flush=True,
    )

    for elemento_fecha in elementos_fecha:
        texto_fecha = limpiar_texto(
            elemento_fecha.get_text(" ", strip=True)
        )
        coincidencia = patron_fecha.search(texto_fecha)

        if not coincidencia:
            continue

        fecha_texto = coincidencia.group(1)
        empresa = obtener_empresa(elemento_fecha)
        contenedor = obtener_contenedor(elemento_fecha)

        if contenedor:
            texto_contenedor = limpiar_texto(
                contenedor.get_text(" ", strip=True)
            )
        else:
            texto_contenedor = texto_fecha

        enlaces_pdf = obtener_enlaces_pdf(
            contenedor,
            elemento_fecha,
        )

        if not enlaces_pdf:
            continue

        asunto = obtener_asunto(
            texto_contenedor,
            fecha_texto,
            empresa,
        )

        paginas = ""

        coincidencia_paginas = re.search(
            r"N[ºo°]\s*de\s*p[aá]ginas?\s*:\s*(\d+)",
            texto_contenedor,
            re.IGNORECASE,
        )

        if coincidencia_paginas:
            paginas = coincidencia_paginas.group(1)

        url_principal = enlaces_pdf[0]["url"]

        clave = (
            empresa.lower(),
            fecha_texto,
            asunto.lower(),
            url_principal,
        )

        identificador = hashlib.sha256(
            "|".join(clave).encode("utf-8")
        ).hexdigest()

        if identificador in identificadores:
            continue

        identificadores.add(identificador)

        enlaces_html = []

        for enlace in enlaces_pdf:
            enlaces_html.append(
                f'<p><a href="{html.escape(enlace["url"])}">'
                f'{html.escape(enlace["idioma"])}</a></p>'
            )

        descripcion = (
            f"<p><strong>Empresa:</strong> "
            f"{html.escape(empresa)}</p>"
            f"<p><strong>Fecha:</strong> "
            f"{html.escape(fecha_texto)}</p>"
            f"<p><strong>Informe:</strong> "
            f"{html.escape(asunto)}</p>"
        )

        if paginas:
            descripcion += (
                f"<p><strong>Número de páginas:</strong> "
                f"{html.escape(paginas)}</p>"
            )

        descripcion += "".join(enlaces_html)

        titulo = f"{empresa}: {asunto}"

        informes.append(
            {
                "id": identificador,
                "titulo": titulo,
                "empresa": empresa,
                "asunto": asunto,
                "fecha": fecha_texto,
                "fecha_iso": convertir_fecha(fecha_texto).isoformat(),
                "paginas": paginas,
                "url": url_principal,
                "descripcion": descripcion,
            }
        )

    informes.sort(
        key=lambda dato: dato["fecha_iso"],
        reverse=True,
    )

    print(
        f"Informes Lighthouse extraídos: {len(informes)}",
        flush=True,
    )

    return informes


def cargar_estado():
    if not ARCHIVO_ESTADO.exists():
        return []

    try:
        contenido = json.loads(
            ARCHIVO_ESTADO.read_text(encoding="utf-8")
        )

        if isinstance(contenido, dict):
            contenido = contenido.get("informes", [])

        if isinstance(contenido, list):
            return contenido

    except Exception as error:
        print(
            f"No se pudo leer estado.json: {error}",
            flush=True,
        )

    return []


def combinar_informes(actuales, anteriores):
    resultado = []
    identificadores = set()

    for informe in actuales + anteriores:
        identificador = informe.get("id")

        if not identificador:
            continue

        if identificador in identificadores:
            continue

        identificadores.add(identificador)
        resultado.append(informe)

    resultado.sort(
        key=lambda dato: dato.get("fecha_iso", ""),
        reverse=True,
    )

    return resultado[:MAXIMO_NOTICIAS]


def guardar_estado(informes):
    contenido = {
        "actualizado": datetime.now(timezone.utc).isoformat(),
        "cantidad": len(informes),
        "informes": informes,
    }

    ARCHIVO_ESTADO.write_text(
        json.dumps(
            contenido,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def crear_rss(informes):
    ET.register_namespace(
        "atom",
        "http://www.w3.org/2005/Atom",
    )
    ET.register_namespace(
        "content",
        "http://purl.org/rss/1.0/modules/content/",
    )

    rss = ET.Element(
        "rss",
        {
            "version": "2.0",
            "xmlns:atom": "http://www.w3.org/2005/Atom",
            "xmlns:content": "http://purl.org/rss/1.0/modules/content/",
        },
    )

    canal = ET.SubElement(rss, "channel")

    ET.SubElement(canal, "title").text = (
        "Informes Lighthouse – Instituto Español de Analistas"
    )
    ET.SubElement(canal, "link").text = URL
    ET.SubElement(canal, "description").text = (
        "Nuevos informes de análisis publicados por Lighthouse."
    )
    ET.SubElement(canal, "language").text = "es-es"
    ET.SubElement(canal, "generator").text = (
        "GitHub Actions - plis2100"
    )
    ET.SubElement(canal, "lastBuildDate").text = format_datetime(
        datetime.now(timezone.utc)
    )
    ET.SubElement(canal, "ttl").text = "60"

    atom_link = ET.SubElement(
        canal,
        "{http://www.w3.org/2005/Atom}link",
    )
    atom_link.set(
        "href",
        "https://raw.githubusercontent.com/"
        "plis2100/rss-lighthouse-informes/main/feed.xml",
    )
    atom_link.set("rel", "self")
    atom_link.set("type", "application/rss+xml")

    for informe in informes:
        item = ET.SubElement(canal, "item")

        ET.SubElement(item, "title").text = informe["titulo"]
        ET.SubElement(item, "link").text = informe["url"]

        guid = ET.SubElement(item, "guid")
        guid.set("isPermaLink", "false")
        guid.text = informe["id"]

        fecha = datetime.fromisoformat(informe["fecha_iso"])

        if fecha.tzinfo is None:
            fecha = fecha.replace(tzinfo=timezone.utc)

        ET.SubElement(item, "pubDate").text = format_datetime(fecha)
        ET.SubElement(item, "description").text = informe[
            "descripcion"
        ]

        contenido = ET.SubElement(
            item,
            "{http://purl.org/rss/1.0/modules/content/}encoded",
        )
        contenido.text = informe["descripcion"]

    arbol = ET.ElementTree(rss)
    ET.indent(arbol, space="  ")

    arbol.write(
        ARCHIVO_RSS,
        encoding="utf-8",
        xml_declaration=True,
    )

    print(
        f"RSS creada correctamente con {len(informes)} informes.",
        flush=True,
    )


def main():
    try:
        codigo_html = descargar_pagina()
        informes_actuales = extraer_informes(codigo_html)

        if not informes_actuales:
            raise RuntimeError(
                "No se han encontrado informes Lighthouse. "
                "La estructura de la página puede haber cambiado."
            )

        informes_anteriores = cargar_estado()
        informes = combinar_informes(
            informes_actuales,
            informes_anteriores,
        )

        guardar_estado(informes)
        crear_rss(informes)

        print("Proceso terminado correctamente.", flush=True)
        print(
            "URL para Feedly: "
            "https://raw.githubusercontent.com/"
            "plis2100/rss-lighthouse-informes/main/feed.xml",
            flush=True,
        )

    except Exception as error:
        print(f"ERROR: {error}", file=sys.stderr, flush=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
