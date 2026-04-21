import os
import sqlite3
import datetime
import asyncio
import httpx
import logging
from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

# --- SELECTORES ACTUALIZADOS 2024 ---
# Max/Tecnofacil: .item.product.product-item
# Pacifiko: .product-block o .product-details
# Walmart/Elektra (VTEX): .vtex-search-result-3-x-galleryItem

async def buscar_max_tecnofacil(client, producto, tienda, url_base):
    url = f"{url_base}/catalogsearch/result/?q={producto}"
    try:
        # Añadimos un referer para que no nos bloqueen
        resp = await client.get(url, timeout=15.0, headers={"Referer": url_base})
        soup = BeautifulSoup(resp.text, 'html.parser')
        items = soup.select('li.item.product.product-item')[:5]
        res = []
        for i in items:
            n = i.select_one('a.product-item-link')
            p = i.select_one('span.price')
            img = i.select_one('img.product-image-photo')
            if n and p:
                res.append({
                    "tienda": tienda, 
                    "nombre": n.text.strip(), 
                    "precio": p.text.strip(), 
                    "link": n['href'], 
                    "imagen": img.get('src') or img.get('data-src') if img else ""
                })
        return res
    except Exception as e:
        logger.error(f"Error en {tienda}: {e}")
        return []

async def buscar_pacifiko(client, producto):
    url = f"https://www.pacifiko.com/busqueda?q={producto}"
    try:
        resp = await client.get(url, timeout=15.0)
        soup = BeautifulSoup(resp.text, 'html.parser')
        # Pacifiko cambió su estructura a product-details
        items = soup.select('.product-details, .product-block')[:5]
        res = []
        for i in items:
            n = i.select_one('h4, .name')
            p = i.select_one('.price')
            l = i.select_one('a')
            img = i.find_previous('img') or i.select_one('img')
            if n and p and l:
                res.append({
                    "tienda": "Pacifiko", 
                    "nombre": n.text.strip(), 
                    "precio": p.text.strip(), 
                    "link": "https://www.pacifiko.com" + l['href'] if not l['href'].startswith('http') else l['href'], 
                    "imagen": img.get('src') if img else ""
                })
        return res
    except Exception as e:
        logger.error(f"Error en Pacifiko: {e}")
        return []

async def scraper_vtex(browser, url, tienda, dominio):
    context = await browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    page = await context.new_page()
    res = []
    try:
        # Walmart GT funciona mejor con /busqueda?_query=
        await page.goto(url, wait_until="networkidle", timeout=30000)
        # Scroll suave para activar carga de imágenes
        await page.mouse.wheel(0, 500)
        await asyncio.sleep(2)
        
        # Intentamos varios selectores por si cambiaron
        items = await page.query_selector_all(".vtex-search-result-3-x-galleryItem, .vtex-product-summary-2-x-container")
        for item in items[:5]:
            n = await item.query_selector(".vtex-product-summary-2-x-productBrandText, .vtex-product-summary-2-x-brandName")
            p = await item.query_selector(".vtex-product-price-1-x-currencyInteger, .vtex-product-summary-2-x-currencyInteger")
            l = await item.query_selector("a")
            img = await item.query_selector("img")
            
            if n and p and l:
                href = await l.get_attribute("href")
                precio_val = await p.inner_text()
                res.append({
                    "tienda": tienda, 
                    "nombre": await n.inner_text(), 
                    "precio": f"Q{precio_val}",
                    "link": href if href.startswith('http') else f"https://www.{dominio}{href}",
                    "imagen": await img.get_attribute("src") if img else ""
                })
    except Exception as e:
        logger.error(f"Error en {tienda}: {e}")
    finally:
        await page.close()
        await context.close()
    return res

@app.get("/", response_class=HTMLResponse)
async def home():
    # ... (Mismo código HTML que tenías, no es necesario cambiarlo) ...
    # Asegúrate de que el fetch apunte a /buscar?q=
    return HTML_CONTENT # Usa el HTML que ya tienes funcionando

@app.get("/buscar")
async def api_buscar(q: str = Query(...)):
    q = q.lower().strip()
    
    async with httpx.AsyncClient(headers=HEADERS, follow_redirects=True) as client:
        # Buscamos en las que casi nunca fallan (Max y Pacifiko)
        t_fast = [
            buscar_max_tecnofacil(client, q, "Max", "https://www.max.com.gt"),
            buscar_max_tecnofacil(client, q, "Tecnofacil", "https://www.tecnofacil.com.gt"),
            buscar_pacifiko(client, q)
        ]
        r_fast = await asyncio.gather(*t_fast)

    r_slow = []
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True, args=["--no-sandbox"])
            # URLs de búsqueda corregidas
            t_slow = [
                scraper_vtex(browser, f"https://www.walmart.com.gt/busqueda?_query={q}", "Walmart", "walmart.com.gt"),
                scraper_vtex(browser, f"https://www.elektra.com.gt/{q}?_q={q}&map=ft", "Elektra", "elektra.com.gt")
            ]
            res_slow_list = await asyncio.gather(*t_slow)
            r_slow = [item for sublist in res_slow_list for item in sublist]
            await browser.close()
    except Exception as e:
        logger.error(f"Error Playwright: {e}")

    # Unimos todo. Si r_fast tiene algo, al menos verás esos resultados.
    final = [item for sublist in r_fast for item in sublist] + r_slow
    return final

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
