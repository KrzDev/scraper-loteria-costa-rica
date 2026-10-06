import os
import re
import json
import unicodedata
from datetime import datetime, timezone, timedelta

import requests
from bs4 import BeautifulSoup


URL = "https://loteriascostarica.com/"

WHAPI_URL = "https://gate.whapi.cloud/messages/text"
ARCHIVO_ESTADO = "ultimo_envio.json"

# Canales de WhatsApp de los que se leen resultados.
# (el número conectado a Whapi debe seguir estos canales)
CANALES_ORIGEN = [
    
    "120363428516815284@newsletter",  # GRUPO MYS
]

# Cuántos mensajes recientes se piden a cada canal
MENSAJES_POR_CANAL = 20

# Solo se publican mensajes de canal de los últimos X minutos.
# Evita publicar sorteos viejos que ya estaban en el canal.
# (debe ser mayor que el intervalo del cron job + posibles retrasos)
MINUTOS_MAXIMOS = 45

# Costa Rica es UTC-6 (sin horario de verano)
TZ_CR = timezone(timedelta(hours=-6))


def obtener_pagina():
    """
    Descarga el HTML de la página.
    """

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/154.0.0.0 Safari/537.36"
        )
    }

    try:
        response = requests.get(
            URL,
            headers=headers,
            timeout=20
        )

        response.raise_for_status()

        return response.text

    except requests.RequestException as error:
        print(f"Error al acceder a la página: {error}")
        return None


def extraer_resultados(html):
    """
    Extrae:

    - Nombre del sorteo
    - Número(s) ganador(es)
    """

    soup = BeautifulSoup(html, "lxml")

    resultados = []

    # Buscar todos los encabezados que dicen "Resultados"
    bloques = soup.find_all(
        ["h1", "h2", "h3", "h4", "h5", "h6"],
        string=lambda texto:
            texto and texto.strip() == "Resultados"
    )

    for bloque in bloques:

        # --------------------------------------------------
        # Buscar el contenedor del sorteo
        # --------------------------------------------------

        contenedor = bloque

        # Subimos hasta encontrar un contenedor
        # que agrupe el nombre + resultados + fecha
        for _ in range(5):

            if contenedor.parent:
                contenedor = contenedor.parent

            elementos = contenedor.find_all(
                recursive=False
            )

            # Si tenemos suficientes elementos,
            # probablemente encontramos la tarjeta.
            if len(elementos) >= 3:
                break

        # --------------------------------------------------
        # Buscar el nombre del sorteo
        # --------------------------------------------------

        nombre = None

        # Buscar imágenes con alt que contengan
        # "Logo de ..."
        imagen = contenedor.find(
            "img",
            alt=True
        )

        if imagen:

            alt = imagen.get("alt", "").strip()

            if alt.lower().startswith("logo de"):

                nombre = alt[7:].strip()

        # Si no encontramos el nombre en el alt,
        # buscamos textos cercanos.
        if not nombre:

            textos = list(
                contenedor.stripped_strings
            )

            for texto in textos:

                if texto == "Resultados":
                    continue

                if texto.startswith("2026-"):
                    continue

                if texto.isdigit():
                    continue

                if len(texto) > 2:
                    nombre = texto
                    break

        # --------------------------------------------------
        # Buscar números ganadores
        # --------------------------------------------------

        numeros = []

        # Los resultados aparecen como botones
        botones = contenedor.find_all("button")

        for boton in botones:

            numero = boton.get_text(
                strip=True
            )

            if numero:

                # Aceptar números como:
                # 34
                # 76
                # 029
                # 733
                # BB / BR también pueden aparecer
                # como resultados especiales.

                if (
                    numero.isdigit()
                    or numero.upper() in ["BB", "BR"]
                ):

                    if numero not in numeros:
                        numeros.append(numero)

        # --------------------------------------------------
        # Si no encontramos botones, buscar elementos
        # con clases que puedan contener resultados.
        # --------------------------------------------------

        if not numeros:

            for elemento in contenedor.find_all(
                ["span", "div", "a"]
            ):

                texto = elemento.get_text(
                    strip=True
                )

                if (
                    texto.isdigit()
                    and len(texto) <= 3
                ):

                    if texto not in numeros:
                        numeros.append(texto)

        # --------------------------------------------------
        # Guardar únicamente si tenemos nombre y números
        # --------------------------------------------------

        if nombre and numeros:

            # Evitar duplicados
            ya_existe = False

            for resultado in resultados:

                if (
                    resultado["nombre"] == nombre
                    and
                    resultado["numeros"] == numeros
                ):
                    ya_existe = True
                    break

            if not ya_existe:

                resultados.append({
                    "nombre": nombre,
                    "numeros": numeros
                })

    return resultados


