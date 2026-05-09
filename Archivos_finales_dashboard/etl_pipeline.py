"""
================================================================================
ETL Pipeline - Modelo Estrella para Power BI
================================================================================
Objetivo: tomar 4 fuentes sin claves (Salarios histórico, Salarios 25-26,
Rating de WhoScored, Rendimiento de FBref) + tabla de logos, normalizarlas y
construir un modelo en estrella con identificadores únicos para Power BI.

Estrategia de relación (decisiones clave):
  1) Construir una DIMENSIÓN DE CLUBES (dim_club) con un ClubID único, que
     contiene los nombres tal como aparecen en cada fuente. Es el "puente"
     entre tablas que antes no se podían unir por nombres distintos
     (ej: 'Atletico Madrid' / 'Atletico' / 'Atlético Madrid').
  2) Construir una DIMENSIÓN DE LIGAS (dim_liga) y otra de TEMPORADAS
     (dim_temporada).
  3) Crear una DIMENSIÓN DE JUGADORES (dim_jugador) con PlayerID, normalizando
     nombres (sin acentos, lowercase) para deduplicar.
  4) Las tablas de hechos quedan: fact_salarios, fact_rating, fact_rendimiento.
     Cada una con FKs (PlayerID, ClubID, TemporadaID, LigaID) y sus métricas.

Salida: 1 archivo Excel multi-hoja + CSVs individuales para Power BI.
================================================================================
"""

import pandas as pd
import unicodedata
import re
from pathlib import Path

# Rutas
SRC = Path('/home/claude')
OUT = Path('/home/claude/output')
OUT.mkdir(exist_ok=True)


# ============================================================
# UTILIDADES
# ============================================================
def norm_text(s):
    """Quita acentos, espacios extra, lowercase. Para matching de nombres."""
    if pd.isna(s):
        return ''
    s = str(s).strip().lower()
    s = unicodedata.normalize('NFKD', s).encode('ascii', 'ignore').decode('ascii')
    s = re.sub(r'\s+', ' ', s)
    return s


# ============================================================
# 1) CARGA DE FUENTES
# ============================================================
print("[1] Cargando fuentes...")
salarios = pd.read_csv(SRC / 'Master_Salarios.csv')           # 22-23, 23-24, 24-25
salarios_25 = pd.read_csv(SRC / 'Master_Salarios_2526.csv')   # 25-26
rating = pd.read_csv(SRC / 'Master_Rating.csv')               # WhoScored
rend = pd.read_csv(SRC / 'Master_Rendimiento.csv')            # FBref
logos = pd.read_excel(SRC / 'logos.xlsx')

# Unificar Salarios. La 25-26 no trae 'Adj_Net_Total_PY_2026' -> se rellena.
salarios_25['Adj_Net_Total_PY_2026'] = salarios_25['Net_Total_PY_USD']
salarios_full = pd.concat([salarios, salarios_25], ignore_index=True)
print(f"    Salarios consolidados: {len(salarios_full):,} filas")
print(f"    Rating: {len(rating):,} filas | Rendimiento: {len(rend):,} filas")


# ============================================================
# 2) LIMPIEZA: errores de scraping en Master_Rating
# ============================================================
# El scraping de WhoScored dejó varios bugs:
#   a) 'Saint-Etienne' partió en 'Saint-' (pegado al jugador) y 'Etienne' (team)
#   b) 'St. Pauli' partió en 'St.' y 'Pauli'
#   c) RB Leipzig -> team='Desconocido', sufijo 'RBL' pegado al jugador
#   d) PSG       -> team='Desconocido', sufijo 'PSG' pegado al jugador
#   e) Parma Calcio 1913 -> team='Desconocido', nombre completo pegado
print("\n[2] Limpiando errores de scraping en Rating...")

