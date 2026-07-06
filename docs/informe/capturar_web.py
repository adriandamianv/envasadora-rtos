"""Captura las pantallas del sistema para el informe (Playwright + Chromium headless).
Requiere el backend corriendo en localhost:5000 y, para el panel en vivo,
la simulación de Wokwi produciendo."""
from pathlib import Path
from playwright.sync_api import sync_playwright

BASE = "http://localhost:5000"
CAP = Path(__file__).parent / "capturas"
CAP.mkdir(exist_ok=True)

with sync_playwright() as p:
    nav = p.chromium.launch()
    pag = nav.new_page(viewport={"width": 1400, "height": 860})

    # 1. login
    pag.goto(f"{BASE}/login")
    pag.wait_for_timeout(700)
    pag.screenshot(path=str(CAP / "01_login.png"))

    # entrar como gerente (ve todos los módulos)
    pag.fill('input[name="usuario"]', "gerente")
    pag.fill('input[name="clave"]', "1234")
    pag.click('button[type="submit"]')
    pag.wait_for_load_state("networkidle")

    # 2. panel en vivo: esperar a que lleguen datos por Socket.IO
    pag.goto(BASE + "/")
    pag.wait_for_timeout(12000)
    pag.screenshot(path=str(CAP / "02_panel_vivo.png"), full_page=True)

    # 3. órdenes de producción
    pag.goto(f"{BASE}/ordenes/")
    pag.wait_for_timeout(900)
    pag.screenshot(path=str(CAP / "03_ordenes.png"), full_page=True)

    # 4. inventario
    pag.goto(f"{BASE}/inventario/")
    pag.wait_for_timeout(900)
    pag.screenshot(path=str(CAP / "04_inventario.png"), full_page=True)

    # 5. reportes
    pag.goto(f"{BASE}/reportes/")
    pag.wait_for_timeout(1200)
    pag.screenshot(path=str(CAP / "05_reportes.png"), full_page=True)

    nav.close()
    print("capturas listas en", CAP)
