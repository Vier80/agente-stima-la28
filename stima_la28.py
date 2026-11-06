"""Agente "Stima qualificazione LA28" degli atleti e delle squadre italiane.

Cosa fa, ogni volta che parte:
 1. legge dal tuo Notion gli atleti italiani (db Athletes) e le simulazioni gia' prodotte dagli altri agenti
    (LA 28 Judo, LA28 Taekwondo, Previsioni Wrestling LA28, LA28 Tennis, LA28 Canoe, LA28 Cycling);
 2. per ogni atleta o squadra calcola un livello (Certo / Probabile / Possibile / Remoto / Fuori) e una percentuale;
 3. scrive il risultato nel database Notion "Stima LA28" (solo le righe cambiate) e crea stima_la28.json per la pagina web.

Regole fisse:
 - se in Athletes la colonna "Pass LA28" vale Q, l'atleta e' CERTO (100%);
 - la colonna "Status LA28" di Athletes NON viene mai usata;
 - gli sport invernali sono esclusi;
 - judo, taekwondo, lotta, tennis, canoa e ciclismo usano le simulazioni gia' presenti in Notion;
 - tutte le altre discipline estive usano le regole del CIO (file regole_la28.py) applicate ai punteggi del db Athletes
   (classifica per prova di tutte le nazioni, limite per nazione, posti disponibili): stima approssimata, da affinare;
 - chi non ha punteggi o ranking utilizzabili compare come "Dati insufficienti".
La percentuale e' una stima euristica (vedi METODO nel file e la pagina web), non un calcolo ufficiale.

Variabili: NOTION_TOKEN, NOTION_DATABASE_ID (il db "Stima LA28"), DRY_RUN (true = non scrive su Notion).
"""
import hashlib
import json
import math
import os
import re
import sys
import time
import unicodedata
from datetime import date, datetime, timezone

import requests

from regole_la28 import RULES, sport_canonico

NOTION_TOKEN = os.environ.get("NOTION_TOKEN", "").strip()
_RAW_ID = os.environ.get("NOTION_DATABASE_ID", "").strip()
_m = re.search(r"[0-9a-fA-F]{8}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{12}", _RAW_ID)
# accetta sia l'ID da solo sia il link intero copiato da Notion: ne estrae i 32 caratteri dell'ID
DATABASE_ID = _m.group(0).replace("-", "").lower() if _m else _RAW_ID
DRY_RUN = os.environ.get("DRY_RUN", "").strip().lower() in ("1", "true", "yes", "si", "sì")
JSON_OUT = "stima_la28.json"
OGGI = date.today()

API = "https://api.notion.com/v1"
HEAD = {"Authorization": "Bearer " + NOTION_TOKEN, "Notion-Version": "2022-06-28", "Content-Type": "application/json"}

# --------------------------------------------------------------------------- parametri del metodo
ALT_ROUTE = 0.08          # chance residua (continentali / riassegnazioni) per chi e' fuori ma vicino alla soglia
VICINO = 2.0              # "vicino" = ranking entro 2 volte la soglia
BASE_STATO = {"in attesa": 0.05}
VIA_FISSA = [             # (parola nella via, probabilita') per chi e' dentro ma non per ranking diretto
    ("universal", 0.05), ("invito", 0.05), ("riassegn", 0.35), ("continent", 0.50),
    ("grand slam", 0.60), ("champ", 0.60), ("ospitant", 0.90), ("paese", 0.90),
]
IN_STATI = {"provvisorio", "qualificato"}
SOGLIE = [(70, "Probabile"), (35, "Possibile"), (8, "Remoto"), (0, "Fuori")]
LIVELLI = ["Certo", "Probabile", "Possibile", "Remoto", "Fuori", "Dati insufficienti"]
COLORI = {"Certo": "green", "Probabile": "blue", "Possibile": "yellow", "Remoto": "orange", "Fuori": "gray",
          "Dati insufficienti": "default"}

# (etichetta sport, titoli possibili del db, fine del periodo di qualificazione, copertura completa?)
SIMS = [
    ("Judo", ["la 28 judo", "la28 judo"], date(2028, 6, 12), True),
    ("Taekwondo", ["la28 taekwondo", "la 28 taekwondo"], date(2028, 5, 16), True),
    ("Tennis", ["la28 tennis", "la 28 tennis"], date(2028, 6, 30), False),
    ("Canoa", ["la28 canoe", "la 28 canoe"], date(2028, 6, 30), False),
    ("Ciclismo", ["la28 cycling", "la 28 cycling"], date(2028, 6, 30), False),
]
WRESTLING_TITLES = ["previsioni wrestling la28"]
WRESTLING_END = date(2028, 6, 30)
# sport di Athletes coperti da una simulazione -> etichetta sport usata nelle simulazioni
SPORT_DI_ATHLETES = {
    "Judo": "Judo", "Taekwondo": "Taekwondo", "Wrestling": "Wrestling", "Tennis": "Tennis",
    "Canoe Slalom": "Canoa", "Canoe Sprint": "Canoa", "Cycling": "Ciclismo", "Cycling Track": "Ciclismo",
    "Cycling Road": "Ciclismo", "Cycling MTB": "Ciclismo", "Cycling BMX Race": "Ciclismo",
    "Cycling BMX Freestyle": "Ciclismo",
}
INVERNALI = {
    "Alpine Skiing", "Biathlon", "Bobsleigh", "Cross-Country Skiing", "Curling", "Figure Skating", "Freestyle Skiing",
    "Ice Hockey", "Luge", "Nordic Combined", "Ski Jumping", "Ski Mountaineering", "Skeleton", "Short Track",
    "Snowboarding", "Speed Skating",
}

# Per alcuni sport il valore che conta non e' "Punti per Disciplina" ma una colonna dedicata di Athletes.
# sport -> (sigla della colonna, come leggere il valore): "punti" = piu' alto e' meglio, "posizione" = piu' basso e' meglio.
# Le colonne si trovano dalla sigla (le emoji nel nome non contano): WON, FEN, WB, UWW, KG.
METRICHE = {
    "Badminton": ("WON", "punti"), "Table Tennis": ("WON", "punti"), "Sailing": ("WON", "punti"),
    "Sport Climbing": ("WON", "punti"), "Archery": ("WON", "punti"), "Triathlon": ("WON", "punti"),
    "Fencing": ("FEN", "punti"), "Boxing": ("WB", "punti"), "Wrestling": ("UWW", "punti"),
    "Weightlifting": ("KG", "punti"),
}
METRICHE_CANON = {sport_canonico(k) for k in METRICHE}
BASE_POSIZIONE = 1_000_000.0   # per le colonne "posizione" il punteggio interno e' BASE - posizione


def sigla_colonna(nome):
    return "".join(c for c in (nome or "") if c.isascii() and c.isalnum()).upper()


def trova_metrica(props, sigla):
    """Colonna di Athletes la cui sigla (solo lettere/numeri ASCII) e' esattamente quella indicata; evita le varianti in %."""
    for k in props:
        if sigla_colonna(k) == sigla and "\uff05" not in k and "%" not in k:
            return k
    return None


def leggi_metrica(raw):
    """Testo/numero della colonna -> ('eventi', {prova: valore}) oppure ('num', valore) oppure None."""
    if raw in ("", None):
        return None
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        return ("num", float(raw))
    ev = parse_punti(str(raw))
    if ev:
        return ("eventi", ev)
    m = re.search(r"-?\d+(?:[.,]\d+)?", str(raw))
    return ("num", float(m.group().replace(",", "."))) if m else None


def die(msg):
    print("ERRORE:", msg, flush=True)
    sys.exit(1)


