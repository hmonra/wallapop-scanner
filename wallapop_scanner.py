#!/usr/bin/env python3
"""
Wallapop Scanner - Monitor de anuncios de mandos PS4/PS5 rotos o baratos.

Busca continuamente nuevos anuncios en Wallapop que cumplan tus criterios de
precio y palabras clave, filtra vendedores sospechosos (cuentas nuevas, sin
actividad de ventas, etc.) y te avisa por consola, archivo y (opcional) Telegram.

Uso:
    python wallapop_scanner.py          # modo monitor continuo
    python wallapop_scanner.py --once   # una sola pasada (útil para programar con el Task Scheduler)
    python wallapop_scanner.py --setup  # guía para configurar Telegram

Requiere: requests
    pip install requests
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

try:
    import requests
except ImportError:
    print("ERROR: falta el modulo 'requests'. Instalalo con: pip install requests")
    sys.exit(1)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")

API_BASE = "https://api.wallapop.com/api/v3"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Origin": "https://es.wallapop.com",
    "Referer": "https://es.wallapop.com/",
    "X-DeviceOS": "0",
}

# Persistencia de estado en GitHub Gist (usado en GitHub Actions). Se configura
# con la variable de entorno GITHUB_TOKEN y el id de gist en config.json.
GH_STATE = {
    "gist_id": os.environ.get("WALLAPOP_GIST_ID", ""),
    "token": os.environ.get("GITHUB_TOKEN", ""),
}


def load_config():
    if not os.path.exists(CONFIG_PATH):
        print(f"ERROR: no existe {CONFIG_PATH}")
        sys.exit(1)
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def load_state(state_file):
    # Si hay Gist configurado (modo GitHub Actions), cargar desde ahi
    gist = GH_STATE.get("gist_id")
    token = GH_STATE.get("token")
    if gist and token:
        try:
            r = requests.get(
                f"https://api.github.com/gists/{gist}",
                headers={"Authorization": f"token {token}"},
                timeout=15,
            )
            if r.status_code == 200:
                files = r.json().get("files", {})
                if state_file in files:
                    return json.loads(files[state_file]["content"])
        except Exception as e:
            print(f"  [!] No se pudo cargar estado del Gist: {e}")
    path = os.path.join(BASE_DIR, state_file)
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                return {"seen": []}
    return {"seen": []}


def save_state(state_file, state):
    gist = GH_STATE.get("gist_id")
    token = GH_STATE.get("token")
    if gist and token:
        try:
            content = json.dumps(state, ensure_ascii=False, indent=2)
            r = requests.patch(
                f"https://api.github.com/gists/{gist}",
                headers={"Authorization": f"token {token}"},
                json={"files": {state_file: {"content": content}}},
                timeout=15,
            )
            if r.status_code not in (200, 201):
                print(f"  [!] No se pudo guardar estado en Gist: {r.status_code}")
            return
        except Exception as e:
            print(f"  [!] Error guardando estado en Gist: {e}")
    path = os.path.join(BASE_DIR, state_file)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def search_items(keywords, min_price, max_price, order_by, location):
    params = {
        "keywords": keywords,
        "min_sale_price": min_price,
        "max_sale_price": max_price,
        "order_by": order_by,
        "source": "keywords",
        "step": 1,
        "limit": 40,
        "latitude": location["latitude"],
        "longitude": location["longitude"],
        "country_code": location.get("country_code", "ES"),
    }
    try:
        r = requests.get(f"{API_BASE}/search", params=params, headers=HEADERS, timeout=20)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        print(f"  [!] Error en búsqueda '{keywords}': {e}")
        return []

    items = []
    section = data.get("data", {}).get("section")
    if section and isinstance(section, dict):
        payload = section.get("payload", {})
        items = payload.get("items", []) if isinstance(payload, dict) else []
    # Fallback por si la estructura cambia
    if not items:
        items = data.get("data", {}).get("items", []) or data.get("search_objects", [])
    return items


def _get_json(url, retries=3):
    for attempt in range(retries):
        try:
            r = requests.get(url, headers=HEADERS, timeout=15)
            if r.status_code == 429:
                wait = 5 * (attempt + 1)
                print(f"  [!] Rate limit (429). Esperando {wait}s...")
                time.sleep(wait)
                continue
            r.raise_for_status()
            return r.json()
        except Exception:
            if attempt < retries - 1:
                time.sleep(2)
                continue
            return None
    return None


def get_user(user_id):
    return _get_json(f"{API_BASE}/users/{user_id}")


def get_user_stats(user_id):
    return _get_json(f"{API_BASE}/users/{user_id}/stats")


def user_is_suspicious(user, stats, filters, now_ms):
    """Devuelve (es_sospechoso, motivo, contadores).

    Por defecto el filtro anti-fake esta DESACTIVADO: no se descarta a nadie,
    porque un vendedor real puede acabar de crear la cuenta para subir justo
    ese anuncio y no queremos perdernos la ganga. Los contadores del vendedor
    se siguen mostrando en el aviso para que TU decidas si escribirle.

    Para reactivarlo: pon "enable_antifake": true en config.json -> filters.
    """
    counters = {"publish": 0, "sells": 0, "buys": 0, "reviews": 0}
    if stats:
        c = stats.get("counters", {})
        if isinstance(c, dict):
            for k in counters:
                counters[k] = c.get(k, 0) or 0
        elif isinstance(c, list):
            for entry in c:
                if isinstance(entry, dict) and "type" in entry:
                    counters[entry.get("type")] = entry.get("value") or 0

    if not filters.get("enable_antifake", False):
        return False, "", counters

    published = counters["publish"]
    sells = counters["sells"]
    buys = counters["buys"]
    reviews = counters["reviews"]

    reg = user.get("register_date")
    if reg:
        age_days = (now_ms - reg) / 86400000.0
        max_new = filters.get("max_new_account_age_days", 30)
        if age_days < max_new and sells == 0 and buys == 0 and reviews == 0:
            return True, f"cuenta de solo {age_days:.0f} dias y sin actividad", counters

    min_published = filters.get("min_seller_published", 0)
    if min_published > 0 and published < min_published:
        return True, f"solo {published} anuncios publicados", counters

    if filters.get("require_top_profile_or_sales", False):
        if not user.get("is_top_profile") and sells == 0:
            return True, "sin ventas ni perfil top (posible cuenta fake)", counters

    if stats is not None and sells == 0 and buys == 0 and reviews == 0 and published == 0:
        return True, "sin historial de actividad (posible cuenta fake)", counters

    return False, "", counters


def title_has_excluded(title, exclude_keywords):
    t = title.lower()
    for kw in exclude_keywords:
        if kw.lower() in t:
            return kw
    return None


def item_age_hours(created_at_ms, now_ms):
    return (now_ms - created_at_ms) / 3600000.0


def format_age(age_h):
    """Convierte horas (float) a texto legible: 'hace 14 h 6 min'."""
    total_min = int(age_h * 60)
    if total_min < 1:
        return "hace menos de 1 min"
    if total_min < 60:
        return f"hace {total_min} min"
    hours = total_min // 60
    minutes = total_min % 60
    if minutes == 0:
        return f"hace {hours} h"
    return f"hace {hours} h {minutes} min"


def resolve_telegram_chat_id(token):
    """Intenta obtener el chat_id del ultimo mensaje recibido por el bot."""
    try:
        r = requests.get(f"https://api.telegram.org/bot{token}/getUpdates", timeout=15)
        data = r.json()
        if data.get("ok") and data.get("result"):
            for upd in reversed(data["result"]):
                chat = (upd.get("message") or upd.get("edited_message") or {}).get("chat")
                if chat and chat.get("id"):
                    return str(chat["id"])
    except Exception:
        pass
    return None


def log_telegram(line):
    try:
        with open(os.path.join(BASE_DIR, "telegram.log"), "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def send_telegram(cfg, message):
    t = cfg.get("notifications", {}).get("telegram", {})
    if not t.get("enabled"):
        return False
    token = t.get("bot_token")
    chat_id = t.get("chat_id")
    if not token:
        return False
    if not chat_id:
        chat_id = resolve_telegram_chat_id(token)
        if chat_id:
            t["chat_id"] = chat_id
            try:
                with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                    raw = json.load(f)
                raw.setdefault("notifications", {}).setdefault("telegram", {})["chat_id"] = chat_id
                with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                    json.dump(raw, f, ensure_ascii=False, indent=2)
                print(f"  [i] chat_id de Telegram guardado: {chat_id}")
            except Exception:
                pass
    if not chat_id:
        return False
    last_err = None
    for attempt in range(3):
        try:
            r = requests.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat_id, "text": message, "parse_mode": "HTML"},
                timeout=10,
            )
            j = r.json()
            if j.get("ok"):
                return True
            last_err = j.get("description")
            log_telegram(f"FAIL {r.status_code} {j.get('description')} :: {message[:60]}")
        except Exception as e:
            last_err = str(e)
            log_telegram(f"EXC {e} :: {message[:60]}")
        time.sleep(1)
    print(f"  [!] Telegram NO enviado: {last_err}")
    return False


def notify(cfg, items_to_report, search_name):
    n = cfg.get("notifications", {})
    if not items_to_report:
        return

    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = [f"[ALERTA] {ts} - {search_name} - {len(items_to_report)} nuevo(s) anuncio(s)"]
    for it in items_to_report:
        lines.append("-" * 50)
        lines.append(f"  {it['title']}")
        lines.append(f"  Precio: {it['price']} EUR  |  {it['location']}")
        lines.append(f"  Vendedor: {it['seller']}  ({it['seller_info']})")
        lines.append(f"  Publicado: {it['age']}  |  {it['shipping']}")
        lines.append(f"  {it['url']}")

    msg = "\n".join(lines)

    if n.get("console", True):
        print("\n" + msg + "\n")

    if n.get("log_file"):
        log_path = os.path.join(BASE_DIR, n["log_file"])
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(msg + "\n\n")

    if n.get("desktop", True):
        try:
            from win10toast import ToastNotifier
            ToastNotifier().show_toast(
                f"Wallapop: {search_name}",
                f"{len(items_to_report)} nuevo(s) anuncio(s). Primero: {items_to_report[0]['title'][:60]}",
                duration=10,
            )
        except Exception:
            pass

    # Telegram: UN mensaje por anuncio (enlace clicable), para que cada alerta
    # llegue por separado y se pueda tocar directo. Respeta el limite de 4096
    # chars y pausa entre envios para no saturar la API de Telegram.
    header = f"🔎 <b>Wallapop - {search_name}</b>"
    tg_sent = 0
    for it in items_to_report:
        tg = (
            f"{header}\n"
            f"🔔 <a href=\"{it['url']}\">{it['title']}</a>\n"
            f"💶 {it['price']} EUR  📍 {it['location']}\n"
            f"👤 {it['seller']} ({it['seller_info']}) · {it['age']} · {it['shipping']}"
        )
        if len(tg) > 4000:
            tg = tg[:3990] + "..."
        ok = send_telegram(cfg, tg)
        if ok:
            tg_sent += 1
        time.sleep(0.5)
    print(f"  [i] Telegram: enviados {tg_sent}/{len(items_to_report)} para '{search_name}'")


def run_once(cfg, initial=False):
    state = load_state(cfg.get("state_file", "seen_items.json"))
    seen = set(state.get("seen", []))
    now_ms = int(time.time() * 1000)
    new_count = 0
    initial_limit = cfg.get("initial_send_count", 10)

    # Resolver y guardar el chat_id de Telegram al arrancar (si esta vacio)
    tcfg = cfg.get("notifications", {}).get("telegram", {})
    if tcfg.get("enabled") and tcfg.get("bot_token") and not tcfg.get("chat_id"):
        resolved = resolve_telegram_chat_id(tcfg["bot_token"])
        if resolved:
            tcfg["chat_id"] = resolved
            try:
                with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                    json.dump(cfg, f, ensure_ascii=False, indent=2)
                print(f"  [i] chat_id de Telegram guardado: {resolved}")
            except Exception:
                pass

    for s in cfg.get("searches", []):
        name = s.get("name", s.get("keywords"))
        keywords_list = s.get("keywords", [])
        min_p = s.get("min_price", 1)
        max_p = s.get("max_price", 100)
        order = s.get("order_by", "newest")
        loc = cfg.get("location", {})
        flt = cfg.get("filters", {})
        max_age = flt.get("max_item_age_hours_to_notify", 72)

        print(f"[*] Buscando: {name} ({keywords_list})")
        collected = {}
        for kw in keywords_list:
            for it in search_items(kw, min_p, max_p, order, loc):
                collected[it["id"]] = it

        for it in collected.values():
            if it["id"] in seen:
                continue

            # Filtro por edad del anuncio
            age_h = item_age_hours(it.get("created_at", now_ms), now_ms)
            if age_h > max_age:
                seen.add(it["id"])
                continue

            title = it.get("title", "")
            excl = title_has_excluded(title, flt.get("exclude_keywords", []))
            if excl:
                seen.add(it["id"])
                print(f"  [-]Descartado (contiene '{excl}'): {title}")
                continue

            # Filtro de relevancia: el titulo debe mencionar alguna de estas
            # palabras (utl para descartar juegos/accesorios que Wallapop
            # devuelve igual con la keyword "mando ps4").
            must = flt.get("must_mention", [])
            if must and not any(k.lower() in title.lower() for k in must):
                seen.add(it["id"])
                print(f"  [-]Descartado (no es mando): {title}")
                continue

            req_kw = flt.get("require_keywords_in_title", [])
            if req_kw and not any(k.lower() in title.lower() for k in req_kw):
                seen.add(it["id"])
                continue

            # Filtro de originalidad: descarta mandos no oficiales / third-party
            if flt.get("require_original", False):
                tl = title.lower()
                non_original = [
                    "compatible", "alternativo", "alternativa", "generico", "gen", "marca",
                    "third party", "third-party", "no original", "no oficial", "reacondicionado",
                    "recambio", "universal", "clone", "clon", "fake", "imitation",
                ]
                if any(k in tl for k in non_original):
                    seen.add(it["id"])
                    print(f"  [-]Descartado (no original): {title}")
                    continue

            # Filtro anti-fake: inspeccionar vendedor
            uid = it.get("user_id")
            user = get_user(uid) if uid else None
            stats = get_user_stats(uid) if uid else None
            time.sleep(0.4)
            susp, reason, counters = user_is_suspicious(user, stats, flt, now_ms)
            if susp:
                seen.add(it["id"])
                print(f"  [-]Descartado (vendedor sospechoso: {reason}): {title}")
                continue

            seller_name = (user or {}).get("micro_name", "desconocido")
            seller_info = f"top={ (user or {}).get('is_top_profile') }"
            seller_info += f" | pub={counters['publish']} vend={counters['sells']} comp={counters['buys']}"

            # Modo de venta: si el vendedor NO acepta envio, es solo en persona
            # (recogida en mano). Util para descartar vendedores lejanos.
            ship = it.get("shipping", {})
            allows_shipping = ship.get("user_allows_shipping", True) if isinstance(ship, dict) else True
            shipping_tag = "📦 Envío" if allows_shipping else "🤝 Solo en persona"

            seen.add(it["id"])
            new_count += 1
            it_url = f"https://es.wallapop.com/item/{it.get('web_slug', it['id'])}"
            report = {
                "title": title,
                "price": it.get("price", {}).get("amount"),
                "location": it.get("location", {}).get("city", "??"),
                "seller": seller_name,
                "seller_info": seller_info,
                "age": format_age(age_h),
                "url": it_url,
                "shipping": shipping_tag,
            }
            if not hasattr(run_once, "_reports"):
                run_once._reports = {}
            run_once._reports.setdefault(name, []).append(report)

    # Notificar agrupado por búsqueda
    reports = getattr(run_once, "_reports", {})
    if initial:
        # En el envio inicial mandamos los N ultimos validos como prueba,
        # sin importar si ya se habian visto.
        for sname in reports:
            reports[sname] = reports[sname][-initial_limit:]
        header_msg = (f"🚀 <b>Wallapop Scanner iniciado</b>\n"
                      f"Te enviare un maximo de {initial_limit} anuncios de prueba por busqueda. "
                      f"Luego solo te avisare de los NUEVOS cada ciclo.")
        send_telegram(cfg, header_msg)
        time.sleep(0.5)
    for sname, items in reports.items():
        print(f"  [i] Notificando {len(items)} anuncios de '{sname}'")
        notify(cfg, items, sname)
    run_once._reports = {}

    # Recortar seen para no crecer indefinidamente
    if len(seen) > 5000:
        seen = set(list(seen)[-3000:])
    state["seen"] = list(seen)
    pass_count = state.get("pass_count", 0) + 1
    state["pass_count"] = pass_count
    save_state(cfg.get("state_file", "seen_items.json"), state)

    # Heartbeat: si no hubo novedades, avisar cada N pasadas (solo debug)
    hb = cfg.get("heartbeat", {})
    if hb.get("enabled") and new_count == 0:
        every = hb.get("every_n_passes", 6)
        if pass_count % every == 0:
            msg = (f"💓 <b>Wallapop Scanner - latido</b>\n"
                   f"Pasada #{pass_count} realizada. 0 mandos nuevos encontrados.\n"
                   f"El scanner sigue activo y vigilando.")
            ok = send_telegram(cfg, msg)
            print(f"  [i] Heartbeat enviado: {ok} (pass {pass_count}, every {every})")

    print(f"[+] Pasada completada. {new_count} nuevo(s) anuncio(s) en Total.")
    return new_count


def main():
    parser = argparse.ArgumentParser(description="Wallapop Scanner")
    parser.add_argument("--once", action="store_true", help="Ejecuta una sola pasada y sale")
    parser.add_argument("--initial", action="store_true", help="En la primera pasada envia los N ultimos anuncios validos como prueba")
    parser.add_argument("--setup", action="store_true", help="Ayuda para configurar Telegram")
    args = parser.parse_args()

    if args.setup:
        print("Para recibir alertas por Telegram:")
        print("1. Habla con @BotFather en Telegram y crea un bot ( /newbot ).")
        print("2. Copia el token que te da y pégalo en config.json -> notifications.telegram.bot_token")
        print("3. Escribe a @myidbot y copia tu chat_id en notifications.telegram.chat_id")
        print("4. Pon notifications.telegram.enabled = true")
        return

    cfg = load_config()
    interval = cfg.get("check_interval_seconds", 60)

    print(f"=== Wallapop Scanner iniciado ===")
    print(f"Intervalo: {interval}s | Búsquedas: {len(cfg.get('searches', []))}")

    if args.once:
        run_once(cfg, initial=args.initial)
        return

    first = True
    while True:
        try:
            run_once(cfg, initial=(first and args.initial))
        except Exception as e:
            print(f"[!] Error inesperado: {e}")
        first = False
        print(f"[*] Esperando {interval}s...\n")
        time.sleep(interval)


if __name__ == "__main__":
    main()
