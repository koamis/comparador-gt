# Usamos la imagen oficial de Playwright (incluye Python y Navegadores)
FROM mcr.microsoft.com/playwright/python:v1.43.0-jammy

# Evita que Python genere archivos .pyc y permite ver logs en tiempo real
ENV PYTHONUNBUFFERED=1

# Carpeta de trabajo
WORKDIR /app

# Copiamos los requerimientos e instalamos
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiamos el resto del código
COPY . .

# Comando para arrancar la aplicación usando el puerto de Railway
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT}"]
