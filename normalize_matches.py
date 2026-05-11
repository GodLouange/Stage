"""
normalize_matches.py
--------------------
Convertit un ou plusieurs fichiers CSV de match (format horizontal OU vertical)
en un fichier master unifié, prêt pour l'analyse.

Usage:
    python normalize_matches.py                         # traite tous les CSV du dossier data/
    python normalize_matches.py fichier1.csv fichier2.csv
    python normalize_matches.py --out master.csv fichier1.csv fichier2.csv

Sortie:  master_matches.csv  (ou le nom spécifié avec --out)
"""

import os
import sys
import re
import argparse
import unicodedata
import pandas as pd


# ─────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────

def _strip_accents(s: str) -> str:
    return unicodedata.normalize("NFD", s).encode("ascii", "ignore").decode()

def _norm_col(c: str) -> str:
    """Normalise un nom de colonne → minuscules, sans accents, espaces→_"""
    return re.sub(r"\s+", "_", _strip_accents(c.strip().lower()))

def _find_col(df: pd.DataFrame, *candidates) -> str | None:
    """Cherche une colonne par nom (insensible à la casse et aux accents)."""
    norm_map = {_norm_col(c): c for c in df.columns}
    for cand in candidates:
        key = _norm_col(cand)
        if key in norm_map:
            return norm_map[key]
    return None

ENCODINGS = ["utf-16", "utf-8-sig", "utf-8", "latin-1"]

def _load_raw(path: str) -> pd.DataFrame:
    """Charge un CSV avec détection automatique de l'encodage."""
    for enc in ENCODINGS:
        try:
            df = pd.read_csv(path, encoding=enc, sep=",",
                             on_bad_lines="skip", low_memory=False)
            if len(df.columns) > 3:
                return df
        except Exception:
            continue
    raise ValueError(f"Impossible de lire le fichier : {path}")


# ─────────────────────────────────────────────
#  Détection et normalisation du format
# ─────────────────────────────────────────────

def _is_vertical(df: pd.DataFrame) -> bool:
    """
    Format vertical : N lignes par action, une valeur par ligne.
    Indicateurs : présence de colonnes "* : Temps", ratio lignes/clips > 3.
    """
    temps_cols = [c for c in df.columns if c.strip().endswith(": Temps")
                  or c.strip().endswith(":   T e m p s")]
    if len(temps_cols) > 5:
        return True
    # Ratio lignes / clips uniques
    debut_col = _find_col(df, "Début du clip", "Debut du clip", "Début", "Temps de début")
    if debut_col:
        nom_col = _find_col(df, "Nom de la ligne")
        if nom_col:
            ratio = len(df) / max(1, df.groupby([nom_col, debut_col]).ngroups)
            return ratio > 2.5
    return False

def _normalize_vertical(df: pd.DataFrame) -> pd.DataFrame:
    """
    Transforme le format vertical en horizontal :
    - supprime les colonnes "* : Temps"
    - groupe par (Nom de la ligne, Début du clip)
    - prend la première valeur non-nulle par colonne
    """
    # Supprimer colonnes de timing
    temps_cols = [c for c in df.columns if ": Temps" in c]
    df = df.drop(columns=temps_cols, errors="ignore")

    nom_col   = _find_col(df, "Nom de la ligne")
    debut_col = _find_col(df, "Début du clip", "Debut du clip")
    fin_col   = _find_col(df, "Fin du clip", "Fin du clip")

    if nom_col is None or debut_col is None:
        return df

    group_cols = [nom_col, debut_col]
    if fin_col:
        group_cols.append(fin_col)

    df[debut_col] = pd.to_numeric(df[debut_col], errors="coerce")
    df = df.sort_values(debut_col)

    agg = df.groupby(group_cols, sort=False).first().reset_index()
    return agg


# ─────────────────────────────────────────────
#  Extraction des métadonnées de match
# ─────────────────────────────────────────────

def _detect_teams(df: pd.DataFrame, nom_col: str):
    """
    Identifie équipe_dom et équipe_ext à partir des noms de lignes.
    Cherche des patterns "[Equipe] - Rucks" ou "[Equipe] - Passes".
    Exclut les lignes SA/ADV (codes courts) et les noms de joueurs.
    """
    teams = set()
    pattern = re.compile(r"^(.+?)\s*-\s*(Rucks|Passes|Contacts|Essais|Plaquages|Remplacement)$", re.I)
    for val in df[nom_col].dropna().unique():
        m = pattern.match(str(val).strip())
        if m:
            teams.add(m.group(1).strip())

    teams = sorted(teams)
    if len(teams) >= 2:
        return teams[0], teams[1]
    elif len(teams) == 1:
        return teams[0], "Adversaire"
    return "Equipe A", "Equipe B"

