# app_prof.py

import os, json, re, csv, io
import streamlit as st
import streamlit.components.v1 as components  # pour afficher le HTML du rapport


from datetime import datetime

from compare_excels import comparer_etudiant
from auth import get_conn, list_submissions, change_password, import_students_csv
from hash_generator import generate_student_files_csv

# ---------------- Dossiers ----------------
DATA_DIR        = os.environ.get("DATA_DIR", "./")
CLASSES_ROOT    = os.path.join(DATA_DIR, "classes")
TEMPLATE_PATH   = os.path.join(DATA_DIR, "Fichier_Excel_Professeur_Template.xlsx")
DEPOSITS_DIR    = os.path.join(DATA_DIR, "copies_etudiants")         # dépôts étudiants (global)
REPORTS_DIR     = os.path.join(DATA_DIR, "rapports_etudiants")       # rapports d'analyse (global)
HISTORY_DIR     = os.path.join(DATA_DIR, "historique_reponses")      # snapshots par étudiant (JSON)
NOTIF_PATH      = os.path.join(DATA_DIR, "notif_depot.json")         # liste des fichiers déposés

os.makedirs(CLASSES_ROOT, exist_ok=True)
os.makedirs(DEPOSITS_DIR, exist_ok=True)
os.makedirs(REPORTS_DIR, exist_ok=True)
os.makedirs(HISTORY_DIR, exist_ok=True)
if not os.path.exists(NOTIF_PATH):
    with open(NOTIF_PATH, "w", encoding="utf-8") as f:
        json.dump([], f)

# ---------------- CSS ----------------
PROF_CSS = """
<style>
.block-container{ padding:14px 26px !important; }
html,body,[class*="css"]{ font-family:Inter,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif; }
.prof-head .title{ color:#0f172a; font-weight:900; font-size:1.6rem; letter-spacing:.2px; display:flex; align-items:baseline; gap:.5rem; margin:4px 0 2px; }
.prof-head .subtitle{ color:#475569; font-weight:600; margin:0 0 12px; }
.prof-head .badge{ background:linear-gradient(90deg,#7C4DFF,#3FA9F5); color:#fff; font-weight:800; padding:.14rem .55rem; border-radius:10px; }
.stTabs [role="tablist"]{ gap:.35rem; border-bottom:1px solid #e5e7eb; padding-bottom:4px; }
.stTabs [role="tab"]{ background:#f8fafc; color:#0f172a; border:1px solid #e5e7eb; border-bottom:none; padding:.5rem .8rem; border-radius:10px 10px 0 0; }
.stTabs [role="tab"][aria-selected="true"]{ background:linear-gradient(90deg,#eef2ff,#e0e7ff); color:#1e293b; font-weight:800; border-color:#c7d2fe; }
.card{ border:1px solid #e5e7eb; border-radius:14px; background:#ffffff; padding:14px 16px; }
.card + .card{ margin-top:12px; }
.note{ border-left:4px solid #7C4DFF; }
.stButton>button, .stDownloadButton>button{
  background:linear-gradient(90deg,#7C4DFF 0%, #3FA9F5 100%);
  color:white; font-weight:900; letter-spacing:.2px; border:0; border-radius:12px; padding:.72rem 1rem;
  box-shadow:0 14px 44px rgba(63,169,245,.28), 0 6px 12px rgba(124,77,255,.18);
  transition:transform .06s ease, box-shadow .15s ease, filter .15s ease;
}
.stButton>button:hover, .stDownloadButton>button:hover{
  transform:translateY(-1px); box-shadow:0 0 18px rgba(124,77,255,.32), 0 24px 60px rgba(63,169,245,.32); filter:saturate(1.05);
}
.danger > button{ background:linear-gradient(90deg,#ef4444,#f97316) !important; }
.ghost > button{ background:#f1f5f9 !important; color:#0f172a !important; box-shadow:none !important; }
.badge{ display:inline-block; padding:.15rem .5rem; border-radius:999px; font-weight:800; background:#f1f5f9; color:#334155; border:1px solid #e2e8f0; }
</style>
"""

# ---------------- Helpers classes ----------------
def _slugify(name: str) -> str:
    s = name.lower().strip()
    s = re.sub(r"[^a-z0-9\-_\s]", "", s)
    s = re.sub(r"\s+", "-", s)
    s = re.sub(r"-+", "-", s)
    return s or "classe"