def mostrar_resultados(resultados):

    print()
    print("=" * 50)
    print("RESULTADOS DE LOTERÍAS")
    print("=" * 50)
    print()

    if not resultados:

        print("No se encontraron resultados.")
        return

    for resultado in resultados:

        nombre = resultado["nombre"]

        numeros = " - ".join(
            resultado["numeros"]
        )

        print(
            f"{nombre}: {numeros}"
        )

    print()


# ======================================================
# WhatsApp (Whapi.Cloud)
# ======================================================

DIAS = [
    "Lunes", "Martes", "Miércoles", "Jueves",
    "Viernes", "Sábado", "Domingo",
]

MESES = [
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "setiembre", "octubre", "noviembre", "diciembre",
]

SEPARADOR = "━━━━━━━━━━━━━━━"

# --------------------------------------------------
# Banderas y nombres especiales
# --------------------------------------------------
# Se evalúa en orden: la primera regla que coincida gana.
# Formato: (palabras_clave, bandera, nombre_alterno)
#   - palabras_clave: se buscan dentro del nombre del sorteo
#     (sin importar mayúsculas ni tildes).
#   - bandera: emoji que se agrega al final del nombre.
#   - nombre_alterno: si no es None, reemplaza el nombre completo.
#
# Si ningún sorteo coincide con una regla, NO se agrega bandera
# (BANDERA_POR_DEFECTO vacío).

BANDERA_POR_DEFECTO = ""

REGLAS_SORTEOS = [
    (("MONAZO",), "", "🐒🐒🐒"),
    (("NICA", "TRIPLETA"), "🇳🇮", None),
    (("HONDURAS",), "🇭🇳", None),
    (("SALVADOR",), "🇸🇻", None),
    (("PANAMA",), "🇵🇦", None),
    (("DOMI", "PRIMERA", "SUERTE", "REAL", "LEIDSA", "LOTEKA"), "🇩🇴", None),
    (("ANGUILA",), "🇦🇮", None),
    (("NEW YORK", "FLORIDA", "KING"), "🇺🇸", None),
    (("PAPA CALIENTE", "DIGITAL", "TICAS", "REVENTADO",
      "TIEMPOS", "NACIONAL", "POPULAR"), "🇨🇷", None),
]

# Resultados especiales de los Tiempos
EMOJIS_ESPECIALES = {
    "BR": "🔴",
    "BB": "⚪",
}


def normalizar(texto):
    """
    Mayúsculas y sin tildes, para comparar nombres.
    """

    texto = unicodedata.normalize("NFD", texto)
    texto = "".join(c for c in texto if unicodedata.category(c) != "Mn")

    return texto.upper().strip()


def nombre_con_bandera(nombre, bandera=None):
    """
    Devuelve el nombre del sorteo con su bandera al final.
    Ejemplo: "Nica 3pm" -> "NICA 3PM🇳🇮"

    Si el resultado viene de un canal, "bandera" es la que
    trae el mensaje original (tiene prioridad sobre las reglas,
    salvo en los nombres alternos como los Monazos).
    """

    clave = normalizar(nombre)       # para comparar (sin tildes)
    visible = nombre.strip().upper() # para mostrar (conserva Ñ y tildes)

    for palabras, bandera_regla, alterno in REGLAS_SORTEOS:

        if any(p in clave for p in palabras):

            if alterno:
                return f"{alterno}{bandera_regla}"

            return f"{visible}{bandera or bandera_regla}"

    return f"{visible}{bandera or BANDERA_POR_DEFECTO}"


def numero_a_emoji(numero):
    """
    Convierte "06" en 0️⃣6️⃣ (y BR/BB en 🔴/⚪).
    """

    especial = EMOJIS_ESPECIALES.get(numero.upper())

    if especial:
        return especial

    # Cada dígito + selector de variación + marco de tecla
    return "".join(
        f"{d}\ufe0f\u20e3" if d.isdigit() else d
        for d in numero
    )


