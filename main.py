import os
import sqlite3
import datetime
import asyncio
import httpx
from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

# 1. INICIALIZACIÓN
app = FastAPI()

def init_db():
    conn = sqlite3.connect('precios_gt.db')
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS productos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            busqueda TEXT,
            tienda TEXT,
            nombre TEXT,
            precio_texto TEXT,
            precio_num REAL,
            link TEXT,
            imagen TEXT,
            fecha TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()

init_db()

# 2. FUNCIONES DE APOYO (DB)
def obtener_cache(busqueda):
    try:
        conn = sqlite3.connect('precios_gt.db')
        cursor = conn.cursor()
        hace_12_horas = datetime.datetime.now() - datetime.timedelta(hours=12)
        cursor.execute('SELECT tienda, nombre, precio_texto, link, imagen FROM productos WHERE busqueda = ? AND fecha > ?', (busqueda.lower(), hace_12_horas))
        rows = cursor.fetchall()
        conn.close()
        if rows:
            res = []
            for r in rows:
                res.append({"tienda": r[0], "nombre": r[1], "precio": r[2], "link": r[3], "imagen": r[4]})
            return res
    except:
        return None
    return None

def guardar_en_db(busqueda, resultados):
    try:
        conn = sqlite3.connect('precios_gt.db')
        cursor = conn.cursor()
        fecha = datetime.datetime.now()
        for r in resultados:
            try:
                p_num = float(r['precio'].replace('Q', '').replace(',', '').strip())
            except:
                p_num = 0
            cursor.execute('INSERT INTO productos (busqueda, tienda, nombre, precio_texto, precio_num, link, imagen, fecha) VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
                           (busqueda.lower(), r['tienda'], r['nombre'], r['precio'], p_num, r['link'], r['imagen'], fecha))
        conn.commit()
        conn.close()
    except:
        pass

# 3. SCRAPERS
async def buscar_magento(client, producto, tienda, url_base):
    url = f"{url_base}/catalogsearch/result/?q={producto}"
    resultados = []
    try:
        resp = await client.get(url, timeout=15.0)
        soup = BeautifulSoup(resp.text, 'html.parser')
        items = soup.find_all('li', class_='item product product-item')[:5]
        for i in items:
            nombre_tag = i.find('a', class_='product-item-link')
            precio_tag = i.find('span', class_='price')
            img_tag = i.find('img', class_='product-image-photo')
            if nombre_tag and precio_tag:
                resultados.append({
                    "tienda": tienda,
                    "nombre": nombre_tag.text.strip(),
                    "precio": precio_tag.text.strip(),
                    "link": nombre_tag['href'],
                    "imagen": img_tag.get('src') if img_tag else ""
                })
    except:
        pass
    return resultados

async def buscar_pacifiko(client, producto):
    url = f"https://www.pacifiko.com/busqueda?q={producto}"
    resultados = []
    try:
        resp = await client.get(url, timeout=15.0)
        soup = BeautifulSoup(resp.text, 'html.parser')
        items = soup.find_all('div', class_='product-block')[:5]
        for i in items:
            nombre_tag = i.find('div', class_='name')
            precio_tag = i.find('div', class_='price')
            link_tag = i.find('a')
            img_tag = i.find('img')
            if nombre_tag and precio_tag and link_tag:
                resultados.append({
                    "tienda": "Pacifiko",
                    "nombre": nombre_tag.text.strip(),
                    "precio": precio_tag.text.strip(),
                    "link": "https://www.pacifiko.com" + link_tag['href'],
                    "imagen": img_tag.get('src') if img_tag else ""
                })
    except:
        pass
    return resultados

async def scraper_vtex_generic(browser, url, tienda, dominio):
    resultados = []
    try:
        page = await browser.new_page()
        await page.goto(url, wait_until="networkidle", timeout=30000)
        items = await page.query_selector_all(".vtex-search-result-3-x-galleryItem")
        for item in items[:5]:
            nombre_el = await item.query_selector(".vtex-product-summary-2-x-productBrandText")
            precio_el = await item.query_selector(".vtex-product-price-1-x-currencyInteger")
            link_el = await item.query_selector("a")
            img_el = await item.query_selector("img")
            if nombre_el and precio_el and link_el:
                p_text = await precio_el.inner_text()
                href = await link_el.get_attribute("href")
                resultados.append({
                    "tienda": tienda,
                    "nombre": await nombre_el.inner_text(),
                    "precio": f"Q{p_text}",
                    "link": href if "http" in href else f"https://www.{dominio}{href}",
                    "imagen": await img_el.get_attribute("src") if img_el else ""
                })
        await page.close()
    except:
        pass
    return resultados

