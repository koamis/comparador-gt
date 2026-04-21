import os
import sqlite3
import datetime
import asyncio
import httpx
import logging
import uuid
from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

# --- SCRAPERS RÁPIDOS CORREGIDOS ---
async def buscar_magento(client, producto, tienda, url_base):
    # Quitamos la barra final para evitar el Redirect 308
    url = f"{url_base}/catalogsearch/result?q={producto}"
    try:
        resp = await client.get(url, timeout=12.0, follow_redirects=True)
        soup = BeautifulSoup(resp.text, 'html.parser')
        # Selectores más flexibles
        items = soup.select('.product-item, .item.product')[:5]
        res = []
        for i in items:
            n = i.select_one('.product-item-link, a.product-item-link')
            p = i.select_one('.price')
            img = i.select_one('img')
            if n and p:
                res.append({
                    "tienda": tienda, "nombre": n.text.strip(), 
                    "precio": p.text.strip(), "link": n['href'], 
                    "imagen": img.get('src') or img.get('data-src') or ""
                })
        return res
    except Exception as e:
        logger.error(f"Error {tienda}: {e}")
        return []

async def buscar_pacifiko(client, producto):
    # URL corregida (Pacifiko usa /search ahora)
    url = f"https://www.pacifiko.com/search?q={producto}"
    try:
        resp = await client.get(url, timeout=12.0, follow_redirects=True)
        soup = BeautifulSoup(resp.text, 'html.parser')
        items = soup.select('.product-details, .product-block, .product-item')[:5]
        res = []
        for i in items:
            n = i.select_one('.name, h4, .product-name')
            p = i.select_one('.price, .product-price')
            l = i.select_one('a')
            img = i.select_one('img')
            if n and p and l:
                link = l['href']
                res.append({
                    "tienda": "Pacifiko", "nombre": n.text.strip(), 
                    "precio": p.text.strip(), "link": "https://www.pacifiko.com" + link if not link.startswith('http') else link, 
                    "imagen": img.get('src') or ""
                })
        return res
    except Exception as e:
        logger.error(f"Error Pacifiko: {e}")
        return []

# --- SCRAPER DINÁMICO (Playwright) ---
async def scraper_vtex(browser, url, tienda, dominio):
    context = await browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
    page = await context.new_page()
    res = []
    try:
        await page.goto(url, wait_until="load", timeout=30000)
        await asyncio.sleep(3) # Espera para que carguen los precios de VTEX
        items = await page.query_selector_all(".vtex-search-result-3-x-galleryItem, .vtex-product-summary-2-x-container")
        for item in items[:5]:
            n = await item.query_selector(".vtex-product-summary-2-x-productBrandText, .vtex-product-summary-2-x-brandName")
            p = await item.query_selector(".vtex-product-price-1-x-currencyInteger, .vtex-product-summary-2-x-currencyInteger")
            l = await item.query_selector("a")
            img = await item.query_selector("img")
            if n and p and l:
                precio_val = await p.inner_text()
                href = await l.get_attribute("href")
                res.append({
                    "tienda": tienda, "nombre": await n.inner_text(), 
                    "precio": f"Q{precio_val}",
                    "link": href if href.startswith('http') else f"https://www.{dominio}{href}",
                    "imagen": await img.get_attribute("src") if img else ""
                })
    except Exception as e:
        logger.error(f"Error {tienda}: {e}")
    finally:
        await page.close()
        await context.close()
    return res

