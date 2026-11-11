"""Agente "Stima qualificazione LA28" degli atleti e delle squadre italiane.

Cosa fa, ogni volta che parte:
 1. legge dal tuo Notion gli atleti italiani (db Athletes) e le simulazioni gia' prodotte dagli altri agenti
    (pagina "Agenti", colonna "LA28 Simulazioni": LA28 Beach Volley, LA28 Canoe, LA28 Cycling, LA 28 Judo,
    LA28 Skateboarding, LA28 Squash, LA28 Taekwondo, LA28 Tennis);
 2. per ogni atleta o squadra calcola un livello (Certo / Probabile / Possibile / Remoto / Fuori) e una percentuale;
 3. scrive il risultato nel database Notion "Stima LA28" (solo le righe cambiate) e crea stima_la28.json per la pagina web;
 4. conta le QUOTE italiane (posti-atleta) per sport, livello e genere: riepilogo nel log, in stima_la28.json
    (chiave "quote") e nella pagina web. Il riepilogo non cambia ne' le righe ne' le colonne di Notion.

Regole fisse:
 - se in Athletes la colonna "Pass LA28" vale Q, l'atleta e' CERTO (100%);
 - la colonna "Status LA28" di Athletes NON viene mai usata;
 - gli sport invernali sono esclusi;
 - beach volley, canoa, ciclismo, judo, skateboarding, squash, taekwondo e tennis usano le simulazioni gia' presenti
   in Notion (elenco SIMS qui sotto);
 - tutte le altre discipline estive (lotta compresa, finche' USA_MODELLO_WRESTLING e' False) usano le regole del CIO
   (file regole_la28.py) applicate ai punteggi del db Athletes
   (classifica per prova di tutte le nazioni, limite per nazione, posti disponibili): stima approssimata, da affinare;
 - chi non ha punteggi o ranking utilizzabili compare come "Dati insufficienti".
La percentuale e' una stima euristica (vedi METODO nel file e la pagina web), non un calcolo ufficiale.

Variabili: NOTION_TOKEN, NOTION_DATABASE_ID (il db "Stima LA28"), DRY_RUN (true = non scrive su Notion).
"""
import difflib
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

from regole_la28 import RULES, sport_canonico, QUOTE_RIEPILOGO, GRUPPI_RIEPILOGO, SEPARA_RIEPILOGO

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
    ("grand slam", 0.60), ("champ", 0.60), ("mondiali", 0.30), ("q-series", 0.20), ("torneo", 0.15),
    ("ospitant", 0.90), ("paese", 0.90),
]
IN_STATI = {"provvisorio", "qualificato", "garantito"}
SCONTO_IPOTESI = 0.8      # stato "Ipotesi" (es. vincitore continentale o mondiale ipotizzato): via fissa x 0.8
TORNEO = re.compile(r"q-?series|torneo|tournament|play-?off", re.I)   # vie decise in un torneo di qualificazione finale
MAX_TORNEO = 0.60         # tetto per chi passa solo da un torneo con pochi posti
SOGLIE = [(70, "Probabile"), (35, "Possibile"), (8, "Remoto"), (0, "Fuori")]
LIVELLI = ["Certo", "Probabile", "Possibile", "Remoto", "Fuori", "Dati insufficienti"]
COLORI = {"Certo": "green", "Probabile": "blue", "Possibile": "yellow", "Remoto": "orange", "Fuori": "gray",
          "Dati insufficienti": "default"}

# Simulazioni della pagina Notion "⚙️ Agenti 🕵🏻‍♂️" (colonna "LA28 Simulazioni").
#   label     etichetta sport scritta in "Stima LA28"
#   db        ID del database in Notion (si cerca prima per ID, poi per titolo)
#   titoli    titoli accettati se l'ID non e' visibile (maiuscole, spazi ed emoji non contano)
#   fine      fine del periodo di qualificazione
#   copertura "ind"     = la simulazione elenca tutti i candidati: chi non c'e' e' Fuori
#             "nazione" = righe per nazione/equipaggio: gli atleti di Athletes non hanno una riga propria
#             "parziale"= la simulazione non copre tutte le prove: chi non c'e' resta "Dati insufficienti"
#   riga_unica True se in Athletes la squadra/coppia e' gia' una riga sola (beach volley: "Nome COGNOME/Nome COGNOME")
#   alias     nomi dello sport usati nella colonna Sport di Athletes (minuscolo, solo lettere e numeri)
SIMS = [
    dict(label="Beach Volleyball", db="7706c27fb15f4fd181db1c09a2bd0fe2",
         titoli=["la28 beach volley", "la 28 beach volley", "la28 beachvolley"],
         fine=RULES["Beach Volleyball"]["fine"], copertura="ind", riga_unica=True,
         alias=["beachvolley", "beachvolleyball"]),
    dict(label="Canoeing", db="40ff48c9aad9800daa02fae8d9e3fc90", titoli=["la28 canoe", "la 28 canoe"],
         fine=date(2028, 6, 30), copertura="nazione",
         alias=["canoeslalom", "canoesprint", "canoe", "canoa", "canoeing"]),
    dict(label="Cycling", db="40ff48c9aad980f692e2d4cf774035ab", titoli=["la28 cycling", "la 28 cycling"],
         fine=date(2028, 6, 30), copertura="nazione",
         alias=["cycling", "cyclingtrack", "cyclingroad", "cyclingmtb", "cyclingmountainbike", "cyclingbmxrace",
                "cyclingbmxfreestyle", "cyclingbmxracing", "bmxrace", "bmxracing", "bmxfreestyle", "mountainbike", "road", "track"]),
    dict(label="Judo", db="410f48c9aad98034bfbdd93791d8cd42", titoli=["la 28 judo", "la28 judo"],
         fine=date(2028, 6, 12), copertura="ind", alias=["judo"]),
    dict(label="Skateboarding", db="bddc45f0eb7647bd844979381048a695",
         titoli=["la28 skateboarding", "la 28 skateboarding"],
         fine=RULES["Skateboarding"]["fine"], copertura="ind", alias=["skateboarding", "skate"]),
    dict(label="Squash", db="54ed8b9a26a44340bc228cc8a8d3e71b", titoli=["la28 squash", "la 28 squash"],
         fine=RULES["Squash"]["fine"], copertura="ind", alias=["squash"]),
    dict(label="Taekwondo", db="410f48c9aad980539764e6e3e5904db3", titoli=["la28 taekwondo", "la 28 taekwondo"],
         fine=date(2028, 5, 16), copertura="ind", alias=["taekwondo"]),
    dict(label="Tennis", db="40ff48c9aad980bcb44add4e19816b05", titoli=["la28 tennis", "la 28 tennis"],
         fine=date(2028, 6, 30), copertura="parziale", alias=["tennis"]),
]
SIM_PER_LABEL = {s["label"]: s for s in SIMS}

# Lotta: il modello "Previsioni Wrestling LA28" non e' tra le simulazioni scelte, quindi per ora la lotta usa le
# regole CIO + colonna UWW di Athletes. Per tornare al modello basta mettere True.
USA_MODELLO_WRESTLING = False
WRESTLING_TITLES = ["previsioni wrestling la28"]
WRESTLING_END = date(2028, 6, 30)


def _norm_sport(s):
    return "".join(ch for ch in (s or "").lower() if ch.isalnum())


# sport di Athletes coperti da una simulazione -> etichetta sport usata nelle simulazioni
_SIM_ALIAS = {}
for _s in SIMS:
    _SIM_ALIAS[_norm_sport(_s["label"])] = _s["label"]
    for _a in _s["alias"]:
        _SIM_ALIAS[_a] = _s["label"]
if USA_MODELLO_WRESTLING:
    _SIM_ALIAS["wrestling"] = "Wrestling"


def sim_di(sport_athletes):
    """Nome dello sport in Athletes -> etichetta della simulazione che lo copre (None = si usano le regole CIO)."""
    return _SIM_ALIAS.get(_norm_sport(sport_athletes))
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
    "Golf": ("WON", "punti"),
    "Diving": ("SCORE", "punti"), "Artistic Swimming": ("SCORE", "punti"),
    "Swimming": ("PFM", "tempo"),       # tempo: il valore piu' basso e' il migliore
    "Athletics": ("PFM", "misto"),      # misto: corsa/marcia/staffette = piu' basso, concorsi (salti, lanci) e prove multiple = piu' alto
}
# sport in cui i "Punti per Disciplina" generici NON vanno usati per le prove individuali (conta solo la colonna dedicata)
STRETTE = {"Archery", "Golf", "Diving", "Artistic Swimming", "Swimming", "Athletics"}
METRICHE_CANON = {sport_canonico(k) for k in METRICHE}
STRETTE_CANON = {sport_canonico(k) for k in STRETTE}
BASE_POSIZIONE = 1_000_000.0
# Atleti ritirati: in Athletes la colonna "Honours" contiene l'opzione "⛔️Retired". Non entrano in nessuna classifica
# (nemmeno quelli delle altre nazioni, cosi' non occupano posti) e le loro righe di simulazione non vengono scritte.
PAROLE_RITIRO = ("retired", "ritirat")
RITIRATI_ITA = []          # riempita da leggi_athletes: italiani ritirati (servono per scartare le righe di simulazione)   # per le colonne "posizione" il punteggio interno e' BASE - posizione