# --------------------------------------------------------------------------- Notion
def call(method, path, body=None):
    last = ""
    for attempt in range(6):
        r = requests.request(method, API + path, headers=HEAD, json=body, timeout=60)
        if r.status_code == 429:
            time.sleep(float(r.headers.get("Retry-After", "2")) + 0.5)
            continue
        if r.status_code >= 500:
            last = f"{r.status_code}"
            time.sleep(2 + attempt)
            continue
        if r.status_code >= 400:
            raise RuntimeError(f"Notion ha risposto {r.status_code} su {path}: {r.text[:300]}")
        time.sleep(0.35)
        return r.json()
    raise RuntimeError("Notion non risponde (" + last + "): riprova piu' tardi.")


def plain(rich):
    return "".join(x.get("plain_text", "") for x in rich or [])


def flat(p, depth=0):
    """Valore di una proprieta' Notion come testo/numero semplice."""
    t = p.get("type")
    v = p.get(t)
    if t in ("title", "rich_text"):
        return plain(v)
    if t in ("select", "status"):
        return v["name"] if v else ""
    if t == "multi_select":
        return "|".join(x["name"] for x in v or [])
    if t in ("number", "checkbox", "url"):
        return "" if v is None else v
    if t == "date":
        return "" if not v else v["start"]
    if t == "relation":
        return ""
    if t == "formula":
        return flat(v, depth + 1) if v else ""
    if t == "rollup":
        if not v:
            return ""
        if v.get("type") == "array":
            return ";".join(str(flat(x, depth + 1)) for x in v["array"][:6])
        return flat(v, depth + 1)
    if t in ("string", "boolean"):
        return v
    return ""


def query(dbid, flt=None):
    out, cur = [], None
    while True:
        body = {"page_size": 100}
        if flt:
            body["filter"] = flt
        if cur:
            body["start_cursor"] = cur
        r = call("POST", f"/databases/{dbid}/query", body)
        out += r["results"]
        if not r.get("has_more"):
            return out
        cur = r["next_cursor"]


def tutti_i_db():
    dbs, cur = [], None
    while True:
        body = {"filter": {"property": "object", "value": "database"}, "page_size": 100}
        if cur:
            body["start_cursor"] = cur
        r = call("POST", "/search", body)
        dbs += r["results"]
        if not r.get("has_more"):
            return dbs
        cur = r["next_cursor"]


def compatto(s):
    return re.sub(r"\s+", "", (s or "").lower().replace("\xa0", " "))


def trova_db(dbs, titoli):
    want = {compatto(t) for t in titoli}
    for d in dbs:
        if compatto(plain(d.get("title"))) in want:
            return d
    return None


def prop(props, *needles, tipo=None):
    """Trova una proprieta' per nome (ignora maiuscole/spazi/emoji parziali)."""
    for n in needles:
        nl = compatto(n)
        for k, v in props.items():
            if compatto(k) == nl and (tipo is None or v["type"] == tipo):
                return k
    for n in needles:
        nl = compatto(n)
        for k, v in props.items():
            if nl in compatto(k) and (tipo is None or v["type"] == tipo):
                return k
    return None


def titolo_di(props):
    for k, v in props.items():
        if v["type"] == "title":
            return k
    return None


def val(page, *needles):
    k = prop(page["properties"], *needles)
    return flat(page["properties"][k]) if k else ""


def num(x):
    if x in ("", None, False, True):
        return None
    try:
        return float(x)
    except (TypeError, ValueError):
        m = re.search(r"-?\d+(\.\d+)?", str(x))
        return float(m.group()) if m else None


# --------------------------------------------------------------------------- nomi
def toks(s):
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    s = re.sub(r"\(.*?\)", " ", s)
    return [t for t in re.split(r"[^a-z0-9]+", s) if t and t != "ita"]


def chiave_nome(s):
    return " ".join(sorted(toks(s)))


def parti_squadra(nome):
    return [p.strip() for p in re.split(r"[/&,;]| e ", nome or "") if p.strip()]


class Rubrica:
    """Atleti italiani di Athletes, cercabili per nome."""

    def __init__(self, atleti):
        self.atleti = atleti
        self.idx = {}
        for a in atleti:
            self.idx.setdefault(chiave_nome(a["nome"]), []).append(a)

    def cerca(self, nome, sport=None):
        t = set(toks(nome))
        if not t:
            return None
        hit = self.idx.get(" ".join(sorted(t)))
        if hit:
            return self._scegli(hit, sport)
        cand = []
        for a in self.atleti:
            u = set(toks(a["nome"]))
            piccolo, grande = (t, u) if len(t) <= len(u) else (u, t)
            if len(piccolo) >= 2 and piccolo <= grande:
                cand.append(a)
        return self._scegli(cand, sport) if cand else None

    @staticmethod
    def _scegli(lst, sport):
        if sport:
            sp = [a for a in lst if SPORT_DI_ATHLETES.get(a["sport"], a["sport"]) == sport]
            if sp:
                return sp[0]
        return lst[0]


def is_q(v):
    v = (v or "").strip()
    return bool(re.match(r"^(🎟️?\s*)?Q(\b|$)", v, re.I)) or v.lower().startswith("qualific")


# --------------------------------------------------------------------------- lettura
RE_PUNTI = re.compile(r"([^:|\n;]+?)\s*:\s*(-?\d+(?:[.,]\d+)?)\s*pt", re.I)


def parse_punti(testo):
    """'Men's Individual Epee: 16.2 pt' (anche piu' prove nello stesso testo) -> {prova: punti}."""
    out = {}
    for m in RE_PUNTI.finditer(testo or ""):
        nome = m.group(1).strip(" ,|;\n\t")
        if nome:
            out[nome] = out.get(nome, 0) + float(m.group(2).replace(",", "."))
    return out