def formatear_mensaje(resultados):
    """
    Arma el texto que se publica en el canal / grupo.
    """

    ahora = datetime.now(TZ_CR)

    dia = DIAS[ahora.weekday()]
    mes = MESES[ahora.month - 1]
    hora = ahora.strftime("%I:%M %p")

    lineas = [
        "🎰 *RESULTADOS DE LOTERÍAS* 🇨🇷",
        f"📅 {dia} {ahora.day} de {mes} de {ahora.year}",
        f"🕐 {hora}",
        SEPARADOR,
        "",
    ]

    for r in resultados:

        numeros = "".join(numero_a_emoji(n) for n in r["numeros"])

        # Los asteriscos ponen el nombre en negrita en WhatsApp
        lineas.append(
            f"*{nombre_con_bandera(r['nombre'], r.get('bandera'))}*"
        )
        lineas.append(numeros)
        lineas.append("")

    lineas.append(SEPARADOR)

    return "\n".join(lineas)


def enviar_whatsapp(mensaje):
    """
    Publica el mensaje en uno o varios destinos
    (canal @newsletter y/o grupo @g.us) usando Whapi.Cloud.

    WHAPI_CHANNEL_ID puede tener varios IDs separados por coma:
    120363XXXX@newsletter,120363YYYY@g.us
    """

    token = os.environ.get("WHAPI_TOKEN")
    destinos = os.environ.get("WHAPI_CHANNEL_ID", "")

    if not token or not destinos:
        print("Faltan WHAPI_TOKEN o WHAPI_CHANNEL_ID")
        return False

    algun_exito = False

    for destino in destinos.split(","):

        destino = destino.strip()

        if not destino:
            continue

        try:
            response = requests.post(
                WHAPI_URL,
                headers={"Authorization": f"Bearer {token}"},
                json={"to": destino, "body": mensaje},
                timeout=20,
            )

            response.raise_for_status()

            print(f"Mensaje enviado a {destino}")
            algun_exito = True

        except requests.RequestException as error:
            detalle = ""

            if getattr(error, "response", None) is not None:
                detalle = error.response.text

            print(f"Error al enviar a {destino}: {error} {detalle}")

    return algun_exito


# ======================================================
# Estado (para no publicar duplicados)
# ======================================================

def cargar_estado():
    try:
        with open(ARCHIVO_ESTADO, "r", encoding="utf-8") as f:
            return json.load(f)

    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def guardar_estado(estado):
    with open(ARCHIVO_ESTADO, "w", encoding="utf-8") as f:
        json.dump(estado, f, ensure_ascii=False, indent=2)


# ======================================================
# Lectura de canales de WhatsApp (origen)
# ======================================================

PATRON_BANDERA = re.compile(r"[\U0001F1E6-\U0001F1FF]{2}")
PATRON_DIGITO = re.compile(r"(\d)\ufe0f?\u20e3")
PATRON_HORA = re.compile(r"RESULTADOS\s*\*?\s*(\d{1,2}:\d{2}\s*[AaPp][Mm])")


def leer_canal(canal_id):
    """
    Devuelve los últimos mensajes de un canal de WhatsApp.
    """

    token = os.environ.get("WHAPI_TOKEN")

    if not token:
        return []

    try:
        response = requests.get(
            f"https://gate.whapi.cloud/newsletters/{canal_id}/messages",
            headers={"Authorization": f"Bearer {token}"},
            params={"count": MENSAJES_POR_CANAL},
            timeout=20,
        )

        response.raise_for_status()

        return response.json().get("messages", [])

    except (requests.RequestException, ValueError) as error:
        print(f"Error al leer el canal {canal_id}: {error}")
        return []


def es_reciente(mensaje):
    """
    True si el mensaje se publicó hace menos de MINUTOS_MAXIMOS
    y es del día de hoy (hora de Costa Rica).
    """

    marca = mensaje.get("timestamp")

    if not marca:
        return False

    publicado = datetime.fromtimestamp(marca, TZ_CR)
    ahora = datetime.now(TZ_CR)

    if publicado.date() != ahora.date():
        return False

    return (ahora - publicado) <= timedelta(minutes=MINUTOS_MAXIMOS)


