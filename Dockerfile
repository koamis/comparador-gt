# Usamos una imagen de Python oficial que ya viene con todo lo necesario
FROM python:3.11-slim

# Instalamos dependencias del sistema para Playwright
RUN apt-get update && apt-get install -y \
    wget \
    gnupg \
    libglib2.0-0 \
    libnss3 \
    libnspr4 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxext6 \
    libxfixes3 \
    librandr2 \
    libgbm1 \
    libpango-1.0-0 \
    libcairo2 \
    libasound2 \
    && rm -rf /var/lib/apt/lists/*

# Establecemos la carpeta de trabajo
WORKDIR /app

# Copiamos los archivos de requerimientos e instalamos
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Instalamos los navegadores de Playwright
RUN playwright install chromium
RUN playwright install-deps chromium

# Copiamos el resto del código
COPY . .

# Comando para arrancar la aplicación
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT}"]
