"""Regole di qualificazione LA28 (sintesi dei Qualification System approvati dal CIO) usate dall'agente di stima.

Come leggerlo (ogni sport e' un blocco):
  kind      "ind" = individuale | "team" = squadre (una per nazione) | "pair" = coppie
  quota     posti totali per ogni prova (atleti se "ind", squadre/coppie/equipaggi se "team"/"pair")
  quota_by  [(regola, posti), ...]: regole piu' specifiche. La regola e' una "regex" cercata nella chiave della prova,
            scritta cosi': "M|singolare" (M = uomini, W = donne, X = misto, poi il nome della prova in minuscolo).
  max_noc   massimo di atleti (o squadre) per nazione in ogni prova
  rank_share  quota dei posti assegnata dal ranking/punteggio; il resto va a host, universality, continentali, ripescaggi
  team_size   quanti atleti contano per la forza di una squadra
  fine      ultimo giorno utile per qualificarsi
Dove i numeri non sono ancora definitivi (atletica, alcune prove a squadre) c'e' la nota "provvisorio".
I nomi dello sport (alias) servono a riconoscere le diciture usate nel tuo db Athletes: se ne manca una, l'agente
la segnala nel log tra gli "sport senza regole".

In fondo al file c'e' anche QUOTE_RIEPILOGO: le regole per CONTARE le quote italiane (posti-atleta) nel riepilogo
per sport. E' separato da RULES apposta: RULES decide le righe della Stima, QUOTE_RIEPILOGO serve solo al riepilogo
e non cambia nessuna riga.
"""
from datetime import date


def d(s):
    y, m, g = map(int, s.split("-"))
    return date(y, m, g)