def sigla_colonna(nome):
    return "".join(c for c in (nome or "") if c.isascii() and c.isalnum()).upper()


def trova_metrica(props, sigla):
    """Colonna di Athletes la cui sigla (solo lettere/numeri ASCII) e' esattamente quella indicata; evita le varianti in %.
    Se non esiste una colonna con quella sigla esatta, ripiega su una che inizia con la sigla (es. 'PFM A')."""
    for k in props:
        if sigla_colonna(k) == sigla and "\uff05" not in k and "%" not in k:
            return k
    for k in props:
        sc = sigla_colonna(k)
        if sc.startswith(sigla) and len(sc) <= len(sigla) + 2 and "\uff05" not in k and "%" not in k:
            return k
    return None


RE_VAL = r"\d+:\d{2}:\d{2}(?:[.,]\d+)?|\d+:\d{2}(?:[.,]\d+)?|\d+(?:[.,]\d+)?"
RE_PREST = re.compile(r"^\s*(?P<lab>[^:=]*?[A-Za-z][^:=]*?)\s*[:=]\s*(?P<val>" + RE_VAL + r")\s*[A-Za-z%\.]{0,4}\s*$")
RE_SOLO = re.compile(r"^\s*(?P<val>" + RE_VAL + r")\s*[A-Za-z%\.]{0,4}\s*$")
CAMPO = re.compile(r"jump|vault|throw|put|discus|hammer|javelin|shot|decathlon|heptathlon|pentathlon|salto|lancio|getto|asta|peso|disco|martello|giavellotto", re.I)


def a_numero(tok):
    """'1:45.23' -> 105.23 (secondi); '48,12' -> 48.12; '2:05:11' -> 7511."""
    parti = tok.replace(",", ".").split(":")
    v = 0.0
    for p in parti:
        v = v * 60 + float(p)
    return v


def formatta_tempo(sec):
    if sec >= 3600:
        return f"{int(sec // 3600)}:{int(sec % 3600 // 60):02d}:{sec % 60:05.2f}"
    if sec >= 60:
        return f"{int(sec // 60)}:{sec % 60:05.2f}"
    return f"{sec:.2f}"


def leggi_prestazioni(raw):
    """Colonna PFM/SCORE -> ('eventi', {etichetta: (testo,)}) con valori etichettati ("Men's 100m: 9.95"),
    oppure ('lista', [testo, ...]) con uno o piu' valori senza etichetta ("1:45.23" o "3:28.72;3:28.86"), oppure None."""
    if raw in ("", None) or isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        return ("lista", [f"{raw:g}"])
    testo = str(raw)
    ev, lista = {}, []
    for seg in re.split(r"[\n;|]+|,\s+", testo):
        if not seg.strip():
            continue
        m = RE_PREST.match(seg)
        if m:
            ev[m.group("lab").strip(" ,")] = m.group("val")
            continue
        m = RE_SOLO.match(seg)
        if m:
            lista.append(m.group("val"))
    if ev:
        return ("eventi", ev)
    if lista:
        return ("lista", lista)
    return None


def secondi(tok, ev):
    """Valore testuale -> numero. I tempi sono in secondi ('1:45.23' = 105.23). Maratona, marcia e mezza maratona sono
    scritte 'h:mm.ss' ('2:27.55' = 2h27'55\")."""
    if tok.count(":") == 1 and re.match(r"^\d+:\d{2}[.,]\d{2}$", tok) and re.search(r"marathon|walk|half|km", ev or "", re.I):
        h, rest = tok.split(":")
        mm, ss = rest.replace(",", ".").split(".")
        return int(h) * 3600 + int(mm) * 60 + int(ss)
    return a_numero(tok)


def prova_di_campo(ev):
    return bool(CAMPO.search(ev or ""))


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
def call(method, path, body=None, versione=None):
    """Chiamata all'API di Notion. versione: per i database con piu' origini dati serve la versione 2025-09-03."""
    last = ""
    head = dict(HEAD, **({"Notion-Version": versione} if versione else {}))
    for attempt in range(6):
        r = requests.request(method, API + path, headers=head, json=body, timeout=60)
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
            return ";".join(str(flat(x, depth + 1)) for x in v["array"][:40])
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


def _solo_alnum(s):
    return "".join(c for c in (s or "").lower() if c.isascii() and c.isalnum())


def trova_db(dbs, titoli, db_id=None):
    """Database per ID (se indicato e visibile alla connessione), altrimenti per titolo (emoji e spazi ignorati)."""
    if db_id:
        want_id = db_id.replace("-", "").lower()
        for d in dbs:
            if d.get("id", "").replace("-", "").lower() == want_id:
                return d
    want = {_solo_alnum(t) for t in titoli}
    for d in dbs:
        if _solo_alnum(plain(d.get("title"))) in want:
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
    if x is None or isinstance(x, bool) or (isinstance(x, str) and not x.strip()):
        return None       # (attenzione: 1 == True in Python, per questo non si usa "x in (..., True)")
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
    """'Rossi / Bianchi, M.' -> ['Rossi', 'Bianchi, M.']: con la barra non si spezza sulla virgola (iniziale del nome)."""
    sep = r"[/&;]| e " if "/" in (nome or "") else r"[/&,;]| e "
    return [p.strip() for p in re.split(sep, nome or "") if p.strip()]


def toks_utili(s):
    """Parole del nome senza iniziali puntate ('Orsi Toth, R.' -> orsi, toth)."""
    t = [x for x in toks(s) if len(x) > 1]
    return set(t) if t else set(toks(s))


class Rubrica:
    """Atleti italiani di Athletes, cercabili per nome."""

    def __init__(self, atleti):
        self.atleti = atleti
        self.idx = {}
        for a in atleti:
            self.idx.setdefault(chiave_nome(a["nome"]), []).append(a)

    def cerca(self, nome, sport=None):
        t = toks_utili(nome)
        if not t:
            return None
        hit = self.idx.get(" ".join(sorted(t))) or self.idx.get(chiave_nome(nome))
        if hit:
            return self._scegli(hit, sport)
        cand = []
        for a in self.atleti:
            u = toks_utili(a["nome"])
            piccolo, grande = (t, u) if len(t) <= len(u) else (u, t)
            if len(piccolo) >= 2 and piccolo <= grande:
                cand.append(a)
        if cand:
            return self._scegli(cand, sport)
        if not sport:
            return None
        # ultimo tentativo, solo tra gli atleti dello stesso sport: piu' parole in comune (es. cognomi della coppia
        # 'Cottafava / Dal Corso' contro 'Samuele COTTAFAVA/Gianluca DEL CORSO'), oppure un cognome solo se e' unico
        best, pari = None, False
        for a in self.atleti:
            if sim_di(a["sport"]) != sport and a["sport"] != sport:
                continue
            n = len(t & toks_utili(a["nome"]))
            if best is None or n > best[0]:
                best, pari = (n, a), False
            elif n == best[0]:
                pari = True
        if best and not pari and (best[0] >= 2 or (len(t) == 1 and best[0] == 1)):
            return best[1]
        return None

    @staticmethod
    def _scegli(lst, sport):
        if sport:
            sp = [a for a in lst if (sim_di(a["sport"]) or a["sport"]) == sport]
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


def assegna_prestazioni(raw, disc, canon, direzione, stat):
    """PFM/SCORE di un atleta -> {prova di Disciplina: (valore interno 'piu' alto = meglio', testo)}.
    - SCORE (punti): vale per tutte le prove della riga (individuali, coppie, squadre).
    - PFM (tempo/misto): vale per le prove individuali; le staffette restano coi punti generici.
      Un valore senza etichetta e' assegnato alla prova individuale unica; se l'atleta ha piu' prove individuali e un solo
      valore, lo si assegna alla prima prova elencata in Disciplina (la principale)."""
    if raw in ("", None) or (isinstance(raw, str) and not raw.strip()):
        return {}, None
    m = leggi_prestazioni(raw)
    if not m:
        stat["illeggibili"] = stat.get("illeggibili", 0) + 1
        return {}, None
    kind = RULES[canon]["kind"]
    eventi_riga = [e for e in disc.split("|") if e and not e.startswith("\U0001F534")]
    ind = [e for e in eventi_riga if parti_prova(e, kind)[2] == "ind"]
    coppie = {}      # prova -> testo del valore
    if m[0] == "eventi":
        for lab, tok in m[1].items():
            g, res, unita = parti_prova(lab, kind)
            if unita != "ind" and direzione != "punti":
                continue
            imp = "".join(sorted(res.replace(" ", "")))
            cand = ind if unita == "ind" else eventi_riga
            trovato = [e for e in cand if "".join(sorted(parti_prova(e, kind)[1].replace(" ", ""))) == imp
                       and (not g or not parti_prova(e, kind)[0] or parti_prova(e, kind)[0] == g)]
            coppie[trovato[0] if trovato else lab] = tok
    else:
        toks = m[1]
        if direzione == "punti":
            best = max(toks, key=lambda t: secondi(t, ""))
            for e in eventi_riga:
                coppie[e] = best
        elif ind:
            if len(ind) == 1:
                e = ind[0]
                campo = direzione == "misto" and prova_di_campo(e)
                coppie[e] = (max if campo else min)(toks, key=lambda t: secondi(t, e))
            else:
                # piu' prove individuali e valori non etichettati: a quale prova appartiene lo decide dopo, confrontando
                # il valore con quelli tipici di ogni prova (vedi risolvi_ambigui)
                return {}, (toks, ind, direzione)
    out = {}
    for ev, tok in coppie.items():
        v = secondi(tok, ev)
        if direzione == "punti":
            out[ev] = (v, tok)
        elif direzione == "tempo" or (direzione == "misto" and not prova_di_campo(ev)):
            out[ev] = (BASE_POSIZIONE - v, tok) if v > 0 else (0.0, tok)
        else:
            out[ev] = (v, tok)
    return out, None


