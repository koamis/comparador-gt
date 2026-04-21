# Asegúrate de que esta parte esté así en tu main.py para que Railway asigne el puerto
from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse
# ... todos los demás imports ...

# ESTA LÍNEA DEBE ESTAR AQUÍ, FUERA DE CUALQUIER FUNCIÓN
app = FastAPI() 

# ... después vienen tus funciones buscar_max, etc ...
import os
import uvicorn

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)
