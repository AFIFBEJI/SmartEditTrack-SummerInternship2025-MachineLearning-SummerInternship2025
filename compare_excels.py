# compare_excels.py
import os
import re
import csv
import json
import hashlib
from datetime import datetime
from collections import defaultdict

import openpyxl
import openpyxl.utils
import difflib
import pandas as pd
import numpy as np
from dotenv import load_dotenv
load_dotenv()


from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

# =============== CONFIG ===============
DATA_DIR          = os.environ.get("DATA_DIR", "./")
template_path     = os.path.join(DATA_DIR, "Fichier_Excel_Professeur_Template.xlsx")
copies_folder     = os.path.join(DATA_DIR, "copies_etudiants")
rapport_folder    = os.path.join(DATA_DIR, "rapports_etudiants")
hash_log_file     = os.path.join(DATA_DIR, "hash_records.csv")          # global
classes_root      = os.path.join(DATA_DIR, "classes")                   # multi-classes
cours_file        = os.path.join(DATA_DIR, "cours_references.txt")
dataset_ia_file   = os.path.join(DATA_DIR, "dataset.csv")
modifs_csv        = os.path.join(DATA_DIR, "modifications_log_secure.csv")
history_folder    = os.path.join(DATA_DIR, "historique_reponses")

os.makedirs(rapport_folder, exist_ok=True)
os.makedirs(history_folder, exist_ok=True)

# =============== HASH INDEX (multi-classes) ===============
def _parse_hash_log(path):
    rows = []
    if not os.path.exists(path):
        return rows
    try:
        with open(path, newline="", encoding="utf-8") as f:
            r = csv.DictReader(f)
            for row in r:
                rid = (row.get("id_etudiant") or "").strip()
                h   = (row.get("hash") or "").strip()
                if rid and h:
                    rows.append({
                        "id": rid,
                        "nom": (row.get("nom") or "").strip(),
                        "prenom": (row.get("prenom") or "").strip(),
                        "hash": h,
                        "nom_fichier": (row.get("nom_fichier") or "").strip()
                    })
    except Exception as e:
        print(f"[WARN] Impossible de lire {path}: {e}")
    return rows

def _load_all_hash_logs():
    merged = []
    merged.extend(_parse_hash_log(hash_log_file))  # global
    if os.path.isdir(classes_root):
        for slug in os.listdir(classes_root):
            d = os.path.join(classes_root, slug)
            if not os.path.isdir(d):
                continue
            for fname in os.listdir(d):
                if fname.startswith("hash_records_") and fname.endswith(".csv"):
                    merged.extend(_parse_hash_log(os.path.join(d, fname)))
    return merged

def _official_hashes_by_id():
    rows = _load_all_hash_logs()
    m = defaultdict(set)
    for r in rows:
        m[r["id"]].add(r["hash"])
    return m

# =============== COURS & DATASET IA (optionnels) ===============
cours_content = ""
if os.path.exists(cours_file):
    try:
        with open(cours_file, "r", encoding="utf-8") as f:
            cours_content = f.read().lower()
    except Exception:
        pass

df_ia = None
vectorizer = None
tfidf_matrix = None
if os.path.exists(dataset_ia_file):
    try:
        df_ia = pd.read_csv(dataset_ia_file)
        if "reponse" in df_ia.columns:
            vectorizer = TfidfVectorizer(stop_words="french")
            tfidf_matrix = vectorizer.fit_transform(df_ia["reponse"])
    except Exception as e:
        print(f"[WARN] Erreur chargement dataset IA: {e}")

# =============== UTILITAIRES ===============
def _safe_str(v):
    try:
        if v is None:
            return ""
        return str(v)
    except Exception:
        return ""

def _html_escape(s: str) -> str:
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

def recalculer_hash_depuis_contenu(ws, id_etudiant):
    contenu_concatene = (id_etudiant or "").encode()
    for row in ws.iter_rows(values_only=True):
        for cell in row:
            if cell is not None:
                contenu_concatene += _safe_str(cell).encode()
    return hashlib.sha256(contenu_concatene).hexdigest()