def fix_rating_row(row):
    """Repara la fila si encaja con uno de los patrones conocidos."""
    player, team = row['player'], row['team']
    # Caso a)
    if team == 'Etienne' and player.endswith('Saint-'):
        return pd.Series([player[:-6].strip(), 'Saint-Etienne'])
    # Caso b)
    if team == 'Pauli' and player.endswith('St.'):
        return pd.Series([player[:-3].strip(), 'St Pauli'])
    # Caso c-d) Desconocido con sufijo RBL/PSG
    if team == 'Desconocido':
        if player.endswith('RBL'):
            return pd.Series([player[:-3].strip(), 'Leipzig'])
        if player.endswith('PSG'):
            return pd.Series([player[:-3].strip(), 'PSG'])
        # Caso e) Parma con nombre completo pegado al final
        if 'Parma Calcio 1913' in player:
            return pd.Series([player.replace('Parma Calcio 1913','').strip(), 'Parma'])
    return pd.Series([player, team])

rating[['player','team']] = rating.apply(fix_rating_row, axis=1)
print(f"    Filas con team='Desconocido' restantes: {(rating['team']=='Desconocido').sum()}")


# ============================================================
# 3) DIMENSIÓN LIGAS  (dim_liga)
# ============================================================
print("\n[3] Construyendo dim_liga...")
ligas_canon = ['La_liga', 'Premier', 'Bundesliga', 'Serie_a', 'Ligue']
liga_display = {
    'La_liga': 'LaLiga',
    'Premier': 'Premier League',
    'Bundesliga': 'Bundesliga',
    'Serie_a': 'Serie A',
    'Ligue': 'Ligue 1',
}
liga_pais = {
    'La_liga': 'España', 'Premier': 'Inglaterra', 'Bundesliga': 'Alemania',
    'Serie_a': 'Italia', 'Ligue': 'Francia',
}

dim_liga = pd.DataFrame({
    'LigaID': range(1, len(ligas_canon)+1),
    'LigaCodigo': ligas_canon,
    'LigaNombre': [liga_display[x] for x in ligas_canon],
    'Pais': [liga_pais[x] for x in ligas_canon],
})
dim_liga = dim_liga.merge(logos, left_on='LigaCodigo', right_on='Liga', how='left').drop(columns='Liga')
dim_liga = dim_liga.rename(columns={'Logo':'LogoURL'})


# ============================================================
# 4) DIMENSIÓN TEMPORADA  (dim_temporada)
# ============================================================
print("[4] Construyendo dim_temporada...")
temporadas = ['2022-2023', '2023-2024', '2024-2025', '2025-2026']
dim_temporada = pd.DataFrame({
    'TemporadaID': range(1, len(temporadas)+1),
    'Temporada': temporadas,
    'AnioInicio': [int(t.split('-')[0]) for t in temporadas],
    'AnioFin':    [int(t.split('-')[1]) for t in temporadas],
})


# ============================================================
# 5) DIMENSIÓN CLUBES  (dim_club)  <-- PIEZA CLAVE DE LA RELACIÓN
# ============================================================
# Cada club tiene un ClubID único + sus aliases en cada fuente.
# Esto permite que las 3 tablas de hechos referencien el mismo ClubID
# aunque originalmente lo escribieran distinto.
print("[5] Construyendo dim_club (mapa de aliases)...")