RULES = {
    # ------------------------------------------------------------------ sport individuali
    "Archery": dict(kind="ind", quota=58, max_noc=3, rank_share=0.6, fine=d("2028-06-20"),
                    quota_by=[("recurve", 58), ("team|mixed", 12), ("compound", 12)],
                    alias=["archery"]),
    "Boxing": dict(kind="ind", quota=18, max_noc=1, rank_share=0.6, fine=d("2028-05-31"),
                   prove_valide=[r"^M\|.*(55|60|65|70|80|90)kg", r"^M\|.*\+ ?90", r"^W\|.*(51|54|57|60|65|70|75)kg"],
                   quota_by=[(r"^M\|.*\+90", 16), (r"^M\|.*90kg", 16), (r"^M\|.*80kg", 16), (r"^M\|.*70kg", 20),
                             (r"^M\|.*65kg", 20), (r"^M\|.*60kg", 18), (r"^M\|.*55kg", 18),
                             (r"^W\|.*75kg", 16), (r"^W\|.*70kg", 16), (r"^W\|.*65kg", 18), (r"^W\|.*60kg", 18),
                             (r"^W\|.*57kg", 20), (r"^W\|.*54kg", 18), (r"^W\|.*51kg", 18)],
                   alias=["boxing"]),
    "Fencing": dict(kind="ind", quota=34, max_noc=3, rank_share=0.7, fine=d("2028-04-30"),
                    quota_by=[("team", 8)], alias=["fencing"], team_size=3,
                    note="posti per squadra provvisori"),
    "Swimming": dict(kind="ind", quota=32, max_noc=2, rank_share=0.9, fine=d("2028-06-18"),
                     quota_by=[("relay|staffetta", 12)], alias=["swimming", "swimmingpool"], team_size=4,
                     note="quota per gara da confermare: stimata a 32; staffette stimate a 12"),
    "Diving": dict(kind="ind", quota=16, max_noc=2, rank_share=0.75, fine=d("2028-05-31"),
                   quota_by=[("synch", 8)], alias=["diving"],
                   note="synchro: 8 coppie stimate"),
    "Shooting": dict(kind="ind", quota=28, max_noc=2, rank_share=0.6, fine=d("2028-05-01"),
                     alias=["shooting"]),
    "Wrestling": dict(kind="ind", quota=16, prove_valide=[r"^M\|.*(57|65|74|86|97|125)kg fs", r"^M\|.*(60|67|77|87|97|130)kg gr",
                                                          r"^W\|.*(50|53|57|62|68|76)kg ww"], max_noc=1, rank_share=0.6, fine=d("2028-06-30"), alias=["wrestling"],
                      note="provvisorio: i posti per categoria dipendono dal regolamento UWW per LA28"),
    "Artistic Gymnastics": dict(kind="ind", quota=24, max_noc=4, rank_share=0.7, fine=d("2028-05-31"),
                                quota_by=[("team", 12)], alias=["gymartistic", "artisticgymnastics"], team_size=4),
    "Rhythmic Gymnastics": dict(kind="ind", quota=24, max_noc=2, rank_share=0.7, fine=d("2028-05-31"),
                                quota_by=[("group", 14)], alias=["gymrhythmic", "rhythmicgym", "rhythmicgymnastics"],
                                team_size=5),
    "Trampoline": dict(kind="ind", quota=16, max_noc=2, rank_share=0.7, fine=d("2028-05-31"),
                       alias=["gymtrampoline", "trampoline", "trampolinegymnastics"]),
    "Artistic Swimming": dict(kind="ind", quota=18, max_noc=2, rank_share=0.7, fine=d("2028-06-18"),
                              quota_by=[("team", 10), ("duet", 18)], alias=["artisticswimming"], team_size=8),
    "Badminton": dict(kind="ind", quota=35, max_noc=2, rank_share=0.9, fine=d("2028-04-30"),
                      quota_by=[("singles", 35), ("doubles", 16)], alias=["badminton"]),
    "Table Tennis": dict(kind="ind", quota=64, max_noc=3, rank_share=0.6, fine=d("2028-06-15"),
                         quota_by=[("singles", 64), ("doubles", 16), ("team|mixed", 16)], alias=["tabletennis"],
                         team_size=3),
    "Golf": dict(kind="ind", quota=60, max_noc=4, rank_share=0.95, fine=d("2028-06-19"),
                 quota_by=[("team|mixed", 16)], alias=["golf"], team_size=2),
    "Sport Climbing": dict(kind="ind", quota=12, max_noc=2, rank_share=0.55, fine=d("2028-06-11"),
                           alias=["sportclimbing", "climbing"]),
    "Sailing": dict(kind="ind", quota=24, max_noc=1, rank_share=0.7, fine=d("2028-06-26"),
                    quota_by=[("windsurf|iqfoil|formula", 24), ("kite", 19), ("dinghy|ilca|laser|470", 40),
                              ("skiff|49er", 19), ("multihull|nacra", 17), ("mixed", 18)],
                    alias=["sailing"]),
    "Modern Pentathlon": dict(kind="ind", quota=32, max_noc=2, rank_share=0.4, fine=d("2028-06-30"),
                              alias=["modernpentathlon", "pentathlon"]),
    "Triathlon": dict(kind="ind", quota=55, max_noc=3, rank_share=0.8, fine=d("2028-05-18"),
                      quota_by=[("relay|mixed", 12)], alias=["triathlon"], team_size=4),
    "Open Water Swimming": dict(kind="ind", quota=22, max_noc=2, rank_share=0.3, fine=d("2028-07-30"),
                                alias=["openwater", "openwaterswimming", "marathonswimming"],
                                note="solo il 30% dei posti dipende dal ranking: gli altri si decidono nell'evento di qualificazione 2028"),
    "Skateboarding": dict(kind="ind", quota=22, max_noc=3, rank_share=0.85, fine=d("2028-06-11"),
                          alias=["skateboarding"]),
    "Surfing": dict(kind="ind", quota=24, max_noc=2, rank_share=0.7, fine=d("2028-06-15"), alias=["surfing"]),
    "Squash": dict(kind="ind", quota=16, max_noc=2, rank_share=0.5, fine=d("2028-06-10"), alias=["squash"]),
    "Rowing": dict(kind="ind", quota=30, max_noc=1, rank_share=0.75, fine=d("2028-06-11"),
                   quota_by=[(r"single|1x", 30), (r"pair|2-|double|2x", 12), (r"four|4-|quad|4x", 9),
                             (r"eight|8\+", 7)], alias=["rowing"], team_size=2,
                   note="barche: una per nazione in ogni prova"),
    "Rowing Coastal": dict(kind="ind", quota=17, max_noc=1, rank_share=0.7, fine=d("2027-10-09"),
                           quota_by=[("mixed", 15)], alias=["rowingcoastal", "coastalrowing", "beachsprint"]),
    "Cycling BMX Freestyle": dict(kind="ind", quota=12, max_noc=2, rank_share=0.8, fine=d("2028-06-11"),
                                  alias=["cyclingbmxfreestyle", "bmxfreestyle"]),
    "Cycling Road": dict(kind="ind", quota=90, max_noc=4, rank_share=0.9, fine=d("2027-10-19"),
                         quota_by=[("time trial|itt|crono", 35)], alias=["cyclingroad", "road"]),
    "Equestrian": dict(kind="ind", quota=75, max_noc=3, rank_share=0.8, fine=d("2028-02-08"),
                       quota_by=[("team", 20)], alias=["equestrian", "equestrianjumping", "equestriandressage",
                                                        "equestrianeventing"], team_size=3,
                       note="posti stimati: squadre x 3 + individuali"),
    "Athletics": dict(kind="ind", quota=40, max_noc=3, rank_share=0.5, fine=d("2028-06-29"),
                      quota_by=[("relay|4x", 16), ("marathon", 70)], alias=["athletics"], team_size=4,
                      note="provvisorio: standard e quote per prova saranno definitivi dopo dicembre 2026"),

    # ------------------------------------------------------------------ sport di squadra / coppie
    "Basketball": dict(kind="team", quota=12, max_noc=1, rank_share=0.6, fine=d("2028-07-02"), team_size=5,
                       alias=["basketball", "5x5basketball"]),
    "3x3 Basketball": dict(kind="team", quota=12, max_noc=1, rank_share=0.5, fine=d("2028-06-12"), team_size=3,
                           alias=["3x3basketball", "basketball3x3", "3x3"]),
    "Volleyball": dict(kind="team", quota=12, max_noc=1, rank_share=0.5, fine=d("2028-06-26"), team_size=6,
                       alias=["volleyball"]),
    "Beach Volleyball": dict(kind="pair", quota=24, max_noc=2, rank_share=0.6, fine=d("2028-06-11"), team_size=2,
                             alias=["beachvolley", "beachvolleyball"]),
    "Water Polo": dict(kind="team", quota=12, max_noc=1, rank_share=0.4, fine=d("2028-07-30"), team_size=7,
                       alias=["waterpolo"]),
    "Handball": dict(kind="team", quota=12, max_noc=1, rank_share=0.5, fine=d("2028-04-09"), team_size=7,
                     alias=["handball"]),
    "Hockey": dict(kind="team", quota=12, max_noc=1, rank_share=0.5, fine=d("2028-03-31"), team_size=9,
                   alias=["hockey", "hockeyfield", "fieldhockey"]),
    "Rugby Sevens": dict(kind="team", quota=12, max_noc=1, rank_share=0.5, fine=d("2028-06-01"), team_size=7,
                         alias=["rugbysevens", "rugby7", "rugby"]),
    "Football": dict(kind="team", quota=12, max_noc=1, rank_share=0.3, fine=d("2028-01-22"), team_size=11,
                     quota_by=[("^W", 16), ("^M", 12)], alias=["football", "foootball", "soccer"],
                     note="uomini 12 squadre, donne 16: i posti si decidono nei tornei per confederazione"),
    "Baseball": dict(kind="team", quota=6, max_noc=1, rank_share=0.4, fine=d("2028-03-31"), team_size=9,
                     alias=["baseball"]),
    "Softball": dict(kind="team", quota=6, max_noc=1, rank_share=0.4, fine=d("2028-03-31"), team_size=9,
                     alias=["softball"]),
    "Flag Football": dict(kind="team", quota=6, max_noc=1, rank_share=0.4, fine=d("2028-06-11"), team_size=5,
                          alias=["flagfootball"]),
    "Lacrosse": dict(kind="team", quota=6, max_noc=1, rank_share=0.4, fine=d("2028-04-01"), team_size=6,
                     alias=["lacrosse", "lacrossesixes"]),
    "Cricket": dict(kind="team", quota=6, max_noc=1, rank_share=0.4, fine=d("2028-03-01"), team_size=8,
                    alias=["cricket"]),
}