# --- INTERFAZ HTML ---
@app.get("/", response_class=HTMLResponse)
async def home():
    return """
    <!DOCTYPE html>
    <html lang="es">
    <head>
        <meta charset="UTF-8"><title>PRECIOS-GT | El Comparador de Guatemala</title>
        <script src="https://cdn.tailwindcss.com"></script>
        <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css">
    </head>
    <body class="bg-slate-50 min-h-screen">
        <nav class="bg-indigo-700 p-4 shadow-lg text-white font-black text-center text-xl italic">PRECIOS.GT</nav>
        <main class="container mx-auto p-4 max-w-5xl">
            <div class="bg-white p-4 rounded-2xl shadow-xl my-8 flex gap-2 border-2 border-indigo-100">
                <input type="text" id="q" placeholder="Ej: Leche, Smart TV, Aceite..." class="flex-1 p-3 outline-none text-lg">
                <button onclick="buscar()" class="bg-indigo-600 hover:bg-orange-500 text-white px-8 rounded-xl font-bold transition-all"><i class="fa-solid fa-magnifying-glass"></i></button>
            </div>
            <div id="loading" class="hidden text-center py-10 font-bold text-indigo-900 animate-pulse">Escaneando tiendas de Guatemala...</div>
            <div id="resultados" class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-6"></div>
        </main>
        <script>
            async function buscar() {
                const q = document.getElementById('q').value;
                if(!q) return;
                const resDiv = document.getElementById('resultados');
                const load = document.getElementById('loading');
                resDiv.innerHTML = ''; load.classList.remove('hidden');
                try {
                    const r = await fetch(`/api/search?q=${encodeURIComponent(q)}`);
                    const data = await r.json();
                    load.classList.add('hidden');
                    if(data.length === 0) { resDiv.innerHTML = '<p class="col-span-full text-center text-gray-500">No hay resultados. Intenta con otra palabra.</p>'; return; }
                    data.forEach(p => {
                        resDiv.innerHTML += `
                            <div class="bg-white rounded-2xl p-4 flex flex-col border hover:shadow-xl transition">
                                <img src="${p.imagen}" class="h-40 w-full object-contain mb-4">
                                <span class="text-[10px] font-black text-indigo-500 uppercase">${p.tienda}</span>
                                <h3 class="text-xs font-bold text-gray-700 h-8 overflow-hidden mb-4">${p.nombre}</h3>
                                <div class="mt-auto flex justify-between items-center">
                                    <span class="text-xl font-black text-slate-800 tracking-tighter">${p.precio}</span>
                                    <a href="${p.link}" target="_blank" class="bg-indigo-600 text-white p-2 px-3 rounded-lg text-xs font-bold">VER</a>
                                </div>
                            </div>`;
                    });
                } catch (e) { load.classList.add('hidden'); alert("Error al buscar"); }
            }
        </script>
    </body></html>
    """

@app.get("/api/search")
async def api_search(q: str = Query(...)):
    query = q.lower().strip()
    # 1. Rápidas (BS4)
    async with httpx.AsyncClient(headers={"User-Agent": "Mozilla/5.0"}, follow_redirects=True) as client:
        tareas_fast = [
            buscar_magento(client, query, "Max", "https://www.max.com.gt"),
            buscar_magento(client, query, "Tecnofacil", "https://www.tecnofacil.com.gt"),
            buscar_pacifiko(client, query)
        ]
        res_fast_list = await asyncio.gather(*tareas_fast)

    # 2. Lentas (Playwright)
    res_slow = []
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True, args=["--no-sandbox"])
            tareas_slow = [
                scraper_vtex(browser, f"https://www.walmart.com.gt/busqueda?_query={query}", "Walmart", "walmart.com.gt"),
                scraper_vtex(browser, f"https://www.elektra.com.gt/{query}?_q={query}&map=ft", "Elektra", "elektra.com.gt"),
                scraper_vtex(browser, f"https://www.cemaco.com/{query}?_q={query}&map=ft", "Cemaco", "cemaco.com"),
                scraper_vtex(browser, f"https://www.latorre.com.gt/{query}", "La Torre", "latorre.com.gt")
            ]
            res_slow_list = await asyncio.gather(*tareas_slow)
            res_slow = [item for sublist in res_slow_list for item in sublist]
            await browser.close()
    except Exception as e:
        logger.error(f"Error Playwright: {e}")

    return [item for sublist in res_fast_list for item in sublist] + res_slow

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