club_map = [
    # (ClubCanonico, LigaCodigo, alias_salarios, alias_rating, alias_rend)
    # ---- LA LIGA ----
    ('Alavés','La_liga','Alaves','Deportivo Alaves','Alavés'),
    ('Almería','La_liga','Almeria','Almeria','Almería'),
    ('Athletic Club','La_liga','Athletic Club','Athletic Club','Athletic Club'),
    ('Atlético Madrid','La_liga','Atletico Madrid','Atletico','Atlético Madrid'),
    ('Barcelona','La_liga','Barcelona','Barcelona','Barcelona'),
    ('Cádiz','La_liga','Cadiz','Cadiz','Cádiz'),
    ('Celta Vigo','La_liga','Celta Vigo','Celta Vigo','Celta Vigo'),
    ('Elche','La_liga','Elche','Elche','Elche'),
    ('Espanyol','La_liga','Espanyol','Espanyol','Espanyol'),
    ('Getafe','La_liga','Getafe','Getafe','Getafe'),
    ('Girona','La_liga','Girona','Girona','Girona'),
    ('Granada','La_liga','Granada','Granada','Granada'),
    ('Las Palmas','La_liga','Las Palmas','Las Palmas','Las Palmas'),
    ('Leganés','La_liga','Leganes','Leganes','Leganés'),
    ('Levante','La_liga','Levante','Levante','Levante'),
    ('Mallorca','La_liga','Mallorca','Mallorca','Mallorca'),
    ('Osasuna','La_liga','Osasuna','Osasuna','Osasuna'),
    ('Rayo Vallecano','La_liga','Rayo Vallecano','Rayo Vallecano','Rayo Vallecano'),
    ('Real Betis','La_liga','Real Betis','Real Betis','Real Betis'),
    ('Real Madrid','La_liga','Real Madrid','Real Madrid','Real Madrid'),
    ('Real Oviedo','La_liga','Real Oviedo','Real Oviedo','Real Oviedo'),
    ('Real Sociedad','La_liga','Real Sociedad','Real Sociedad','Real Sociedad'),
    ('Real Valladolid','La_liga','Real Valladolid','Real Valladolid','Real Valladolid'),
    ('Sevilla','La_liga','Sevilla','Sevilla','Sevilla'),
    ('Valencia','La_liga','Valencia','Valencia','Valencia'),
    ('Villarreal','La_liga','Villarreal','Villarreal','Villarreal'),
    # Casos: 'Valladolid' aparece en rating/rend sin "Real" -> agregar como alias adicional
    # ---- PREMIER ----
    ('Arsenal','Premier','Arsenal','Arsenal','Arsenal'),
    ('Aston Villa','Premier','Aston Villa','Aston Villa','Aston Villa'),
    ('Bournemouth','Premier','Bournemouth','Bournemouth','Bournemouth'),
    ('Brentford','Premier','Brentford','Brentford','Brentford'),
    ('Brighton','Premier','Brighton','Brighton','Brighton'),
    ('Burnley','Premier','Burnley','Burnley','Burnley'),
    ('Chelsea','Premier','Chelsea','Chelsea','Chelsea'),
    ('Crystal Palace','Premier','Crystal Palace','Crystal Palace','Crystal Palace'),
    ('Everton','Premier','Everton','Everton','Everton'),
    ('Fulham','Premier','Fulham','Fulham','Fulham'),
    ('Ipswich Town','Premier','Ipswich Town','Ipswich','Ipswich Town'),
    ('Leeds United','Premier','Leeds','Leeds','Leeds United'),
    ('Leicester City','Premier','Leicester','Leicester','Leicester City'),
    ('Liverpool','Premier','Liverpool','Liverpool','Liverpool'),
    ('Luton Town','Premier','Luton Town','Luton','Luton Town'),
    ('Manchester City','Premier','Manchester City','Man City','Manchester City'),
    ('Manchester United','Premier','Manchester United','Man Utd','Manchester Utd'),
    ('Newcastle','Premier','Newcastle','Newcastle','Newcastle United'),
    ('Nottingham Forest','Premier','Nottingham Forest','Nottingham Forest','Nottingham Forest'),
    ('Sheffield United','Premier','Sheffield United','Sheff Utd','Sheffield United'),
    ('Southampton','Premier','Southampton','Southampton','Southampton'),
    ('Sunderland','Premier','Sunderland','Sunderland','Sunderland'),
    ('Tottenham','Premier','Tottenham','Tottenham','Tottenham Hotspur'),
    ('West Ham','Premier','West Ham','West Ham','West Ham United'),
    ('Wolverhampton','Premier','Wolverhampton','Wolves','Wolves'),
    # ---- BUNDESLIGA ----
    ('Augsburg','Bundesliga','Augsburg','Augsburg','Augsburg'),
    ('Bayer Leverkusen','Bundesliga','Bayer Leverkusen','Leverkusen','Leverkusen'),
    ('Bayern Munich','Bundesliga','Bayern Munich','Bayern','Bayern Munich'),
    ('Bochum','Bundesliga','Bochum','Bochum','Bochum'),
    ('Borussia Dortmund','Bundesliga','Borussia Dortmund','Borussia Dortmund','Dortmund'),
    ('Darmstadt','Bundesliga','Darmstadt','Darmstadt','Darmstadt 98'),
    ('Eintracht Frankfurt','Bundesliga','Eintracht Frankfurt','Eintracht Frankfurt','Eintracht Frankfurt'),
    ('Freiburg','Bundesliga','Freiburg','Freiburg','Freiburg'),
    ('Hamburg','Bundesliga','Hamburg','Hamburg','Hamburg'),
    ('Heidenheim','Bundesliga','Heidenheim','Heidenheim','Heidenheim'),
    ('Hertha Berlin','Bundesliga','Hertha Berlin','Hertha Berlin','Hertha BSC'),
    ('Hoffenheim','Bundesliga','Hoffenheim','Hoffenheim','Hoffenheim'),
    ('Holstein Kiel','Bundesliga','Holstein Kiel','Holstein Kiel','Holstein Kiel'),
    ('Köln','Bundesliga','Koln','Koln','Köln'),
    ('Mainz','Bundesliga','Mainz','Mainz','Mainz 05'),
    ('Mönchengladbach','Bundesliga','Monchengladbach','Gladbach','Gladbach'),
    ('RB Leipzig','Bundesliga','Leipzig','Leipzig','RB Leipzig'),
    ('Schalke 04','Bundesliga','Schalke 04','Schalke','Schalke 04'),
    ('St Pauli','Bundesliga','St Pauli','St Pauli','St. Pauli'),
    ('Stuttgart','Bundesliga','Stuttgart','Stuttgart','Stuttgart'),
    ('Union Berlin','Bundesliga','Union Berlin','Union Berlin','Union Berlin'),
    ('Werder Bremen','Bundesliga','Werder Bremen','Werder Bremen','Werder Bremen'),
    ('Wolfsburg','Bundesliga','Wolfsburg','Wolfsburg','Wolfsburg'),
    # ---- SERIE A ----
    ('AC Milan','Serie_a','AC Milan','Milan','Milan'),
    ('Atalanta','Serie_a','Atalanta','Atalanta','Atalanta'),
    ('Bologna','Serie_a','Bologna','Bologna','Bologna'),
    ('Cagliari','Serie_a','Cagliari','Cagliari','Cagliari'),
    ('Como','Serie_a','Como','Como','Como'),
    ('Cremonese','Serie_a','Cremonese','Cremonese','Cremonese'),
    ('Empoli','Serie_a','Empoli','Empoli','Empoli'),
    ('Fiorentina','Serie_a','Fiorentina','Fiorentina','Fiorentina'),
    ('Frosinone','Serie_a','Frosinone','Frosinone','Frosinone'),
    ('Genoa','Serie_a','Genoa','Genoa','Genoa'),
    ('Hellas Verona','Serie_a','Hellas Verona','Verona','Hellas Verona'),
    ('Inter','Serie_a','Inter Milan','Inter','Inter'),
    ('Juventus','Serie_a','Juventus','Juventus','Juventus'),
    ('Lazio','Serie_a','Lazio','Lazio','Lazio'),
    ('Lecce','Serie_a','Lecce','Lecce','Lecce'),
    ('Monza','Serie_a','Monza','Monza','Monza'),
    ('Napoli','Serie_a','Napoli','Napoli','Napoli'),
    ('Parma','Serie_a','Parma','Parma','Parma'),
    ('Pisa','Serie_a','Pisa','Pisa','Pisa'),
    ('Roma','Serie_a','Roma','Roma','Roma'),
    ('Salernitana','Serie_a','Salernitana','Salernitana','Salernitana'),
    ('Sampdoria','Serie_a','Sampdoria','Sampdoria','Sampdoria'),
    ('Sassuolo','Serie_a','Sassuolo','Sassuolo','Sassuolo'),
    ('Spezia','Serie_a','Spezia','Spezia','Spezia'),
    ('Torino','Serie_a','Torino','Torino','Torino'),
    ('Udinese','Serie_a','Udinese','Udinese','Udinese'),
    ('Venezia','Serie_a','Venezia','Venezia','Venezia'),
    # ---- LIGUE 1 ----
    ('Ajaccio','Ligue','Ajaccio','Ajaccio','Ajaccio'),
    ('Angers','Ligue','Angers','Angers','Angers'),
    ('Auxerre','Ligue','Auxerre','Auxerre','Auxerre'),
    ('Brest','Ligue','Brest','Brest','Brest'),
    ('Clermont','Ligue','Clermont','Clermont Foot','Clermont Foot'),
    ('Le Havre','Ligue','Le Havre','Le Havre','Le Havre'),
    ('Lens','Ligue','Lens','Lens','Lens'),
    ('Lille','Ligue','Lille','Lille','Lille'),
    ('Lorient','Ligue','Lorient','Lorient','Lorient'),
    ('Lyon','Ligue','Lyon','Lyon','Lyon'),
    ('Marseille','Ligue','Marseille','Marseille','Marseille'),
    ('Metz','Ligue','Metz','Metz','Metz'),
    ('Monaco','Ligue','Monaco','Monaco','Monaco'),
    ('Montpellier','Ligue','Montpellier','Montpellier','Montpellier'),
    ('Nantes','Ligue','Nantes','Nantes','Nantes'),
    ('Nice','Ligue','Nice','Nice','Nice'),
    ('Paris FC','Ligue','Paris FC','Paris FC','Paris FC'),
    ('PSG','Ligue','PSG','PSG','Paris Saint-Germain'),
    ('Reims','Ligue','Reims','Reims','Reims'),
    ('Rennes','Ligue','Rennes','Rennes','Rennes'),
    ('Saint-Etienne','Ligue','St-Etienne','Saint-Etienne','Saint-Étienne'),
    ('Strasbourg','Ligue','Strasbourg','Strasbourg','Strasbourg'),
    ('Toulouse','Ligue','Toulouse','Toulouse','Toulouse'),
    ('Troyes','Ligue','Troyes','Troyes','Troyes'),
]