def leggi_athletes(dbs, log):
    """Legge Athletes a fette per sport (Notion non restituisce piu' di 10000 righe per interrogazione).
    Per gli sport con regole legge tutte le nazioni; per gli altri solo gli italiani."""
    d = trova_db(dbs, ["athletes"])
    if not d:
        die("non trovo il db 'Athletes' tra quelli condivisi con la connessione Notion.")
    pr0 = d["properties"]
    sport_k = prop(pr0, "Sport", tipo="select")
    noc_k = prop(pr0, "NOC", tipo="select")
    if not sport_k or not noc_k:
        die(f"in Athletes non trovo le colonne Sport/NOC (select). Colonne: {list(pr0.keys())[:40]}")
    opzioni = [o["name"] for o in pr0[sport_k]["select"]["options"]]
    log(f"Athletes: {len(opzioni)} sport nel db. Colonne usate: Sport='{sport_k}', NOC='{noc_k}', "
        f"Disciplina='{prop(pr0, 'Disciplina', tipo='multi_select')}', Pass='{prop(pr0, 'Pass LA28', tipo='select')}', "
        f"Punti per disciplina='{prop(pr0, 'Punti per Disciplina')}', PTS Q='{prop(pr0, 'PTS Q')}'")
    itf = {"property": noc_k, "select": {"equals": "\U0001F1EE\U0001F1F9ITA"}}
    letture = []
    for o in opzioni:
        if o in INVERNALI:
            continue
        completo = sport_canonico(o) is not None
        flt = {"property": sport_k, "select": {"equals": o}}
        if not completo:
            flt = {"and": [flt, itf]}
        letture.append((o, flt, completo))
    letture.append(("(senza sport)", {"and": [{"property": sport_k, "select": {"is_empty": True}}, itf]}, False))
    out, pass_vals = [], {}
    pk = prop(pr0, "Pass LA28", "Pass", tipo="select")
    dk = prop(pr0, "Disciplina", tipo="multi_select")
    pdk = prop(pr0, "Punti per Disciplina")
    qk = prop(pr0, "PTS Q")
    col_metrica = {}
    for sp, (sigla, _) in METRICHE.items():
        col_metrica[sp] = trova_metrica(pr0, sigla)
    log("Colonne dedicate per sport: " + ", ".join(f"{sp}={col_metrica[sp]!r}" for sp in METRICHE))
    campioni = {}
    for o, flt, completo in letture:
        pagine = query(d["id"], flt)
        n_it = 0
        for p in pagine:
            pr = p["properties"]
            tk = titolo_di(pr)
            nome = flat(pr[tk]).strip()
            if not nome:
                continue
            noc = flat(pr[noc_k])
            pas = flat(pr[pk]) if pk else ""
            ita = "ITA" in (noc or "").upper()
            if ita:
                pass_vals[pas] = pass_vals.get(pas, 0) + 1
                n_it += 1
            ptsq = num(flat(pr[qk])) if qk else None
            canon = sport_canonico(o)
            disc = flat(pr[dk]) if dk else ""
            pts = parse_punti(flat(pr[pdk]) if pdk else "")
            pt_txt = {}
            if canon in METRICHE and col_metrica.get(canon) and col_metrica[canon] in pr:
                sigla, direzione = METRICHE[canon]
                raw = flat(pr[col_metrica[canon]])
                m = leggi_metrica(raw)
                cs = campioni.setdefault(canon, {"ita": [], "altri": [], "num": []})
                if len(cs["ita" if ita else "altri"]) < 4 and raw not in ("", None):
                    cs["ita" if ita else "altri"].append(f"{nome} [{disc[:30]}] {sigla}={str(raw)[:50]}")
                if m:
                    if m[0] == "num":
                        cs["num"].append(m[1])
                    nuovi = {}
                    if m[0] == "eventi":
                        nuovi = {ev: v for ev, v in m[1].items()}
                    else:
                        eventi_riga = [e for e in disc.split("|") if e and not e.startswith("\U0001F534")]
                        for ev in eventi_riga:
                            g, res, unita = parti_prova(ev, RULES[canon]["kind"])
                            # riga con una sola prova (anche coppia/squadra): il valore e' di quella prova;
                            # riga con piu' prove: lo si assegna solo alle prove individuali
                            # (le squadre con valore 0 tengono i punti generici: la colonna dedicata per loro e' vuota)
                            if unita == "ind" or (len(eventi_riga) == 1 and m[1] > 0):
                                nuovi[ev] = m[1]
                    for ev, v in nuovi.items():
                        kev = parti_prova(ev, RULES[canon]["kind"])[:2]
                        for vecchio in [e for e in pts if parti_prova(e, RULES[canon]["kind"])[:2] == kev]:
                            del pts[vecchio]       # la colonna dedicata sostituisce i punti generici della stessa prova
                        if direzione == "posizione":
                            pts[ev] = BASE_POSIZIONE - v
                            pt_txt[ev] = f"{sigla} {v:g}"
                        else:
                            pts[ev] = v
                            pt_txt[ev] = f"{v:g} {sigla}"
            out.append({"id": p["id"], "nome": nome, "sport": "" if o == "(senza sport)" else o,
                        "canon": canon, "noc": noc, "ita": ita,
                        "disc": disc, "pass": pas, "q": is_q(pas),
                        "pts": pts, "ptsq": ptsq, "pt_txt": pt_txt})
        log(f"   {o:<24} {len(pagine):>5} atleti letti ({'tutte le nazioni' if completo else 'solo italiani'}), "
            f"italiani {n_it}")
    for sp, cs in sorted(campioni.items()):
        nums = sorted(cs["num"])
        rng = f"valori numerici {nums[0]:g} .. {nums[-1]:g} (mediana {nums[len(nums)//2]:g}), n={len(nums)}" if nums else "nessun valore numerico"
        log(f"Colonna {METRICHE[sp][0]} per {sp} ({METRICHE[sp][1]}): {rng}")
        for r in cs["ita"] + cs["altri"]:
            log("      " + r)
    log(f"Athletes: {len(out)} atleti letti, di cui italiani {sum(1 for x in out if x['ita'])}. "
        f"Valori di 'Pass LA28' tra gli italiani: {pass_vals}")
    return out


def pulisci_sim_label(rows):
    """Tiene solo l'ultima simulazione (le vecchie possono restare in Notion in modalita' archivio)."""
    labels = sorted({r["sim"] for r in rows if r["sim"]})
    if len(labels) > 1:
        rows = [r for r in rows if r["sim"] == labels[-1]]
    return rows, (labels[-1] if labels else "")


def leggi_sim(db, sport, end, log):
    rows = []
    for p in query(db["id"]):
        pr = p["properties"]
        tk = titolo_di(pr)
        nome = flat(pr[tk]).strip() if tk else ""
        r = {"sport": sport, "end": end, "nome": nome, "noc": val(p, "NOC"), "rank": num(val(p, "Ranking")),
             "stato": val(p, "Stato"), "via": val(p, "Via di qualificazione", "Via"), "dett": val(p, "Dettagli"),
             "atleti": val(p, "Atleti"), "evento": val(p, "Evento"), "disc": val(p, "Disciplina"),
             "genere": val(p, "Genere"), "cat": val(p, "Categoria"), "sim": val(p, "Simulazione"),
             "nazione": val(p, "Nazione")}
        rows.append(r)
    rows, lab = pulisci_sim_label(rows)
    log(f"{sport}: {len(rows)} righe di simulazione ({lab or 'senza etichetta'}).")
    return rows


def gruppo(r):
    parti = [r["evento"], r["disc"], r["genere"], r["cat"]]
    return " | ".join(x for x in parti if x)


def etichetta_disciplina(r):
    if r["sport"] in ("Judo", "Taekwondo"):
        return " ".join(x for x in (r["genere"], r["cat"]) if x)
    if r["sport"] == "Tennis":
        return r["evento"] or r["disc"]
    return " - ".join(x for x in (r["disc"], r["evento"], r["genere"]) if x)


def is_italiano(r):
    return "ITA" in (r["noc"] or "").upper() or "(ITA)" in (r["nome"] or "").upper() or \
        "ITALY" in (r["nazione"] or "").upper() or "ITALIA" in (r["nome"] or "").upper()


def leggi_wrestling(db, log):
    props = db["properties"]
    noc_k = prop(props, "NOC")
    ttype = props[noc_k]["type"] if noc_k else None
    flt = None
    if ttype in ("rich_text", "title"):
        flt = {"property": noc_k, ttype: {"contains": "ITA"}}
    elif ttype == "select":
        flt = {"property": noc_k, "select": {"equals": "ITA"}}
    out = []
    for p in query(db["id"], flt):
        if "ITA" not in val(p, "NOC").upper():
            continue
        pq = num(val(p, "P Qualifica"))
        if pq is not None and pq <= 1:
            pq *= 100
        cat = val(p, "Categoria")
        stile = val(p, "Stile") or cat[:2]
        out.append({"nome": val(p, "Atleta") or flat(p["properties"][titolo_di(p["properties"])]),
                    "cat": cat, "stile": stile, "p": pq, "rank": num(val(p, "Rank")),
                    "via": val(p, "Via probabile"), "bilancio": val(p, "Bilancio"),
                    "agg": val(p, "Aggiornato")})
    log(f"Wrestling: {len(out)} atleti italiani nel modello.")
    return out


# --------------------------------------------------------------------------- stima
def mesi_rimasti(end):
    return max(0.0, (end - OGGI).days / 30.4)


def logistica(z):
    return 1 / (1 + math.exp(-max(-30, min(30, z))))


def livello(p):
    for soglia, nome in SOGLIE:
        if p >= soglia:
            return nome
    return "Fuori"


