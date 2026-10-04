import requests
from bs4 import BeautifulSoup


URL = "https://loteriascostarica.com/"


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
                #  BB / BR también pueden aparecer
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


def main():

    print()
    print("Consultando resultados...")
    print()

    html = obtener_pagina()

    if html is None:
        return

    resultados = extraer_resultados(html)

    mostrar_resultados(resultados)


if __name__ == "__main__":
    main()
