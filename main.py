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

# Configuración de Logs para ver errores en Railway
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

# Ruta de base de datos absoluta para evitar errores de permisos
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
        logger.error(f"Error DB: {e}")

init_db()

async def buscar_magento(client, producto, tienda, url_base):
    url = f"{url_base}/catalogsearch/result/?q={producto}"
    try:
        resp = await client.get(url, timeout=10.0)
        soup = BeautifulSoup(resp.text, 'html.parser')
        items = soup.find_all('li', class_='item product product-item')[:3]
        res = []
        for i in items:
            n = i.find('a', class_='product-item-link')
            p = i.find('span', class_='price')
            img = i.find('img', class_='product-image-photo')
            if n and p:
                res.append({"tienda": tienda, "nombre": n.text.strip(), "precio": p.text.strip(), "link": n['href'], "imagen": img.get('src') if img else ""})
        return res
    except: return []

async def buscar_pacifiko(client, producto):
    url = f"https://www.pacifiko.com/busqueda?q={producto}"
    try:
        resp = await client.get(url, timeout=10.0)
        soup = BeautifulSoup(resp.text, 'html.parser')
        items = soup.find_all('div', class_='product-block')[:3]
        res = []
        for i in items:
            n = i.find('div', class_='name')
            p = i.find('div', class_='price')
            l = i.find('a')
            img = i.find('img')
            if n and p:
                res.append({"tienda": "Pacifiko", "nombre": n.text.strip(), "precio": p.text.strip(), "link": "https://www.pacifiko.com" + l['href'], "imagen": img.get('src') if img else ""})
        return res
    except: return []

async def scraper_vtex(browser, url, tienda, dominio):
    context = await browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
    page = await context.new_page()
    res = []
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=20000)
        # Esperar un poco por los precios
        await asyncio.sleep(2)
        items = await page.query_selector_all(".vtex-search-result-3-x-galleryItem")
        for item in items[:3]:
            n = await item.query_selector(".vtex-product-summary-2-x-productBrandText")
            p = await item.query_selector(".vtex-product-price-1-x-currencyInteger")
            l = await item.query_selector("a")
            img = await item.query_selector("img")
            if n and p:
                href = await l.get_attribute("href")
                res.append({
                    "tienda": tienda, "nombre": await n.inner_text(), "precio": f"Q{await p.inner_text()}",
                    "link": href if "http" in href else f"https://www.{dominio}{href}",
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
    return """
    <!DOCTYPE html>
    <html lang="es">
    <head>
        <meta charset="UTF-8"><title>PRECIOS-GT</title>
        <script src="https://cdn.tailwindcss.com"></script>
        <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css">
    </head>
    <body class="bg-slate-100">
        <nav class="bg-indigo-700 p-4 text-white font-bold text-center">PRECIOS GUATEMALA</nav>
        <main class="container mx-auto p-4 max-w-4xl">
            <div class="bg-white p-6 rounded-2xl shadow-lg my-6 flex gap-2">
                <input type="text" id="q" placeholder="Ej: iPhone, Leche, TV..." class="flex-1 p-2 border-b outline-none">
                <button onclick="buscar()" class="bg-indigo-600 text-white px-6 py-2 rounded-xl">BUSCAR</button>
            </div>
            <div id="load" class="hidden text-center py-10 font-bold text-indigo-600 animate-pulse">Buscando en tiendas de GT...</div>
            <div id="res" class="grid grid-cols-1 md:grid-cols-3 gap-4"></div>
        </main>
        <script>
            async function buscar() {
                const q = document.getElementById('q').value;
                if(!q) return;
                document.getElementById('res').innerHTML = '';
                document.getElementById('load').classList.remove('hidden');
                try {
                    const r = await fetch(`/buscar?q=${encodeURIComponent(q)}`);
                    const data = await r.json();
                    document.getElementById('load').classList.add('hidden');
                    if(data.length === 0) { document.getElementById('res').innerHTML = '<p class="col-span-full text-center">No se hallaron resultados.</p>'; return; }
                    data.forEach(p => {
                        document.getElementById('res').innerHTML += `
                            <div class="bg-white p-4 rounded-xl shadow border">
                                <img src="${p.imagen}" class="h-32 w-full object-contain mb-2">
                                <p class="text-[10px] font-bold text-indigo-500">${p.tienda}</p>
                                <h3 class="text-xs font-bold h-8 overflow-hidden">${p.nombre}</h3>
                                <div class="flex justify-between items-center mt-4">
                                    <span class="font-black">${p.precio}</span>
                                    <a href="${p.link}" target="_blank" class="bg-indigo-600 text-white p-2 rounded text-xs">VER</a>
                                </div>
                            </div>`;
                    });
                } catch(e) { 
                    document.getElementById('load').classList.add('hidden');
                    alert("Error en la conexión con el servidor.");
                }
            }
        </script>
    </body></html>
    """

@app.get("/buscar")
async def api_buscar(q: str = Query(...)):
    q = q.lower().strip()
    
    # 1. Intentar buscar en las tiendas rápidas (Max, Tecnofacil, Pacifiko)
    async with httpx.AsyncClient(headers={"User-Agent": "Mozilla/5.0"}, follow_redirects=True) as client:
        t_fast = [
            buscar_magento(client, q, "Max", "https://www.max.com.gt"),
            buscar_magento(client, q, "Tecnofacil", "https://www.tecnofacil.com.gt"),
            buscar_pacifiko(client, q)
        ]
        r_fast = await asyncio.gather(*t_fast)

    # 2. Intentar buscar en tiendas lentas con Playwright (Walmart, Elektra)
    r_slow = []
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-setuid-sandbox"])
            t_slow = [
                scraper_vtex(browser, f"https://www.walmart.com.gt/{q}", "Walmart", "walmart.com.gt"),
                scraper_vtex(browser, f"https://www.elektra.com.gt/{q}?_q={q}&map=ft", "Elektra", "elektra.com.gt")
            ]
            res_slow_list = await asyncio.gather(*t_slow)
            r_slow = [item for sublist in res_slow_list for item in sublist]
            await browser.close()
    except Exception as e:
        logger.error(f"Error Playwright: {e}")

    final = [item for sublist in r_fast for item in sublist] + r_slow
    return final

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
