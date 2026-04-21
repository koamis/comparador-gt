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

# Configuración de logs para Railway
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

# --- BASE DE DATOS ---
DB_PATH = os.path.join(os.getcwd(), "precios_gt.db")

def init_db():
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS productos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                busqueda TEXT, tienda TEXT, nombre TEXT,
                precio_texto TEXT, precio_num REAL, link TEXT,
                imagen TEXT, fecha TIMESTAMP
            )
        ''')
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"Error DB Init: {e}")

init_db()

# --- SCRAPERS ESTÁTICOS (Rápidos) ---
async def buscar_magento(client, producto, tienda, url_base):
    url = f"{url_base}/catalogsearch/result/?q={producto}"
    try:
        resp = await client.get(url, timeout=10.0, headers={"User-Agent": "Mozilla/5.0"})
        soup = BeautifulSoup(resp.text, 'html.parser')
        items = soup.select('li.item.product.product-item')[:4]
        res = []
        for i in items:
            n = i.select_one('a.product-item-link')
            p = i.select_one('span.price')
            img = i.select_one('img.product-image-photo')
            if n and p:
                res.append({
                    "tienda": tienda, "nombre": n.text.strip(), 
                    "precio": p.text.strip(), "link": n['href'], 
                    "imagen": img.get('src') or img.get('data-src') if img else ""
                })
        return res
    except: return []

async def buscar_pacifiko(client, producto):
    url = f"https://www.pacifiko.com/busqueda?q={producto}"
    try:
        resp = await client.get(url, timeout=10.0)
        soup = BeautifulSoup(resp.text, 'html.parser')
        items = soup.select('.product-block, .product-details')[:4]
        res = []
        for i in items:
            n = i.select_one('.name, h4')
            p = i.select_one('.price')
            l = i.select_one('a')
            img = i.select_one('img')
            if n and p and l:
                res.append({
                    "tienda": "Pacifiko", "nombre": n.text.strip(), 
                    "precio": p.text.strip(), "link": "https://www.pacifiko.com" + l['href'], 
                    "imagen": img.get('src') if img else ""
                })
        return res
    except: return []

# --- SCRAPER DINÁMICO (Walmart, Elektra, Cemaco, La Torre) ---
async def scraper_vtex(browser, url, tienda, dominio):
    context = await browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
    page = await context.new_page()
    res = []
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=25000)
        await asyncio.sleep(2) # Espera para carga de JS
        items = await page.query_selector_all(".vtex-search-result-3-x-galleryItem, .vtex-product-summary-2-x-container")
        for item in items[:4]:
            n = await item.query_selector(".vtex-product-summary-2-x-productBrandText, .vtex-product-summary-2-x-brandName")
            p = await item.query_selector(".vtex-product-price-1-x-currencyInteger, .vtex-product-summary-2-x-currencyInteger")
            l = await item.query_selector("a")
            img = await item.query_selector("img")
            if n and p and l:
                href = await l.get_attribute("href")
                res.append({
                    "tienda": tienda, "nombre": await n.inner_text(), 
                    "precio": f"Q{await p.inner_text()}",
                    "link": href if href.startswith('http') else f"https://www.{dominio}{href}",
                    "imagen": await img.get_attribute("src") if img else ""
                })
    except: pass
    finally:
        await page.close()
        await context.close()
    return res

# --- INTERFAZ HTML ---
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>BuscaPrecios GT | El Comparador de Guatemala</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css">
    <style>
        .card-best { border: 4px solid #22c55e; box-shadow: 0 10px 15px -3px rgba(34, 197, 94, 0.2); }
        .card-expensive { border: 2px solid #ef4444; opacity: 0.8; }
    </style>
</head>
<body class="bg-slate-50 min-h-screen">
    <nav class="bg-indigo-700 p-4 shadow-lg text-white">
        <div class="container mx-auto flex justify-between items-center">
            <h1 class="text-2xl font-black italic tracking-tighter">PRECIOS<span class="text-orange-400 font-bold text-3xl">.GT</span></h1>
            <div class="hidden md:block text-xs uppercase font-bold opacity-60">Walmart • Max • Elektra • Cemaco • Pacifiko</div>
        </div>
    </nav>

    <div class="container mx-auto p-4 md:p-8">
        <div class="max-w-3xl mx-auto mb-10">
            <div class="bg-white p-2 rounded-2xl shadow-2xl flex border-2 border-indigo-100">
                <input type="text" id="q" placeholder="¿Qué buscas hoy en Guatemala?" class="flex-1 p-4 outline-none text-lg rounded-l-xl">
                <button onclick="buscar()" class="bg-indigo-600 hover:bg-orange-500 text-white px-8 rounded-xl transition-all font-bold">
                    <i class="fa-solid fa-magnifying-glass"></i>
                </button>
            </div>
        </div>

        <div id="loading" class="hidden text-center py-10">
            <div class="animate-spin h-12 w-12 border-4 border-indigo-600 border-t-transparent rounded-full mx-auto mb-4"></div>
            <p class="text-indigo-900 font-bold animate-pulse italic">Consultando tiendas de Guatemala...</p>
        </div>

        <div id="metricas" class="hidden grid grid-cols-1 md:grid-cols-3 gap-4 mb-8">
            <div class="bg-white p-4 rounded-xl shadow-sm border-l-8 border-green-500">
                <p class="text-xs font-bold text-gray-400 uppercase">Precio más bajo</p>
                <p id="m-min" class="text-2xl font-black text-green-600">Q0</p>
            </div>
            <div class="bg-white p-4 rounded-xl shadow-sm border-l-8 border-indigo-500 text-center">
                <p class="text-xs font-bold text-gray-400 uppercase">Promedio</p>
                <p id="m-avg" class="text-xl font-bold text-indigo-800">Q0</p>
            </div>
            <div class="bg-white p-4 rounded-xl shadow-sm border-l-8 border-red-500 text-right">
                <p class="text-xs font-bold text-gray-400 uppercase">Precio más alto</p>
                <p id="m-max" class="text-2xl font-black text-red-600">Q0</p>
            </div>
        </div>

        <div id="resultados" class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-6"></div>
    </div>

    <script>
        async function buscar() {
            const query = document.getElementById('q').value;
            if(!query) return;

            const resDiv = document.getElementById('resultados');
            const load = document.getElementById('loading');
            const metrics = document.getElementById('metricas');

            resDiv.innerHTML = '';
            metrics.classList.add('hidden');
            load.classList.remove('hidden');

            try {
                const response = await fetch(`/api/search?q=${encodeURIComponent(query)}`);
                const data = await response.json();
                load.classList.add('hidden');

                if(data.length === 0) {
                    resDiv.innerHTML = '<p class="col-span-full text-center text-gray-500 py-10">No encontramos resultados para tu búsqueda.</p>';
                    return;
                }

                // Calcular métricas
                const precios = data.map(p => parseFloat(p.precio.replace(/[^\\d.]/g, ''))).filter(p => p > 0);
                const min = Math.min(...precios);
                const max = Math.max(...precios);
                const avg = precios.reduce((a, b) => a + b, 0) / precios.length;

                metrics.classList.remove('hidden');
                document.getElementById('m-min').innerText = 'Q' + min.toLocaleString();
                document.getElementById('m-max').innerText = 'Q' + max.toLocaleString();
                document.getElementById('m-avg').innerText = 'Q' + avg.toLocaleString();

                data.forEach(p => {
                    const pNum = parseFloat(p.precio.replace(/[^\\d.]/g, ''));
                    let statusClass = '';
                    let badge = '';

                    if(pNum === min) {
                        statusClass = 'card-best';
                        badge = '<span class="absolute -top-3 -right-3 bg-green-500 text-white text-[10px] px-3 py-1 rounded-full font-black shadow-lg">MEJOR PRECIO</span>';
                    } else if (pNum === max) {
                        statusClass = 'card-expensive';
                    }

                    resDiv.innerHTML += `
                        <div class="bg-white rounded-2xl p-4 flex flex-col relative border shadow-sm hover:shadow-2xl transition-all ${statusClass}">
                            ${badge}
                            <div class="h-40 w-full mb-4">
                                <img src="${p.imagen}" class="h-full w-full object-contain">
                            </div>
                            <span class="text-[10px] font-black text-indigo-500 uppercase tracking-tighter mb-1">${p.tienda}</span>
                            <h3 class="text-xs font-bold text-gray-700 h-8 overflow-hidden line-clamp-2 mb-4 italic leading-tight">${p.nombre}</h3>
                            <div class="mt-auto flex justify-between items-center">
                                <span class="text-xl font-black text-slate-800 tracking-tighter">${p.precio}</span>
                                <a href="${p.link}" target="_blank" class="bg-indigo-600 hover:bg-orange-500 text-white p-2 px-4 rounded-lg text-xs font-bold shadow-md transition-colors">VER</a>
                            </div>
                        </div>
                    `;
                });
            } catch (e) {
                load.classList.add('hidden');
                alert("Error al conectar con el servidor. Revisa los logs en Railway.");
            }
        }
        document.getElementById('q').addEventListener('keypress', (e) => e.key === 'Enter' && buscar());
    </script>
</body>
</html>
"""

# --- RUTAS ---
@app.get("/", response_class=HTMLResponse)
async def home():
    return HTML_TEMPLATE

@app.get("/api/search")
async def api_search(q: str = Query(...)):
    query = q.lower().strip()
    
    # 1. Scrapers Rápidos
    async with httpx.AsyncClient(headers={"User-Agent": "Mozilla/5.0"}, follow_redirects=True) as client:
        tareas_fast = [
            buscar_magento(client, query, "Max", "https://www.max.com.gt"),
            buscar_magento(client, query, "Tecnofacil", "https://www.tecnofacil.com.gt"),
            buscar_magento(client, query, "Curacao", "https://www.lacuracao.com.gt/guatemala"),
            buscar_pacifiko(client, query)
        ]
        res_fast_list = await asyncio.gather(*tareas_fast)

    # 2. Scrapers Playwright
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
        logger.error(f"Error Playwright Global: {e}")

    final = [item for sublist in res_fast_list for item in sublist] + res_slow
    return final

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
