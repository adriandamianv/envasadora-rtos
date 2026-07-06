# -*- coding: utf-8 -*-
"""Genera Informe_Final.pdf con fpdf2 a partir de contenido.py.
Dos pasadas: la primera recoge las páginas de cada sección para armar el
índice; la segunda escribe el documento definitivo."""
from pathlib import Path

from fpdf import FPDF
from contenido import BLOQUES, INTEGRANTES, PORTADA

AQUI = Path(__file__).parent
FUENTES = Path("/usr/share/fonts/truetype/dejavu")


class InformePDF(FPDF):
    def __init__(self):
        super().__init__(format="A4")
        self.add_font("DejaVu", "", FUENTES / "DejaVuSans.ttf")
        self.add_font("DejaVu", "B", FUENTES / "DejaVuSans-Bold.ttf")
        self.add_font("DejaVu", "I", FUENTES / "DejaVuSans-Oblique.ttf")
        self.set_auto_page_break(True, margin=20)
        self.en_portada = True

    def multi_cell(self, w, h=None, text="", *args, **kwargs):
        # que el cursor siempre baje a la siguiente línea, pegado al margen
        kwargs.setdefault("new_x", "LMARGIN")
        kwargs.setdefault("new_y", "NEXT")
        return super().multi_cell(w, h, text, *args, **kwargs)

    def footer(self):
        if self.en_portada:
            return
        self.set_y(-15)
        self.set_font("DejaVu", "", 9)
        self.set_text_color(120)
        self.cell(0, 8, f"{self.page_no()}", align="C")
        self.set_text_color(0)


def portada(pdf: InformePDF):
    pdf.en_portada = True
    pdf.add_page()
    # logos: UG arriba a la izquierda, Facultad Industrial arriba a la derecha
    pdf.image(str(AQUI / PORTADA["logo_izq"]), x=15, y=12, w=34)
    pdf.image(str(AQUI / PORTADA["logo_der"]), x=210 - 15 - 27, y=12, w=27)
    pdf.set_y(48)
    pdf.set_font("DejaVu", "B", 15)
    pdf.multi_cell(0, 8, PORTADA["universidad"], align="C")
    pdf.set_font("DejaVu", "", 12)
    pdf.multi_cell(0, 7, PORTADA["carrera"], align="C")
    pdf.ln(16)
    pdf.set_font("DejaVu", "B", 16)
    pdf.multi_cell(0, 9, PORTADA["titulo"], align="C")
    pdf.ln(12)
    pdf.set_font("DejaVu", "", 12)
    pdf.multi_cell(0, 7, f"Materia: {PORTADA['materia']}", align="C")
    pdf.multi_cell(0, 7, f"Docente: {PORTADA['profesor']}", align="C")
    pdf.multi_cell(0, 7, PORTADA["periodo"], align="C")
    pdf.ln(14)
    pdf.set_font("DejaVu", "B", 12)
    etiqueta = "Integrante:" if len(INTEGRANTES) == 1 else "Integrantes:"
    pdf.multi_cell(0, 7, etiqueta, align="C")
    pdf.set_font("DejaVu", "", 12)
    for nombre in INTEGRANTES:
        pdf.multi_cell(0, 7, nombre, align="C")
    pdf.ln(14)
    pdf.multi_cell(0, 7, PORTADA["fecha"], align="C")


def indice(pdf: InformePDF, entradas):
    pdf.en_portada = False
    pdf.add_page()
    pdf.set_font("DejaVu", "B", 14)
    pdf.cell(0, 10, "Índice", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)
    for nivel, titulo, pagina in entradas:
        pdf.set_font("DejaVu", "B" if nivel == 1 else "", 11 if nivel == 1 else 10)
        sangria = 0 if nivel == 1 else 8
        pdf.set_x(pdf.l_margin + sangria)
        ancho_titulo = pdf.epw - sangria - 14
        pdf.cell(ancho_titulo, 7, titulo)
        pdf.cell(14, 7, str(pagina), align="R", new_x="LMARGIN", new_y="NEXT")


def cuerpo(pdf: InformePDF, entradas=None):
    """Escribe los bloques; si entradas es una lista, registra el TOC."""
    for bloque in BLOQUES:
        tipo = bloque[0]
        if tipo == "h1":
            pdf.add_page()
            if entradas is not None:
                entradas.append((1, bloque[1], pdf.page_no()))
            pdf.set_font("DejaVu", "B", 15)
            pdf.set_fill_color(240, 240, 238)
            pdf.multi_cell(0, 10, bloque[1], fill=True)
            pdf.ln(3)
        elif tipo == "h2":
            if pdf.get_y() > 250:
                pdf.add_page()
            if entradas is not None:
                entradas.append((2, bloque[1], pdf.page_no()))
            pdf.set_font("DejaVu", "B", 12)
            pdf.ln(2)
            pdf.multi_cell(0, 8, bloque[1])
            pdf.ln(1)
        elif tipo == "p":
            pdf.set_font("DejaVu", "", 10.5)
            pdf.multi_cell(0, 6, bloque[1])
            pdf.ln(2)
        elif tipo == "lista":
            pdf.set_font("DejaVu", "", 10.5)
            for item in bloque[1]:
                pdf.set_x(pdf.l_margin + 4)
                pdf.multi_cell(pdf.epw - 4, 6, f"•  {item}")
                pdf.ln(1)
            pdf.ln(1)
        elif tipo == "tabla":
            _, cab, filas = bloque
            pdf.set_font("DejaVu", "", 9)
            with pdf.table(
                borders_layout="SINGLE_TOP_LINE",
                text_align="LEFT",
                first_row_as_headings=True,
                line_height=5.5,
                padding=1.5,
            ) as tabla:
                fila_cab = tabla.row()
                for c in cab:
                    fila_cab.cell(c)
                for fila in filas:
                    r = tabla.row()
                    for celda in fila:
                        r.cell(celda)
            pdf.ln(3)
        elif tipo == "img":
            _, ruta, pie = bloque
            ancho = 165 if "lcd" not in ruta else 90
            if pdf.get_y() > 190:
                pdf.add_page()
            pdf.image(str(AQUI / ruta), w=ancho, x=(210 - ancho) / 2)
            pdf.set_font("DejaVu", "I", 9)
            pdf.set_text_color(90)
            pdf.multi_cell(0, 5, pie, align="C")
            pdf.set_text_color(0)
            pdf.ln(3)


def generar(entradas_toc=None):
    pdf = InformePDF()
    portada(pdf)
    if entradas_toc is None:
        pdf.en_portada = False
        pdf.add_page()  # página reservada para el índice (pasada 1)
        entradas = []
        cuerpo(pdf, entradas)
        return entradas
    indice(pdf, entradas_toc)
    cuerpo(pdf)
    return pdf


if __name__ == "__main__":
    entradas = generar()                 # pasada 1: medir páginas
    pdf = generar(entradas_toc=entradas)  # pasada 2: documento final
    salida = AQUI / "Informe_Final.pdf"
    pdf.output(str(salida))
    print(f"OK: {salida} ({salida.stat().st_size // 1024} KB, {pdf.page_no()} páginas)")