def _class_dir(slug: str) -> str:
    return os.path.join(CLASSES_ROOT, slug)

def _class_meta_path(slug: str) -> str:
    return os.path.join(_class_dir(slug), "meta.json")

def _class_csv(slug: str) -> str:
    return os.path.join(_class_dir(slug), "liste_etudiants.csv")

def _class_copies_dir(slug: str) -> str:
    return os.path.join(_class_dir(slug), "copies_generees")

def _class_hash_log(slug: str) -> str:
    return os.path.join(_class_dir(slug), f"hash_records_{slug}.csv")

def _ensure_class(slug: str, name: str = None):
    os.makedirs(_class_dir(slug), exist_ok=True)
    os.makedirs(_class_copies_dir(slug), exist_ok=True)
    if name:
        with open(_class_meta_path(slug), "w", encoding="utf-8") as f:
            json.dump({"name": name, "slug": slug}, f, ensure_ascii=False, indent=2)

def _load_classes():
    out = []
    for slug in sorted(os.listdir(CLASSES_ROOT)):
        d = _class_dir(slug)
        if not os.path.isdir(d):
            continue
        name = slug
        meta = _class_meta_path(slug)
        if os.path.exists(meta):
            try:
                with open(meta, "r", encoding="utf-8") as f:
                    name = json.load(f).get("name", slug)
            except Exception:
                pass
        out.append({"slug": slug, "name": name})
    return out

# ---------------- Notifications & filtrage par classe ----------------
def _load_notifs():
    if os.path.exists(NOTIF_PATH):
        with open(NOTIF_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return []

def _save_notifs(lst):
    with open(NOTIF_PATH, "w", encoding="utf-8") as f:
        json.dump(lst, f)

def _cleanup_notifs():
    notifs = _load_notifs()
    valid = [f for f in notifs if os.path.exists(os.path.join(DEPOSITS_DIR, f))]
    if len(valid) != len(notifs):
        _save_notifs(valid)
    return valid

def _user_class(user_id: str) -> str | None:
    conn = get_conn()
    row = conn.execute("SELECT class_name FROM users WHERE id=?", (user_id,)).fetchone()
    return row[0] if row and row[0] else None

def _id_from_deposit(filename: str) -> str | None:
    # dépôt = "YYYYmmdd_HHMMSS__ETUD028_Amara_Ali.xlsx"
    try:
        after = filename.split("__", 1)[1]
        return after.split("_", 1)[0]
    except Exception:
        return None

def _filter_deposits_by_class(target_class: str):
    files = _cleanup_notifs()
    if not target_class:
        return files
    kept = []
    for fn in files:
        uid = _id_from_deposit(fn)
        if not uid:
            continue
        if _user_class(uid) == target_class:
            kept.append(fn)
    return kept

# ---------------- Historique helpers ----------------
def _history_list():
    """Retourne une liste d'objets: {id, path, count, last_ts} pour chaque JSON d'historique."""
    entries = []
    for fname in sorted(os.listdir(HISTORY_DIR)):
        if not fname.lower().endswith(".json"):
            continue
        sid = os.path.splitext(fname)[0]
        path = os.path.join(HISTORY_DIR, fname)
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f) or []
        except Exception:
            data = []
        count = len(data)
        last_ts = data[-1].get("timestamp") if count else "-"
        entries.append({"id": sid, "path": path, "count": count, "last_ts": last_ts})
    return entries

def _delete_history(student_id: str) -> bool:
    """Supprime le fichier d'historique d'un étudiant."""
    path = os.path.join(HISTORY_DIR, f"{student_id}.json")
    if os.path.exists(path):
        try:
            os.remove(path)
            return True
        except Exception:
            return False
    return False

def _delete_all_history() -> int:
    """Supprime tous les historiques. Retourne le nombre de fichiers supprimés."""
    n = 0
    for fname in os.listdir(HISTORY_DIR):
        if fname.lower().endswith(".json"):
            try:
                os.remove(os.path.join(HISTORY_DIR, fname))
                n += 1
            except Exception:
                pass
    return n