def via_ranking(via):
    v = (via or "").lower()
    if any(w in v for w in ("continent", "ospitant", "host", "universal", "grand slam", "champ", "invito",
                            "riassegn", "riserva", "primi fuori")):
        return False
    return any(w in v for w in ("ranking", "diretta", "diretto", "oqr", "top ")) or v == ""


def soglie(rows):
    """Per ogni gruppo (categoria/prova): ultimo ranking tra quelli dentro per ranking diretto."""
    cut = {}
    for r in rows:
        if r["stato"].lower() in IN_STATI and via_ranking(r["via"]) and r["rank"]:
            g = gruppo(r)
            cut[g] = max(cut.get(g, 0), r["rank"])
    return cut


def stima_sim(r, cut):
    """Restituisce (probabilita' 0-100, margine, motivazione)."""
    st = r["stato"].lower()
    end = r["end"]
    m = mesi_rimasti(end)
    c = cut.get(gruppo(r))
    rank = r["rank"]
    margine = None
    p_rank = None
    if c and rank:
        sigma = max(1.5, c * (0.05 + 0.02 * math.sqrt(m)))
        margine = c - rank
        p_rank = logistica((margine + 0.5) / sigma)
    if st in IN_STATI:
        if via_ranking(r["via"]):
            if p_rank is None:
                return 60.0, None, "dentro nella simulazione, ma senza ranking utilizzabile per misurare il margine"
            p = min(0.97, max(0.05, p_rank))
            return round(p * 100, 1), margine, (f"ranking {rank:g}, ultimo posto utile {c:g}: margine {margine:+g}; "
                                                f"{m:.0f} mesi alla fine del periodo")
        v = (r["via"] or "").lower()
        p = next((pp for w, pp in VIA_FISSA if w in v), 0.50)
        return round(p * 100, 1), margine, f"posto condizionato alla via '{r['via']}': stima prudenziale fissa"
    if st == "riserva":
        if p_rank is None:
            return 12.0, margine, "prima riserva: entra solo se un posto resta libero"
        p = min(0.6, max(0.10, p_rank * 0.8))
        return round(p * 100, 1), margine, f"riserva: ranking {rank:g}, soglia {c:g} (margine {margine:+g})"
    if st == "fuori":
        if p_rank is None:
            return 2.0, margine, "fuori dai posti, senza ranking utile"
        alt = ALT_ROUTE if rank <= c * VICINO else 0.02
        p = 1 - (1 - p_rank) * (1 - alt)
        return round(min(0.9, max(0.01, p)) * 100, 1), margine, \
            f"fuori dai posti: ranking {rank:g}, soglia {c:g} (margine {margine:+g}), piu' chance residua di altre vie"
    base = BASE_STATO.get(st, 0.05)
    return round(base * 100, 1), margine, "posto ancora da assegnare / non simulabile"


# --------------------------------------------------------------------------- stima generica (tutti gli altri sport)
PROXY_SIGMA = 1.4        # i punteggi di Athletes sono un'approssimazione del ranking ufficiale: curva piu' dolce
ALT_SHARE = 0.30         # parte dei posti non-ranking che un atleta "vicino" puo' ancora intercettare
PARSE_TEAM = re.compile(r"team|relay|group|squad|eight|four|quad|8\+|4x|4-|squadra", re.I)
PARSE_PAIR = re.compile(r"doubles|duet|synchro|pair|double|2x|2-|coppia", re.I)
SPORT_WORDS = re.compile(r"beach\s*volley\w*|volley\w*|basket\w*|football|cricket|hockey|rugby|handball|polo|"
                         r"baseball|softball|lacrosse|flag", re.I)
IT_GENERE = {"M": "uomini", "W": "donne", "X": "misto", "": ""}


def senza_emoji(t):
    t = (t or "").replace("’", "'")
    return "".join(c for c in t if unicodedata.category(c)[0] in "LNZ" or c in "'+-./|&")


def parti_prova(testo, kind):
    """Testo di una prova (es. "Men's Individual Epee") -> (genere M/W/X, residuo senza genere, tipo unita')."""
    t = senza_emoji(testo).lower().strip()
    if re.search(r"\bwomen|\bfemmin|\bdonne|\bw\b", t):
        g = "W"
    elif re.search(r"\bmen|\bmaschil|\buomini|\bm\b", t):
        g = "M"
    elif re.search(r"mixed|misto", t):
        g = "X"
    else:
        g = ""
    res = re.sub(r"\b(women|men|womens|mens)('s)?\b|'s\b|\bmale\b|\bfemale\b", " ", t)
    res = re.sub(r"\s+", " ", res.replace("'", " ")).strip(" -/")
    if kind in ("team", "pair"):
        unita = kind
        res = SPORT_WORDS.sub(" ", res)
        res3 = "3x3" if re.search(r"3\s*x\s*3", t) else ""
        res = re.sub(r"\b(t20|t10|7s|sevens|field|3x3|5x5)\b", " ", res)
        res = re.sub(r"\s+", " ", res).strip(" -/") if kind == "pair" else res3
    else:
        unita = "team" if PARSE_TEAM.search(res) else "pair" if PARSE_PAIR.search(res) else "ind"
    return g, res, unita


def quota_prova(regola, chiave, unita):
    for rx, q in regola.get("quota_by", []):
        if re.search(rx, chiave, re.I):
            return q
    if unita == "team" and regola["kind"] == "ind":
        return 12
    return regola["quota"]


def grandezza_squadra(regola, res, unita):
    if unita == "pair":
        return 2
    if re.search(r"eight|8\+", res):
        return 8
    if re.search(r"four|quad|4x|4-", res):
        return 4
    if "relay" in res or "4x" in res:
        return 4
    return regola.get("team_size", 4)


def valuta_posizione(pos, n_in_classifica, posti, quota, fine):
    """pos = posizione (1 = migliore) nella classifica della prova gia' ridotta dal limite per nazione.
    Restituisce (probabilita' 0-100, margine, testo)."""
    m = mesi_rimasti(fine)
    margine = posti - pos
    sigma = max(2.0, posti * (0.12 + 0.04 * math.sqrt(m))) * PROXY_SIGMA
    p_rank = logistica((margine + 0.5) / sigma)
    alt = (1 - posti / max(quota, 1)) * ALT_SHARE if pos <= 2 * posti else 0.02
    p = 1 - (1 - p_rank) * (1 - alt) if margine < 0 else max(p_rank, 0.0)
    p = min(0.90, max(0.01, p))
    nota = ""
    if n_in_classifica < 1.5 * posti:
        # il db contiene solo una parte del campo mondiale: la posizione conta ancora, ma la stima non supera il 60%
        # e scende con la posizione nella classifica parziale
        p = min(p, 0.60 * math.sqrt(max(0.0, 1 - (pos - 1) / max(n_in_classifica, 1))))
        p = max(p, 0.02)
        nota = (f" Nel db ci sono solo {n_in_classifica} atleti con punteggio per questa prova (posti da ranking: {posti}): "
                "stima prudente, migliora quando si aggiungono i risultati.")
    return round(p * 100, 1), margine, nota


def codice_noc(noc):
    return "".join(c for c in (noc or "") if c.isascii() and c.isalpha()).upper()


def riga_squadra(a):
    """True se la riga di Athletes e' una squadra/coppia intera (es. "ITA Men's Team Foil"), non un atleta singolo:
    il nome comincia con il codice della nazione (ITA, FRA...) oppure contiene "/" (coppia)."""
    n = (a["nome"] or "").strip()
    cod = codice_noc(a["noc"])
    return bool((cod and n.upper().startswith(cod + " ")) or " / " in n or "/" in n)


