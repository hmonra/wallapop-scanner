# Wallapop Scanner 🎮

Script en Python que monitoriza Wallapop y te avisa de nuevos anuncios de
**mandos de PS4 / PS5 rotos o baratos** antes que nadie, filtrando vendedores
sospechosos (cuentas fake / inactivas).

## Qué hace

- Busca continuamente anuncios nuevos (`order_by=newest`) dentro de tu rango de
  precio y palabras clave.
- Descarta anuncios de vendedores sospechosos usando señales públicas de la API
  (cuenta recién creada, sin historial de ventas/compras, sin valoraciones).
- Te avisa por **consola**, **archivo de log** y (opcional) **Telegram / notificación
  de Windows**.

> ⚠️ Nota sobre el filtro "última conexión": Wallapop **no expone** la última
> conexión del vendedor en su API pública (solo aparece en la app móvil). Por eso
> el script usa proxies: cuenta recién creada + cero actividad = muy probablemente
> fake/inactiva. Esto captura la mayoría de los casos que describes.

## Requisitos

- Python 3.10+
- `requests`:  `pip install requests`
- (Opcional) notificaciones de Windows: `pip install win10toast`

## Instalación

```powershell
cd "D:\Proyecto Walla-Scanner"
pip install requests
```

## Uso

Una sola pasada (ideal para programar con el Task Scheduler):

```powershell
python wallapop_scanner.py --once
```

Modo monitor continuo (se queda corriendo, revisando cada `check_interval_seconds`):

```powershell
python wallapop_scanner.py
```

Configurar Telegram:

```powershell
python wallapop_scanner.py --setup
```

## Configuración (`config.json`)

- `check_interval_seconds`: cada cuánto revisa (en segundos).
- `location`: lat/lng para centrar la búsqueda (por defecto Madrid, España).
- `searches`: lista de búsquedas. Cada una con `keywords` (puedes poner varias
  variantes), `min_price`, `max_price`, `order_by`.
- `filters`:
  - `min_seller_published`: mínimo de anuncios publicados por el vendedor.
  - `max_seller_account_age_days`: descarta cuentas más viejas que esto (posible inactiva).
  - `require_top_profile_or_sales`: exige perfil top o al menos 1 venta.
  - `exclude_keywords`: descarta títulos que contengan estas palabras.
  - `max_item_age_hours_to_notify`: solo avisa de anuncios más nuevos que esto.
- `notifications`: activa/desactiva consola, log, escritorio y Telegram.

## Automatización (sin dejar la ventana abierta)

Crea una tarea en el **Programador de tareas de Windows** que ejecute:

```
python "D:\Proyecto Walla-Scanner\wallapop_scanner.py" --once
```

cada minuto. De ese modo el script corre en segundo plano y las alertas se
acumulan en `alerts.log` y/o te llegan por Telegram.

## Cómo ajustar tus búsquedas

Edita `config.json` -> `searches`. Ejemplo para mandos PS4 a 5€ o menos y PS5 a
15-18€:

```json
{
  "name": "PS4 baratos",
  "keywords": ["mando ps4", "mando ps4 roto", "ps4 drift"],
  "min_price": 1, "max_price": 5, "order_by": "newest"
}
```

## Notas legales

Wallapop no tiene API pública oficial; este script usa endpoints no documentados
a modo de investigación personal. No hagas demasiadas peticiones seguidas (respeta
el `check_interval_seconds`) para no saturar el servicio. Úsalo bajo tu propia
responsabilidad y respeta los Términos de Servicio de Wallapop.