# ---------------- Vue PROF ----------------
def run(user):
    # state pour afficher le dernier rapport analysé sans le perdre après rerun
    st.session_state.setdefault("report_text", None)
    st.session_state.setdefault("report_txt_path", None)
    st.session_state.setdefault("report_html_path", None)
    st.session_state.setdefault("report_file", None)

    st.markdown(PROF_CSS, unsafe_allow_html=True)
    st.markdown(
        f"""
        <div class="prof-head">
          <div class="title">🧑‍🏫 Espace Professeur — <span class="badge">{user['id']}</span></div>
          <div class="subtitle">Gérez vos classes, générez les copies, recevez les dépôts et analysez.</div>
        </div>
        """,
        unsafe_allow_html=True
    )

    tabs = st.tabs(["📚 Classes", "📂 Dépôts & Rapports", "📈 Historique", "👤 Compte"])

    # -------- 📚 Classes --------
    with tabs[0]:
        st.markdown("### Gestion des classes")
        left, right = st.columns([1.1, 1.9])

        with left:
            st.markdown('<div class="card note"><b>Créer une classe</b></div>', unsafe_allow_html=True)
            name = st.text_input("Nom de la classe (ex. 3A61)")
            if st.button("Créer la classe", use_container_width=True):
                if not name.strip():
                    st.error("Nom requis.")
                else:
                    slug = _slugify(name)
                    _ensure_class(slug, name.strip())
                    st.success(f"✅ Classe créée : {name} (slug: {slug})")
                    st.rerun()

            st.markdown('<div class="card" style="margin-top:12px"><b>Classes existantes</b></div>', unsafe_allow_html=True)
            classes = _load_classes()
            if not classes:
                st.info("Aucune classe pour l’instant.")
            else:
                for c in classes:
                    st.write(f"• **{c['name']}** — slug: `{c['slug']}`")

        with right:
            classes = _load_classes()
            if not classes:
                st.info("Crée d’abord une classe.")
            else:
                st.markdown('<div class="card note"><b>Configurer / synchroniser une classe</b></div>', unsafe_allow_html=True)
                choices = {c["slug"]: c["name"] for c in classes}
                chosen = st.selectbox("Classe :", list(choices.keys()), format_func=lambda s: choices[s])

                # Upload CSV
                up = st.file_uploader("Uploader liste_etudiants.csv (colonnes: id, nom, prenom)", type=["csv"])
                if up is not None:
                    _ensure_class(chosen)
                    csv_path = _class_csv(chosen)
                    with open(csv_path, "wb") as f:
                        f.write(up.getbuffer())
                    st.success(f"✅ CSV enregistré : {csv_path}")

                colA, colB, colC = st.columns(3)
                with colA:
                    if st.button("🔄 Synchroniser vers la BD"):
                        csv_path = _class_csv(chosen)
                        if not os.path.exists(csv_path):
                            st.error("Aucun CSV pour cette classe.")
                        else:
                            created, updated = import_students_csv(get_conn(), csv_path, choices[chosen])
                            st.success(f"✅ Synchro BD : {created} créé(s), {updated} mis à jour.")
                with colB:
                    if st.button("⚡ Générer les copies"):
                        csv_path = _class_csv(chosen)
                        if not os.path.exists(csv_path):
                            st.error("Aucun CSV pour cette classe.")
                        elif not os.path.exists(TEMPLATE_PATH):
                            st.error("Template introuvable.")
                        else:
                            out_dir = _class_copies_dir(chosen)
                            log_path = _class_hash_log(chosen)
                            generate_student_files_csv(
                                input_csv=csv_path,
                                template_path=TEMPLATE_PATH,
                                output_folder=out_dir,
                                log_file=log_path
                            )
                            st.success(f"✅ Copies générées dans : {out_dir}")
                            st.info(f"Log des hashs : {log_path}")
                with colC:
                    st.markdown("**Chemins**")
                    st.caption(f"CSV : {_class_csv(chosen)}")
                    st.caption(f"Copies : {_class_copies_dir(chosen)}")
                    st.caption(f"Hash log : {_class_hash_log(chosen)}")

    # -------- 📂 Dépôts & Rapports --------
    with tabs[1]:
        classes = _load_classes()
        class_filter = st.selectbox("Filtrer par classe :", ["(toutes)"] + [c["name"] for c in classes])
        selected_class = None if class_filter == "(toutes)" else class_filter

        files = _filter_deposits_by_class(selected_class)
        st.markdown(f'<div class="card"><strong>🔔 Dépôts reçus :</strong> {len(files)}</div>', unsafe_allow_html=True)

        if not files:
            st.markdown('<div class="card">Aucun dépôt pour cette sélection.</div>', unsafe_allow_html=True)
            st.session_state.update(report_text=None, report_txt_path=None, report_html_path=None, report_file=None)
        else:
            left, right = st.columns([1.05, 1.95])

            with left:
                st.markdown('<div class="card">', unsafe_allow_html=True)
                fsel = st.selectbox("Choisir un dépôt :", files, index=0, key="deposit_select")
                if fsel:
                    p = os.path.join(DEPOSITS_DIR, fsel)
                    if os.path.exists(p):
                        with open(p, "rb") as fdep:
                            st.download_button(
                                "📥 Télécharger la copie sélectionnée",
                                fdep, file_name=fsel,
                                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                use_container_width=True
                            )
                    else:
                        st.error("❌ Fichier déposé introuvable.")

                # Boutons d'analyse
                col1, col2 = st.columns(2)
                with col1:
                    if st.button("🔍 Analyser ce dépôt", use_container_width=True):
                        if not fsel:
                            st.warning("Sélectionne un dépôt d'abord.")
                        else:
                            target = os.path.join(DEPOSITS_DIR, fsel)
                            if os.path.exists(target):
                                res = comparer_etudiant(target)
                                st.success(res)
                                txt_path, html_path = None, None
                                try:
                                    if ": " in res:
                                        after = res.split(": ", 1)[1].strip()
                                        parts = [p.strip() for p in after.split("|")]
                                        if len(parts) >= 1:
                                            txt_path = parts[0]
                                        if len(parts) >= 2:
                                            html_path = parts[1]
                                except Exception:
                                    pass

                                st.session_state.report_text = None
                                st.session_state.report_txt_path = None
                                if txt_path and os.path.exists(txt_path):
                                    try:
                                        with open(txt_path, "r", encoding="utf-8") as fr:
                                            st.session_state.report_text = fr.read()
                                        st.session_state.report_txt_path = txt_path
                                        st.session_state.report_file = os.path.basename(txt_path)
                                    except Exception:
                                        pass

                                st.session_state.report_html_path = html_path if html_path and os.path.exists(html_path) else None
                            else:
                                st.error("Fichier sélectionné introuvable.")
                with col2:
                    if st.button("🧪 Analyser tous les dépôts filtrés", use_container_width=True):
                        with st.spinner("Analyse en cours..."):
                            for f in files:
                                p = os.path.join(DEPOSITS_DIR, f)
                                if os.path.exists(p):
                                    r = comparer_etudiant(p)
                                    with st.expander(f"Rapport — {f}", expanded=False):
                                        st.text(r)
                                else:
                                    st.warning(f"Fichier manquant : {f}")

                st.divider()
                if st.button("📭 Réinitialiser les notifications", use_container_width=True):
                    _save_notifs([])
                    st.success("✅ Notifications réinitialisées.")
                    st.session_state.update(report_text=None, report_txt_path=None, report_html_path=None, report_file=None)
                st.markdown('</div>', unsafe_allow_html=True)

            with right:
                st.markdown('<div class="card">', unsafe_allow_html=True)
                st.subheader("📑 Rapport d'analyse")

                if st.session_state.report_html_path and os.path.exists(st.session_state.report_html_path):
                    html_height = st.slider("Hauteur d'affichage du rapport (px)", 600, 2200, 1100, 50)
                    with open(st.session_state.report_html_path, "r", encoding="utf-8") as fh:
                        components.html(fh.read(), height=html_height, scrolling=True)
                    with open(st.session_state.report_html_path, "rb") as fb:
                        st.download_button("📥 Télécharger le rapport HTML",
                                           fb,
                                           file_name=os.path.basename(st.session_state.report_html_path),
                                           use_container_width=True)

                elif st.session_state.report_text:
                    st.text_area("Contenu du rapport (TXT) :", value=st.session_state.report_text, height=420)
                    if st.session_state.report_txt_path and os.path.exists(st.session_state.report_txt_path):
                        with open(st.session_state.report_txt_path, "rb") as fb:
                            st.download_button("📥 Télécharger le rapport TXT",
                                               fb,
                                               file_name=st.session_state.report_file or "rapport.txt",
                                               use_container_width=True)
                else:
                    st.info("Sélectionne un dépôt puis clique sur **🔍 Analyser ce dépôt** pour générer et afficher le rapport.")
                st.markdown('</div>', unsafe_allow_html=True)

    # -------- 📈 Historique --------
    with tabs[2]:
        conn = get_conn()
        subs = list_submissions(conn)
        classes = _load_classes()
        names = [c["name"] for c in classes]
        chosen = st.selectbox("Filtrer historique par classe :", ["(toutes)"] + names)
        selected_class = None if chosen == "(toutes)" else chosen

        def _row_class(uid: str) -> str:
            row = conn.execute("SELECT class_name FROM users WHERE id=?", (uid,)).fetchone()
            return row[0] if row and row[0] else ""

        filtered = []
        for r in subs:
            cls = _row_class(r["user_id"])
            if (not selected_class) or (cls == selected_class):
                filtered.append({
                    "date": r["submitted_at"],
                    "user_id": r["user_id"],
                    "classe": cls,
                    "fichier": r["filename"],
                    "statut": r["status"]
                })

        st.write(f"🗂️ {len(filtered)} dépôt(s) pour la sélection")
        if filtered:
            import pandas as pd
            st.dataframe(pd.DataFrame(filtered), use_container_width=True)
        else:
            st.markdown('<div class="card">Aucun dépôt.</div>', unsafe_allow_html=True)

        st.markdown("---")
        st.markdown("### 🕓 Gestion de l’historique des réponses (snapshots)")

        # Tableau des historiques présents sur disque
        entries = _history_list()
        if not entries:
            st.info("Aucun historique enregistré pour le moment.")
        else:
            import pandas as pd
            df_hist = pd.DataFrame(entries)[["id", "count", "last_ts"]].rename(
                columns={"id":"ID étudiant", "count":"# snapshots", "last_ts":"Dernier enregistrement"}
            )
            st.dataframe(df_hist, use_container_width=True)

            # Sélection d'un étudiant pour opérations
            sid_choices = ["(choisir)"] + [e["id"] for e in entries]
            colA, colB = st.columns([1, 1])
            with colA:
                sid = st.selectbox("Sélectionner un étudiant :", sid_choices)
                if sid != "(choisir)":
                    # boutons: Télécharger JSON, Supprimer l'historique de cet étudiant
                    p = os.path.join(HISTORY_DIR, f"{sid}.json")
                    if os.path.exists(p):
                        with open(p, "rb") as fb:
                            st.download_button("⬇️ Télécharger l'historique (JSON)", fb, file_name=f"{sid}_historique.json")

                    st.write(" ")
                    conf = st.text_input(f"Confirmer la suppression de l'historique de **{sid}** (tape {sid})")
                    btn_class = "danger" if conf == sid else "ghost"
                    if st.button("🗑️ Supprimer l'historique de cet étudiant", key="del_one", use_container_width=True, type="primary"):
                        if conf != sid:
                            st.warning("Pour confirmer, tape exactement l'ID de l'étudiant.")
                        else:
                            ok = _delete_history(sid)
                            if ok:
                                st.success(f"Historique de {sid} supprimé.")
                                st.rerun()
                            else:
                                st.error("Suppression impossible (fichier absent ou verrouillé).")

            with colB:
                st.markdown("**Suppression globale**")
                conf_all = st.text_input("Écris : SUPPRIMER TOUT", placeholder="SUPPRIMER TOUT")
                if st.button("🧨 Vider tous les historiques", key="del_all", use_container_width=True, type="primary"):
                    if conf_all.strip().upper() != "SUPPRIMER TOUT":
                        st.warning("Confirmation incorrecte. Tape : SUPPRIMER TOUT")
                    else:
                        n = _delete_all_history()
                        st.success(f"{n} fichier(s) d'historique supprimé(s).")
                        st.rerun()

        st.caption("ℹ️ Ces actions ne touchent pas la base des dépôts ni le CSV des modifications. Elles ne suppriment que les snapshots JSON.")

    # -------- 👤 Compte --------
    with tabs[3]:
        st.subheader("🔒 Mettre à jour mon mot de passe (admin)")
        cur = st.text_input("Mot de passe actuel", type="password")
        new1 = st.text_input("Nouveau mot de passe", type="password")
        new2 = st.text_input("Confirmer le nouveau mot de passe", type="password")
        if st.button("Mettre à jour mon mot de passe"):
            if not cur or not new1 or not new2:
                st.error("Champs incomplets.")
            elif new1 != new2:
                st.error("La confirmation ne correspond pas.")
            elif len(new1) < 8:
                st.error("Min. 8 caractères.")
            else:
                ok = change_password(get_conn(), user["id"], cur, new1)
                st.success("✅ Mot de passe mis à jour.") if ok else st.error("Mot de passe actuel incorrect.")
