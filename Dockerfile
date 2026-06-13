# syntax=docker/dockerfile:1

# ============================================================================
# J.A.R.V.I.S — image Docker (mode serveur headless)
#
# Le conteneur fait tourner le backend (WebSocket 8765 + HTTP mobile 8080 +
# frontend statique 5173). Pas de micro / haut-parleur / GUI : le STT et le TTS
# se font cote navigateur (Web Speech API) via l'interface web ou mobile.
# main2.py detecte JARVIS_HEADLESS=1 et desactive la boucle vocale + l'audio local.
#
# Build :  docker build -t jarvis .
# Run   :  docker run --env-file .env -p 5173:5173 -p 8765:8765 -p 8080:8080 jarvis
# (ou plus simple : docker compose up -d)
# ============================================================================

# ---------- Etage 1 : build du frontend (Vite) ----------
FROM node:20-slim AS frontend
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm install
COPY frontend/ ./
RUN npm run build          # produit frontend/dist (index.html + dashboard.html)

# ---------- Etage 2 : runtime Python ----------
FROM python:3.12-slim AS runtime

# Dependances Python du mode headless (curated, voir requirements-docker.txt)
WORKDIR /app
COPY requirements-docker.txt ./
RUN pip install --no-cache-dir -r requirements-docker.txt

# Code de l'application (le .dockerignore exclut le superflu)
COPY . .

# Bundle frontend pre-build depuis l'etage 1
COPY --from=frontend /app/frontend/dist ./frontend/dist

# Mode serveur : pas de peripheriques, pas de navigateur a ouvrir
ENV JARVIS_HEADLESS=1 \
    JARVIS_NO_BROWSER=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8

# 5173 = UI orbe + dashboard | 8765 = WebSocket | 8080 = UI mobile
EXPOSE 5173 8765 8080

CMD ["python", "jarvis_core/main2.py"]
