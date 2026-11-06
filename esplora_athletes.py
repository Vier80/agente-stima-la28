"""Esplora i db Notion degli atleti (seconda passata): non scrive nulla, legge soltanto.

Scopo: capire com'e' fatto il db Athletes e il db dei risultati (MASTER RESULTS), per costruire poi
l'agente che stima le qualificazioni a LA28. Il risultato va nel log e nel file esplora_athletes.txt.
"""
import json
import os
import sys
import time

import requests

TOKEN = os.environ.get("NOTION_TOKEN", "").strip()
if not TOKEN:
    sys.exit("Manca il segreto NOTION_TOKEN.")

API = "https://api.notion.com/v1"
HEAD = {"Authorization": "Bearer " + TOKEN, "Notion-Version": "2022-06-28", "Content-Type": "application/json"}
OUT = open("esplora_athletes.txt", "w", encoding="utf-8")


def say(*a):
    line = " ".join(str(x) for x in a)
    print(line, flush=True)
    OUT.write(line + "\n")


def call(method, path, body=None):
    for attempt in range(6):
        r = requests.request(method, API + path, headers=HEAD, json=body, timeout=60)
        if r.status_code == 429:
            time.sleep(float(r.headers.get("Retry-After", "2")) + 0.5)
            continue
        if r.status_code >= 500:
            time.sleep(2 + attempt)
            continue
        if r.status_code >= 400:
            raise RuntimeError(f"Notion ha risposto {r.status_code} su {path}: {r.text[:300]}")
        time.sleep(0.35)
        return r.json()
    raise RuntimeError("Notion non risponde: riprova piu' tardi.")


def plain(rich):
    return "".join(x.get("plain_text", "") for x in rich or [])


def flat(p, depth=0):
    """Trasforma il valore di una proprieta' Notion in un testo corto e leggibile."""
    t = p.get("type")
    v = p.get(t)
    if t in ("title", "rich_text"):
        return plain(v)
    if t in ("select", "status"):
        return v["name"] if v else ""
    if t == "multi_select":
        return "|".join(x["name"] for x in v or [])
    if t in ("number", "checkbox", "url", "email", "phone_number"):
        return "" if v is None else v
    if t == "date":
        return "" if not v else (v["start"] + (" -> " + v["end"] if v.get("end") else ""))
    if t == "relation":
        return f"[{len(v or [])} collegamenti{'+' if p.get('has_more') else ''}]"
    if t == "formula":
        return flat(v, depth + 1) if v else ""
    if t == "rollup":
        if not v:
            return ""
        rt = v.get("type")
        if rt == "array":
            return "{" + ";".join(str(flat(x, depth + 1)) for x in v["array"][:6]) + ("..." if len(v["array"]) > 6 else "") + "}"
        return flat(v, depth + 1)
    if t in ("string", "boolean"):
        return v
    if t == "place":
        return v.get("name", "") if v else ""
    if t in ("created_time", "last_edited_time"):
        return v
    if t in ("files",):
        return f"[{len(v or [])} file]"
    return f"<{t}>"


def row_text(page, skip_empty=True):
    parts = []
    for name, p in page["properties"].items():
        val = flat(p)
        if skip_empty and val in ("", None, False, "{}", "[0 collegamenti]"):
            continue
        parts.append(f"{name}={val}")
    return " | ".join(parts)


def query(dbid, flt=None, limit=None):
    out, cur = [], None
    while True:
        body = {"page_size": 100}
        if flt:
            body["filter"] = flt
        if cur:
            body["start_cursor"] = cur
        r = call("POST", f"/databases/{dbid}/query", body)
        out += r["results"]
        if limit and len(out) >= limit:
            return out[:limit]
        if not r.get("has_more"):
            return out
        cur = r["next_cursor"]



def short(t, n=700):
    return t if len(t) <= n else t[:n] + " ..."


def nid(x):
    return (x or "").replace("-", "").lower()


def sel(pr, name):
    return flat(pr.get(name, {"type": "select", "select": None}))


say("=== 1. Database visibili alla connessione ===")
dbs, cur = [], None
while True:
    body = {"filter": {"property": "object", "value": "database"}, "page_size": 100}
    if cur:
        body["start_cursor"] = cur
    r = call("POST", "/search", body)
    dbs += r["results"]
    if not r.get("has_more"):
        break
    cur = r["next_cursor"]
for d in dbs:
    title = plain(d.get("title"))
    names = list(d["properties"].keys())
    say(f"  {title!r}  id={d['id']}  proprieta'={len(names)}" + ("  -> " + ", ".join(names[:12]) if not title else ""))


def find(*needles):
    for d in dbs:
        t = plain(d.get("title")).lower()
        if any(n.lower() in t for n in needles):
            return d
    return None


