import os
import json
import unicodedata
from datetime import datetime, timezone, timedelta

import requests
from bs4 import BeautifulSoup


URL = "https://loteriascostarica.com/"

WHAPI_URL = "https://gate.whapi.cloud/messages/text"
ARCHIVO_ESTADO = "ultimo_envio.json"

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
# Si ningún sorteo coincide, se usa BANDERA_POR_DEFECTO.

BANDERA_POR_DEFECTO = "🇨🇷"

REGLAS_SORTEOS = [
    (("MONAZO",), "", "🐒🐒🐒"),
    (("NICA", "TRIPLETA"), "🇳🇮", None),
    (("HONDURAS",), "🇭🇳", None),
    (("SALVADOR",), "🇸🇻", None),
    (("PANAMA",), "🇵🇦", None),
    (("LEIDSA", "LOTEKA", "DOMINICAN"), "🇩🇴", None),
    (("NEW YORK", "FLORIDA"), "🇺🇸", None),
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


def nombre_con_bandera(nombre):
    """
    Devuelve el nombre del sorteo con su bandera al final.
    Ejemplo: "Nica 3pm" -> "NICA 3PM🇳🇮"
    """

    clave = normalizar(nombre)

    for palabras, bandera, alterno in REGLAS_SORTEOS:

        if any(p in clave for p in palabras):

            texto = alterno if alterno else clave
            return f"{texto}{bandera}"

    return f"{clave}{BANDERA_POR_DEFECTO}"


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
        lineas.append(f"*{nombre_con_bandera(r['nombre'])}*")
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


def main():

    print()
    print("Consultando resultados...")
    print()

    html = obtener_pagina()

    if html is None:
        return

    resultados = extraer_resultados(html)

    mostrar_resultados(resultados)

    if not resultados:
        print("Sin resultados, no se envía nada.")
        return

    # --------------------------------------------------
    # Deduplicación: solo enviar sorteos nuevos
    # o que cambiaron durante el día
    # --------------------------------------------------

    estado = cargar_estado()
    hoy = datetime.now(TZ_CR).strftime("%Y-%m-%d")

    nuevos = []

    for r in resultados:
        clave = f"{hoy}|{r['nombre']}"
        valor = "-".join(r["numeros"])

        if estado.get(clave) != valor:
            nuevos.append(r)
            estado[clave] = valor

    if not nuevos:
        print("No hay resultados nuevos.")
        return

    if enviar_whatsapp(formatear_mensaje(nuevos)):

        # Solo se guarda el estado si el envío fue exitoso.
        # Además se limpian días anteriores para que
        # el archivo no crezca.
        estado = {
            k: v for k, v in estado.items()
            if k.startswith(hoy)
        }

        guardar_estado(estado)


if __name__ == "__main__":
    main()