def _guess_match_id(filepath: str) -> str:
    base = os.path.splitext(os.path.basename(filepath))[0]
    # Nettoyer le nom du fichier
    base = re.sub(r"[Cc][Ss][Vv]", "", base).strip(" _-")
    return base.strip()


# ─────────────────────────────────────────────
#  Catégorisation des lignes
# ─────────────────────────────────────────────

# Noms de joueur : Prénom NOM (tout-caps), ou NOM Prénom
_JOUEUR_RE = re.compile(r"^[A-ZÀ-Ÿa-záàâäéèêëîïôùûü'\-]+\s+[A-ZÀ-Ÿ][A-ZÀ-Ÿ\-']+$")
_CODES_SA  = re.compile(r"^(SA|ADV)\s*-\s*", re.I)

def _categorize(nom: str) -> str:
    """
    Renvoie la catégorie de la ligne :
      SEQUENCE | ACTION | STATS | JOUEUR | CHRONO | AUTRE
    """
    nom = str(nom).strip()
    upper = nom.upper()

    if upper in ("SEQUENCE", "SEQUENCE DE JEU"):
        return "SEQUENCE"
    if upper.startswith("CHRONO"):
        return "CHRONO"
    if _CODES_SA.match(nom):
        return "ACTION"
    # Stats équipe : "[Equipe] - [Stat]" avec stat connue
    if re.match(r"^.+\s*-\s*(Rucks|Passes|Contacts|Essais|Plaquages|Possession|Touches|Melees|"
                r"Penalites|Buteur|Botteur|Remplacement|Cartons|Franchissements|Jeux|"
                r"Soutiens|Defenseurs|Ballons|Avantage|Coups|Receptions|Contre|Contest|"
                r"Lancements|Bras|Maul|Turn|TMO|22m|Renvois|Assistant)", nom, re.I):
        return "STATS"
    # Récupération
    if nom.lower() in ("recuperation",):
        return "AUTRE"
    # Joueur (Prénom NOM ou NOM Prénom)
    if _JOUEUR_RE.match(nom):
        return "JOUEUR"
    return "AUTRE"

def _parse_equipe_action(nom: str, equipe_dom: str, equipe_ext: str):
    """
    À partir du nom de ligne, extrait (equipe, action_type).
    """
    nom = str(nom).strip()

    # Format SA - XXX / ADV - XXX
    m = re.match(r"^(SA|ADV)\s*-\s*(.+)$", nom, re.I)
    if m:
        code, action = m.group(1).upper(), m.group(2).strip().upper()
        equipe = equipe_dom if code == "SA" else equipe_ext
        return equipe, action

    # Format "[Equipe] - [Stat]"
    m2 = re.match(r"^(.+?)\s*-\s*(.+)$", nom)
    if m2:
        eq_raw, action = m2.group(1).strip(), m2.group(2).strip()
        # Normalise l'équipe
        if _strip_accents(eq_raw.lower()) in _strip_accents(equipe_dom.lower()):
            eq = equipe_dom
        elif _strip_accents(eq_raw.lower()) in _strip_accents(equipe_ext.lower()):
            eq = equipe_ext
        else:
            eq = eq_raw
        return eq, action

    return "", nom


# ─────────────────────────────────────────────
#  Construction du schéma unifié
# ─────────────────────────────────────────────