def stima_generica(atleti, escludi_ids, log):
    """Una riga per ogni atleta (o squadra/coppia) italiano degli sport con regole, esclusi gli atleti gia' coperti
    dalle simulazioni dedicate. Restituisce (righe, id_coperti)."""
    gruppi = {}   # (sport canonico, genere, impronta della prova) -> {"label", "unita", "chiave", "membri": {noc: {id: (pts, atleta)}}}
    non_olimpiche, duplicati, zero_ids = set(), set(), set()
    for a in atleti:
        if not a["canon"] or a["sport"] in INVERNALI:
            continue
        regola = RULES[a["canon"]]
        prove = dict(a["pts"])
        if not prove and a["ptsq"] and a["ptsq"] > 0:
            primo = (a["disc"].split("|")[0] if a["disc"] else "")
            if primo:
                prove = {primo: a["ptsq"]}
        for ev, pt in prove.items():
            if ev.startswith("\U0001F534"):
                continue
            if pt <= 0:
                if a["canon"] in METRICHE_CANON and pt == 0 and a["ita"]:
                    zero_ids.add(a["id"])     # colonna dedicata (WON/FEN/WB/UWW/KG) presente ma a zero: non e' in classifica
                continue
            g, res, unita = parti_prova(ev, regola["kind"])
            chiave = f"{g}|{res}"
            if regola.get("prove_valide") and not any(re.search(rx, chiave, re.I) for rx in regola["prove_valide"]):
                non_olimpiche.add(a["id"])      # categoria che non e' in programma a LA28
                continue
            impronta_prova = "".join(sorted(res.replace(" ", "")))   # 'recurve individual' = 'individual recurve'
            gr = gruppi.setdefault((a["canon"], g, impronta_prova),
                                   {"label": ev, "unita": unita, "g": g, "res": res, "chiave": chiave, "membri": {}})
            d = gr["membri"].setdefault(a["noc"], {})
            kd = chiave_nome(a["nome"])          # lo stesso atleta puo' comparire in due pagine con la prova scritta in modo diverso
            if kd not in d:
                d[kd] = (pt, a)
            else:
                if a["id"] != d[kd][1]["id"]:
                    duplicati.add(a["id"] if pt <= d[kd][0] else d[kd][1]["id"])
                if pt > d[kd][0]:
                    d[kd] = (pt, a)
    for gr in gruppi.values():
        gr["membri"] = {noc: list(dd.values()) for noc, dd in gr["membri"].items()}
    righe, coperti = [], set()
    senza_dati = {}
    for (sport, _g, _imp), gr in sorted(gruppi.items(), key=lambda kv: (kv[0][0], kv[0][1], kv[1]["chiave"])):
        chiave = gr["chiave"]
        regola = RULES[sport]
        unita, res, g = gr["unita"], gr["res"], gr["g"]
        quota = quota_prova(regola, chiave, unita)
        posti = max(1, round(quota * regola["rank_share"]))
        dimensione = grandezza_squadra(regola, res, unita)
        massimo = regola["max_noc"] if unita == "ind" else (1 if unita == "team" else min(2, regola["max_noc"]))
        unita_lista = []
        for noc, lst in gr["membri"].items():
            lst.sort(key=lambda x: -x[0])
            if unita == "ind":
                unita_lista += [{"noc": noc, "pts": pt, "membri": [a]} for pt, a in lst]
            elif unita == "team" and (regola["kind"] == "team" or any(riga_squadra(a) for _, a in lst)):
                # nel db la squadra e' gia' una riga (es. "ITA Men's Volley", "ITA Men's Team Foil") con i suoi punti
                righe_sq = [(pt, a) for pt, a in lst if riga_squadra(a)] or lst
                unita_lista += [{"noc": noc, "pts": pt, "membri": [a], "entry": True} for pt, a in righe_sq]
            elif unita == "team":
                top = lst[:dimensione]
                unita_lista.append({"noc": noc, "pts": sum(pt for pt, _ in top), "membri": [a for _, a in top]})
            elif all(riga_squadra(a) for _, a in lst):
                # la coppia e' gia' una riga unica (es. "ITA Men's Beach" o "ROSSI / BIANCHI")
                unita_lista += [{"noc": noc, "pts": pt, "membri": [a], "entry": True} for pt, a in lst]
            else:
                for i in range(0, len(lst), 2):
                    ch = lst[i:i + 2]
                    unita_lista.append({"noc": noc, "pts": sum(pt for pt, _ in ch), "membri": [a for _, a in ch]})
        unita_lista.sort(key=lambda u: -u["pts"])
        conta, classifica, fuori_limite = {}, [], []
        for u in unita_lista:
            conta[u["noc"]] = conta.get(u["noc"], 0) + 1
            (classifica if conta[u["noc"]] <= massimo else fuori_limite).append(u)
        for pos, u in enumerate(classifica, 1):
            u["pos"] = pos
        for u in fuori_limite:
            u["fuori"] = True
        for u in unita_lista:
            ita = [a for a in u["membri"] if a["ita"]]
            if not ita or any(a["id"] in escludi_ids for a in ita):
                continue
            for a in ita:
                coperti.add(a["id"])
            if u.get("fuori") and unita != "ind":
                continue      # seconda formazione italiana oltre il limite: la riga della migliore c'e' gia'
            if regola["kind"] in ("team", "pair"):
                for _, a in gr["membri"].get(u["noc"], []):
                    coperti.add(a["id"])      # tutta la rosa italiana presente in db appartiene a questa squadra
            certo = any(a["q"] for a in ita) or (regola["kind"] in ("team", "pair") and
                                                  any(a["q"] for _, a in gr["membri"].get(u["noc"], [])))
            n_rosa = len(gr["membri"].get(u["noc"], [])) if unita == "team" else len(u["membri"])
            minimo = 2 if unita == "pair" else max(2, (dimensione + 1) // 2)
            if unita != "ind" and regola["kind"] != "team" and not u.get("entry") and not certo and n_rosa < minimo:
                righe.append(dict(sport=sport, disciplina=(gr["label"] if unita == "ind" or regola["kind"] == "ind"
                                                          else f"{sport} {IT_GENERE[g]}".strip())[:100],
                                  nome=(" / ".join(a["nome"] for a in u["membri"]) if unita == "pair"
                                        else "Italia" + (f" ({IT_GENERE[g]})" if g else "")),
                                  tipo="Squadra", livello="Dati insufficienti", p=None, via="", rank=None,
                                  margine=None, stato="Rosa incompleta", pass_="", fine=regola["fine"].isoformat(),
                                  nota=f"in Athletes ci sono solo {n_rosa} atleti italiani con punti per questa squadra "
                                       f"(ne servono almeno {minimo}): la forza della squadra non e' misurabile"))
                continue
            label = gr["label"]
            if unita == "ind":
                nome, tipo = ita[0]["nome"], "Atleta"
            elif u.get("entry") and "/" in ita[0]["nome"]:
                nome, tipo = ita[0]["nome"], "Squadra"      # coppia/formazione indicata per nome (es. squadre miste del tiro)
            elif unita == "pair":
                nome, tipo = " / ".join(a["nome"] for a in u["membri"]), "Squadra"
            else:
                nome = "Italia" + (" 3x3" if "3x3" in res else "") + (f" ({IT_GENERE[g]})" if g else "")
                tipo = "Squadra"
            disc = label if unita == "ind" else (f"{sport}{' 3x3' if '3x3' in res else ''} {IT_GENERE[g]}".strip()
                                                if regola["kind"] != "ind" else f"{label}")
            if certo:
                p, marg, nota = 100.0, None, "in Athletes la colonna Pass LA28 e' Q: qualificazione acquisita"
                liv, pas = "Certo", "Q"
            else:
                pas = ""
                if u.get("fuori"):
                    p, marg = 3.0, None
                    nota = f"oltre il limite di {massimo} per nazione in questa prova: passa solo se un connazionale rinuncia"
                else:
                    p, marg, extra = valuta_posizione(u["pos"], len(classifica), posti, quota, regola["fine"])
                    dato = (ita[0].get("pt_txt", {}).get(gr["label"]) or f"{u['pts']:g} pt") if unita == "ind" else f"{u['pts']:g} pt"
                    nota = (f"{dato}, posizione {u['pos']} su {len(classifica)} in classifica per questa prova; "
                            f"posti decisi dal ranking {posti} su {quota} (margine {marg:+d}); "
                            f"{mesi_rimasti(regola['fine']):.0f} mesi alla fine del periodo." + extra)
                liv = livello(p)
            righe.append(dict(sport=sport, disciplina=disc[:100], nome=nome, tipo=tipo, livello=liv, p=p,
                              via="Ranking da punteggi Athletes", rank=u.get("pos"), margine=marg,
                              stato="Stima da punteggi", nota=nota[:1900], pass_=pas,
                              fine=regola["fine"].isoformat()))
    # italiani degli sport con regole che non compaiono in nessuna classifica
    squadre_senza = {}
    for a in atleti:
        if not a["ita"] or not a["canon"] or a["sport"] in INVERNALI or a["id"] in coperti or a["id"] in escludi_ids:
            continue
        if a["id"] in duplicati:
            coperti.add(a["id"])      # doppione della stessa persona: la riga esiste gia' con l'altra pagina
            continue
        regola = RULES[a["canon"]]
        disc = a["disc"].replace("|", ", ") if a["disc"] else a["canon"]
        if regola["kind"] in ("team", "pair"):
            g = parti_prova(a["disc"].split("|")[0] if a["disc"] else "", "team")[0]
            x = squadre_senza.setdefault((a["canon"], g), {"q": False, "n": 0})
            x["q"] = x["q"] or a["q"]
            x["n"] += 1
        elif a["id"] in zero_ids and not a["q"] and a["canon"] in METRICHE_CANON:
            righe.append(dict(sport=a["canon"], disciplina=disc[:100], nome=a["nome"],
                              tipo="Squadra" if riga_squadra(a) else "Atleta", livello="Fuori", p=2.0, via="",
                              rank=None, margine=None, stato="Senza punti nel ranking", pass_="",
                              fine=regola["fine"].isoformat(),
                              nota="nella colonna di riferimento (WON/FEN/WB/UWW/KG) ha 0 punti: non e' in classifica; "
                                   "passa solo con una via diversa dal ranking"))
        elif a["id"] in non_olimpiche and not a["q"]:
            righe.append(dict(sport=a["canon"], disciplina=disc[:100], nome=a["nome"], tipo="Atleta", livello="Fuori",
                              p=1.0, via="", rank=None, margine=None, stato="Categoria non olimpica", pass_="",
                              fine=regola["fine"].isoformat(),
                              nota="la categoria in cui compare in Athletes non e' in programma a LA28"))
        elif a["q"]:
            righe.append(dict(sport=a["canon"], disciplina=disc[:100], nome=a["nome"], tipo="Atleta", livello="Certo",
                              p=100.0, via="", rank=None, margine=None, stato="Pass LA28",
                              nota="in Athletes la colonna Pass LA28 e' Q: qualificazione acquisita", pass_="Q",
                              fine=regola["fine"].isoformat()))
        else:
            righe.append(dict(sport=a["canon"], disciplina=disc[:100], nome=a["nome"],
                              tipo="Squadra" if riga_squadra(a) else "Atleta",
                              livello="Dati insufficienti", p=None, via="", rank=None, margine=None,
                              stato="Senza punteggio", pass_="", fine=regola["fine"].isoformat(),
                              nota="in Athletes non ci sono punti per la prova: serve un ranking o un risultato per stimare"))
        coperti.add(a["id"])
    for (sport, g), x in sorted(squadre_senza.items()):
        regola = RULES[sport]
        nome = "Italia" + (f" ({IT_GENERE[g]})" if g else "")
        disc = f"{sport} {IT_GENERE[g]}".strip()
        if x["q"]:
            righe.append(dict(sport=sport, disciplina=disc, nome=nome, tipo="Squadra", livello="Certo", p=100.0,
                              via="", rank=None, margine=None, stato="Pass LA28", pass_="Q",
                              nota="in Athletes la colonna Pass LA28 e' Q: qualificazione acquisita",
                              fine=regola["fine"].isoformat()))
        else:
            righe.append(dict(sport=sport, disciplina=disc, nome=nome, tipo="Squadra", livello="Dati insufficienti",
                              p=None, via="", rank=None, margine=None, stato="Senza punteggio", pass_="",
                              fine=regola["fine"].isoformat(),
                              nota="in Athletes la squadra italiana non ha punti per questa prova: "
                                   "serve il ranking della nazione per stimare"))
    # diagnostica
    log(f"\nStima generica: {len(gruppi)} prove con almeno un punteggio, {len(righe)} righe italiane.")
    per_sport = {}
    for (sport, _g, _imp), gr in gruppi.items():
        x = per_sport.setdefault(sport, [0, 0])
        x[0] += 1
        x[1] += sum(len(v) for v in gr["membri"].values())
    for sport, (n_prove, n_att) in sorted(per_sport.items()):
        log(f"   {sport:<24} {n_prove:>3} prove con punteggi, {n_att:>5} atleti con punti")
    return righe, coperti


def costruisci(tutti, sims, wrest, log):
    athletes = [a for a in tutti if a["ita"]]
    rub = Rubrica(athletes)
    righe, usati = [], set()

    def aggiungi(**k):
        k.setdefault("tipo", "Atleta")
        k.setdefault("pass_", "")
        k.setdefault("margine", None)
        k.setdefault("rank", None)
        k.setdefault("via", "")
        k.setdefault("stato", "")
        k.setdefault("nota", "")
        k.setdefault("fine", "")
        righe.append(k)

    # --- simulazioni a righe (judo, taekwondo, tennis, canoa, ciclismo)
    for sport, rows in sims.items():
        cut = soglie(rows)
        for r in rows:
            if not is_italiano(r):
                continue
            nome = r["nome"] or "(senza nome)"
            squadra = bool(r["atleti"]) or "/" in nome or "(ITA)" in nome.upper() or sport in ("Canoa", "Ciclismo")
            nomi = parti_squadra(r["atleti"] or nome) if squadra else [nome]
            trovati = [rub.cerca(n, sport) for n in nomi if "(ita)" not in n.lower()]
            trovati = [t for t in trovati if t]
            for t in trovati:
                usati.add(t["id"])
            certo = bool(trovati) and all(t["q"] for t in trovati) and (not squadra or len(trovati) == len(nomi))
            pas = "Q" if certo else ""
            if certo:
                p, marg, nota = 100.0, None, "in Athletes la colonna Pass LA28 e' Q: qualificazione acquisita"
                liv = "Certo"
            else:
                p, marg, nota = stima_sim(r, cut)
                liv = livello(p)
            aggiungi(sport=sport, disciplina=etichetta_disciplina(r) or sport, nome=nome,
                     tipo="Squadra" if squadra else "Atleta", livello=liv, p=p, via=r["via"], rank=r["rank"],
                     margine=marg, stato=r["stato"], nota=(nota + ("; " + r["dett"] if r["dett"] else ""))[:1900],
                     pass_=pas, fine=r["end"].isoformat())

    # --- wrestling (modello a simulazione di incontri, ha gia' la probabilita' di qualifica)
    for w in wrest:
        a = rub.cerca(w["nome"], "Wrestling")
        if a:
            usati.add(a["id"])
        stile = {"FS": "Libera", "GR": "Greco-romana", "WW": "Femminile"}.get(w["stile"], w["stile"])
        kg = re.sub(r"^[A-Z]{2}\s*", "", w["cat"])
        if a and a["q"]:
            p, liv, pas, nota = 100.0, "Certo", "Q", "in Athletes la colonna Pass LA28 e' Q: qualificazione acquisita"
        else:
            p = round(w["p"], 1) if w["p"] is not None else 5.0
            liv, pas = livello(p), ""
            nota = ("modello UWW a 5000 simulazioni; " + (f"bilancio {w['bilancio']}" if w["bilancio"] else "")).strip("; ")
        aggiungi(sport="Wrestling", disciplina=f"{stile} {kg}".strip(), nome=w["nome"], livello=liv, p=p,
                 via=w["via"], rank=w["rank"], stato="Modello", nota=nota, pass_=pas,
                 fine=WRESTLING_END.isoformat())

    # --- tutte le altre discipline: regole CIO + punteggi di Athletes
    righe_gen, coperti_gen = stima_generica(tutti, usati, log)
    righe += righe_gen
    usati |= coperti_gen

    # --- atleti di Athletes non coperti da nessuna riga di simulazione
    non_abbinati = []
    for a in athletes:
        if a["id"] in usati or a["sport"] in INVERNALI:
            continue
        sp_sim = SPORT_DI_ATHLETES.get(a["sport"])
        disc = a["disc"].replace("|", ", ") if a["disc"] else a["sport"]
        if a["q"]:
            aggiungi(sport=a["sport"] or "Altro", disciplina=disc, nome=a["nome"], livello="Certo", p=100.0,
                     stato="Pass LA28", nota="in Athletes la colonna Pass LA28 e' Q: qualificazione acquisita",
                     pass_="Q")
        elif re.search(r"\bteam\b|\bmixed\b", a["nome"], re.I):
            continue      # voce di squadra (es. 'ITA Judo Mixed Team'), non un atleta
        elif a["sport"] in ("Judo", "Taekwondo", "Wrestling"):
            non_abbinati.append(a)
            end = dict((s, e) for s, _, e, _ in SIMS).get(a["sport"], WRESTLING_END)
            aggiungi(sport=a["sport"], disciplina=disc, nome=a["nome"], livello="Fuori", p=1.0, stato="Non in classifica",
                     nota="non compare nella simulazione: fuori dalle posizioni utili del ranking olimpico",
                     fine=end.isoformat())
        elif sp_sim in ("Canoa", "Ciclismo"):
            continue      # la simulazione e' a livello di nazione/equipaggio: le righe di squadra coprono questi sport
        else:
            motivo = ("sport con simulazione a squadre/nazione: l'atleta non e' legato a una riga" if sp_sim
                      else "sport senza regole di qualificazione nel file regole_la28.py")
            aggiungi(sport=a["sport"] or "Altro", disciplina=disc, nome=a["nome"], livello="Dati insufficienti",
                     p=None, stato="Senza simulazione", nota=motivo)
    log(f"Atleti di Athletes non abbinati a una riga di simulazione ma in sport simulati (judo/tkd/wrestling): "
        f"{len(non_abbinati)}")
    for a in non_abbinati[:40]:
        log(f"   - {a['sport']}: {a['nome']}")
    # righe identiche (stesso sport, disciplina e nome): ne tengo una sola, quella con probabilita' piu' alta
    migliori = {}
    for r in righe:
        k = (r["sport"], r["disciplina"], r["nome"])
        if k not in migliori or (r.get("p") or 0) > (migliori[k].get("p") or 0):
            migliori[k] = r
    if len(migliori) < len(righe):
        log(f"Righe doppie eliminate: {len(righe) - len(migliori)}")
        visti, unici = set(), []
        for r in righe:
            k = (r["sport"], r["disciplina"], r["nome"])
            if k in visti or migliori[k] is not r:
                continue
            visti.add(k)
            unici.append(r)
        righe = unici
    return righe


# --------------------------------------------------------------------------- scrittura su Notion
SCHEMA = {
    "Chiave": ("rich_text", {}), "Sport": ("select", {}), "Disciplina": ("select", {}), "Tipo": ("select", {}),
    "Livello": ("select", {"options": [{"name": n, "color": COLORI[n]} for n in LIVELLI]}),
    "Probabilità %": ("number", {}), "Stato simulazione": ("select", {}),
    "Via di qualificazione": ("rich_text", {}), "Ranking": ("number", {}), "Margine": ("number", {}),
    "Fine periodo": ("date", {}), "Motivazione": ("rich_text", {}), "Pass LA28": ("select", {}),
    "Aggiornato": ("date", {}), "Impronta": ("rich_text", {}),
}


def prepara_db():
    if not re.fullmatch(r"[0-9a-f]{32}", DATABASE_ID):
        die("il segreto NOTION_DATABASE_ID non contiene un ID valido (servono 32 caratteri, lettere a-f e numeri). "
            "Apri il db 'Stima LA28' in Notion, Condividi -> Copia link, e incolla il link intero nel segreto.")
    try:
        d = call("GET", f"/databases/{DATABASE_ID}")
    except RuntimeError as e:
        die("Notion non trova il db 'Stima LA28' con l'ID indicato nel segreto NOTION_DATABASE_ID. Controlla che sia l'ID "
            "del database (non di una vista o di una pagina) e che il db sia collegato alla connessione "
            f"({e})")
    props = d["properties"]
    nuove = {}
    tk = titolo_di(props)
    if tk and tk != "Nome":
        nuove[tk] = {"name": "Nome"}
    for nome, (tipo, conf) in SCHEMA.items():
        if nome not in props:
            nuove[nome] = {tipo: conf}
    if nuove:
        call("PATCH", f"/databases/{DATABASE_ID}", {"properties": nuove})
        print("Colonne create/rinominate nel database:", ", ".join(nuove.keys()), flush=True)


def txt(v):
    return {"rich_text": [{"text": {"content": (v or "")[:1990]}}]} if v else {"rich_text": []}


def sel(v):
    return {"select": {"name": str(v).replace(",", " ")[:100]}} if v else {"select": None}


def chiave_riga(r):
    return "|".join([r["sport"], r["disciplina"], chiave_nome(r["nome"]), r["tipo"]])[:200]


def props_riga(r, ora):
    return {
        "Nome": {"title": [{"text": {"content": r["nome"][:200]}}]},
        "Chiave": txt(chiave_riga(r)),
        "Sport": sel(r["sport"]), "Disciplina": sel(r["disciplina"]), "Tipo": sel(r["tipo"]),
        "Livello": sel(r["livello"]),
        "Probabilità %": {"number": r["p"]},
        "Stato simulazione": sel(r["stato"]),
        "Via di qualificazione": txt(r["via"]),
        "Ranking": {"number": r["rank"]}, "Margine": {"number": r["margine"]},
        "Fine periodo": {"date": {"start": r["fine"]} if r["fine"] else None},
        "Motivazione": txt(r["nota"]),
        "Pass LA28": sel(r["pass_"]),
        "Aggiornato": {"date": {"start": ora}},
    }


def impronta(r):
    base = json.dumps([r["sport"], r["disciplina"], r["nome"], r["tipo"], r["livello"], r["p"], r["stato"], r["via"],
                       r["rank"], r["margine"], r["fine"], r["nota"], r["pass_"]], ensure_ascii=False)
    return hashlib.md5(base.encode()).hexdigest()[:16]


def scrivi(righe):
    prepara_db()
    esistenti = {}
    for p in query(DATABASE_ID):
        pr = p["properties"]
        k = flat(pr["Chiave"]) if "Chiave" in pr else ""
        esistenti.setdefault(k, []).append((p["id"], flat(pr["Impronta"]) if "Impronta" in pr else ""))
    ora = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")
    nuovi = agg = uguali = errori = 0
    viste = set()
    for r in righe:
        k = chiave_riga(r)
        h = impronta(r)
        viste.add(k)
        pr = props_riga(r, ora)
        pr["Impronta"] = txt(h)
        try:
            if k in esistenti:
                pid, h_old = esistenti[k][0]
                if h_old == h:
                    uguali += 1
                    continue
                call("PATCH", f"/pages/{pid}", {"properties": pr})
                agg += 1
            else:
                call("POST", "/pages", {"parent": {"database_id": DATABASE_ID}, "properties": pr})
                nuovi += 1
        except RuntimeError as e:
            errori += 1
            print(f"  Errore su {r['nome']}: {e}", flush=True)
    archiviati = 0
    for k, lst in esistenti.items():
        for i, (pid, _) in enumerate(lst):
            if k not in viste or i > 0:
                try:
                    call("PATCH", f"/pages/{pid}", {"archived": True})
                    archiviati += 1
                except RuntimeError as e:
                    errori += 1
                    print("  Errore in archiviazione:", e, flush=True)
    print(f"Notion: {nuovi} righe nuove, {agg} aggiornate, {uguali} invariate, {archiviati} archiviate, "
          f"{errori} errori.", flush=True)
    return errori


# --------------------------------------------------------------------------- json per la pagina web
METODO = [
    "Il livello Certo vale solo se in Athletes la colonna Pass LA28 e' Q. La colonna Status LA28 non viene usata.",
    "Judo, taekwondo, lotta, tennis, canoa e ciclismo partono dalle simulazioni gia' presenti in Notion (ranking olimpico "
    "attuale): il margine e' la distanza in posti tra l'atleta o la nazione e l'ultimo posto utile della stessa categoria.",
    "Tutte le altre discipline estive usano i regolamenti di qualificazione del CIO (posti per prova, limite per nazione, "
    "data di chiusura) applicati ai punteggi del db Athletes: per ogni prova si ordinano gli atleti di tutte le nazioni, "
    "si applica il limite per nazione e si guarda se l'atleta e' entro i posti assegnati dal ranking.",
    "Negli sport di squadra ogni nazione e' una riga-squadra in Athletes (es. 'ITA Men's Volley') e si usano i suoi punti; "
    "nelle prove a squadre degli sport individuali (staffette, scherma a squadre) si sommano i punti dei migliori atleti; "
    "le coppie sono formate dai due migliori atleti della stessa nazione.",
    "Il margine diventa una percentuale con una curva logistica: piu' mesi mancano alla chiusura delle qualificazioni, piu' la "
    "curva e' dolce; i punteggi di Athletes sono un'approssimazione del ranking ufficiale, quindi la curva e' ancora piu' prudente "
    "e la probabilita' non supera il 90% prima del Pass.",
    "Una parte dei posti non dipende dal ranking (paese ospitante, universality, continentali, ripescaggi): chi e' fuori ma vicino "
    "alla soglia conserva una piccola chance residua.",
    "Livelli: Probabile 70% o piu', Possibile 35-69%, Remoto 8-34%, Fuori sotto l'8%. Se mancano punteggi o ranking l'agente "
    "scrive 'Dati insufficienti' invece di inventare un numero.",
    "Atletica: quote e standard sono provvisori fino a dicembre 2026. E' una stima euristica per orientarsi, non un calcolo "
    "ufficiale: i regolamenti completi sono sul sito del CIO.",
]


def scrivi_json(righe, note):
    conteggi = {n: 0 for n in LIVELLI}
    sport = {}
    for r in righe:
        conteggi[r["livello"]] += 1
        s = sport.setdefault(r["sport"], {"nome": r["sport"], "n": 0, **{n: 0 for n in LIVELLI}})
        s["n"] += 1
        s[r["livello"]] += 1
    elenco = sorted(sport.values(), key=lambda s: (-(s["Certo"] + s["Probabile"]), -s["n"], s["nome"]))
    out = {
        "aggiornato": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "totali": conteggi, "sport": elenco, "metodo": METODO, "note": note,
        "righe": [{"sport": r["sport"], "disciplina": r["disciplina"], "nome": r["nome"], "tipo": r["tipo"],
                   "livello": r["livello"], "p": r["p"], "via": r["via"], "rank": r["rank"], "margine": r["margine"],
                   "stato": r["stato"], "nota": r["nota"], "pass": r["pass_"], "fine": r["fine"]} for r in righe],
    }
    with open(JSON_OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"File per la pagina grafica scritto: {JSON_OUT} ({len(righe)} righe).", flush=True)


# --------------------------------------------------------------------------- main
def main():
    if not NOTION_TOKEN:
        die("manca NOTION_TOKEN (controlla i Secrets su GitHub).")
    if not DRY_RUN and not DATABASE_ID:
        die("manca NOTION_DATABASE_ID (il database 'Stima LA28').")
    note = []

    def log(m):
        print(m, flush=True)

    dbs = tutti_i_db()
    log(f"Database visibili alla connessione: {len(dbs)}")
    athletes = leggi_athletes(dbs, log)
    sims = {}
    for sport, titoli, end, _ in SIMS:
        d = trova_db(dbs, titoli)
        if not d:
            msg = f"{sport}: database di simulazione non trovato (titoli cercati: {titoli}); sport trattato come 'dati insufficienti'."
            log("ATTENZIONE: " + msg)
            note.append(msg)
            continue
        sims[sport] = leggi_sim(d, sport, end, log)
    wrest = []
    dw = trova_db(dbs, WRESTLING_TITLES)
    if dw:
        wrest = leggi_wrestling(dw, log)
    else:
        msg = "Wrestling: database 'Previsioni Wrestling LA28' non trovato."
        log("ATTENZIONE: " + msg)
        note.append(msg)

    senza_regole = {}
    for a in athletes:
        if a["ita"] and not a["canon"] and a["sport"] not in INVERNALI and a["sport"] not in SPORT_DI_ATHLETES:
            senza_regole[a["sport"] or "(senza sport)"] = senza_regole.get(a["sport"] or "(senza sport)", 0) + 1
    if senza_regole:
        log("Sport con atleti italiani ma SENZA regole di qualificazione (compaiono come 'Dati insufficienti'): "
            + ", ".join(f"{k} ({v})" for k, v in sorted(senza_regole.items())))
    righe = costruisci(athletes, sims, wrest, log)
    ordine = {n: i for i, n in enumerate(LIVELLI)}
    righe.sort(key=lambda r: (r["sport"], ordine[r["livello"]], -(r["p"] or 0), r["nome"]))
    log("\n=== Riepilogo per sport e livello ===")
    tab = {}
    for r in righe:
        tab.setdefault(r["sport"], {n: 0 for n in LIVELLI})[r["livello"]] += 1
    for s, c in sorted(tab.items()):
        log(f"  {s:<24} " + "  ".join(f"{n}={c[n]}" for n in LIVELLI if c[n]))
    log("\n=== Righe degli sport con simulazione ===")
    for r in righe:
        if r["livello"] != "Dati insufficienti" and r["stato"] != "Non in classifica":
            log(f"  {r['sport']:<10} | {r['disciplina'][:34]:<34} | {r['nome'][:34]:<34} | {r['livello']:<9} | "
                f"{('%.1f' % r['p']) if r['p'] is not None else '-':>5}% | {r['stato']:<10} | {r['via'][:40]}")
    scrivi_json(righe, note)
    if DRY_RUN:
        print(f"\nProva terminata: {len(righe)} righe calcolate, non e' stato scritto nulla su Notion.")
        return
    errori = scrivi(righe)
    if errori:
        sys.exit(1)


if __name__ == "__main__":
    code = 0
    try:
        main()
    except SystemExit as e:
        code = e.code if isinstance(e.code, int) else 1
    except Exception:
        import traceback
        traceback.print_exc()
        code = 1
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(code)
