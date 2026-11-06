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
                   quota_by=[("synchro", 8)], alias=["diving"],
                   note="synchro: 8 coppie stimate"),
    "Shooting": dict(kind="ind", quota=28, max_noc=2, rank_share=0.6, fine=d("2028-05-01"),
                     alias=["shooting"]),
    "Wrestling": dict(kind="ind", quota=16, prove_valide=[r"^M\|.*(57|65|74|86|97|125)kg fs", r"^M\|.*(60|67|77|87|97|130)kg gr",
                                                          r"^W\|.*(50|53|57|62|68|76)kg ww"], max_noc=1, rank_share=0.6, fine=d("2028-06-30"), alias=["wrestling"],
                      note="provvisorio: i posti per categoria dipendono dal regolamento UWW per LA28"),
    "Weightlifting": dict(kind="ind", quota=12, max_noc=1, rank_share=0.8, fine=d("2028-05-07"),
                          alias=["weightlifting"]),
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
