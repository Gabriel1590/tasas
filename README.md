# Tasas · ¿Cómo pago?

Calculadora de precios para Venezuela (BCV $, BCV €, USDT Binance P2P) con comparador de formas de pago.

## Deploy (una vez, ~5 min)
1. Crea un repo en GitHub y sube todos estos archivos (con la carpeta `.github`).
2. Settings → Pages → Source: *Deploy from a branch* → `main` / `/ (root)` → Save.
3. Actions → *Update rates* → *Run workflow*. Eso genera el primer `rates.json`.
4. Abre `https://TU-USUARIO.github.io/TU-REPO/` en el teléfono → *Añadir a pantalla de inicio*.

Después de eso el workflow corre solo cada 30 min y la app se refresca cada 10 min mientras esté abierta y cada vez que la vuelvas a abrir.

## Fuentes
- `usd`, `eur`: página oficial del BCV (bcv.org.ve); si falla, pydolarve.org.
- `usdt`: mediana de los 10 primeros anuncios SELL USDT/VES en Binance P2P.

Si una fuente falla, se conserva el valor anterior y el error queda en `rates.json → errors`.
Cambia la frecuencia en `.github/workflows/rates.yml` (`cron`). Ojo: GitHub puede retrasar los crons unos minutos.
