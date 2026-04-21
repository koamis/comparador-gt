# Asegúrate de que esta parte esté así en tu main.py para que Railway asigne el puerto
import os
import uvicorn

if __name__ == "__main__":
    # Railway asigna un puerto dinámico, esto lo captura
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)