def limpiar_numero_linea(texto):
    """
    Quita emojis de número, banderas y símbolos de formato
    para quedarse solo con el texto (el nombre del sorteo).
    """

    limpio = PATRON_DIGITO.sub("", texto)
    limpio = PATRON_BANDERA.sub("", limpio)

    for simbolo in ("🔴", "⚪", "\ufe0f", "*", "#"):
        limpio = limpio.replace(simbolo, "")

    return limpio.strip()


def parsear_formato_numeral(cuerpo):
    """
    Formato del canal RESULTADOS - INFO & MAS:

        🇨🇷 *TICA TARDE #* 3️⃣3️⃣

        *BOLITA* 🔴

        *RESULTADOS 4:30 PM*
    """

    linea = next((l for l in cuerpo.splitlines() if "#" in l), None)

    if not linea:
        return []

    izquierda, derecha = linea.split("#", 1)

    banderas = PATRON_BANDERA.findall(izquierda)
    bandera = banderas[0] if banderas else ""

    if bandera == "🇺🇲":
        bandera = "🇺🇸"

    nombre = limpiar_numero_linea(izquierda)
    digitos = "".join(PATRON_DIGITO.findall(derecha))

    if not nombre or not digitos:
        return []

    numeros = [digitos]

    # 🔴 = bola roja (BR), ⚪ = bola blanca (BB)
    if "🔴" in cuerpo:
        numeros.append("BR")

    if "⚪" in cuerpo:
        numeros.append("BB")

    coincidencia = PATRON_HORA.search(cuerpo)
    hora = coincidencia.group(1).upper() if coincidencia else ""

    return [{
        "nombre": nombre,
        "numeros": numeros,
        "bandera": bandera,
        "hora": hora,
    }]


def parsear_formato_libre(cuerpo):
    """
    Formatos del canal GRUPO MYS. Un mismo mensaje puede traer
    varios sorteos, con el número en la misma línea o en la siguiente:

        NICA 11AM 1️⃣7️⃣
        FECHA 7️⃣ NOVIEMBRE
        TRIPLETA 7️⃣0️⃣7️⃣

        Digital Día 🇨🇷
        3️⃣5️⃣⚪️

        King Lottery
        1️⃣3️⃣
    """

    resultados = []
    pendiente = None  # (nombre, bandera) esperando su número

    for linea in cuerpo.splitlines():

        texto = linea.strip()

        if not texto:
            continue

        # La línea "FECHA 7 NOVIEMBRE" no es un resultado
        if normalizar(texto).startswith("FECHA"):
            pendiente = None
            continue

        digitos = "".join(PATRON_DIGITO.findall(texto))

        banderas = PATRON_BANDERA.findall(texto)
        bandera = banderas[0] if banderas else ""

        if bandera == "🇺🇲":
            bandera = "🇺🇸"

        nombre = limpiar_numero_linea(texto)

        if not digitos:
            # Línea con solo el nombre: el número viene después
            pendiente = (nombre, bandera) if nombre else None
            continue

        if not nombre:
            if not pendiente:
                continue

            nombre, bandera_pendiente = pendiente
            bandera = bandera or bandera_pendiente

        pendiente = None

        numeros = [digitos]

        if "🔴" in texto:
            numeros.append("BR")

        if "⚪" in texto:
            numeros.append("BB")

        resultados.append({
            "nombre": nombre,
            "numeros": numeros,
            "bandera": bandera,
            "hora": "",
        })

    return resultados


def parsear_mensaje_canal(mensaje):
    """
    Devuelve la lista de sorteos que trae un mensaje de canal
    (vacía si es una imagen, un aviso u otro texto sin resultados).
    """

    if mensaje.get("type") != "text":
        return []

    cuerpo = mensaje.get("text", {}).get("body", "")

    if "#" in cuerpo:
        return parsear_formato_numeral(cuerpo)

    return parsear_formato_libre(cuerpo)


# Palabras que no identifican al sorteo (horarios, artículos)
PALABRAS_COMUNES = {
    "LA", "EL", "LOS", "LAS", "DE", "DEL", "DIA", "TARDE", "NOCHE",
    "MANANA", "MD", "MEDIODIA", "AM", "PM", "P", "M", "A",
}

# Nombres distintos para un mismo sorteo
ALIAS_SORTEOS = {
    "TICA": "DIGITAL",
    "TICAS": "DIGITAL",
}


