# Despliegue 24/7 (gratis)

Tienes dos opciones. Ambas corren sin tu PC encendido.

## Opción A — GitHub Actions (RECOMENDADA: 100% gratis, ilimitado)

No consume crédito: GitHub permite cron jobs gratis en repos públicos. El script
corre cada 5 min y guarda su memoria (anuncios ya vistos) en un **GitHub Gist**,
para no reenviarte lo mismo entre ejecuciones.

### Pasos
1. Crea un repo en https://github.com/new (público, sin README).
2. Sube los archivos (usa `subir_a_github.ps1`).
3. Crea un **Gist** en https://gist.github.com (puede ser secreto) con un archivo
   cualquiera, y copia su ID de la URL (`https://gist.github.com/TUUSUARIO/<ID>`).
4. En el repo: **Settings → Secrets and variables → Actions → New repository secret**:
   - `WALLAPOP_GIST_ID` = el ID del gist (sin las comillas).
   - `GIST_TOKEN` = un token de GitHub con permiso `gist` (https://github.com/settings/tokens,
     marca "gist", expiración None).
5. En **Actions** del repo, habilita el workflow "Wallapop Scanner" (primera vez
   puede pedirte "Enable"). Se ejecutará solo cada 5 min.
6. Para la primera pasada de prueba, ve a Actions → Workflow → "Run workflow".

El workflow (` .github/workflows/scan.yml`) ya pasa esos secrets como variables
de entorno al script. El script usa el Gist para persistir `seen_items.json`.

## Opción B — Railway (más simple, free tier con crédito mensual)

1. Crea repo en GitHub (igual que arriba) y súbelo.
2. En https://railway.app → New Project → Deploy from GitHub repo.
3. Railway lee `railway.json` y arranca `python wallapop_scanner.py` (bucle cada 5 min).
4. El estado se guarda en el disco de Railway, así que no repite anuncios.
5. El free tier tiene crédito mensual; si se agota, pausa y reanuda el mes siguiente,
   o sube `check_interval_seconds` a 600 (10 min) para consumir la mitad.

## Comprobar que funciona
- GitHub Actions: pestaña Actions → verás cada ejecución y su log.
- Railway: pestaña Deploy → logs en vivo.
- Telegram: recibirás los avisos y el latido cada 6 pasadas sin novedad.

## Parar
- GitHub Actions: desactiva el workflow (botón en Actions).
- Railway: pausa el proyecto.