# Mapping : nom de colonne source → nom normalisé dans le master
_COL_MAP = {
    # Temporel
    "temps_de_debut":          "debut",
    "debut_du_clip":           "debut",
    "temps_de_fin":            "fin",
    "fin_du_clip":             "fin",
    "duree":                   "duree",
    # Action
    "nom_de_la_ligne":         "nom_ligne",
    "numero_du_clip":          "clip_id",
    "qualifier":               "qualifier",
    "periode_de_jeu":          "periode",
    "chrono":                  "chrono",
    # Résultat
    "resultat":                "resultat",
    "reussite":                "reussite",
    "efficacite":              "efficacite",
    "efficacite_ligne":        "efficacite_ligne",
    # Géographie
    "coordonnee_x":            "coord_x",
    "coordonnee_y":            "coord_y",
    "coordonnee_x_arrivee":    "coord_x_fin",
    "coordonnee_y_arrivee":    "coord_y_fin",
    "cote_terrain":            "cote",
    "cote_terrain_fin":        "cote_fin",
    "zone_terrain":            "zone",
    "zone_terrain_fin":        "zone_fin",
    "metres_parcourus":        "metres",
    # Acteurs
    "joueur":                  "joueur",
    "botteur":                 "botteur",
    # Type
    "type":                    "type",
    "type_de_passe":           "type_passe",
    "type_de_jeu_au_pied":     "type_jeu_pied",
    "type_de_jeu_a_la_main":   "type_jeu_main",
    "type_d_essai":            "type_essai",
    "type_de_tir_au_but":      "type_tir",
    "type_de_penalite":        "type_penalite",
    "type_de_perte_de_balle":  "type_perte",
    "type_de_franchissement":  "type_franchissement",
    "type_de_defense":         "type_defense",
    "type_de_carton":          "type_carton",
    "type_de_recuperation":    "type_recuperation",
    "type_de_lancement_sur_melee":  "type_lancement_melee",
    "type_de_lancement_sur_touche": "type_lancement_touche",
    # Spécifique
    "structure":               "structure",
    "ruck":                    "ruck",
    "touche":                  "touche",
    "largeur_terrain":         "largeur",
    "enchainement":            "enchainement",
    "contest":                 "contest",
    "conquete":                "conquete",
    "livraison":               "livraison",
    "lancement":               "lancement",
    "zone_lancement":          "zone_lancement",
    "zone_lance":              "zone_lance",
    "nombre":                  "nombre",
    "origine":                 "origine",
    "specificite":             "specificite",
    "forme":                   "forme",
    "hauteur":                 "hauteur",
    "vitesse_de_liberation":   "vitesse_lib",
    "nombre_de_defenseurs_battus":              "def_battus",
    "nombre_de_joueurs_offensifs_consommes":    "joueurs_off_conso",
    "nombre_de_joueurs_defensifs_consommes":    "joueurs_def_conso",
    "ordre_d_arrivee":         "ordre_arrivee",
    "duel_aerien":             "duel_aerien",
    "plaquages_dangereux":     "plaquages_dangereux",
    "action_de_fin_de_franchissement": "action_fin_franchissement",
    "type_de_bras_casse":      "type_bras_casse",
    "star_wars":               "star_wars",
    "fin_de_la_premiere_mi-temps": "fin_mt1",
    "fin_de_la_seconde_mi-temps":  "fin_mt2",
    "50_22":                   "50_22",
    "code":                    "code",
}

# Colonnes finales dans l'ordre logique
_MASTER_COLS = [
    "match_id", "equipe_dom", "equipe_ext",
    "categorie", "equipe", "action_type",
    "nom_ligne", "clip_id",
    "debut", "fin", "duree",
    "periode", "chrono",
    "joueur", "botteur",
    "resultat", "reussite", "efficacite", "efficacite_ligne",
    "coord_x", "coord_y", "coord_x_fin", "coord_y_fin",
    "cote", "cote_fin", "zone", "zone_fin", "metres",
    "type", "type_passe", "type_jeu_pied", "type_jeu_main",
    "type_essai", "type_tir", "type_penalite", "type_perte",
    "type_franchissement", "type_defense", "type_carton", "type_recuperation",
    "type_lancement_melee", "type_lancement_touche",
    "structure", "ruck", "touche", "largeur",
    "enchainement", "contest", "conquete", "livraison",
    "lancement", "zone_lancement", "zone_lance", "nombre",
    "origine", "specificite", "forme", "hauteur",
    "vitesse_lib", "def_battus", "joueurs_off_conso", "joueurs_def_conso",
    "ordre_arrivee", "duel_aerien", "plaquages_dangereux",
    "action_fin_franchissement", "type_bras_casse", "star_wars",
    "fin_mt1", "fin_mt2", "50_22", "code", "qualifier",
]


# ─────────────────────────────────────────────
#  Traitement d'un fichier → DataFrame master
# ─────────────────────────────────────────────