ALIAS = {}
for _nome, _r in RULES.items():
    ALIAS[_nome.lower().replace(" ", "")] = _nome
    for _a in _r["alias"]:
        ALIAS[_a.replace(" ", "").lower()] = _nome


def sport_canonico(nome_sport):
    """Nome usato nel tuo db Athletes -> nome standard delle regole (None se non c'e' una regola)."""
    k = "".join(ch for ch in (nome_sport or "").lower() if ch.isalnum())
    return ALIAS.get(k)


# =====================================================================================================================
# RIEPILOGO DELLE QUOTE ITALIANE PER SPORT (decisioni dell'11/11/2026, scheda 17 del progetto)
# =====================================================================================================================
# Serve SOLO al riepilogo (log, stima_la28.json, sezione della pagina stima.html): non cambia nessuna riga della Stima
# e nessuna colonna di Notion.
#
# Cosa si conta: le QUOTE, cioe' i posti-atleta che l'Italia porterebbe a LA28, non le righe della Stima.
#
# Come si conta ("conteggio a scalini"), per ogni sport e genere, a ogni livello L
# (prima Certo, poi Probabile, Possibile, Remoto):
#   - nominati = persone diverse con un nome, ciascuna contata al suo livello MIGLIORE
#   - squadra  = posti della squadra/staffetta piu' grande a quel livello o meglio (righe senza nomi: "Italia ...")
#   - posti    = il piu' grande tra nominati e squadra (modo "pesca": la squadra pesca dagli individuali)
#                oppure nominati + squadre (modo "somma": equipaggi e gruppi fatti di persone diverse)
#   - mai oltre il tetto per NOC.
# Le quote del livello L sono la differenza tra lo scalino di L e quello del livello prima.
#
# Come leggere un blocco di QUOTE_RIEPILOGO:
#   tetto     massimo di atleti per NOC in tutto lo sport: {"U": uomini, "D": donne} oppure {"X": n} se lo sport e' Open
#   genere    se c'e', il genere di tutte le righe dello sport ("U", "D" oppure "X" = Open, colonna Misto)
#   rosa      solo sport di squadra: atleti per squadra (tabella ROSE della scheda 04)
#   pool      gruppi di prove con un tetto proprio. Una riga va nel PRIMO pool la cui regex "prove" la descrive
#             (prove = None: tutte le righe rimaste). Ogni pool puo' avere:
#               modo           "pesca" (predefinito) oppure "somma"
#               tetto          massimo per genere in quel pool (un numero, oppure {"U": .., "D": ..})
#               tetto_squadra / tetto_senza / squadra
#                              tetto se c'e' una squadra di quel genere a quel livello (riga che corrisponde
#                              alla regex "squadra") / tetto senza squadra. Esempio arco ricurvo: 3 / 1.
#               posti          [(regex, n), ...]: quanti posti vale una riga senza nomi ("Italia ...") di quella prova.
#                              Se nessuna regex corrisponde vale "rosa" (sport di squadra) oppure 1.
#               famiglia       nome di un insieme di pool con un tetto comune (vedi "famiglie")
#   famiglie  {nome: tetto}: tetto comune di piu' pool (es. ciclismo su pista: velocita' + endurance = 8)
#   nota      avviso da scrivere nel log e nella pagina quando lo sport ha quote
#
# Le prove miste (es. squadra mista dell'arco, staffetta mista) si dividono a meta' tra uomini e donne:
# 2 posti = 1 uomo + 1 donna, 4 posti = 2 + 2. Il genere di una persona con nome si prende dalle sue altre righe
# dello stesso sport; se non ne ha, si completa la composizione (prima gli uomini, poi le donne).