dim_club = pd.DataFrame(club_map, columns=[
    'ClubNombre','LigaCodigo','AliasSalarios','AliasRating','AliasRend'
])
dim_club.insert(0, 'ClubID', range(1, len(dim_club)+1))
# Agregar LigaID
dim_club = dim_club.merge(dim_liga[['LigaID','LigaCodigo']], on='LigaCodigo')


# Tabla larga de aliases para hacer los joins de las hechos
def expand_aliases(df, src_col):
    """Devuelve [ClubID, LigaCodigo, alias] expandido por fuente."""
    out = df[['ClubID','LigaCodigo',src_col]].rename(columns={src_col:'alias'})
    out['alias_norm'] = out['alias'].apply(norm_text)
    return out

aliases_sal  = expand_aliases(dim_club, 'AliasSalarios')
aliases_rat  = expand_aliases(dim_club, 'AliasRating')
aliases_rend = expand_aliases(dim_club, 'AliasRend')

# Aliases extra (mismo nombre, pero a veces aparece distinto)
extra = pd.DataFrame([
    {'ClubID': dim_club.loc[dim_club['ClubNombre']=='Real Valladolid','ClubID'].iloc[0],
     'LigaCodigo':'La_liga', 'alias':'Valladolid', 'alias_norm':'valladolid'},
])
extra_sp = pd.DataFrame([{
    'ClubID': dim_club.loc[dim_club['ClubNombre']=='St Pauli','ClubID'].iloc[0],
    'LigaCodigo':'Bundesliga', 'alias':'St Pauli', 'alias_norm':'st pauli'
}])
aliases_sal  = pd.concat([aliases_sal, extra], ignore_index=True)
aliases_rat  = pd.concat([aliases_rat, extra], ignore_index=True)
aliases_rend = pd.concat([aliases_rend, extra, extra_sp], ignore_index=True)


