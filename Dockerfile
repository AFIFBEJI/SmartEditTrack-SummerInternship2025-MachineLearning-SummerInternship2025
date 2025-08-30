# ---------- Image ----------
FROM python:3.11-slim

# ---------- OS deps ----------
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential && \
    rm -rf /var/lib/apt/lists/*

# ---------- App dir ----------
WORKDIR /app
COPY requirements.txt /app/
RUN python -m pip install --upgrade pip && pip install -r requirements.txt

# tout le code
COPY . /app

# ---------- Streamlit ----------
# Empêche Streamlit de tenter d’ouvrir un navigateur
ENV STREAMLIT_BROWSER_GATHER_USAGE_STATS=false

# Montre le port via variable d’environnement (Render fournit $PORT)
CMD ["sh", "-c", "streamlit run main.py --server.port=${PORT:-8501} --server.address=0.0.0.0"]