ATH = find("athletes")
RA = next((d for d in dbs if plain(d.get("title")).strip() == "Risultati A"), None)
RB = next((d for d in dbs if plain(d.get("title")).strip() == "Risultati B"), None)
OTHERS = [
    ("Direct Q Events", find("direct q events")),
    ("Qualification Schedule", find("qualification schedule")),
    ("Qualification System", find("qualification system")),
    ("World Rankings", find("world rankings")),
    ("Tempi Limite", find("tempi limite")),
    ("LA28 Sports Program", find("sports program", "home of the olympic")),
    ("Archivio Sport", find("archivio sport")),
    ("DB Events", find("db events")),
    ("Direct Event Winners", find("direct event winners")),
]
if not ATH:
    sys.exit("Manca il db Athletes.")

say("")
say("=== 2. Struttura dei db ===")
for label, d in [("Risultati A", RA), ("Risultati B", RB)] + OTHERS:
    if not d:
        say(f"-- {label}: NON TROVATO tra i db condivisi")
        continue
    say(f"-- {label}  (id {d['id']})")
    say("   " + " ; ".join(f"{k}:{v['type']}" for k, v in d["properties"].items()))

say("")
say("=== 3. Righe di esempio e contenuto dei db di supporto ===")
LIMITS = {"Qualification System": 40, "Qualification Schedule": 40, "Direct Q Events": 40, "World Rankings": 12,
          "Tempi Limite": 15, "LA28 Sports Program": 25, "Archivio Sport": 10, "DB Events": 10, "Direct Event Winners": 10}
for label, d in OTHERS:
    if not d:
        continue
    rows = query(d["id"], limit=LIMITS.get(label, 8))
    say(f"-- {label}: prime {len(rows)} righe")
    for r in rows:
        say("   - " + short(row_text(r), 600))

say("")
say("=== 4. Atleti italiani e risultati di esempio (Risultati A e B) ===")
ita = query(ATH["id"], {"property": "NOC", "select": {"equals": "🇮🇹ITA"}})
say(f"  atleti italiani: {len(ita)}")


def rel_prop(d):
    for k, v in d["properties"].items():
        if v["type"] == "relation" and nid(v["relation"].get("database_id")) == nid(ATH["id"]):
            return k
    return None


for label, d in [("Risultati A", RA), ("Risultati B", RB)]:
    if d:
        say(f"  {label}: la relazione verso Athletes si chiama {rel_prop(d)!r}")

SAMPLE = ["Judo", "Tennis", "Fencing", "Archery", "Boxing", "Wrestling", "Taekwondo", "Weightlifting", "Sport Climbing",
          "Shooting", "Swimming", "Athletics", "Table Tennis", "Canoe Slalom", "Cycling Track"]
for sp in SAMPLE:
    picks = [a for a in ita if sel(a["properties"], "Sport") == sp and
             flat(a["properties"].get("MASTER RESULTS", {"type": "relation", "relation": []})) != "[0 collegamenti]"][:1]
    for a in picks:
        say("")
        say(f"##### [{sp}] {flat(a['properties']['Cognome e Nome'])}  (pagina {a['id']})")
        for label, d in [("Risultati A", RA), ("Risultati B", RB)]:
            rp = rel_prop(d) if d else None
            if not rp:
                continue
            rows = query(d["id"], {"property": rp, "relation": {"contains": a["id"]}}, limit=4)
            say(f"   {label}: {len(rows)} righe lette (max 4)")
            for r in rows:
                say("     - " + short(row_text(r), 1100))

say("")
say("=== 5. Quanti risultati ci sono, per anno e per edizione (lettura completa) ===")
for label, d in [("Risultati A", RA), ("Risultati B", RB)]:
    if not d:
        continue
    rows = query(d["id"])
    say(f"-- {label}: {len(rows)} righe in tutto")
    k = {}
    for r in rows:
        pr = r["properties"]
        key = (sel(pr, "Edition") or "-", flat(pr.get("Anno", {"type": "number", "number": None})))
        k[key] = k.get(key, 0) + 1
    for key, n in sorted(k.items(), key=lambda x: -x[1])[:25]:
        say(f"   edizione={key[0]} anno={key[1]}: {n}")
    ev = {}
    for r in rows:
        e = sel(r["properties"], "Evento") or "-"
        ev[e] = ev.get(e, 0) + 1
    say("   eventi piu' frequenti: " + "; ".join(f"{e}={n}" for e, n in sorted(ev.items(), key=lambda x: -x[1])[:40]))

say("")
say("Esplorazione finita: non e' stato scritto nulla su Notion.")
OUT.close()