# ============================================================
# 6) ATAR ClubID a cada tabla de hechos
# ============================================================
print("\n[6] Asignando ClubID a las 3 fuentes...")

def add_clubid(fact_df, club_col, liga_col, aliases_df):
    """Une fact_df con la tabla de aliases por (alias_normalizado, liga)."""
    df = fact_df.copy()
    df['_alias_norm'] = df[club_col].apply(norm_text)
    df = df.merge(
        aliases_df[['ClubID','LigaCodigo','alias_norm']].rename(columns={'LigaCodigo':'_liga'}),
        left_on=['_alias_norm', liga_col], right_on=['alias_norm','_liga'], how='left'
    )
    return df.drop(columns=['_alias_norm','alias_norm','_liga'])

# Salarios: la liga "Desconocida" en 25-26 es La_liga + Serie_a -> hay que recuperarla
# por nombre de club antes de join.
# Construimos un mapa club->liga a partir del dim_club.
club_to_liga = dim_club.set_index(dim_club['AliasSalarios'].apply(norm_text))['LigaCodigo'].to_dict()

mask_desc = salarios_full['Liga'] == 'Desconocida'
salarios_full.loc[mask_desc, 'Liga'] = (
    salarios_full.loc[mask_desc, 'Club'].apply(norm_text).map(club_to_liga)
)
print(f"    Filas con Liga='Desconocida' arregladas: {mask_desc.sum()}")