# 4. RUTAS (HTML Y API)
@app.get("/", response_class=HTMLResponse)
async def home():
    html_content = """
    <!DOCTYPE html>
    <html lang="es">
    <head>
        <meta charset="UTF-8">
        <title>PRECIOS-GT | Buscador</title>
        <script src="https://cdn.tailwindcss.com"></script>
        <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css">
    </head>
    <body class="bg-slate-100 min-h-screen font-sans">
        <nav class="bg-indigo-700 p-4 text-white shadow-md">
            <div class="container mx-auto font-bold text-xl uppercase tracking-widest">Precios Guatemala</div>
        </nav>
        <main class="container mx-auto p-4 max-w-5xl">
            <div class="bg-white p-6 rounded-3xl shadow-lg my-8 flex gap-2">
                <input type="text" id="q" placeholder="¿Qué quieres comprar?" class="flex-1 p-3 outline-none">
                <button onclick="buscar()" class="bg-indigo-600 text-white px-8 py-3 rounded-2xl font-bold">BUSCAR</button>
            </div>
            <div id="loading" class="hidden text-center py-10">
                <div class="animate-spin h-10 w-10 border-4 border-indigo-600 border-t-transparent rounded-full mx-auto"></div>
                <p class="mt-4 text-indigo-700 font-bold italic">Consultando precios...</p>
            </div>
            <div id="results" class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-6"></div>
        </main>
        <script>
            async function buscar() {
                const q = document.getElementById('q').value;
                const resDiv = document.getElementById('results');
                const load = document.getElementById('loading');
                if(!q) return;
                resDiv.innerHTML = ''; 
                load.classList.remove('hidden');
                try {
                    const resp = await fetch(`/buscar?q=${encodeURIComponent(q)}`);
                    const datos = await resp.json();
                    load.classList.add('hidden');
                    if(datos.length === 0) {
                        resDiv.innerHTML = '<p class="col-span-full text-center text-gray-500">No se encontraron productos.</p>';
                        return;
                    }
                    datos.forEach(p => {
                        resDiv.innerHTML += `
                            <div class="bg-white p-4 rounded-2xl shadow-sm border flex flex-col hover:shadow-xl transition">
                                <img src="${p.imagen}" class="h-40 object-contain mb-4">
                                <span class="text-[10px] font-black text-indigo-500 uppercase tracking-tighter">${p.tienda}</span>
                                <h3 class="text-sm font-bold text-slate-700 mb-4 h-10 line-clamp-2">${p.nombre}</h3>
                                <div class="mt-auto flex justify-between items-center">
                                    <span class="text-xl font-black text-slate-900">${p.precio}</span>
                                    <a href="${p.link}" target="_blank" class="bg-indigo-600 text-white p-2 px-4 rounded-xl text-xs font-bold">VER</a>
                                </div>
                            </div>`;
                    });
                } catch(e) { 
                    load.classList.add('hidden'); 
                    alert("Error en la búsqueda"); 
                }
            }
            document.getElementById('q').addEventListener('keypress', (e) => e.key === 'Enter' && buscar());
        </script>
    </body>
    </html>
    """
    return html_content

@app.get("/buscar")
async def api_buscar(q: str = Query(...)):
    q_limpio = q.lower().strip()
    # Revisar Cache
    cache = obtener_cache(q_limpio)
    if cache:
        return cache

    # Scrapear si no hay cache
    async with httpx.AsyncClient(headers={"User-Agent": "Mozilla/5.0"}, follow_redirects=True) as client:
        tareas_rapidas = [
            buscar_magento(client, q_limpio, "Max", "https://www.max.com.gt"),
            buscar_magento(client, q_limpio, "Tecnofacil", "https://www.tecnofacil.com.gt"),
            buscar_pacifiko(client, q_limpio)
        ]
        resultados_rapidos = await asyncio.gather(*tareas_rapidas)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        tareas_vtex = [
            scraper_vtex_generic(browser, f"https://www.walmart.com.gt/{q_limpio}", "Walmart", "walmart.com.gt"),
            scraper_vtex_generic(browser, f"https://www.elektra.com.gt/{q_limpio}?_q={q_limpio}&map=ft", "Elektra", "elektra.com.gt")
        ]
        resultados_vtex = await asyncio.gather(*tareas_vtex)
        await browser.close()
    
    # Combinar
    final = []
    for sublist in resultados_rapidos + resultados_vtex:
        for item in sublist:
            final.append(item)
    
    if final:
        guardar_en_db(q_limpio, final)
        
    return final

# 5. INICIO DE SERVIDOR
if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
