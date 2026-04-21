import os
import sqlite3
import datetime
import asyncio
import json
import httpx
from fastapi import FastAPI, Query, Body
from fastapi.responses import HTMLResponse
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

# 1. INICIALIZACIÓN DE LA APP
app = FastAPI()

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36"
}

# 2. BASE DE DATOS
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

# --- FUNCIONES DE APOYO ---
def obtener_cache(busqueda):
    try:
        conn = sqlite3.connect('precios_gt.db')
        cursor = conn.cursor()
        hace_12_horas = datetime.datetime.now() - datetime.timedelta(hours=12)
        cursor.execute('SELECT tienda, nombre, precio_texto, link, imagen FROM productos WHERE busqueda = ? AND fecha > ?', (busqueda.lower(), hace_12_horas))
        rows = cursor.fetchall()
        conn.close()
        if rows:
            return [{"tienda": r[0], "nombre": r[1], "precio": r[2], "link": r[3], "imagen": r[4]} for r in rows]
    except: pass
    return None

def guardar_en_db(busqueda, resultados):
    try:
        conn = sqlite3.connect('precios_gt.db')
        cursor = conn.cursor()
        fecha = datetime.datetime.now()
        for r in resultados:
            p_num = float(r['precio'].replace('Q', '').replace(',', '').strip()) if 'Q' in r['precio'] else 0
            cursor.execute('INSERT INTO productos (busqueda, tienda, nombre, precio_texto, precio_num, link, imagen, fecha) VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
                           (busqueda.lower(), r['tienda'], r['nombre'], r['precio'], p_num, r['link'], r['imagen'], fecha))
        conn.commit()
        conn.close()
    except: pass

# --- SCRAPERS ---
async def buscar_magento(client, producto, tienda, url_base):
    url = f"{url_base}/catalogsearch/result/?q={producto}"
    try:
        resp = await client.get(url, timeout=15.0)
        soup = BeautifulSoup(resp.text, 'html.parser')
        items = soup.find_all('li', class_='item product product-item')[:5]
        return [{
            "tienda": tienda, "nombre": i.find('a', class_='product-item-link').text.strip(),
            "precio": i.find('span', class_='price').text.strip(),
            "link": i.find('a', class_='product-item-link')['href'],
            "imagen": i.find('img')['src'] if i.find('img')