# Asignar ClubID a las 3 tablas
salarios_full = add_clubid(salarios_full, 'Club', 'Liga', aliases_sal)
rating        = add_clubid(rating, 'team', 'liga', aliases_rat)
rend          = add_clubid(rend, 'squad', 'liga', aliases_rend)

# Reportar matching
for name, df in [('salarios', salarios_full), ('rating', rating), ('rendimiento', rend)]:
    miss = df['ClubID'].isna().sum()
    print(f"    {name}: {len(df):,} filas, sin ClubID: {miss} ({miss/len(df)*100:.1f}%)")


# ============================================================
# 7) DIMENSIÓN JUGADORES  (dim_jugador)
# ============================================================
# Estrategia: clave compuesta = (nombre_normalizado, ClubID, TemporadaID).
# Esto evita problemas cuando el mismo nombre aparece en distintos clubes/temporadas
# (ej: "Sergio García" hay varios). Es una solución pragmática: asume que un
# jugador en un club-temporada es único, lo cual es cierto en 99.9% de casos.
#
# Para construir dim_jugador unificamos los 3 sources (todos los nombres vistos)
# y conservamos PlayerKey = (nombre_norm, ClubID, TemporadaID). Esa será la
# clave para hacer JOIN entre las tablas de hechos.
print("\n[7] Construyendo dim_jugador...")

def take_player(df, name_col, age_col=None, country_col=None, pos_col=None, source=''):
    keep = {name_col:'Player'}
    cols = ['ClubID','Temporada', name_col]
    if age_col and age_col in df.columns:
        cols.append(age_col); keep[age_col]='Age'
    if country_col and country_col in df.columns:
        cols.append(country_col); keep[country_col]='Country'
    if pos_col and pos_col in df.columns:
        cols.append(pos_col); keep[pos_col]='Position'
    out = df[cols].rename(columns=keep)
    out['Source'] = source
    return out