def _looks_like_formula(text: str) -> bool:
    if not text:
        return False
    return bool(re.search(r"[0-9=+\-*/^()_%·⋅×÷σΣ√π]", text))

def detecter_triche(reponse, question):
    """
    Heuristiques renforcées:
      - vide / très court
      - copier-coller du cours
      - style IA générique
      - caractères spéciaux
      - "gibberish"
      - MAJUSCULES
      - formule attendue absente
      - similarité IA via dataset (si dispo)
    """
    if reponse is None or _safe_str(reponse).strip() == "":
        return "Non répondu"

    reponse = _safe_str(reponse).strip()
    rlow = reponse.lower()

    if len(reponse) < 3:
        return "Réponse très courte"

    if cours_content:
        seq = difflib.SequenceMatcher(None, rlow, cours_content)
        m = seq.find_longest_match(0, len(rlow), 0, len(cours_content))
        if m.size > 50 and seq.ratio() > 0.80:
            return f"Copier-coller du cours (≈{seq.ratio()*100:.0f}%)"

    ia_keywords = [
        "en tant que", "système", "fonctionnalité", "dans le cadre",
        "il est important de noter", "cependant", "par conséquent",
        "d'après la", "selon les", "il convient de", "dans un premier temps"
    ]
    if any(k in rlow for k in ia_keywords):
        return "Style IA générique"

    if re.search(r'[^\w\s.,;:?!\'"()\-=/+*^%°]', reponse):
        return "Caractères spéciaux suspects"

    letters = re.sub(r"[^A-Za-zÀ-ÿ]", "", reponse)
    if len(letters) >= 5:
        vowels = re.findall(r"[aeiouyAEIOUYàâäéèêëîïôöùûüÿ]", letters)
        if (len(vowels) / len(letters)) < 0.20:
            return "Texte non lexical (gibberish?)"

    letters_alpha = [c for c in reponse if c.isalpha()]
    if letters_alpha:
        up_ratio = sum(1 for c in letters_alpha if c.isupper()) / len(letters_alpha)
        if up_ratio > 0.85 and len(letters_alpha) >= 5:
            return "Texte anormalement en MAJUSCULES"

    qlow = (question or "").lower()
    if any(t in qlow for t in ["formule", "calcul", "expression", "expr", "σ", "sigma", "moment", "contrainte", "équation"]):
        if not _looks_like_formula(reponse):
            return "Formule attendue non détectée"

    if "définir" in qlow and len(reponse) < 20:
        return "Réponse trop courte pour une définition"
    if "expliquer" in qlow and len(reponse) < 30:
        return "Réponse trop courte pour une explication"

    if df_ia is not None and vectorizer is not None and tfidf_matrix is not None:
        try:
            new_vec = vectorizer.transform([reponse])
            sims = cosine_similarity(new_vec, tfidf_matrix)
            max_sim = float(np.max(sims))
            if max_sim > 0.75:
                idx = int(np.argmax(sims))
                label = int(df_ia.iloc[idx].get("label", 0))  # 0 = IA, 1 = humain
                return "Réponse IA probable" if label == 0 else "Réponse humaine probable"
        except Exception:
            pass

    return "Réponse normale"

# --------- Historique ----------
def _history_path(student_id: str) -> str:
    sid = (student_id or "").strip() or "unknown"
    return os.path.join(history_folder, f"{sid}.json")

