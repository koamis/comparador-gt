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
            busqueda TEXT, tienda TEXT, nombre TEXT,
            precio_texto TEXT, precio_num REAL, link TEXT,
            imagen TEXT, fecha TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()

init_db()

# 2. FUNCIONES DE APOYO
def obtener_cache(busqueda):
    try:
        conn = sqlite3.connect('precios_gt.db')
        cursor = conn.cursor()
        hace_12_horas = datetime.datetime.now() - datetime.timedelta(hours=12)
        cursor.execute('SELECT tienda, nombre, precio_texto, link, imagen FROM productos WHERE busqueda = ? AND fecha > ?', (busqueda.lower(), hace_12_horas))
        rows = cursor.fetchall()
        conn.close()
        return [{"tienda": r[0], "nombre": r[1], "precio": r[2], "link": r[3], "imagen": r[4]} for r in rows] if rows else None
    except: return None

def guardar_en_db(busqueda, resultados):
    try:
        conn = sqlite3.connect('precios_gt.db')
        cursor = conn.cursor()
        fecha = datetime.datetime.now()
        for r in resultados:
            try: p_num = float(r['precio'].replace('Q', '').replace(',', '').strip())
            except: p_num = 0
            cursor.execute('INSERT INTO productos (busqueda, tienda, nombre, precio_texto, precio_num, link, imagen, fecha) VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
                           (busqueda.lower(), r['tienda'], r['nombre'], r['precio'], p_num, r['link'], r['imagen'], fecha))
        conn.commit()
        conn.close()
    except: pass

# 3. SCRAPERS
async def buscar_magento(client, producto, tienda, url_base):
    url = f"{url_base}/catalogsearch/result/?q={producto}"
    try:
        resp = await client.get(url, timeout=15.0)
        soup = BeautifulSoup(resp.text, 'html.parser')
        items = soup.find_all('li', class_='item product product-item')[:5]
        res = []
        for i in items:
            link_tag = i.find('a', class_='product-item-link')
            precio_tag = i.find('span', class_='price')
            img_tag = i.find('img', class_='product-image-photo')
            if link_tag and precio_tag:
                res.append({
                    "tienda": tienda, "nombre": link_tag.text.strip(),
                    "precio": precio_tag.text.strip(), "link": link_tag['href'],
                    "imagen": img_tag.get('src') if img_tag else ""
                })
        return res
    except: return []

async def buscar_pacifiko(client, producto):
    url = f"https://www.pacifiko.com/busqueda?q={producto}"
    try:
        resp = await client.get(url, timeout=15.0)
        soup = BeautifulSoup(resp.text, 'html.parser')
        items = soup.find_all('div', class_='product-block')[:5]
        res = []
        for i in items:
            nombre = i.find('div', class_='name')
            precio = i.find('div', class_='price')
            link = i.find('a')
            img = i.find('img')
            if nombre and precio:
                res.append({
                    "tienda": "Pacifiko", "nombre": nombre.text.strip(),
                    "precio": precio.text.strip(), "link": "https://www.pacifiko.com" + link['href'],
                    "imagen": img.get('src') if img else ""
                })
        return res
    except: return []

async def scraper_vtex_generic(browser, url, tienda, dominio):
    page = await browser.new_page()
    res = []
    try:
        await page.goto(url, wait_until="networkidle", timeout=30000)
        items = await page.query_selector_all(".vtex-search-result-3-x-galleryItem")
        for item in items[:5]:
            nombre = await item.query_selector(".vtex-product-summary-2-x-productBrandText")
            precio = await item.query_selector(".vtex-product-price-1-x-currencyInteger")
            link_el = await item.query_selector("a")
            img_el = await item.query_selector("img")
            if nombre and precio:
                p_text = await precio.inner_text()
                href = await link_el.get_attribute("href")
                res.append({
                    "tienda": tienda, "nombre": await nombre.inner_text(), "precio": f"Q{p_text}",