def process_file(filepath: str, match_id: str = None) -> pd.DataFrame:
    print(f"  → Chargement : {os.path.basename(filepath)}")
    df_raw = _load_raw(filepath)

    # Normalisation verticale → horizontale si besoin
    if _is_vertical(df_raw):
        print(f"     Format détecté : VERTICAL — normalisation en cours…")
        df_raw = _normalize_vertical(df_raw)
    else:
        print(f"     Format détecté : HORIZONTAL")

    print(f"     {len(df_raw)} lignes × {len(df_raw.columns)} colonnes après normalisation")

    nom_col = _find_col(df_raw, "Nom de la ligne")
    if nom_col is None:
        raise ValueError(f"Colonne 'Nom de la ligne' introuvable dans {filepath}")

    # Métadonnées du match
    mid = match_id or _guess_match_id(filepath)
    equipe_dom, equipe_ext = _detect_teams(df_raw, nom_col)
    print(f"     Équipes : {equipe_dom} (dom) vs {equipe_ext} (ext)")

    # Renommage des colonnes vers le schéma normalisé
    rename_map = {}
    for col in df_raw.columns:
        nkey = _norm_col(col)
        if nkey in _COL_MAP:
            rename_map[col] = _COL_MAP[nkey]
    df_raw = df_raw.rename(columns=rename_map)

    # Après renommage, "Nom de la ligne" → "nom_ligne"
    nom_col_final = "nom_ligne" if "nom_ligne" in df_raw.columns else nom_col

    # Colonnes de temps : convertir en float
    for tc in ["debut", "fin", "duree"]:
        if tc in df_raw.columns:
            df_raw[tc] = pd.to_numeric(df_raw[tc], errors="coerce")

    # Ajout des colonnes de catégorisation
    df_raw["categorie"]   = df_raw[nom_col_final].apply(_categorize)
    df_raw[["equipe", "action_type"]] = df_raw[nom_col_final].apply(
        lambda x: pd.Series(_parse_equipe_action(x, equipe_dom, equipe_ext))
    )

    # Métadonnées match
    df_raw.insert(0, "match_id",   mid)
    df_raw.insert(1, "equipe_dom", equipe_dom)
    df_raw.insert(2, "equipe_ext", equipe_ext)

    # Garder uniquement les colonnes du schéma master (+ toutes les autres à la fin)
    master_present = [c for c in _MASTER_COLS if c in df_raw.columns]
    extra_cols     = [c for c in df_raw.columns if c not in _MASTER_COLS]
    final_cols     = master_present + extra_cols

    return df_raw[final_cols]


# ─────────────────────────────────────────────
#  Point d'entrée
# ─────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Normalise des fichiers CSV de match rugby")
    parser.add_argument("files", nargs="*", help="Fichiers CSV à traiter")
    parser.add_argument("--out", default="master_matches.csv",
                        help="Nom du fichier de sortie (défaut: master_matches.csv)")
    parser.add_argument("--data-dir", default="data",
                        help="Dossier à scanner si aucun fichier spécifié (défaut: data/)")
    args = parser.parse_args()

    files = args.files
    if not files:
        if os.path.isdir(args.data_dir):
            files = [os.path.join(args.data_dir, f)
                     for f in os.listdir(args.data_dir)
                     if f.lower().endswith(".csv")]
        if not files:
            print(f"Aucun fichier CSV trouvé. Placez vos fichiers dans '{args.data_dir}/' "
                  f"ou passez-les en argument.")
            sys.exit(1)

    print(f"\n{'='*55}")
    print(f"  RUGBY — Normalisation de {len(files)} fichier(s)")
    print(f"{'='*55}\n")

    dfs = []
    for fp in files:
        try:
            df_match = process_file(fp)
            print(f"     ✓ {len(df_match)} lignes extraites\n")
            dfs.append(df_match)
        except Exception as e:
            print(f"     ✗ Erreur : {e}\n")

    if not dfs:
        print("Aucun fichier traité avec succès.")
        sys.exit(1)

    # Dédoublonner les colonnes dans chaque df avant concat
    dfs_clean = []
    for d in dfs:
        d = d.loc[:, ~d.columns.duplicated()]
        dfs_clean.append(d)
    master = pd.concat(dfs_clean, ignore_index=True)

    out_path = args.out
    master.to_csv(out_path, index=False, encoding="utf-8-sig")

    print(f"{'='*55}")
    print(f"  Master créé : {out_path}")
    print(f"  Total lignes : {len(master):,}")
    print(f"  Matchs       : {master['match_id'].nunique()}")
    print(f"  Colonnes     : {len(master.columns)}")
    print(f"\n  Répartition par catégorie :")
    for cat, n in master["categorie"].value_counts().items():
        print(f"    {cat:12s} : {n:6,} lignes")
    print(f"{'='*55}\n")


if __name__ == "__main__":
    main()