# Etichette della Stima che nel riepilogo diventano un unico sport (stesso sport, discipline diverse: una persona
# conta una volta sola).
GRUPPI_RIEPILOGO = {
    "Open Water Swimming": "Swimming",      # nuoto in corsia + acque libere
    "Rowing Coastal": "Rowing",             # canottaggio + canottaggio costiero
}
# Etichette della Stima che nel riepilogo si dividono in due sport, in base alla disciplina (regex).
# Il basket 5x5 e il 3x3 nella Stima sono entrambi "Basketball": nel riepilogo restano separati.
SEPARA_RIEPILOGO = [
    ("Basketball", r"3\s*x\s*3", "Basketball 3x3"),
]

QUOTE_RIEPILOGO = {
    # ---------------------------------------------------------------- sport individuali con squadre o gruppi
    "Archery": dict(
        tetto={"U": 4, "D": 4},             # 3 ricurvo + 1 compound
        pool=[
            dict(nome="compound", prove=r"compound", tetto=1, posti=[(r"mixed|team", 2)]),
            dict(nome="ricurvo", prove=None, tetto_squadra=3, tetto_senza=1, squadra=r"recurve team|team recurve",
                 posti=[(r"mixed", 2), (r"team", 3)]),
        ]),
    "Artistic Gymnastics": dict(
        tetto={"U": 5, "D": 5},
        pool=[dict(nome="ginnastica", prove=None, tetto_squadra=5, tetto_senza=3, squadra=r"team",
                   posti=[(r"team", 5)])]),
    "Artistic Swimming": dict(
        genere="D", tetto={"D": 8},
        pool=[dict(nome="nuoto artistico", prove=None, tetto_squadra=8, tetto_senza=2, squadra=r"team",
                   posti=[(r"team", 8), (r"duet", 2)])]),
    "Athletics": dict(
        tetto={"U": 63, "D": 63},           # 21 prove individuali x 3; max 1 staffetta per evento
        pool=[dict(nome="atletica", prove=None, posti=[(r"4\s*x|relay|staffett", 4)])]),
    "Badminton": dict(
        tetto={"U": 8, "D": 8},
        pool=[dict(nome="badminton", prove=None, posti=[(r"doubles|doppio", 2)])]),
    "Beach Volleyball": dict(
        tetto={"U": 4, "D": 4},             # 2 coppie
        pool=[dict(nome="beach volley", prove=None, posti=[(r".", 2)])]),
    "Boxing": dict(tetto={"U": 7, "D": 7}, pool=[dict(nome="pugilato", prove=None)]),
    "Canoeing": dict(
        tetto={"U": 11, "D": 11},
        # "il piu' grande" (gli atleti fanno piu' prove), separando canoa e kayak, che sono atleti diversi
        pool=[
            dict(nome="slalom canoa", prove=r"slalom.*\bc1\b", tetto=2),
            dict(nome="slalom kayak", prove=r"slalom", tetto=2),
            dict(nome="sprint canoa", prove=r"sprint.*\bc[12]\b", tetto=3, posti=[(r"\bc2\b", 2)]),
            dict(nome="sprint kayak", prove=r"sprint", tetto=5, posti=[(r"\bk4\b", 4), (r"\bk2\b", 2)]),
        ]),
    "Cycling": dict(
        tetto={"U": 19, "D": 19},           # strada 4 + pista 8 + MTB 2 + BMX freestyle 2 + BMX racing 3
        famiglie={"pista": 8},
        pool=[
            dict(nome="strada", prove=r"strada|road|crono|time trial", tetto=4),
            dict(nome="BMX racing", prove=r"bmx rac", tetto=3),
            dict(nome="BMX freestyle", prove=r"bmx free|freestyle|bmx park", tetto=2),
            dict(nome="MTB", prove=r"mtb|mountain", tetto=2),
            dict(nome="pista velocita'", prove=r"velocit|team sprint|sprint|keirin", famiglia="pista",
                 posti=[(r"velocit|team sprint", 3)]),
            dict(nome="pista endurance", prove=r"pista|track|inseguimento|pursuit|omnium|madison|americana",
                 famiglia="pista", posti=[(r"inseguimento|pursuit", 4), (r"madison|americana", 2)]),
        ],
        nota="[DA VERIFICARE] Cycling: il ciclismo su strada non ha righe nella Stima (la simulazione UCI non lo copre: "
             "manca l'UCI Road World Ranking by nations su cui si basa la qualificazione)."),
    "Diving": dict(
        tetto={"U": 8, "D": 8},
        pool=[dict(nome="tuffi", prove=None, posti=[(r"synch|sincro", 2)])]),
    "Equestrian": dict(
        genere="X", tetto={"X": 9},         # Open: uomini e donne insieme
        pool=[
            dict(nome="dressage", prove=r"dressage", tetto_squadra=3, tetto_senza=1, squadra=r"team",
                 posti=[(r"team", 3)]),
            dict(nome="eventing", prove=r"eventing", tetto_squadra=3, tetto_senza=2, squadra=r"team",
                 posti=[(r"team", 3)]),
            dict(nome="jumping", prove=None, tetto_squadra=3, tetto_senza=1, squadra=r"team",
                 posti=[(r"team", 3)]),
        ]),
    "Fencing": dict(
        tetto={"U": 9, "D": 9},             # 3 armi: squadra di 3, oppure 1 senza squadra
        pool=[
            dict(nome="spada", prove=r"epee|spada", tetto_squadra=3, tetto_senza=1, squadra=r"team|squadr",
                 posti=[(r"team|squadr", 3)]),
            dict(nome="fioretto", prove=r"foil|fioretto", tetto_squadra=3, tetto_senza=1, squadra=r"team|squadr",
                 posti=[(r"team|squadr", 3)]),
            dict(nome="sciabola", prove=None, tetto_squadra=3, tetto_senza=1, squadra=r"team|squadr",
                 posti=[(r"team|squadr", 3)]),
        ]),
    "Golf": dict(
        tetto={"U": 4, "D": 4},
        pool=[dict(nome="golf", prove=None, posti=[(r"team|mixed", 2)])]),
    "Judo": dict(
        tetto={"U": 7, "D": 7},
        # la squadra mista non aggiunge posti (decisione 5): i componenti sono judoka gia' qualificati
        pool=[dict(nome="judo", prove=None, posti=[(r"squadra mista|mixed|team", 0)])]),
    "Modern Pentathlon": dict(tetto={"U": 2, "D": 2}, pool=[dict(nome="pentathlon", prove=None)]),
    "Rhythmic Gymnastics": dict(
        genere="D", tetto={"D": 7},         # 2 individuali + 5 del gruppo (persone diverse: si sommano)
        pool=[
            dict(nome="gruppo", prove=r"group|gruppo", tetto=5, posti=[(r".", 5)]),
            dict(nome="individuali", prove=None, tetto=2),
        ]),
    "Rowing": dict(
        tetto={"U": 23, "D": 23},           # canottaggio + costiero, 1 barca per evento
        pool=[dict(nome="barche", prove=None, modo="somma",
                   posti=[(r"eight|8\+", 8), (r"four|quad|4x|4-", 4), (r"pair|double|2x|2-", 2)])]),
    "Sailing": dict(
        tetto={"U": 7, "D": 7},
        pool=[dict(nome="barche", prove=None, modo="somma", posti=[(r"470|nacra|49er|skiff", 2)])]),
    "Shooting": dict(
        tetto={"U": 12, "D": 12},
        pool=[dict(nome="tiro", prove=None, posti=[(r"mixed|team", 2)])]),
    "Skateboarding": dict(tetto={"U": 6, "D": 6}, pool=[dict(nome="skate", prove=None)]),
    "Sport Climbing": dict(tetto={"U": 6, "D": 6}, pool=[dict(nome="arrampicata", prove=None)]),
    "Squash": dict(tetto={"U": 2, "D": 2}, pool=[dict(nome="squash", prove=None)]),
    "Surfing": dict(tetto={"U": 2, "D": 2}, pool=[dict(nome="surf", prove=None)]),
    "Swimming": dict(
        tetto={"U": 28, "D": 28},           # corsia + acque libere; staffette: pescano dagli individuali
        pool=[dict(nome="nuoto", prove=None, posti=[(r"4\s*x|relay|staffett", 4)])]),
    "Table Tennis": dict(
        tetto={"U": 3, "D": 3},
        pool=[dict(nome="tennistavolo", prove=None, posti=[(r"team|squadr", 6), (r"doubles|doppio", 2)])]),
    "Taekwondo": dict(tetto={"U": 4, "D": 4}, pool=[dict(nome="taekwondo", prove=None)]),
    "Tennis": dict(
        tetto={"U": 6, "D": 6},
        pool=[dict(nome="tennis", prove=None, posti=[(r"doubles|doppio", 2)])]),
    "Trampoline": dict(tetto={"U": 2, "D": 2}, pool=[dict(nome="trampolino", prove=None)]),
    "Triathlon": dict(
        tetto={"U": 3, "D": 3},
        pool=[dict(nome="triathlon", prove=None, posti=[(r"relay|mixed|staffett", 4)])]),
    # pesi: 1 per categoria, al massimo 3 delle 6 categorie per genere (4 solo con il titolo Best Lifter, non contato)
    "Weightlifting": dict(tetto={"U": 3, "D": 3}, pool=[dict(nome="pesi", prove=None)]),
    "Wrestling": dict(tetto={"U": 12, "D": 6}, pool=[dict(nome="lotta", prove=None)]),

    # ---------------------------------------------------------------- sport di squadra (rosa: tabella ROSE)
    "Baseball": dict(genere="U", rosa=24),
    "Basketball": dict(rosa=12),
    "Basketball 3x3": dict(rosa=4),
    "Cricket": dict(rosa=15),
    "Flag Football": dict(rosa=10),
    "Football": dict(rosa=18),
    "Handball": dict(rosa=14),
    "Hockey": dict(rosa=16),
    "Lacrosse": dict(rosa=11),
    "Rugby Sevens": dict(rosa=12),
    "Softball": dict(genere="D", rosa=15),
    "Volleyball": dict(rosa=12),
    "Water Polo": dict(rosa=11),
}