# Estandarizar nombres de columnas Temporada en cada source
salarios_full = salarios_full.rename(columns={'Temporada':'Temporada'})  # ya está
rating        = rating.rename(columns={'temporada':'Temporada'})
rend          = rend.rename(columns={'temporada':'Temporada'})

p1 = take_player(salarios_full, 'Player','Age','Country','Position','salarios')
p2 = take_player(rating, 'player', source='rating')
p3 = take_player(rend, 'player', age_col='age', country_col='nation', pos_col='pos', source='rend')

players_all = pd.concat([p1,p2,p3], ignore_index=True)
players_all['PlayerNorm'] = players_all['Player'].apply(norm_text)

# dim_jugador: una fila por (PlayerNorm, ClubID, Temporada). Tomamos la primera
# aparición de Age/Country/Position (las 3 fuentes pueden discrepar levemente).
dim_jugador = (players_all
    .dropna(subset=['ClubID','Temporada'])
    .sort_values('Source')   # rend > rating > salarios alfabéticamente; rend trae nation
    .groupby(['PlayerNorm','ClubID','Temporada'], as_index=False)
    .agg({'Player':'first', 'Age':'first', 'Country':'first', 'Position':'first'})
)
dim_jugador.insert(0, 'PlayerID', range(1, len(dim_jugador)+1))

# Mapa para buscar PlayerID rápidamente desde las hechos
player_lookup = dim_jugador.set_index(['PlayerNorm','ClubID','Temporada'])['PlayerID'].to_dict()

def attach_playerid(df, name_col):
    df = df.copy()
    df['PlayerNorm'] = df[name_col].apply(norm_text)
    df['PlayerID'] = list(zip(df['PlayerNorm'], df['ClubID'], df['Temporada']))
    df['PlayerID'] = df['PlayerID'].map(player_lookup)
    return df.drop(columns='PlayerNorm')

salarios_full = attach_playerid(salarios_full, 'Player')
rating        = attach_playerid(rating, 'player')
rend          = attach_playerid(rend, 'player')

print(f"    dim_jugador: {len(dim_jugador):,} jugadores únicos (por temporada-club)")


# ============================================================
# 8) AGREGAR TemporadaID y LigaID a las hechos
# ============================================================
def add_temp_liga_id(df, temp_col='Temporada', liga_col='Liga'):
    df = df.merge(dim_temporada[['TemporadaID','Temporada']], left_on=temp_col, right_on='Temporada', how='left')
    if 'Temporada_y' in df.columns:
        df = df.drop(columns='Temporada_y').rename(columns={'Temporada_x':'Temporada'})
    df = df.merge(dim_liga[['LigaID','LigaCodigo']], left_on=liga_col, right_on='LigaCodigo', how='left')
    if 'LigaCodigo' in df.columns:
        df = df.drop(columns='LigaCodigo')
    return df

salarios_full = add_temp_liga_id(salarios_full, 'Temporada', 'Liga')
rating        = add_temp_liga_id(rating, 'Temporada', 'liga')
rend          = add_temp_liga_id(rend, 'Temporada', 'liga')


# ============================================================
# 9) HECHOS finales (con FKs limpias)
# ============================================================
print("\n[8] Generando tablas de hechos limpias...")

fact_salarios = salarios_full[[
    'PlayerID','ClubID','LigaID','TemporadaID',
    'Net_Fixed_PW_USD','Net_Fixed_PY_USD','Net_Bonus_PY_USD',
    'Net_Total_PY_USD','Adj_Net_Total_PY_2026'
]].copy()

fact_rating = rating[[
    'PlayerID','ClubID','LigaID','TemporadaID',
    'rating','mins','goals','assists','apps'
]].copy()
fact_rating = fact_rating.rename(columns={'rating':'Rating','mins':'Mins',
    'goals':'Goals','assists':'Assists','apps':'Apps'})