def firma_sorteo(nombre):
    """
    Palabras que identifican un sorteo, sin horarios ni artículos.
    "Primera Noche" -> {"PRIMERA"}   "LA PRIMERA" -> {"PRIMERA"}
    """

    limpio = re.sub(r"[^A-Z0-9 ]", " ", normalizar(nombre))
    palabras = set()

    for palabra in limpio.split():

        # Descartar horas: 3PM, 11AM, 6, 4
        if re.fullmatch(r"\d+(AM|PM)?", palabra):
            continue

        if palabra in PALABRAS_COMUNES:
            continue

        palabras.add(ALIAS_SORTEOS.get(palabra, palabra))

    return palabras


def ya_publicado(estado, hoy, nombre, valor):
    """
    True si hoy ya se publicó el mismo sorteo con los mismos números,
    aunque venga de otra fuente (página web o canal) y el nombre
    esté escrito distinto ("Primera Noche" y "LA PRIMERA",
    "KING LOTTERY" y "KING LOTTERY NOCHE").
    """

    firma = firma_sorteo(nombre)
    valor_n = valor.replace("-", "")

    for clave, otro_valor in estado.items():

        if not clave.startswith(f"{hoy}|"):
            continue

        if otro_valor.replace("-", "") != valor_n:
            continue

        otra_firma = firma_sorteo(clave.split("|")[1])

        if firma & otra_firma:
            return True

    return False


def guardar_todo(estado, hoy, ids_procesados, ids_nuevos):
    """
    Guarda el estado: limpia días anteriores y limita la lista de IDs.
    """

    estado = {
        k: v for k, v in estado.items()
        if k.startswith(hoy)
    }

    estado["__ids__"] = (ids_procesados + ids_nuevos)[-300:]

    guardar_estado(estado)


def main():

    print()
    print("Consultando resultados...")
    print()

    estado = cargar_estado()
    hoy = datetime.now(TZ_CR).strftime("%Y-%m-%d")

    nuevos = []

    # --------------------------------------------------
    # 1) Página web
    # --------------------------------------------------

    html = obtener_pagina()

    if html is not None:

        resultados = extraer_resultados(html)

        mostrar_resultados(resultados)

        for r in resultados:

            clave = f"{hoy}|{r['nombre']}"
            valor = "-".join(r["numeros"])

            if estado.get(clave) == valor:
                continue

            # Ya publicado desde otra fuente (canal)
            if clave not in estado and ya_publicado(
                estado, hoy, r["nombre"], valor
            ):
                estado[clave] = valor
                continue

            nuevos.append(r)
            estado[clave] = valor

    # --------------------------------------------------
    # 2) Canales de WhatsApp
    # --------------------------------------------------

    ids_procesados = estado.get("__ids__", [])
    ids_nuevos = []

    for canal in CANALES_ORIGEN:

        for mensaje in leer_canal(canal):

            msg_id = mensaje.get("id")

            if not msg_id or msg_id in ids_procesados:
                continue

            ids_nuevos.append(msg_id)

            if not es_reciente(mensaje):
                continue

            for r in parsear_mensaje_canal(mensaje):

                clave = f"{hoy}|{r['nombre']}|{r['hora']}"
                valor = "-".join(r["numeros"])

                if ya_publicado(estado, hoy, r["nombre"], valor):
                    estado[clave] = valor
                    continue

                nuevos.append(r)
                estado[clave] = valor

    # --------------------------------------------------
    # 3) Publicar lo nuevo
    # --------------------------------------------------

    if not nuevos:
        print("No hay resultados nuevos.")
        return

    # Modo "solo registrar": marca todo lo que hay ahora como ya
    # publicado, SIN enviar nada. Úsalo la primera vez del día
    # (o al empezar) para no publicar sorteos viejos.
    solo_registrar = os.environ.get(
        "SOLO_REGISTRAR", ""
    ).strip().lower() in ("1", "true", "si", "sí")

    if solo_registrar:
        print(
            f"Modo solo registrar: {len(nuevos)} resultado(s) "
            "marcados como publicados, sin enviar."
        )
        guardar_todo(estado, hoy, ids_procesados, ids_nuevos)
        return

    if enviar_whatsapp(formatear_mensaje(nuevos)):

        # Solo se guarda el estado si el envío fue exitoso.
        guardar_todo(estado, hoy, ids_procesados, ids_nuevos)


if __name__ == "__main__":
    main()