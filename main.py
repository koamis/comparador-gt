import os
import sqlite3
import datetime
import asyncio
import httpx
import logging
import uuid
from fastapi import FastAPI, Query, Body
from fastapi.responses import HTMLResponse
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

# Configuración de logs
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

# --- CONFIGURACIÓN DE BASE DE DATOS ---
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
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS alertas (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT, busqueda TEXT, precio_objetivo REAL, tienda TEXT, fecha_creacion TIMESTAMP
            )
        ''')
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"Error DB Init: {e}")

init_db()

# --- SCRAPERS ---
async def buscar_magento(client, producto, tienda, url_base):
    url = f"{url_base}/catalogsearch/result/?q={producto}"
    try:
        resp = await client.get(url, timeout=12.0, headers={"User-Agent": "Mozilla/5.0"})
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
        resp = await client.get(url, timeout=12.0)
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

async def scraper_vtex(browser, url, tienda, dominio):
    context = await browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
    page = await context.new_page()
    res = []
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=25000)
        await asyncio.sleep(2)
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

# --- RUTAS ---

@app.get("/", response_class=HTMLResponse)
async def home():
    return """
    <!DOCTYPE html>
    <html lang="es">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>BuscaPrecios GT | El Comparador de Guatemala</title>
        <script src="https://cdn.tailwindcss.com"></script>
        <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css">
        <style>
            .card-best { border: 4px solid #22c55e; box-shadow: 0 10px 15px -3px rgba(34, 197, 94, 0.3); }
            .card-expensive { border: 2px solid #ef4444; opacity: 0.7; }
        </style>
    </head>
    <body class="bg-slate-50 min-h-screen">
        <nav class="bg-indigo-700 p-4 shadow-lg text-white">
            <div class="container mx-auto flex justify-between items-center">
                <h1 class="text-2xl font-black italic tracking-tighter">PRECIOS<span class="text-orange-400">.GT</span></h1>
                <div class="hidden md:block text-[10px] uppercase font-bold opacity-60 italic">Walmart • La Torre • Max • Elektra • Cemaco • Pacifiko</div>
            </div>
        </nav>

        <div class="container mx-auto p-4 md:p-8">
            <div class="max-w-3xl mx-auto mb-10">
                <div class="bg-white p-2 rounded-2xl shadow-2xl flex border-2 border-indigo-100">
                    <input type="text" id="q" placeholder="¿Qué buscas comprar hoy?" class="flex-1 p-4 outline-none text-lg rounded-l-xl">
                    <button onclick="buscar()" class="bg-indigo-600 hover:bg-orange-500 text-white px-8 rounded-xl transition-all font-bold">
                        <i class="fa-solid fa-magnifying-glass"></i>
                    </button>
                </div>
            </div>

            <div id="