# Limpiar 'apps' tipo "31(7)" -> Starts=31, SubsApps=7, TotalApps=38
def split_apps(x):
    if pd.isna(x):
        return pd.Series([None,None,None])
    s = str(x).strip()
    m = re.match(r'^(\d+)\s*\((\d+)\)$', s)
    if m:
        st, sb = int(m.group(1)), int(m.group(2))
        return pd.Series([st, sb, st+sb])
    if s.isdigit():
        return pd.Series([int(s), 0, int(s)])
    return pd.Series([None,None,None])

fact_rating[['Starts','SubsIn','TotalApps']] = fact_rating['Apps'].apply(split_apps)
fact_rating['Assists'] = pd.to_numeric(fact_rating['Assists'], errors='coerce')
fact_rating = fact_rating.drop(columns='Apps')

fact_rendimiento = rend[[
    'PlayerID','ClubID','LigaID','TemporadaID',
    'mp','min','starts','90s','gls','ast','g+a','g-pk','pk','pkatt','crdy','crdr',
    'ppm','ong','onga','+/-','+/-90','on-off'
]].copy()
fact_rendimiento.columns = [
    'PlayerID','ClubID','LigaID','TemporadaID',
    'MP','Mins','Starts','Nineties','Goals','Assists','GoalsAssists','GoalsNoPK',
    'PK','PKAtt','YellowCards','RedCards','PointsPerMatch','OnGoals','OnGoalsAgainst',
    'PlusMinus','PlusMinus90','OnOff'
]


# ============================================================
# 10) GUARDAR
# ============================================================
print("\n[9] Guardando archivos...")

# CSVs (recomendado para Power BI - carga rápida)
dim_liga.to_csv(OUT/'dim_liga.csv', index=False)
dim_temporada.to_csv(OUT/'dim_temporada.csv', index=False)
dim_club.to_csv(OUT/'dim_club.csv', index=False)
dim_jugador.to_csv(OUT/'dim_jugador.csv', index=False)
fact_salarios.to_csv(OUT/'fact_salarios.csv', index=False)
fact_rating.to_csv(OUT/'fact_rating.csv', index=False)
fact_rendimiento.to_csv(OUT/'fact_rendimiento.csv', index=False)

# Y un Excel multi-hoja por comodidad
with pd.ExcelWriter(OUT/'modelo_powerbi.xlsx', engine='openpyxl') as w:
    dim_liga.to_excel(w, sheet_name='dim_liga', index=False)
    dim_temporada.to_excel(w, sheet_name='dim_temporada', index=False)
    dim_club.to_excel(w, sheet_name='dim_club', index=False)
    dim_jugador.to_excel(w, sheet_name='dim_jugador', index=False)
    fact_salarios.to_excel(w, sheet_name='fact_salarios', index=False)
    fact_rating.to_excel(w, sheet_name='fact_rating', index=False)
    fact_rendimiento.to_excel(w, sheet_name='fact_rendimiento', index=False)

# Reporte de calidad
print("\n" + "="*60)
print("RESUMEN FINAL")
print("="*60)
print(f"dim_liga         : {len(dim_liga):>6,} filas")
print(f"dim_temporada    : {len(dim_temporada):>6,} filas")
print(f"dim_club         : {len(dim_club):>6,} filas")
print(f"dim_jugador      : {len(dim_jugador):>6,} filas")
print(f"fact_salarios    : {len(fact_salarios):>6,} filas | sin PlayerID: {fact_salarios['PlayerID'].isna().sum()}")
print(f"fact_rating      : {len(fact_rating):>6,} filas | sin PlayerID: {fact_rating['PlayerID'].isna().sum()}")
print(f"fact_rendimiento : {len(fact_rendimiento):>6,} filas | sin PlayerID: {fact_rendimiento['PlayerID'].isna().sum()}")
print("\nArchivos guardados en:", OUT)
