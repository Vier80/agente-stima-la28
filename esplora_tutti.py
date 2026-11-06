"""Esplora i db Notion per la stima di TUTTI gli sport (terza passata): non scrive nulla, legge soltanto.

Scopo: capire com'e' fatto il db Athletes e il db dei risultati (MASTER RESULTS), per costruire poi
l'agente che stima le qualificazioni a LA28. Il risultato va nel log e nel file esplora_tutti.txt.
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
OUT = open("esplora_tutti.txt", "w", encoding="utf-8")


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



def nid(x):
    return (x or "").replace("-", "").lower()


def short(t, n=300):
    return t if len(t) <= n else t[:n] + " ..."


def numv(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def pk(props, *needles):
    for n in needles:
        for k in props:
            if n.lower().replace(" ", "") in k.lower().replace(" ", ""):
                return k
    return None


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


def find(*needles):
    for d in dbs:
        t = plain(d.get("title")).lower()
        if any(n.lower() in t for n in needles):
            return d
    return None


ATH = next(d for d in dbs if plain(d.get("title")).strip() == "Athletes")
P = ATH["properties"]
K_SPORT, K_DISC, K_NOC = pk(P, "Sport"), pk(P, "Disciplina"), pk(P, "NOC")
K_PASS = pk(P, "Pass LA28")
K_PQ = pk(P, "PTS Q")
K_PD = pk(P, "Punti per Disciplina")
K_TOT = pk(P, "TOT PTS")
K_POW = pk(P, "Power Score")
say("Colonne usate:", dict(sport=K_SPORT, disc=K_DISC, noc=K_NOC, pas=K_PASS, ptsq=K_PQ, punti_disc=K_PD, tot=K_TOT, power=K_POW))

say("")
say("=== A. Tutti gli atleti: lettura completa ===")
rows = query(ATH["id"])
say(f"atleti letti: {len(rows)}")
ath = []
for p in rows:
    pr = p["properties"]
    ath.append({
        "nome": flat(pr[pk(pr, "Cognome e Nome")]), "sport": flat(pr[K_SPORT]) or "-", "disc": flat(pr[K_DISC]),
        "noc": flat(pr[K_NOC]) or "-", "pas": flat(pr[K_PASS]) if K_PASS else "",
        "pq": numv(flat(pr[K_PQ])) if K_PQ else None, "pd": flat(pr[K_PD]) if K_PD else "",
        "tot": numv(flat(pr[K_TOT])) if K_TOT else None, "pow": numv(flat(pr[K_POW])) if K_POW else None,
    })

say("")
say("=== B. Per sport: atleti, italiani, con punti Q > 0, valori di Pass LA28, discipline (top 25) ===")
sports = {}
for a in ath:
    sports.setdefault(a["sport"], []).append(a)
for sp, lst in sorted(sports.items(), key=lambda x: -len(x[1])):
    ita = [a for a in lst if "ITA" in a["noc"]]
    conq = [a for a in lst if a["pq"]]
    pas = {}
    for a in lst:
        if a["pas"]:
            pas[a["pas"]] = pas.get(a["pas"], 0) + 1
    disc = {}
    for a in lst:
        for d in (a["disc"] or "(nessuna)").split("|"):
            disc[d] = disc.get(d, 0) + 1
    say(f"-- {sp}: atleti={len(lst)} italiani={len(ita)} con PTS Q>0={len(conq)} pass={pas}")
    say("   discipline: " + "; ".join(f"{d}={n}" for d, n in sorted(disc.items(), key=lambda x: -x[1])[:25]))

say("")
say("=== C. Esempi di punteggi (primi 4 per PTS Q in alcuni sport + italiani) ===")
for sp in ["Fencing", "Swimming", "Athletics", "Archery", "Shooting", "Boxing", "Weightlifting", "Rowing", "Sailing", "Sport Climbing"]:
    lst = sorted([a for a in sports.get(sp, []) if a["pq"]], key=lambda a: -a["pq"])
    say(f"-- {sp}")
    for a in lst[:4] + [a for a in lst if "ITA" in a["noc"]][:3]:
        say(f"   {a['nome']} | {a['noc']} | disc={a['disc']} | PTS Q={a['pq']} | per disciplina={short(a['pd'], 200)} | tot={a['tot']} | power={a['pow']}")

say("")
say("=== D. Direct Q Events e Qualification Schedule (tutte le righe) ===")
for label, d in [("Direct Q Events", find("direct q events")), ("Qualification Schedule", find("qualification schedule")),
                 ("Direct Event Winners", find("direct event winners"))]:
    if not d:
        say(f"-- {label}: NON TROVATO")
        continue
    rs = query(d["id"])
    say(f"-- {label}: {len(rs)} righe")
    for r in rs:
        say("   - " + short(row_text(r), 400))

say("")
say("=== E. Qualification System: file allegati per sport ===")
d = find("qualification system")
if d:
    for r in query(d["id"]):
        pr = r["properties"]
        sp = flat(pr[pk(pr, "Sport")]) if pk(pr, "Sport") else ""
        fk = pk(pr, "Files")
        files = pr[fk]["files"] if fk else []
        txt = flat(pr[pk(pr, "Text")]) if pk(pr, "Text") else ""
        say(f"   {sp}: {len(files)} file; testo={short(str(txt), 200)}")

say("")
say("Esplorazione finita: non e' stato scritto nulla su Notion.")
OUT.close()