def chiave_prova(canon, ev):
    g, res, _u = parti_prova(ev, RULES[canon]["kind"])
    return (canon, g, "".join(sorted(res.replace(" ", ""))))


def risolvi_ambigui(ambigui, valori, log):
    """Atleti con piu' prove individuali e una lista di valori PFM senza etichetta (i migliori tempi/misure di tutte le loro
    prove, in ordine sparso): ogni valore e' assegnato alla prova il cui valore tipico (mediana degli atleti con una sola prova)
    e' piu' vicino; per ogni prova si tiene poi il migliore. Valori troppo lontani da ogni prova si scartano."""
    SOGLIA = math.log(1.35)

    def mediane(canon, ind):
        med = {}
        for e in ind:
            v_tip = sorted(valori.get(chiave_prova(canon, e), []))
            if len(v_tip) >= 3:
                med[e] = v_tip[len(v_tip) // 2]
        return med

    # passo 1: per le prove senza valori di confronto (nessun atleta con quella prova sola) si usano i valori "orfani"
    # di chi ha una sola prova senza mediana: tutto cio' che non somiglia alle altre sue prove appartiene a quella
    for _ in range(2):
        for rec, canon, toks, ind, direzione in ambigui:
            med = mediane(canon, ind)
            mancanti = [e for e in ind if e not in med]
            if len(mancanti) != 1:
                continue
            orfani = []
            for t in toks:
                vicino = any(secondi(t, e) > 0 and abs(math.log(secondi(t, e) / m)) <= SOGLIA for e, m in med.items())
                if not vicino:
                    orfani.append(t)
            if orfani:
                e = mancanti[0]
                campo = direzione == "misto" and prova_di_campo(e)
                valori.setdefault(chiave_prova(canon, e), []).append(
                    secondi((max if campo else min)(orfani, key=lambda x: secondi(x, e)), e))
    n_ok, n_prima, esempi = 0, 0, []
    for rec, canon, toks, ind, direzione in ambigui:
        med = mediane(canon, ind)
        per_prova = {}
        if med:
            for t in toks:
                scelta = None
                for e, m in med.items():
                    v = secondi(t, e)
                    if v > 0 and m > 0:
                        dist = abs(math.log(v / m))
                        if scelta is None or dist < scelta[0]:
                            scelta = (dist, e)
                if scelta and scelta[0] <= SOGLIA:
                    per_prova.setdefault(scelta[1], []).append(t)
            n_ok += 1
        if not per_prova:
            e = ind[0]
            campo = direzione == "misto" and prova_di_campo(e)
            per_prova[e] = [(max if campo else min)(toks, key=lambda t: secondi(t, e))]
            n_prima += 1
        for e, tl in per_prova.items():
            campo = direzione == "misto" and prova_di_campo(e)
            t = (max if campo else min)(tl, key=lambda x: secondi(x, e))
            v = secondi(t, e)
            if direzione == "tempo" or (direzione == "misto" and not campo):
                interno = BASE_POSIZIONE - v if v > 0 else 0.0
            else:
                interno = v
            kev = parti_prova(e, RULES[canon]["kind"])[:2]
            for vecchio in [x for x in rec["pts"] if parti_prova(x, RULES[canon]["kind"])[:2] == kev]:
                del rec["pts"][vecchio]
            rec["pts"][e] = interno
            rec["pt_txt"][e] = f"PFM {t}"
        if rec["ita"] and len(esempi) < 10:
            esempi.append(f"{rec['nome']}: " + "; ".join(f"{e} = {rec['pt_txt'][e][4:]}" for e in per_prova)
                          + f"  (valori in lista: {len(toks)}, prove: {len(ind)})")
    if ambigui:
        log(f"PFM con piu' prove e lista di valori: {n_ok} atleti smistati per prova, {n_prima} alla prima prova "
            f"(mancano valori di confronto)")
        for x in esempi:
            log("      " + x)


def leggi_athletes(dbs, log):
    """Legge Athletes a fette per sport (Notion non restituisce piu' di 10000 righe per interrogazione).
    Per gli sport stimati con le regole CIO legge tutte le nazioni (servono per la classifica); per gli sport coperti da
    una simulazione e per quelli senza regole legge solo gli italiani."""
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
        completo = sport_canonico(o) is not None and sim_di(o) is None
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
    hk = prop(pr0, "Honours", tipo="multi_select")
    n_ritirati = 0
    col_metrica = {}
    for sp, (sigla, _) in METRICHE.items():
        col_metrica[sp] = trova_metrica(pr0, sigla)
        if col_metrica[sp] is None:
            log(f"ATTENZIONE: per {sp} non trovo la colonna {sigla} in Athletes")
    log("Colonne dedicate per sport: " + ", ".join(f"{sp}={col_metrica[sp]!r}" for sp in METRICHE))
    campioni = {}
    valori_prova, ambigui = {}, []
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
            if hk and any(w in flat(pr[hk]).lower() for w in PAROLE_RITIRO):
                n_ritirati += 1
                if ita:
                    RITIRATI_ITA.append({"id": p["id"], "nome": nome, "sport": "" if o == "(senza sport)" else o,
                                         "ita": True})
                continue           # ritirato: fuori da classifiche e stime
            if ita:
                pass_vals[pas] = pass_vals.get(pas, 0) + 1
                n_it += 1
            ptsq = num(flat(pr[qk])) if qk else None
            canon = None if sim_di(o) else sport_canonico(o)   # sport con simulazione: niente regole CIO
            disc = flat(pr[dk]) if dk else ""
            pts = parse_punti(flat(pr[pdk]) if pdk else "")
            pt_txt, assegnati, amb_pending = {}, set(), None
            if canon in METRICHE and col_metrica.get(canon) and col_metrica[canon] in pr:
                sigla, direzione = METRICHE[canon]
                raw = flat(pr[col_metrica[canon]])
                cs = campioni.setdefault(canon, {"ita": [], "altri": [], "num": [], "stat": {}})
                if sigla in ("PFM", "SCORE"):
                    m = None
                    ris, amb = assegna_prestazioni(raw, disc, canon, direzione, cs["stat"])
                    if amb:
                        amb_pending = (canon,) + amb
                    for ev, (interno, txt) in ris.items():
                        if direzione != "punti":
                            valori_prova.setdefault(chiave_prova(canon, ev), []).append(secondi(txt, ev))
                        kev = parti_prova(ev, RULES[canon]["kind"])[:2]
                        for vecchio in [e for e in pts if parti_prova(e, RULES[canon]["kind"])[:2] == kev]:
                            del pts[vecchio]
                        pts[ev] = interno
                        pt_txt[ev] = f"{sigla} {txt}"
                        assegnati.add(ev)
                        if direzione != "misto":
                            cs["num"].append(interno if direzione == "punti" else BASE_POSIZIONE - interno)
                else:
                    m = leggi_metrica(raw)
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
                        assegnati.add(ev)
                        kev = parti_prova(ev, RULES[canon]["kind"])[:2]
                        for vecchio in [e for e in pts if parti_prova(e, RULES[canon]["kind"])[:2] == kev]:
                            del pts[vecchio]       # la colonna dedicata sostituisce i punti generici della stessa prova
                        if direzione == "posizione":
                            pts[ev] = BASE_POSIZIONE - v
                            pt_txt[ev] = f"{sigla} {v:g}"
                        else:
                            pts[ev] = v
                            pt_txt[ev] = f"{v:g} {sigla}"
            if canon in STRETTE_CANON:
                # solo la colonna dedicata conta per le prove individuali: i punti generici restano solo per le prove a squadre/coppie
                pts = {e: v for e, v in pts.items()
                       if e in assegnati or parti_prova(e, RULES[canon]["kind"])[2] != "ind"}
            out.append({"id": p["id"], "nome": nome, "sport": "" if o == "(senza sport)" else o,
                        "canon": canon, "noc": noc, "ita": ita,
                        "disc": disc, "pass": pas, "q": is_q(pas),
                        "pts": pts, "ptsq": ptsq, "pt_txt": pt_txt})
            if amb_pending:
                ambigui.append((out[-1], amb_pending[0], amb_pending[1], amb_pending[2], amb_pending[3]))
        log(f"   {o:<24} {len(pagine):>5} atleti letti ({'tutte le nazioni' if completo else 'solo italiani'}), "
            f"italiani {n_it}")
    risolvi_ambigui(ambigui, valori_prova, log)
    for sp, cs in sorted(campioni.items()):
        nums = sorted(cs["num"])
        rng = f"valori numerici {nums[0]:g} .. {nums[-1]:g} (mediana {nums[len(nums)//2]:g}), n={len(nums)}" if nums else "nessun valore numerico"
        log(f"Colonna {METRICHE[sp][0]} per {sp} ({METRICHE[sp][1]}): {rng}")
        if cs.get("stat"):
            log(f"      note di lettura: {cs['stat']}")
        for r in cs["ita"] + cs["altri"]:
            log("      " + r)
    log(f"Atleti ritirati (Honours = Retired) esclusi da classifiche e stime: {n_ritirati}"
        + (f"; italiani: {', '.join(a['nome'] for a in RITIRATI_ITA)}" if RITIRATI_ITA else ""))
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
    qk = prop(db.get("properties", {}), "Q Athletes", tipo="checkbox")
    for p in query(db["id"]):
        pr = p["properties"]
        tk = titolo_di(pr)
        nome = flat(pr[tk]).strip() if tk else ""
        r = {"sport": sport, "end": end, "nome": nome, "noc": val(p, "NOC"), "rank": num(val(p, "Ranking")),
             "stato": val(p, "Stato"), "via": val(p, "Via di qualificazione", "Via"), "dett": val(p, "Dettagli"),
             "atleti": val(p, "Atleti"), "evento": val(p, "Evento"), "disc": val(p, "Disciplina"),
             "genere": val(p, "Genere"), "cat": val(p, "Categoria"), "sim": val(p, "Simulazione"),
             "nazione": val(p, "Nazione"),
             # beach volley: la simulazione riporta gia' se in Athletes la coppia ha Pass LA28 = Q
             "q_ath": bool(qk and qk in pr and flat(pr[qk]) is True)}
        rows.append(r)
    rows, lab = pulisci_sim_label(rows)
    stati = {}
    for r in rows:
        stati[r["stato"] or "(vuoto)"] = stati.get(r["stato"] or "(vuoto)", 0) + 1
    log(f"{sport}: {len(rows)} righe di simulazione ({lab or 'senza etichetta'}). Stati: {stati}")
    return rows


def gruppo(r):
    parti = [r["evento"], r["disc"], r["genere"], r["cat"]]
    return " | ".join(x for x in parti if x)


def etichetta_disciplina(r):
    if r["sport"] in ("Judo", "Taekwondo"):
        return " ".join(x for x in (r["genere"], r["cat"]) if x)
    if r["sport"] == "Tennis":
        return r["evento"] or r["disc"]
    if r["sport"] in ("Beach Volleyball", "Skateboarding"):
        return r["evento"] or " ".join(x for x in (r["disc"], r["genere"]) if x)   # "Torneo maschile", "Park femminile"
    if r["sport"] == "Squash":
        return r["cat"] or " ".join(x for x in ("Singolare", r["genere"]) if x)    # "Singolare maschile"
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



# --------------------------------------------------------------------------- prove del programma senza italiani
# Programma olimpico LA28: database "HOME OF THE OLYMPIC GAMES 🌏" (righe con Tipo = "Olympic Sport Program", estive).
# Per ogni prova del programma in cui in Athletes (e nelle simulazioni) non c'e' nessun atleta o squadra italiana,
# l'agente scrive comunque una riga "Fuori", cosi' la pagina mostra tutto il programma.
PROGRAMMA_DB = "2c5f48c9aad980b690d5e1aa2ce386b4"
# il db ha due origini dati: si legge quella con le prove (serve la versione 2025-09-03 dell'API, quella vecchia non lo vede)
PROGRAMMA_DS = "2c5f48c9aad980ae9bed000b638276c7"
API_DATA_SOURCES = "2025-09-03"
PROGRAMMA_TITOLI = ["home of the olympic games"]
PROGRAMMA_TIPO = "Olympic Sport Program"

_PAROLE_GENERE = {"men", "mens", "man", "women", "womens", "woman", "mixed", "mix", "misto", "mista", "uomini", "donne",
                  "maschile", "femminile", "maschili", "femminili", "ladies", "male", "female"}
_STOP = {"m", "s", "kg", "event", "throw", "the", "and", "di", "a", "e", "del", "della", "tae", "iwf", "box"}
_TRAD = {"inseguimento": "pursuit", "squadre": "team", "squadra": "team", "velocita": "sprint", "strada": "road",
         "cronometro": "trial", "crono": "trial", "singolare": "singles", "doppio": "doubles", "staffetta": "relay",
         "medley": "med", "im": "med", "individuale": "individual", "freestyle": "fs", "synchro": "synch",
         "sync": "synch", "plaftorm": "platform", "parallels": "parallel", "buttefly": "butterfly", "racing": "race",
         "hurdles": "hs", "volley": "", "beach": ""}
# parole che indicano solo lo sport (vanno tolte per confrontare le prove)
_PAROLE_SPORT = {
    "Basketball": {"basketball", "x"}, "Volleyball": {"volleyball"}, "Handball": {"handball"},
    "Hockey": {"hockey", "field"}, "Rugby Sevens": {"rugby", "sevens"}, "Football": {"football", "soccer"},
    "Flag Football": {"flag", "football"}, "Lacrosse": {"lacrosse", "sixes"}, "Cricket": {"cricket", "t"},
    "Water Polo": {"water", "polo"}, "Baseball": {"baseball"}, "Softball": {"softball"}, "Golf": {"golf"},
    "Squash": {"squash", "singles"}, "Surfing": {"surfing", "shortboard"}, "Triathlon": {"triathlon"},
    "Trampoline": {"trampoline"}, "Modern Pentathlon": {"modern", "pentathlon"},
    "Open Water Swimming": {"open", "water", "km", "10", "marathon", "swimming"}, "Judo": {"judo"},
    "Canoeing": {"canoa", "canoe", "canoeing", "slalom", "sprint"}, "Cycling": {"pista", "track", "ciclismo", "cycling"},
    "Beach Volleyball": {"torneo", "volleyball"}, "Skateboarding": {"skateboarding"},
}
_EXTRA_SPORT = {"cyclingbmxracing": {"bmx"}, "cyclingbmxrace": {"bmx"}, "cyclingbmxfreestyle": {"bmx"}}
TIPO_SQUADRA = re.compile(r"team|relay|4x|doubles|duet|synch|sync|pair|double|four|eight|quad|madison|group|"
                          r"\b[kc][24]\b|\b470\b|nacra|49er|sculls \([mwx]?[24]|squadr", re.I)


def famiglia_sport(nome):
    """Nome dello sport (Athletes o programma) -> etichetta usata nella stima (simulazione o regole CIO)."""
    sim = sim_di(nome)
    if sim:
        return sim
    canon = sport_canonico(nome)
    if canon == "3x3 Basketball":
        return "Basketball"
    return canon


def genere_prova(testo):
    t = senza_emoji(testo).lower()
    if re.search(r"\bwom[ae]n|\bfemmin|\bdonne|\bladies", t):
        return "W"
    if re.search(r"\bm[ae]n\b|\bmens\b|\bmaschil|\buomini", t):
        return "M"
    if re.search(r"mixed|\bmist[oa]\b|\bmix", t):
        return "X"
    return ""


def parole_prova(testo, fam, extra=()):
    """Testo della prova -> (numeri, parole): '+100kg' e '-100kg' restano diversi, '3x3' resta un'unica parola."""
    t = senza_emoji(testo).lower().replace("+", " piu ").replace("3x3", " tretre ").replace("'", " ")
    t = re.sub(r"(\d)([a-z])", r"\1 \2", t)
    t = re.sub(r"([a-z])(\d)", r"\1 \2", t)
    togli = _PAROLE_SPORT.get(fam, set())
    out = set(extra)
    for w in re.findall(r"[a-z]+|\d+", t):
        w = _TRAD.get(w, w)
        if not w or w in _STOP or w in _PAROLE_GENERE or w in togli:
            continue
        out.add(w)
    num = {w for w in out if w.isdigit() or w == "piu"}
    return frozenset(num), frozenset(out - num)


def stessa_prova(a, b):
    """a, b = (genere, numeri, parole). Genere uguale (o non indicato), stessi numeri, parole compatibili."""
    ga, na, pa = a
    gb, nb, pb = b
    if ga and gb and ga != gb:
        return False
    if na != nb:
        return False
    if pa <= pb or pb <= pa:
        return True
    sa, sb = "".join(sorted(pa)), "".join(sorted(pb))
    return sa in sb or sb in sa or difflib.SequenceMatcher(None, sa, sb).ratio() >= 0.85


def leggi_programma(dbs, log):
    """Prove estive del programma LA28. Prima prova l'origine dati del programma con l'API nuova (il db ha due origini
    dati), poi il db per ID/titolo con l'API vecchia."""
    pr0, pagine, fonte = None, None, ""
    try:
        ds = call("GET", f"/data_sources/{PROGRAMMA_DS}", versione=API_DATA_SOURCES)
        pr0 = ds["properties"]
        fonte = plain(ds.get("title")) or "programma LA28"
    except RuntimeError as e:
        log(f"Programma LA28: origine dati non leggibile con l'API nuova ({str(e)[:160]})")
    d = None
    if pr0 is None:
        d = trova_db(dbs, PROGRAMMA_TITOLI, PROGRAMMA_DB)
        if not d:
            log("ATTENZIONE: non trovo il db del programma olimpico ('HOME OF THE OLYMPIC GAMES'): le prove senza "
                "italiani non vengono aggiunte. Collega il db alla connessione Notion dell'agente.")
            return None
        pr0, fonte = d["properties"], plain(d.get("title"))
    tk = prop(pr0, "Tipo", tipo="select")
    sk = prop(pr0, "Season", "Stagione", tipo="select")
    spk = prop(pr0, "Sport", tipo="select")
    dk = prop(pr0, "Disciplina", tipo="select")
    if not (tk and spk and dk):
        log(f"ATTENZIONE: nel db del programma non trovo le colonne Tipo/Sport/Disciplina: {list(pr0)[:30]}")
        return None
    flt = {"property": tk, "select": {"equals": PROGRAMMA_TIPO}}
    if d is None:
        pagine, cur = [], None
        while True:
            body = {"page_size": 100, "filter": flt}
            if cur:
                body["start_cursor"] = cur
            r = call("POST", f"/data_sources/{PROGRAMMA_DS}/query", body, versione=API_DATA_SOURCES)
            pagine += r["results"]
            if not r.get("has_more"):
                break
            cur = r["next_cursor"]
    else:
        pagine = query(d["id"], flt)
    out = []
    for p in pagine:
        pr = p["properties"]
        if sk and sk in pr and "winter" in str(flat(pr[sk])).lower():
            continue
        sp = flat(pr[spk]).strip() if spk in pr else ""
        di = flat(pr[dk]).strip() if dk in pr else ""
        if sp and di and sp not in INVERNALI:
            out.append((sp, di))
    log(f"Programma LA28: {len(out)} prove estive lette da '{fonte}'.")
    return out


def prove_senza_italiani(programma, atleti, sims, righe_stima, log):
    """Righe 'Fuori' per le prove del programma in cui non c'e' nessun italiano (ne' in Athletes ne' nelle simulazioni)."""
    presenti = {}      # famiglia -> [(genere, numeri, parole)]
    for a in atleti:
        if not a["ita"]:
            continue
        fam = famiglia_sport(a["sport"])
        if not fam:
            continue
        for ev in (a["disc"] or "").split("|"):
            if ev and not ev.startswith("\U0001F534"):
                presenti.setdefault(fam, []).append((genere_prova(ev),) + parole_prova(ev, fam))
    for sport, rows in sims.items():
        for r in rows:
            if is_italiano(r):
                testo = " ".join(x for x in (r["evento"], r["disc"], r["cat"]) if x)
                g = genere_prova(" ".join((r["genere"], r["evento"], r["cat"])))
                presenti.setdefault(sport, []).append((g,) + parole_prova(testo, sport))
    for r in righe_stima:          # prove che hanno gia' una riga nella stima (anche se la Disciplina di Athletes e' diversa)
        presenti.setdefault(r["sport"], []).append((genere_prova(r["disciplina"] + " " + r["nome"]),)
                                                   + parole_prova(r["disciplina"], r["sport"]))
    righe, viste, senza_fam = [], set(), set()
    for sp, di in programma:
        fam = famiglia_sport(sp)
        if not fam:
            senza_fam.add(sp)
            continue
        extra = _EXTRA_SPORT.get(_norm_sport(sp), ())
        prova = (genere_prova(di),) + parole_prova(di, fam, extra)
        if (fam,) + prova in viste:
            continue
        viste.add((fam,) + prova)
        if any(stessa_prova(prova, x) for x in presenti.get(fam, [])):
            continue
        g = prova[0]
        disc = re.sub(r"^[^A-Za-z0-9+\-]+", "", di).strip()
        squadra = (RULES.get(fam, {}).get("kind") in ("team", "pair") or fam == "Beach Volleyball"
                   or bool(TIPO_SQUADRA.search(disc)))
        nome = ("Italia" + (f" ({IT_GENERE[g]})" if g else "")) if squadra else "Nessun atleta italiano"
        fine = (SIM_PER_LABEL[fam]["fine"] if fam in SIM_PER_LABEL else
                RULES[fam]["fine"] if fam in RULES else None)
        righe.append(dict(sport=fam, disciplina=disc[:100], nome=nome, tipo="Squadra" if squadra else "Atleta",
                          livello="Fuori", p=1.0, via="", rank=None, margine=None, stato="Nessun italiano",
                          pass_="", fine=fine.isoformat() if fine else "",
                          nota=("prova in programma a LA28 ma in Athletes non c'e' nessun atleta o squadra italiana "
                                "(e nessuna riga nelle simulazioni): oggi l'Italia non risulta in corsa. Se ci sono "
                                "italiani in questa prova, aggiungili ad Athletes con la disciplina corretta.")))
    log(f"\nProve del programma LA28 senza nessun italiano in Athletes o nelle simulazioni: {len(righe)}")
    for r in righe:
        log(f"   - {r['sport']}: {r['disciplina']}")
    if senza_fam:
        log(f"   (sport del programma non riconosciuti, saltati: {', '.join(sorted(senza_fam))})")
    return righe

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
    # "Ranking WSR (posto ospitante riassegnato)", "Qualificazione diretta (posto ospitante riassegnato)":
    # il posto del paese ospitante torna al ranking, quindi e' un posto da ranking a tutti gli effetti
    if re.search(r"(ranking|diretta|diretto).*riassegnat", v):
        return True
    if any(w in v for w in ("continent", "ospitant", "host", "universal", "grand slam", "champ", "invito",
                            "riassegn", "riserva", "primi fuori", "mondiali")) or TORNEO.search(v):
        return False
    return any(w in v for w in ("ranking", "diretta", "diretto", "oqr", "top ")) or v == ""


def contesto_tornei(rows):
    """Per ogni gruppo (prova/categoria): posti assegnati da un torneo di qualificazione finale (righe 'In attesa' con via
    torneo/Q-Series) e forza complessiva dei candidati (somma di 1/ranking), per dividere i posti tra i candidati."""
    ctx = {}
    for r in rows:
        if not TORNEO.search(r["via"] or ""):
            continue
        x = ctx.setdefault(gruppo(r), {"posti": 0, "n": 0, "forza": 0.0})
        st = r["stato"].lower()
        if st == "in attesa":
            x["posti"] += 1
        elif st == "candidato" and r["rank"]:
            x["n"] += 1
            x["forza"] += 1.0 / r["rank"]
    return ctx


def via_fissa(via, default=0.50):
    v = (via or "").lower()
    return next((pp for w, pp in VIA_FISSA if w in v), default)


def soglie(rows):
    """Per ogni gruppo (categoria/prova): ultimo ranking tra quelli dentro per ranking diretto."""
    cut = {}
    for r in rows:
        if r["stato"].lower() in IN_STATI and via_ranking(r["via"]) and r["rank"]:
            g = gruppo(r)
            cut[g] = max(cut.get(g, 0), r["rank"])
    return cut


def stima_sim(r, cut, tornei=None):
    """Restituisce (probabilita' 0-100, margine, motivazione)."""
    st = r["stato"].lower()
    via = (r["via"] or "").lower()
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
            if st in ("qualificato", "garantito"):
                p = max(p, 0.90)
            return round(p * 100, 1), margine, (f"ranking {rank:g}, ultimo posto utile {c:g}: margine {margine:+g}; "
                                                f"{m:.0f} mesi alla fine del periodo")
        p = via_fissa(via)
        if st in ("qualificato", "garantito"):
            p = max(p, 0.90)
            return round(p * 100, 1), margine, f"posto gia' assegnato nella simulazione ('{r['via']}'), in attesa del Pass"
        return round(p * 100, 1), margine, f"posto condizionato alla via '{r['via']}': stima prudenziale fissa"
    if st == "ipotesi":
        p = via_fissa(via, 0.30) * SCONTO_IPOTESI
        return round(p * 100, 1), margine, (f"posto ipotizzato dalla simulazione via '{r['via']}' "
                                            "(evento non ancora disputato): stima prudenziale")
    if st == "riserva" or (st == "candidato" and "riserv" in via):
        if p_rank is None:
            return 12.0, margine, "riserva: entra solo se un posto resta libero"
        p = min(0.6, max(0.10, p_rank * 0.8))
        return round(p * 100, 1), margine, (f"riserva: ranking {rank:g}, ultimo posto utile {c:g} (margine {margine:+g}); "
                                            f"{m:.0f} mesi alla fine del periodo")
    if st == "candidato" and TORNEO.search(via):
        t = (tornei or {}).get(gruppo(r), {})
        posti = t.get("posti") or 1
        if rank and t.get("forza"):
            p_t = posti * (1.0 / rank) / t["forza"]
            dett = (f"candidato al torneo finale ('{r['via']}'): {posti} posti per {t['n']} candidati, "
                    f"quota stimata in base al ranking {rank:g}")
        else:
            p_t = 0.05
            dett = f"candidato al torneo finale ('{r['via']}'): posti e avversari non misurabili"
        p_t = min(MAX_TORNEO, max(0.01, p_t))
        p = 1 - (1 - (p_rank or 0.0)) * (1 - p_t)        # resta anche la strada del ranking diretto
        if p_rank is not None:
            dett += f"; per il ranking diretto serve risalire al posto {c:g} (margine {margine:+g})"
        return round(min(0.9, p) * 100, 1), margine, dett
    if st == "candidato":
        p = max(0.03, (p_rank or 0.0) * 0.5)
        return round(p * 100, 1), margine, f"candidato senza posto assegnato (via '{r['via']}')"
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
PARSE_PAIR = re.compile(r"doubles|duet|synch|pair|double|2x|2-|coppia", re.I)
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
        if not prove and a["ptsq"] and a["ptsq"] > 0 and a["canon"] not in STRETTE_CANON:
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
    rub_rit = Rubrica(RITIRATI_ITA)
    scartati_rit = []
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

    # --- simulazioni a righe (beach volley, canoa, ciclismo, judo, skateboarding, squash, taekwondo, tennis)
    nomi_sim = {}        # sport -> parole di ogni nome italiano nella simulazione (per non dare "Fuori" a chi c'e' ma non e' abbinato)
    for sport, rows in sims.items():
        cfg = SIM_PER_LABEL.get(sport, {})
        cut = soglie(rows)
        tornei = contesto_tornei(rows)
        for r in rows:
            if not is_italiano(r):
                continue
            nome = r["nome"] or "(senza nome)"
            if RITIRATI_ITA and not r["atleti"] and "/" not in nome and cfg.get("copertura") != "nazione":
                rit = rub_rit.cerca(nome, sport)
                if rit and not rub.cerca(nome, sport):
                    scartati_rit.append(f"{sport}: {nome}")
                    continue       # atleta ritirato ancora presente nella simulazione
            nomi_sim.setdefault(sport, []).append({x for x in toks_utili(r["atleti"] or nome) if len(x) >= 3})
            squadra = bool(r["atleti"]) or "/" in nome or "(ITA)" in nome.upper() or cfg.get("copertura") == "nazione"
            trovati = []
            if squadra and cfg.get("riga_unica"):
                # in Athletes la coppia e' una riga sola ("Valentina GOTTARDI/Reka ORSI TOTH")
                nomi = [r["atleti"] or nome]
                trovati = [rub.cerca(nomi[0], sport)]
                if not trovati[0]:
                    nomi = parti_squadra(r["atleti"] or nome)
                    trovati = [rub.cerca(n, sport) for n in nomi]
            else:
                nomi = parti_squadra(r["atleti"] or nome) if squadra else [nome]
                trovati = [rub.cerca(n, sport) for n in nomi if "(ita)" not in n.lower()]
            trovati = [t for t in trovati if t]
            for t in trovati:
                usati.add(t["id"])
            certo = bool(trovati) and all(t["q"] for t in trovati) and (not squadra or len(trovati) == len(nomi))
            certo = certo or r.get("q_ath", False)
            pas = "Q" if certo else ""
            if certo:
                p, marg, nota = 100.0, None, "in Athletes la colonna Pass LA28 e' Q: qualificazione acquisita"
                liv = "Certo"
            else:
                p, marg, nota = stima_sim(r, cut, tornei)
                liv = livello(p)
            aggiungi(sport=sport, disciplina=etichetta_disciplina(r) or sport, nome=nome,
                     tipo="Squadra" if squadra else "Atleta", livello=liv, p=p, via=r["via"], rank=r["rank"],
                     margine=marg, stato=r["stato"], nota=(nota + ("; " + r["dett"] if r["dett"] else ""))[:1900],
                     pass_=pas, fine=r["end"].isoformat())

    # --- wrestling (modello a simulazione di incontri): usato solo se USA_MODELLO_WRESTLING = True
    for w in (wrest if USA_MODELLO_WRESTLING else []):
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
    non_abbinati, quasi = [], []
    for a in athletes:
        if a["id"] in usati or a["sport"] in INVERNALI:
            continue
        sp_sim = sim_di(a["sport"])
        cfg = SIM_PER_LABEL.get(sp_sim, {})
        disc = a["disc"].replace("|", ", ") if a["disc"] else a["sport"]
        if a["q"]:
            aggiungi(sport=sp_sim or a["sport"] or "Other", disciplina=disc, nome=a["nome"], livello="Certo", p=100.0,
                     stato="Pass LA28", nota="in Athletes la colonna Pass LA28 e' Q: qualificazione acquisita",
                     pass_="Q")
        elif re.search(r"\bteam\b|\bmixed\b", a["nome"], re.I):
            continue      # voce di squadra (es. 'ITA Judo Mixed Team'), non un atleta
        elif sp_sim and sp_sim not in sims and sp_sim != "Wrestling":
            aggiungi(sport=sp_sim, disciplina=disc, nome=a["nome"], livello="Dati insufficienti", p=None,
                     stato="Senza simulazione", fine=cfg["fine"].isoformat(),
                     nota="il database di simulazione di questo sport non e' leggibile dalla connessione Notion")
        elif cfg.get("copertura") == "nazione":
            continue      # la simulazione e' a livello di nazione/equipaggio: le righe di squadra coprono questi sport
        elif sp_sim and any(len({x for x in toks_utili(a["nome"]) if len(x) >= 3} & ns) >= 2
                            for ns in nomi_sim.get(sp_sim, [])):
            # nome e cognome compaiono nella stessa riga della simulazione ma l'abbinamento non e' riuscito: meglio nessuna
            # riga che un "Fuori" sbagliato (un solo cognome in comune, es. fratelli o omonimi, non basta)
            quasi.append(a)
        elif cfg.get("copertura") == "ind" or (sp_sim == "Wrestling" and USA_MODELLO_WRESTLING):
            non_abbinati.append(a)
            end = cfg["fine"] if cfg else WRESTLING_END
            tipo = "Squadra" if cfg.get("riga_unica") and "/" in a["nome"] else "Atleta"
            aggiungi(sport=sp_sim, disciplina=disc, nome=a["nome"], tipo=tipo, livello="Fuori", p=1.0,
                     stato="Non in classifica", fine=end.isoformat(),
                     nota=("la coppia non compare nella simulazione: fuori dalle posizioni utili" if tipo == "Squadra"
                           else "non compare nella simulazione: fuori dalle posizioni utili del ranking olimpico"))
        else:
            motivo = ("la simulazione non ha una riga per questo atleta" if sp_sim
                      else "sport senza regole di qualificazione nel file regole_la28.py")
            aggiungi(sport=sp_sim or a["sport"] or "Other", disciplina=disc, nome=a["nome"], livello="Dati insufficienti",
                     p=None, stato="Senza simulazione", nota=motivo,
                     fine=cfg["fine"].isoformat() if cfg else "")
    if scartati_rit:
        log(f"Righe di simulazione scartate perche' l'atleta e' ritirato: {', '.join(scartati_rit)}")
    log(f"Atleti di Athletes in sport simulati che non compaiono nella simulazione (scritti come Fuori): "
        f"{len(non_abbinati)}")
    for a in non_abbinati[:80]:
        log(f"   - {a['sport']}: {a['nome']}")
    if quasi:
        log(f"ATTENZIONE: {len(quasi)} atleti hanno nome e cognome in una riga della simulazione ma l'abbinamento non e' "
            f"riuscito (nessuna riga scritta per loro, controlla la grafia):")
        for a in quasi[:40]:
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


# --------------------------------------------------------------------------- riepilogo delle quote italiane per sport
# Conta le QUOTE (posti-atleta) che l'Italia porterebbe a LA28, per sport, livello e genere. Non tocca le righe della
# stima ne' Notion: il risultato va solo nel log, in stima_la28.json (chiave "quote") e nella pagina stima.html.
# Le regole per contare (tetti per NOC, rose delle squadre, gruppi di prove) sono in regole_la28.py, QUOTE_RIEPILOGO.
LIVELLI_QUOTE = ["Certo", "Probabile", "Possibile", "Remoto"]     # Fuori e Dati insufficienti non contano
NOMI_GENERE = {"U": "Uomini", "D": "Donne", "X": "Misto"}
MISTA = "M"            # prova mista (es. squadra mista dell'arco): i posti si dividono tra uomini e donne
ANONIMA = re.compile(r"^\s*(italia|italy)\b", re.I)    # righe di squadra senza nomi: "Italia (uomini)", "Italy (ITA)"
METODO_QUOTE = (
    "Si contano i posti-atleta, non le righe: un atleta conta una volta sola per sport, al suo livello migliore "
    "(anche se e' stimato in piu' prove o discipline dello stesso sport). Una squadra vale i suoi componenti (la rosa "
    "olimpica negli sport di squadra); se una squadra si qualifica, i suoi componenti coprono anche le prove "
    "individuali e non si sommano. Le prove miste valgono meta' uomini e meta' donne. Mai oltre il massimo di atleti "
    "per nazione. Fuori e Dati insufficienti non sono contati."
)


def gruppo_riepilogo(r):
    """Sport della riga -> sport del riepilogo (es. Open Water Swimming -> Swimming, basket 3x3 separato dal 5x5)."""
    sport = GRUPPI_RIEPILOGO.get(r["sport"], r["sport"])
    for sp, rx, nuovo in SEPARA_RIEPILOGO:
        if sport == sp and re.search(rx, f"{r['disciplina']} {r['nome']}", re.I):
            return nuovo
    return sport


def genere_quota(r, cfg):
    """Genere dei posti della riga: "U" uomini, "D" donne, MISTA (da dividere), "X" Open, "?" non riconosciuto.
    Si guarda prima la disciplina, poi il nome (es. "Italia (donne)")."""
    if cfg.get("genere"):
        return cfg["genere"]
    for testo in (r["disciplina"], r["nome"]):
        t = senza_emoji(testo).lower()
        if re.search(r"mixed|\bmist[oa]\b|\bmix\b|\bnacra\b", t):
            return MISTA
        if re.search(r"\bwom[ae]n|\bfemmin|\bdonne\b|\bladies\b|heptathlon|\bwag\b", t):
            return "D"
        if re.search(r"\bm[ae]n\b|\bmens\b|\bmaschil|\buomini\b|decathlon|\bmag\b", t):
            return "U"
    return "?"


def chiave_persona(nome):
    """Nome di una persona -> insieme delle parole del nome, per riconoscerla in righe diverse.
    Toglie le note tra parentesi quadre ([L], [R]), i segni in apice (²ˣʷᶜ, ᵒᶜ⁺ʷᶜ), le iniziali e la parola ITA."""
    s = re.sub(r"\[.*?\]", " ", nome or "")
    s = "".join(c for c in s if not unicodedata.decomposition(c).startswith(("<super>", "<sub>")))
    return frozenset(t for t in toks(s) if len(t) > 1 and not t.isdigit())


def persone_riga(nome):
    """Persone con nome nella riga: [] per le righe di squadra senza nomi ("Italia", "Italy (ITA)"),
    una persona per gli atleti, due per le coppie scritte "A/B" o "A / B"."""
    if ANONIMA.match(nome or ""):
        return []
    parti = parti_squadra(nome) if "/" in (nome or "") else [nome]
    return [k for k in (chiave_persona(p) for p in parti) if k]


def posti_riga(pool, cfg, disciplina):
    """Quanti posti vale una riga senza nomi: la prima regex di "posti" del pool che descrive la prova, altrimenti
    la rosa (sport di squadra), altrimenti 1."""
    for rx, n in pool.get("posti", []):
        if re.search(rx, disciplina, re.I):
            return n
    return cfg.get("rosa") or 1


class Persone:
    """Le persone con nome di uno sport. Riconosce la stessa persona anche se il nome e' scritto in modo diverso:
    stesse parole, oppure parole di uno contenute nell'altro (es. "Gottardi" e "Valentina GOTTARDI"), purche' non ci
    siano due persone possibili."""

    def __init__(self):
        self.parole = []       # id -> insieme di parole
        self.genere = []       # id -> "U" / "D" / None

    def trova(self, tok):
        uguali = [i for i, p in enumerate(self.parole) if p == tok]
        if uguali:
            return uguali[0]
        simili = [i for i, p in enumerate(self.parole) if tok <= p or p <= tok]
        if len(simili) == 1:
            if len(tok) > len(self.parole[simili[0]]):
                self.parole[simili[0]] = tok          # tengo la forma piu' completa del nome
            return simili[0]
        self.parole.append(tok)
        self.genere.append(None)
        return len(self.parole) - 1


def _pool_di(cfg, disciplina):
    """Indice del pool della prova: il primo la cui regex "prove" la descrive (None = tutte le righe rimaste)."""
    for i, p in enumerate(cfg["pool"]):
        if p.get("prove") is None or re.search(p["prove"], disciplina, re.I):
            return i
    return len(cfg["pool"]) - 1


def _tetto(valore, g):
    """Tetto del pool o dello sport per il genere g: un numero vale per tutti i generi, un dizionario per genere."""
    if valore is None:
        return None
    if isinstance(valore, dict):
        return valore.get(g)
    return valore


def quote_sport(nome, righe_sport, avvisi):
    """Quote di uno sport. Restituisce {genere: [scalino Certo, scalino Probabile, scalino Possibile, scalino Remoto]},
    dove ogni scalino e' il numero di posti a quel livello O MEGLIO."""
    cfg = QUOTE_RIEPILOGO.get(nome)
    if cfg is None:
        avvisi.append(f"[DA VERIFICARE] {nome}: sport senza regole di conteggio in QUOTE_RIEPILOGO "
                      "(contati gli atleti, senza tetto per nazione)")
        cfg = {}
    cfg = dict(cfg)
    if "pool" not in cfg:                   # sport di squadra (rosa) o sport senza regole: un solo pool
        rosa = cfg.get("rosa")
        cfg["pool"] = [dict(nome="squadra", prove=None, tetto=rosa, posti=[(".", rosa)] if rosa else [])]
        if rosa and "tetto" not in cfg:
            cfg["tetto"] = rosa
    persone = Persone()
    grezze = []                             # (riga, livello 0-3, pool, genere, [id persone], posti senza nomi, squadra)
    for r in righe_sport:
        k = LIVELLI_QUOTE.index(r["livello"])
        ip = _pool_di(cfg, r["disciplina"])
        pool = cfg["pool"][ip]
        g = genere_quota(r, cfg)
        if g == "?":
            avvisi.append(f"[DA VERIFICARE] {nome}: genere non riconosciuto per '{r['disciplina']}' "
                          f"({r['nome']}): contato in Misto")
            g = "X"
        ids = [persone.trova(t) for t in persone_riga(r["nome"])]
        posti = 0 if ids else posti_riga(pool, cfg, r["disciplina"])
        squadra = bool(pool.get("squadra") and re.search(pool["squadra"], r["disciplina"], re.I))
        if g in ("U", "D"):
            for i in ids:
                persone.genere[i] = persone.genere[i] or g      # il genere della persona serve alle prove miste
        grezze.append((k, ip, g, ids, posti, squadra))
    # le prove miste si dividono: meta' uomini, meta' donne (con un numero dispari, uno in piu' alle donne)
    voci = []                               # (livello, pool, genere, [id], posti senza nomi, squadra)
    for k, ip, g, ids, posti, squadra in grezze:
        if g != MISTA:
            voci.append((k, ip, g, ids, posti, squadra))
            continue
        n = len(ids) or posti
        resto = {"U": n // 2, "D": n - n // 2}
        per_genere = {"U": [], "D": []}
        for i in ids:                       # prima chi ha gia' un genere dalle altre righe
            gi = persone.genere[i]
            if gi in resto and resto[gi] > 0:
                per_genere[gi].append(i)
                resto[gi] -= 1
        for i in ids:                       # poi gli altri, a completare la composizione
            if any(i in v for v in per_genere.values()):
                continue
            gi = "U" if resto["U"] > 0 else "D"
            per_genere[gi].append(i)
            resto[gi] -= 1
            persone.genere[i] = persone.genere[i] or gi
        for gi in ("U", "D"):
            if ids and per_genere[gi]:
                voci.append((k, ip, gi, per_genere[gi], 0, False))
            elif not ids and resto[gi] > 0:
                voci.append((k, ip, gi, [], resto[gi], False))
    # livello migliore di ogni persona (e il pool e il genere in cui lo raggiunge): una persona conta una volta sola
    migliore = {}
    for k, ip, g, ids, _p, _s in voci:
        for i in ids:
            if i not in migliore or k < migliore[i][0]:
                migliore[i] = (k, ip, g)
    risultato = {}
    for g in sorted({v[2] for v in voci}):
        famiglie = {}
        for ip, pool in enumerate(cfg["pool"]):
            mie = [v for v in voci if v[1] == ip and v[2] == g]
            if not mie and not any(m[1] == ip and m[2] == g for m in migliore.values()):
                continue
            scalini = []
            for k in range(len(LIVELLI_QUOTE)):
                nominati = sum(1 for (kk, pp, gg) in migliore.values() if pp == ip and gg == g and kk <= k)
                senza_nomi = [v[4] for v in mie if v[0] <= k and v[4] > 0]
                if pool.get("modo") == "somma":
                    tot = nominati + sum(senza_nomi)
                else:
                    tot = max([nominati] + senza_nomi)
                if pool.get("tetto_squadra") is not None:
                    con_squadra = any(v[5] for v in mie if v[0] <= k)
                    tetto = pool["tetto_squadra"] if con_squadra else pool.get("tetto_senza")
                else:
                    tetto = _tetto(pool.get("tetto"), g)
                scalini.append(min(tot, tetto) if tetto is not None else tot)
            fam = pool.get("famiglia") or f"#{ip}"
            prec = famiglie.get(fam, [0] * len(LIVELLI_QUOTE))
            famiglie[fam] = [a + b for a, b in zip(prec, scalini)]
        totale = [0] * len(LIVELLI_QUOTE)
        for fam, scalini in famiglie.items():
            tetto_fam = cfg.get("famiglie", {}).get(fam)
            if tetto_fam is not None:
                scalini = [min(s, tetto_fam) for s in scalini]
            totale = [a + b for a, b in zip(totale, scalini)]
        tetto_sport = _tetto(cfg.get("tetto"), g)
        if tetto_sport is not None:
            totale = [min(s, tetto_sport) for s in totale]
        elif cfg.get("tetto") is not None:
            avvisi.append(f"[DA VERIFICARE] {nome}: nessun tetto per {NOMI_GENERE[g].lower()}")
        risultato[g] = totale
    if cfg.get("nota"):
        avvisi.append(cfg["nota"])
    return risultato


def per_livello(scalini):
    """Dagli scalini ("a quel livello o meglio") alle quote di ogni livello: differenza con lo scalino prima."""
    out, prima = {}, 0
    for liv, s in zip(LIVELLI_QUOTE, scalini):
        out[liv] = s - prima
        prima = s
    out["Totale"] = scalini[-1] if scalini else 0
    return out


def riepilogo_quote(righe, log):
    """Riepilogo delle quote italiane per sport, livello e genere (log + dati per stima_la28.json)."""
    per_sport = {}
    for r in righe:
        if r["livello"] in LIVELLI_QUOTE:
            per_sport.setdefault(gruppo_riepilogo(r), []).append(r)
    avvisi, sport = [], []
    vuoto = {liv: 0 for liv in LIVELLI_QUOTE + ["Totale"]}
    tot = dict(vuoto, genere={NOMI_GENERE[g]: dict(vuoto) for g in ("U", "D", "X")})
    for nome in sorted(per_sport, key=chiave_alfabetica):
        q = quote_sport(nome, per_sport[nome], avvisi)
        voce = dict(vuoto, nome=nome, genere={})
        for g in ("U", "D", "X"):
            if g not in q:
                continue
            liv = per_livello(q[g])
            voce["genere"][NOMI_GENERE[g]] = liv
            for k, v in liv.items():
                voce[k] += v
                tot[k] += v
                tot["genere"][NOMI_GENERE[g]][k] += v
        if voce["Totale"]:
            sport.append(voce)
    tot["genere"] = {k: v for k, v in tot["genere"].items() if v["Totale"]}
    # log: una riga per sport con il totale e il dettaglio per genere
    log("\n=== Quote italiane per sport (posti-atleta, non righe) ===")
    intest = "".join(f"{x[:9]:>10}" for x in LIVELLI_QUOTE + ["Totale"])
    log(f"  {'Sport':<22}{intest}   dettaglio per genere (C/Pb/Ps/R)")
    for s in sport + [dict(tot, nome="TOTALE ITALIA")]:
        dett = "  ".join(f"{gn[0]} {v['Certo']}/{v['Probabile']}/{v['Possibile']}/{v['Remoto']}"
                         for gn, v in s["genere"].items())
        log(f"  {s['nome'][:22]:<22}" + "".join(f"{s[x]:>10}" for x in LIVELLI_QUOTE + ["Totale"]) + f"   {dett}")
    avvisi = list(dict.fromkeys(avvisi))           # senza doppioni, nell'ordine in cui sono comparsi
    for a in avvisi:
        log("  " + a)
    return {"livelli": LIVELLI_QUOTE, "sport": sport, "totale": tot, "avvisi": avvisi, "metodo": METODO_QUOTE}


# --------------------------------------------------------------------------- json per la pagina web
METODO = [
    "Il livello Certo vale solo se in Athletes la colonna Pass LA28 e' Q. La colonna Status LA28 non viene usata.",
    "Beach volley, canoa, ciclismo, judo, skateboarding, squash, taekwondo e tennis partono dalle simulazioni gia' presenti "
    "in Notion (ranking olimpico attuale): il margine e' la distanza in posti tra l'atleta, la coppia o la nazione e l'ultimo "
    "posto utile della stessa categoria. Le riserve valgono in base alla distanza da quel posto; chi e' candidato a un torneo "
    "finale (Q-Series del beach volley, torneo finale dello squash) riceve la sua quota dei posti del torneo in proporzione "
    "al ranking, piu' la chance di rientrare dal ranking diretto; i posti ipotizzati (es. vincitore continentale non ancora "
    "deciso) hanno una stima prudenziale fissa.",
    "Tutte le altre discipline estive, lotta compresa, usano i regolamenti di qualificazione del CIO (posti per prova, limite per nazione, "
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
    "Per alcuni sport il punteggio non e' la colonna 'Punti per Disciplina' ma una colonna dedicata di Athletes: WON (badminton, "
    "tennis tavolo, vela, arrampicata, arco individuale, triathlon, golf), FEN (scherma), WB (pugilato), UWW (lotta), KG (pesi), "
    "SCORE (tuffi, nuoto artistico), PFM (nuoto e atletica: tempo piu' basso = meglio per nuoto, corsa, marcia; misura piu' alta = "
    "meglio per salti, lanci e prove multiple).",
    "Sono elencate anche le prove del programma LA28 in cui in Athletes non c'e' nessun atleta o squadra italiana: "
    "compaiono come 'Fuori' con la nota 'Nessun italiano'.",
    "Atletica: quote e standard sono provvisori fino a dicembre 2026. E' una stima euristica per orientarsi, non un calcolo "
    "ufficiale: i regolamenti completi sono sul sito del CIO.",
]


def chiave_alfabetica(t):
    t = unicodedata.normalize("NFKD", t or "")
    return "".join(c for c in t if not unicodedata.combining(c)).casefold()


def scrivi_json(righe, note, quote=None):
    conteggi = {n: 0 for n in LIVELLI}
    sport = {}
    for r in righe:
        conteggi[r["livello"]] += 1
        s = sport.setdefault(r["sport"], {"nome": r["sport"], "n": 0, **{n: 0 for n in LIVELLI}})
        s["n"] += 1
        s[r["livello"]] += 1
    elenco = sorted(sport.values(), key=lambda s: chiave_alfabetica(s["nome"]))      # ordine alfabetico
    out = {
        "aggiornato": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "totali": conteggi, "sport": elenco, "metodo": METODO, "note": note,
        "quote": quote,          # riepilogo delle quote italiane per sport (sezione nuova della pagina)
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
    for s in SIMS:
        d = trova_db(dbs, s["titoli"], s["db"])
        if not d:
            msg = (f"{s['label']}: database di simulazione non trovato (ID {s['db']}, titoli {s['titoli']}): collega il db "
                   "alla connessione Notion dell'agente; per ora lo sport e' trattato come 'dati insufficienti'.")
            log("ATTENZIONE: " + msg)
            note.append(msg)
            continue
        sims[s["label"]] = leggi_sim(d, s["label"], s["fine"], log)
    wrest = []
    if USA_MODELLO_WRESTLING:
        dw = trova_db(dbs, WRESTLING_TITLES)
        if dw:
            wrest = leggi_wrestling(dw, log)
        else:
            msg = "Wrestling: database 'Previsioni Wrestling LA28' non trovato."
            log("ATTENZIONE: " + msg)
            note.append(msg)
    else:
        log("Wrestling: modello 'Previsioni Wrestling LA28' non usato (USA_MODELLO_WRESTLING = False): regole CIO + UWW.")

    senza_regole = {}
    for a in athletes:
        if a["ita"] and not a["canon"] and a["sport"] not in INVERNALI and not sim_di(a["sport"]):
            senza_regole[a["sport"] or "(senza sport)"] = senza_regole.get(a["sport"] or "(senza sport)", 0) + 1
    if senza_regole:
        log("Sport con atleti italiani ma SENZA regole di qualificazione (compaiono come 'Dati insufficienti'): "
            + ", ".join(f"{k} ({v})" for k, v in sorted(senza_regole.items())))
    righe = costruisci(athletes, sims, wrest, log)
    programma = leggi_programma(dbs, log)
    if programma is None:
        note.append("Programma LA28 non leggibile: le prove senza italiani non sono elencate.")
    else:
        righe += prove_senza_italiani(programma, athletes, sims, righe, log)
    ordine = {n: i for i, n in enumerate(LIVELLI)}
    righe.sort(key=lambda r: (chiave_alfabetica(r["sport"]), ordine[r["livello"]], -(r["p"] or 0), r["nome"]))
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
    quote = riepilogo_quote(righe, log)      # riepilogo delle quote: solo log e json, Notion non cambia
    scrivi_json(righe, note, quote)
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
