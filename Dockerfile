# ---------- Image ----------
FROM python:3.11-slim

# ---------- ENV ----------
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false

# ---------- OS deps ----------
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
  && rm -rf /var/lib/apt/lists/*

# ---------- App dir ----------
WORKDIR /app
COPY requirements.txt /app/
RUN python -m pip install --upgrade pip && pip install -r requirements.txt

# tout le code
COPY . /app

# ---------- Run ----------
EXPOSE 8501
CMD ["sh", "-c", "python create_admin.py; streamlit run main.py --server.port=${PORT:-8501} --server.address=0.0.0.0"]