def _load_history(student_id: str):
    p = _history_path(student_id)
    if os.path.exists(p):
        try:
            with open(p, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []
    return []

def _save_history(student_id: str, history_list: list):
    p = _history_path(student_id)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(history_list, f, ensure_ascii=False, indent=2)

def _snapshot_ws(ws, include_cols=(3, 25)) -> dict:
    out = {}
    max_row = ws.max_row or 2
    min_col, max_col = include_cols
    for row in range(2, max_row + 1):
        for col in range(min_col, max_col + 1):
            addr = f"{openpyxl.utils.get_column_letter(col)}{row}"
            out[addr] = _safe_str(ws.cell(row=row, column=col).value)
    return out

def _parse_expected_id_from_filename(nom_fichier: str) -> str | None:
    try:
        after = nom_fichier.split("__", 1)[1]
        return after.split("_", 1)[0]
    except Exception:
        return None

def _append_modif_csv(row_dict: dict):
    header = [
        "timestamp","fichier","id_etudiant",
        "cellule","question","valeur_avant","valeur_prof","valeur_etudiant",
        "source_diff","alerte","hash_z2","hash_recalcule","tentative_index"
    ]
    file_exists = os.path.exists(modifs_csv)
    try:
        with open(modifs_csv, "a", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=header)
            if not file_exists:
                w.writeheader()
            w.writerow({k: row_dict.get(k, "") for k in header})
    except Exception as e:
        print("[WARN] Erreur écriture journal modifs:", e)

# =============== COEUR : COMPARAISON ===============
def comparer_etudiant(fichier_etudiant):
    """
    Compare une copie au template, conserve l'historique et génère :
      - TXT + HTML dans rapports_etudiants/
      - journal CSV des modifications
      - historique JSON par étudiant
    """
    nom_fichier = os.path.basename(fichier_etudiant)
    official_by_id = _official_hashes_by_id()  # {id: set(hashes_officiels)}
    expected_id = _parse_expected_id_from_filename(nom_fichier)

    # --- Ouverture
    try:
        wb_prof = openpyxl.load_workbook(template_path, data_only=True)
        wb_etud = openpyxl.load_workbook(fichier_etudiant, data_only=True)
        ws_prof = wb_prof.active
        ws_etud = wb_etud.active
    except Exception as e:
        return f"❌ Erreur d'ouverture des fichiers : {e}"

    # --- Identité & Hash
    id_cell = _safe_str(ws_etud["Z1"].value)
    hash_cell = _safe_str(ws_etud["Z2"].value)
    hash_calcule = recalculer_hash_depuis_contenu(ws_etud, id_cell)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # --- Authenticité
    authenticity = "unknown"
    authenticity_msg = ""
    official_ok_for_id = id_cell and (hash_cell in official_by_id.get(id_cell, set()))
    if not id_cell or not hash_cell:
        authenticity = "critical"
        authenticity_msg = "❌ L'ID (Z1) ou le hash (Z2) est manquant."
    else:
        if expected_id and expected_id != id_cell:
            authenticity = "mismatch"
            authenticity_msg = f"⚠️ ID du fichier (Z1={id_cell}) ≠ ID attendu ({expected_id})."
        if official_ok_for_id and hash_calcule == hash_cell:
            authenticity = "official_clean"
            authenticity_msg = "✅ Copie officielle intacte."
        elif official_ok_for_id and hash_calcule != hash_cell:
            authenticity = "official_then_edited"
            authenticity_msg = "✅ Copie officielle utilisée puis contenu modifié pour répondre (normal)."
        elif (not official_ok_for_id) and hash_calcule == hash_cell:
            authenticity = "self_consistent_non_official"
            authenticity_msg = "⚠️ Fichier cohérent mais non reconnu parmi les copies officielles de cet étudiant."
        elif (not official_ok_for_id) and hash_calcule != hash_cell:
            authenticity = "tampered"
            authenticity_msg = "🚨 Incohérence : Z2 ≠ contenu et Z2 non-officiel."

    # --- Colonnes actives = celles qui ont une VRAIE question en ligne 1
    questions = {}
    active_cols = []
    for col in range(3, 26):  # C..Y
        addr = f"{openpyxl.utils.get_column_letter(col)}1"
        qtext = _safe_str(ws_prof[addr].value).strip()
        if qtext:  # <-- on ignore les colonnes sans question
            questions[addr[:-1]] = qtext
            active_cols.append(col)

    # --- Snapshots / diffs
    history_list = _load_history(id_cell or expected_id or "unknown")
    attempt_index = len(history_list) + 1
    snapshot_values = _snapshot_ws(ws_etud)  # on garde tout pour l'historique
    prev_values = history_list[-1]["values"] if history_list else {}

    diffs_vs_prev = []
    if history_list:
        for cell, new_val in snapshot_values.items():
            old_val = _safe_str(prev_values.get(cell, ""))
            if new_val != old_val:
                diffs_vs_prev.append((cell, old_val, new_val))

    # Diff vs template + matrice complète (UNIQUEMENT colonnes actives)
    diffs_vs_template = []
    matrix_full = []  # (addr, question, val_template, val_etud, statut, alerte)
    max_row = max(ws_prof.max_row, ws_etud.max_row)
    answered_count = 0
    unanswered_count = 0

    for row in range(2, max_row + 1):
        for col in active_cols:
            addr = f"{openpyxl.utils.get_column_letter(col)}{row}"
            col_letter = openpyxl.utils.get_column_letter(col)
            question = questions.get(col_letter, "")  # toujours non vide ici
            v_prof = _safe_str(ws_prof.cell(row=row, column=col).value)
            v_etud = _safe_str(ws_etud.cell(row=row, column=col).value)

            if v_etud.strip() == "":
                statut = "Non répondu"
                alerte = "Non répondu"
                unanswered_count += 1
            elif v_prof == v_etud:
                statut = "Identique au template"
                alerte = ""
            else:
                statut = "Modifiée"
                alerte = detecter_triche(v_etud, question)
                diffs_vs_template.append((addr, v_prof, v_etud))
                answered_count += 1

            matrix_full.append((addr, question, v_prof, v_etud, statut, alerte))

    alerts_by_cell = {addr: detecter_triche(ve, questions.get(re.match(r"[A-Z]+", addr).group(0), ""))
                      for addr, vp, ve in diffs_vs_template}

    # --- Journal CSV
    for addr, v_prof, v_etud in diffs_vs_template:
        col_letter = re.match(r"[A-Z]+", addr).group(0)
        question = questions.get(col_letter, "")
        _append_modif_csv({
            "timestamp": now,
            "fichier": nom_fichier,
            "id_etudiant": id_cell,
            "cellule": addr,
            "question": question,
            "valeur_avant": "",
            "valeur_prof": v_prof,
            "valeur_etudiant": v_etud,
            "source_diff": "TEMPLATE",
            "alerte": alerts_by_cell.get(addr, "Réponse normale"),
            "hash_z2": hash_cell,
            "hash_recalcule": hash_calcule,
            "tentative_index": attempt_index,
        })
    for addr, old_val, new_val in diffs_vs_prev:
        col_letter = re.match(r"[A-Z]+", addr).group(0)
        question = questions.get(col_letter, "")
        _append_modif_csv({
            "timestamp": now,
            "fichier": nom_fichier,
            "id_etudiant": id_cell,
            "cellule": addr,
            "question": question,
            "valeur_avant": old_val,
            "valeur_prof": "",
            "valeur_etudiant": new_val,
            "source_diff": "PREVIOUS",
            "alerte": detecter_triche(new_val, question),
            "hash_z2": hash_cell,
            "hash_recalcule": hash_calcule,
            "tentative_index": attempt_index,
        })

    # --- Historique
    history_entry = {
        "timestamp": now,
        "filename": nom_fichier,
        "hash_z2": hash_cell,
        "hash_recalcule": hash_calcule,
        "authenticity": authenticity,
        "values": snapshot_values
    }
    history_list.append(history_entry)
    _save_history(id_cell or expected_id or "unknown", history_list)

    # --- Timeline par cellule (valeurs successives)
    timeline = defaultdict(list)
    prev_map = {}
    for h in history_list:
        vals = h.get("values", {})
        ts = h.get("timestamp")
        for cell, v in vals.items():
            if prev_map.get(cell, None) != v:
                timeline[cell].append((ts, v))
                prev_map[cell] = v

    # --- Compteurs
    total_changes_template = len(diffs_vs_template)
    total_changes_prev = len(diffs_vs_prev)
    total_alerts = sum(1 for _, _, _, _, _, al in matrix_full
                       if al not in ["", "Réponse normale", "Réponse humaine probable", "Non répondu"])

    # ================== RAPPORT TXT ==================
    txt_lines = []
    txt_lines.append(f"📄 Rapport : {nom_fichier}")
    txt_lines.append(f"📅 Date : {now}")
    txt_lines.append(f"🧑 ID Étudiant (Z1) : {id_cell}")
    if expected_id:
        txt_lines.append(f"🧾 ID attendu (depuis nom du fichier) : {expected_id}")
    txt_lines.append(f"🔐 Hash (Z2) : {hash_cell}")
    txt_lines.append(f"🧪 Hash recalculé : {hash_calcule}")
    txt_lines.append(f"🛡️ Authenticité : {authenticity} — {authenticity_msg}\n")

    txt_lines.append("🔎 Modifications vs TEMPLATE :")
    if not diffs_vs_template:
        txt_lines.append("  • Aucune différence avec le template.")
    else:
        for addr, vp, ve in diffs_vs_template:
            col_letter = re.match(r"[A-Z]+", addr).group(0)
            question = questions.get(col_letter, "")
            txt_lines.append(f"  ✏️ {addr} — {question}")
            txt_lines.append(f"     – Réponse : {ve}")
            alert = alerts_by_cell.get(addr, "Réponse normale")
            if alert and alert != "Réponse normale":
                txt_lines.append(f"     – Alerte : {alert}")

    txt_lines.append("\n🔁 Modifications depuis la tentative précédente :")
    if not diffs_vs_prev:
        txt_lines.append("  • Aucune (premier dépôt ou pas de changement).")
    else:
        for addr, old_val, new_val in diffs_vs_prev:
            col_letter = re.match(r"[A-Z]+", addr).group(0)
            question = questions.get(col_letter, "")
            txt_lines.append(f"  ⟲ {addr} — {question}")
            txt_lines.append(f"     – Avant : {old_val}")
            txt_lines.append(f"     – Maintenant : {new_val}")

    txt_lines.append("\n🧾 Résumé")
    txt_lines.append(f"  • Cells ≠ template : {total_changes_template}")
    txt_lines.append(f"  • Changements vs dépôt précédent : {total_changes_prev}")
    txt_lines.append(f"  • Réponses renseignées : {answered_count}")
    txt_lines.append(f"  • Non répondu : {unanswered_count}")
    txt_lines.append(f"  • Alertes : {total_alerts}")
    if total_alerts == 0:
        txt_lines.append("  • ✅ Aucune alerte de triche/IA détectée.")

    # TIMELINE
    txt_lines.append("\n🕓 Historique par cellule (valeurs au fil des dépôts)")
    if not timeline:
        txt_lines.append("  • Aucun changement historisé.")
    else:
        for cell in sorted(timeline.keys()):
            txt_lines.append(f"  ▸ {cell}")
            for ts, v in timeline[cell]:
                txt_lines.append(f"     [{ts}] {v}")

    # Sauvegarde TXT
    base = os.path.splitext(nom_fichier)[0]
    path_txt = os.path.join(rapport_folder, f"{base}_rapport.txt")
    try:
        with open(path_txt, "w", encoding="utf-8") as f:
            f.write("\n".join(txt_lines))
    except Exception as e:
        return f"❌ Erreur écriture rapport TXT : {e}"

    # ================== RAPPORT HTML (lisible + pas coupé) ==================
    def badge(text, kind):
        colors = {
            "ok": "#10b981",       # vert
            "warn": "#fb923c",     # orange doux (remplace jaune)
            "err": "#ef4444",      # rouge
            "info": "#3b82f6",     # bleu
            "muted": "#64748b"     # slate
        }
        return f'<span class="pill" style="background:{colors.get(kind, "#64748b")}">{_html_escape(text)}</span>'

    def alert_kind(alerte: str) -> str:
        if not alerte or alerte in ["Réponse normale", "Réponse humaine probable"]:
            return "muted"
        a = alerte.lower()
        if "ia" in a or "incohérence" in a or "altération" in a or "tamper" in a:
            return "err"
        if "non répondu" in a:
            return "muted"
        return "warn"

    if authenticity == "official_clean":
        auth_badge = badge("Copie officielle intacte", "ok")
    elif authenticity == "official_then_edited":
        auth_badge = badge("Copie officielle puis modifiée", "info")
    elif authenticity == "self_consistent_non_official":
        auth_badge = badge("Cohérente non-officielle", "warn")
    elif authenticity == "tampered":
        auth_badge = badge("Incohérence / altération", "err")
    elif authenticity == "mismatch":
        auth_badge = badge("ID ≠ attendu", "warn")
    elif authenticity == "critical":
        auth_badge = badge("Infos manquantes", "err")
    else:
        auth_badge = badge("Inconnu", "muted")

    def html_rows_diff(rows, kind="template"):
        out = []
        if kind == "template":
            for addr, vp, ve in rows:
                col = re.match(r"[A-Z]+", addr).group(0)
                q = questions.get(col, "")
                al = alerts_by_cell.get(addr, "Réponse normale")
                al_html = "" if al in ["Réponse normale", "Réponse humaine probable", ""] else badge(al, alert_kind(al))
                out.append(f"""
                  <tr>
                    <td><code>{addr}</code></td>
                    <td>{_html_escape(q)}</td>
                    <td>{_html_escape(ve)}</td>
                    <td style="text-align:center">{al_html}</td>
                  </tr>""")
        else:
            for addr, old_val, new_val in rows:
                col = re.match(r"[A-Z]+", addr).group(0)
                q = questions.get(col, "")
                out.append(f"""
                  <tr>
                    <td><code>{addr}</code></td>
                    <td>{_html_escape(q)}</td>
                    <td>{_html_escape(old_val)}</td>
                    <td>{_html_escape(new_val)}</td>
                  </tr>""")
        return "\n".join(out)

    def html_rows_matrix(matrix):
        out = []
        for addr, q, vp, ve, statut, alerte in matrix:
            al = "" if alerte in ["", "Réponse normale", "Réponse humaine probable"] else badge(alerte, alert_kind(alerte))
            out.append(f"""
              <tr>
                <td><code>{addr}</code></td>
                <td>{_html_escape(q)}</td>
                <td>{_html_escape(vp)}</td>
                <td>{_html_escape(ve)}</td>
                <td>{_html_escape(statut)}</td>
                <td style="text-align:center">{al}</td>
              </tr>""")
        return "\n".join(out)

    html = f"""<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Rapport — { _html_escape(nom_fichier) }</title>
<style>
  :root{{--b:#e5e7eb;--bg:#f8fafc;--muted:#64748b}}
  html,body{{margin:0;padding:0;background:var(--bg);color:#0f172a;font-family:system-ui,-apple-system,Segoe UI,Roboto,Inter,sans-serif}}
  .wrap{{max-width:1200px;margin:0 auto;padding:20px}}
  .card{{background:#fff;border:1px solid var(--b);border-radius:14px;padding:14px 16px;margin:12px 0}}
  h1{{margin:.2rem 0 0;font-size:1.35rem}}
  h2{{margin:.2rem 0 .6rem;font-size:1.1rem}}
  .muted{{color:var(--muted)}}
  .pill{{display:inline-flex;align-items:center;flex-wrap:wrap;max-width:100%;white-space:normal;line-height:1.2;padding:.28rem .6rem;border-radius:999px;font-weight:800;color:#fff}}
  table{{border-collapse:collapse;width:100%;table-layout:fixed}}
  th,td{{border:1px solid #e2e8f0;padding:.55rem;vertical-align:top;word-break:break-word;overflow-wrap:anywhere;white-space:pre-wrap}}
  th{{background:#f1f5f9;text-align:left;position:sticky;top:0;z-index:1}}
  tbody tr:nth-child(odd){{background:#fcfcfd}}
  code{{background:#f1f5f9;padding:.1rem .35rem;border-radius:6px}}
  .grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:12px}}
  .kpi{{background:linear-gradient(180deg,#ffffff,#fbfdff);border:1px solid var(--b);border-radius:12px;padding:12px}}
  .kpi b{{font-size:1.05rem;font-weight:800;word-break:break-word;white-space:normal}}
  .small{{font-size:.92rem}}
  .table-note{{margin:.4rem 0 0}}
  .scroll-x{{overflow-x:auto}}
</style>
</head>
<body>
<div class="wrap">

<div class="card">
  <h1>📄 Rapport d'analyse</h1>
  <div class="muted small">{_html_escape(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))}</div>
</div>

<div class="grid">
  <div class="kpi"><div class="muted">Étudiant (Z1)</div><b>{_html_escape(id_cell)}</b></div>
  <div class="kpi"><div class="muted">Fichier</div><b>{_html_escape(nom_fichier)}</b></div>
  <div class="kpi"><div class="muted">Authenticité</div><b>{auth_badge}</b><div class="muted small" style="margin-top:.3rem">{_html_escape(authenticity_msg)}</div></div>
  <div class="kpi"><div class="muted">Hash Z2</div><b><code>{_html_escape(hash_cell)}</code></b></div>
  <div class="kpi"><div class="muted">Hash recalculé</div><b><code>{_html_escape(hash_calcule)}</code></b></div>
  <div class="kpi"><div class="muted">Tentative</div><b>#{attempt_index}</b></div>
</div>

<div class="card scroll-x">
  <h2>🔎 Modifications vs template</h2>
  <table>
    <thead><tr><th>Cellule</th><th>Question</th><th>Réponse</th><th>Alerte</th></tr></thead>
    <tbody>
      {html_rows_diff(diffs_vs_template, kind="template")}
    </tbody>
  </table>
  {"<div class='muted table-note'>Aucune</div>" if not diffs_vs_template else ""}
</div>

<div class="card scroll-x">
  <h2>🔁 Changements depuis la tentative précédente</h2>
  <table>
    <thead><tr><th>Cellule</th><th>Question</th><th>Avant</th><th>Maintenant</th></tr></thead>
    <tbody>
      {html_rows_diff(diffs_vs_prev, kind="previous")}
    </tbody>
  </table>
  {"<div class='muted table-note'>Aucun</div>" if not diffs_vs_prev else ""}
</div>

<div class="card scroll-x">
  <h2>🗺️ Grille complète (colonnes avec question)</h2>
  <table>
    <thead>
      <tr><th>Cellule</th><th>Question</th><th>Valeur template</th><th>Valeur étudiante</th><th>Statut</th><th>Alerte / IA</th></tr>
    </thead>
    <tbody>
      {html_rows_matrix(matrix_full)}
    </tbody>
  </table>
  <div class="muted table-note">Les colonnes sans intitulé de question sont ignorées (vide normal, non compté).</div>
</div>

<div class="grid">
  <div class="kpi"><div class="muted">Cells ≠ template</div><b>{total_changes_template}</b></div>
  <div class="kpi"><div class="muted">Changements vs dépôt précédent</div><b>{total_changes_prev}</b></div>
  <div class="kpi"><div class="muted">Réponses renseignées</div><b>{answered_count}</b></div>
  <div class="kpi"><div class="muted">Non répondu</div><b>{unanswered_count}</b></div>
  <div class="kpi"><div class="muted">Alertes</div><b>{total_alerts}</b></div>
</div>

</div>
</body>
</html>
"""

    path_html = os.path.join(rapport_folder, f"{base}_rapport.html")
    try:
        with open(path_html, "w", encoding="utf-8") as f:
            f.write(html)
    except Exception as e:
        return f"❌ Erreur écriture rapport HTML : {e}"

    return f"📁 Rapports générés : {path_txt} | {path_html}"

# =============== CLI (optionnel) ===============
if __name__ == "__main__":
    print("🔍 Analyse des copies en cours...\n")
    for fichier in os.listdir(copies_folder):
        if fichier.lower().endswith(".xlsx"):
            chemin = os.path.join(copies_folder, fichier)
            print(comparer_etudiant(chemin))
    print("\n✅ Analyse terminée. Rapports dans :", rapport_folder)
