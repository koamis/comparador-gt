import os
import asyncio
import httpx
import sqlite3
import datetime
from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

app = FastAPI()

# --- CONFIGURACIÓN DE NAVEGADOR REAL ---
# Esto hace que parezcamos un humano navegando desde Chrome
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Accept-Language": "es-GT,es;q=0.9,en-US;q=0.8,en;q=0.7",
    "Referer": "https://www.google.com/"
}

# --- BUSCADOR EN TIENDAS MAGENTO (MAX, TECNOFACIL) ---
async def buscar_tienda_estatica(client, q, tienda, url_base):
    # Intentamos la URL de búsqueda estándar
    url = f"{url_base}/catalogsearch/result/?q={q.replace(' ', '+')}"
    try:
        resp = await client.get(url, timeout=12.0, follow_redirects=True)
        soup = BeautifulSoup(resp.text, 'html.parser')
        
        # Buscamos por selectores comunes en Guatemala
        items = soup.select('.product-item, .item.product')
        resultados = []
        
        for i in items[:5]:
            try:
                nombre = i.select_one('.product-item-link, a[class*="link"]').get_text(strip=True)
                precio = i.select_one('.price, [id^="product-price"]').get_text(strip=True)
                link = i.select_one('a')['href']
                img = i.select_one('img')['src'] if i.select_one('img') else ""
                
                if nombre and precio:
                    resultados.append({
                        "tienda": tienda, "nombre": nombre, 
                        "precio": precio, "link": link, "imagen": img
                    })
            except: continue
        return resultados
    except: return []

# --- BUSCADOR EN TIENDAS VTEX (WALMART, ELEKTRA, CEMACO) ---
async def buscar_tienda_vtex(browser, q, tienda, dominio):
    # Walmart y otros usan diferentes rutas de búsqueda
    url = f"https://www.{dominio}/{q.replace(' ', '%20')}"
    if tienda == "Walmart":
        url = f"https://www.walmart.com.gt/busqueda?_query={q}"
    
    page = await browser.new_page()
    # Le decimos al navegador que parezca una pantalla de PC real
    await page.set_viewport_size({"width": 1280, "height": 800})
    
    resultados = []
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=25000)
        # Esperamos un momento para que el JavaScript cargue los precios
        await asyncio.sleep(3) 
        
        # Selector universal para tiendas VTEX en Guatemala
        items = await page.query_selector_all(".vtex-search-result-3-x-galleryItem, .vtex-product-summary-2-x-container")
        
        for item in items[:5]:
            try:
                n = await item.query_selector(".vtex-product-summary-2-x-productBrandText, h3")
                p = await item.query_selector(".vtex-product-price-1-x-currencyInteger, [class*='currencyInteger']")
                l = await item.query_selector("a")
                img = await item.query_selector("img")
                
                if n and p:
                    res_n = await n.inner_text()
                    res_p = await p.inner_text()
                    res_l = await l.get_attribute("href")
                    res_img = await img.get_attribute("src")
                    
                    resultados.append({
                        "tienda": tienda, "nombre": res_n.strip(),
                        "precio": f"Q{res_p.strip()}",
                        "link": res_l if "http" in res_l else f"https://www.{dominio}{res_l}",
                        "imagen": res_img
                    })
            except: continue
    except: pass
    finally: await page.close()
    return resultados

# --- RUTA PRINCIPAL (HTML) ---
@app.get("/", response_class=HTMLResponse)
async def home():
    # Retornamos un HTML simple pero funcional
    with open("index.html", "r", encoding="utf-8") as f:
        return f.read()

# --- API DE BÚSQUEDA ---
@app.get("/api/search")
async def api_search(q: str = Query(...)):
    # Usamos un cliente HTTP para las tiendas rápidas
    async with httpx.AsyncClient(headers=HEADERS, follow_redirects=True) as client:
        tareas_rapidas = [
            buscar_tienda_estatica(client, q, "Max", "https://www.max.com.gt"),
            buscar_tienda_estatica(client, q, "Tecnofacil", "https://www.tecnofacil.com.gt"),
            buscar_tienda_estatica(client, q, "La Curacao", "https://www.lacuracao.com.gt/guatemala")
        ]
        res_fast = await asyncio.gather(*tareas_fast)

    # Usamos Playwright para las tiendas difíciles
    res_slow = []
    async with async_playwright() as p:
        # IMPORTANTE: Argumentos para que Railway no bloquee el navegador
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-gpu"])
        tareas_lentas = [
            buscar_tienda_vtex(browser, q, "Walmart", "walmart.com.gt"),
            buscar_tienda_vtex(browser, q, "Elektra", "elektra.com.gt"),
            buscar_tienda_vtex(browser, q, "Cemaco", "cemaco.com")
        ]
        res_slow_list = await asyncio.gather(*tareas_lentas)
        res_slow = [item for sublist in res_slow_list for item in sublist]
        await browser.close()

    # Combinamos todo
    final = [item for sublist in res_fast for item in sublist] + res_slow
    return final

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
