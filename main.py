import os
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

# Headers reales para evitar bloqueos en Max y Tecnofacil
REAL_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "es-ES,es;q=0.8,en-US;q=0.5,en;q=0.3",
    "Referer": "https://www.google.com/"
}

async def buscar_magento(client, producto, tienda, url_base):
    # Forzamos la URL sin barras finales y con parámetros limpios
    url = f"{url_base}/catalogsearch/result/?q={producto.replace(' ', '+')}"
    try:
        resp = await client.get(url, timeout=15.0, follow_redirects=True)
        if resp.status_code != 200:
            logger.warning(f"{tienda} devolvió status {resp.status_code}")
            return []
            
        soup = BeautifulSoup(resp.text, 'html.parser')
        # Selectores actualizados para Max/Tecnofacil 2024
        items = soup.select('ol.products.list.items.product-items li.item.product.product-item')
        if not items:
            items = soup.select('.product-item') # Selector de respaldo
            
        res = []
        for i in items[:5]:
            n = i.select_one('.product-item-link')
            p = i.select_one('.price')
            img = i.select_one('img')
            if n and p:
                res.append({
                    "tienda": tienda,
                    "nombre": n.get_text().strip(),
                    "precio": p.get_text().strip(),
                    "link": n['href'],
                    "imagen": img.get('src') or img.get('data-src') or ""
                })
        logger.info(f"{tienda} encontró {len(res)} productos")
        return res
    except Exception as e:
        logger.error(f"Error en {tienda}: {e}")
        return []

async def buscar_pacifiko(client, producto):
    url = f"https://www.pacifiko.com/search?q={producto.replace(' ', '%20')}"
    try:
        resp = await client.get(url, timeout=15.0, follow_redirects=True)
        soup = BeautifulSoup(resp.text, 'html.parser')
        # Pacifiko usa product-details o product-item-container
        items = soup.select('.product-item-container, .product-block, .product-details')
        res = []
        for i in items[:5]:
            n = i.select_one('.name, h4, .product-name')
            p = i.select_one('.price, .product-price')
            l = i.select_one('a')
            img = i.select_one('img')
            if n and p and l:
                link = l['href']
                res.append({
                    "tienda": "Pacifiko",
                    "nombre": n.get_text().strip(),
                    "precio": p.get_text().strip(),
                    "link": f"https://www.pacifiko.com{link}" if not link.startswith('http') else link,
                    "imagen": img.get('src') or ""
                })
        return res
    except Exception as e:
        logger.error(f"Error en Pacifiko: {e}")
        return []

async def scraper_vtex(browser, url, tienda, dominio):
    # Usamos un contexto de incógnito con dimensiones reales
    context = await browser.new_context(
        viewport={'width': 1280, 'height': 800},
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
    page = await context.new_page()
    res = []
    try:
        logger.info(f"Navegando a {tienda}...")
        await page.goto(url, wait_until="load", timeout=40000)
        # Scroll para activar carga de productos (lazy load)
        await page.evaluate("window.scrollTo(0, 500)")
        await asyncio.sleep(4) 
        
        # Selectores VTEX (Walmart/Elektra/Cemaco)
        items = await page.query_selector_all(".vtex-search-result-3-x-galleryItem")
        if not items:
            items = await page.query_selector_all("[class*='galleryItem']")

        for item in items[:5]:
            n = await item.query_selector("h3, .vtex-product-summary-2-x-brandName")
            p = await item.query_selector("[class*='currencyInteger'], .vtex-product-price-1-x-currencyInteger")
            l = await item.query_selector("a")
            img = await item.query_selector("img")
            
            if n and p and l:
                nombre_text = await n.inner_text()
                precio_text = await p.inner_text()
                href = await l.get_attribute("href")
                res.append({
                    "tienda": tienda,
                    "nombre": nombre_text.strip(),
                    "precio": f"Q{precio_text.strip()}",
                    "link": f"https://www.{dominio}{href}" if not href.startswith('http') else href,
                    "imagen": await img.get_attribute("src") if img else ""
                })
        logger.info(f"{tienda} encontró {len(res)} productos")
    except Exception as e:
        logger.error(f"Error en {tienda}: {e}")
    finally:
        await page.close()
        await context.close()
    return res

@app.get("/", response_class=HTMLResponse)
async def home():
    # Retornamos el HTML directamente para asegurar que cargue
    with open("index.html", "r", encoding="utf-8") as f:
        return f.read()

@app.get("/api/search")
async def api_search(q: str = Query(...)):
    query = q.strip()
    logger.info(f"Iniciando búsqueda para: {query}")
    
    # 1. Búsquedas rápidas con HTTPX
    async with httpx.AsyncClient(headers=REAL_HEADERS, follow_redirects=True) as client:
        tareas_fast = [
            buscar_magento(client, query, "Max", "https://www.max.com.gt"),
            buscar_magento(client, query, "Tecnofacil", "https://www.tecnofacil.com.gt"),
            buscar_pacifiko(client, query)
        ]
        resultados_fast = await asyncio.gather(*tareas_fast)

    # 2. Búsquedas lentas con Playwright
    resultados_slow = []
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-setuid-sandbox"])
            tareas_slow = [
                scraper_vtex(browser, f"https://www.walmart.com.gt/busqueda?_query={query}", "Walmart", "walmart.com.gt"),
                scraper_vtex(browser, f"https://www.elektra.com.gt/{query}?_q={query}&map=ft", "Elektra", "elektra.com.gt")
            ]
            res_slow_list = await asyncio.gather(*tareas_slow)
            resultados_slow = [item for sublist in res_slow_list for item in sublist]
            await browser.close()
    except Exception as e:
        logger.error(f"Fallo Playwright Global: {e}")

    final = [item for sublist in resultados_fast for item in sublist] + resultados_slow
    return final

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
