"""Esplora i db Notion degli atleti: non scrive nulla, legge soltanto.

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
by_title = {}
for d in dbs:
    title = plain(d.get("title"))
    by_title.setdefault(title, d)
    say(f"  {title!r}  id={d['id']}  proprieta'={len(d['properties'])}")

WANT = ["Athletes", "MASTER RESULTS", "Nations", "LA28 Sports Program", "🎟️ Direct Q Events LA28", "MASTER MINOR"]
say("")
say("=== 2. Struttura dei db che servono ===")
found = {}
for w in WANT:
    d = by_title.get(w)
    if not d:
        say(f"  !! NON TROVATO: {w!r}. Il db non e' condiviso con la connessione (vedi guida) oppure ha un altro nome.")
        continue
    found[w] = d
    say(f"-- {w}  (id {d['id']})")
    say("   " + " ; ".join(f"{k}:{v['type']}" for k, v in d["properties"].items()))
if "Athletes" not in found:
    sys.exit("Senza il db Athletes non posso andare avanti.")

ath_id = found["Athletes"]["id"]
say("")
say("=== 3. Atleti italiani per sport (e quanti con Pass LA28 = Q) ===")
noc_opts = [o["name"] for o in found["Athletes"]["properties"]["NOC"]["select"]["options"] if "ITA" in o["name"]]
say("  opzioni NOC con ITA:", noc_opts)
ita = []
for n in noc_opts:
    ita += query(ath_id, {"property": "NOC", "select": {"equals": n}})
say(f"  atleti italiani letti: {len(ita)}")
cnt = {}
for a in ita:
    pr = a["properties"]
    sp = flat(pr["Sport"]) if "Sport" in pr else ""
    q = flat(pr.get("🎟️Pass LA28", {"type": "select", "select": None}))
    c = cnt.setdefault(sp or "(vuoto)", [0, 0])
    c[0] += 1
    c[1] += 1 if q == "Q" else 0
for sp, (n, q) in sorted(cnt.items(), key=lambda x: -x[1][0]):
    say(f"  {sp:24} atleti={n:4}  Q={q}")

SAMPLE_SPORTS = ["Judo", "Tennis", "Fencing", "Archery", "Boxing", "Wrestling", "Taekwondo", "Table Tennis", "Weightlifting", "Equestrian"]
say("")
say("=== 4. Esempi: scheda atleta + suoi risultati (tutte le proprieta' con un valore) ===")
res_db = found.get("MASTER RESULTS")
for sp in SAMPLE_SPORTS:
    picks = [a for a in ita if flat(a["properties"].get("Sport", {"type": "select", "select": None})) == sp][:2]
    for a in picks:
        say("")
        say(f"##### [{sp}] ATLETA: " + row_text(a))
        if not res_db:
            continue
        rows = query(res_db["id"], {"property": "Athlete", "relation": {"contains": a["id"]}}, limit=6)
        say(f"   risultati letti (max 6): {len(rows)}")
        for r in rows:
            say("   - " + row_text(r))

say("")
say("=== 5. Altri db: 4 righe di esempio ciascuno ===")
for w in ["Nations", "LA28 Sports Program", "🎟️ Direct Q Events LA28", "MASTER MINOR"]:
    d = found.get(w)
    if not d:
        continue
    say(f"-- {w}")
    for r in query(d["id"], limit=4):
        say("   - " + row_text(r))

say("")
say("=== 6. Conteggio dei risultati per Sport, Edition e Anno (campione: primi 1500 risultati) ===")
if res_db:
    rows = query(res_db["id"], limit=1500)
    k = {}
    for r in rows:
        pr = r["properties"]
        key = (flat(pr.get("Sport", {"type": "select", "select": None})) or "(vuoto)",
               flat(pr.get("Edition", {"type": "select", "select": None})) or "(vuoto)",
               flat(pr.get("Anno", {"type": "number", "number": None})))
        k[key] = k.get(key, 0) + 1
    for key, n in sorted(k.items(), key=lambda x: -x[1])[:60]:
        say(f"  {key}: {n}")

say("")
say("Esplorazione finita: non e' stato scritto nulla su Notion.")
OUT.close()
