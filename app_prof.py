# app_prof.py — Espace professeur (classes, copies, dépôts, rapports) — version .xlsm
import os, json, re, shutil, glob
import streamlit as st
import streamlit.components.v1 as components
from datetime import datetime

# --- Supabase (optionnel : on continue même si non dispo)
try:
    # helpers présents dans ton projet (à compléter dans supa.py)
    from supa import upload_file, delete_prefix
    _SUPA_OK = True
except Exception:
    upload_file = None
    delete_prefix = None
    _SUPA_OK = False

from compare_excels import comparer_etudiant
from auth import get_conn, list_submissions, change_password, import_students_csv
from hash_generator import generate_student_files_csv

# ---------------- Dossiers & chemins ----------------
DATA_DIR        = os.environ.get("DATA_DIR", "/tmp")  # /tmp sur Render free
CLASSES_ROOT    = os.path.join(DATA_DIR, "classes")
TEMPLATE_PATH   = os.path.join(DATA_DIR, "Fichier_Excel_Professeur_Template.xlsm")  # <<< .xlsm
DEPOSITS_DIR    = os.path.join(DATA_DIR, "copies_etudiants")
REPORTS_DIR     = os.path.join(DATA_DIR, "rapports_etudiants")
HISTORY_DIR     = os.path.join(DATA_DIR, "historique_reponses")
NOTIF_PATH      = os.path.join(DATA_DIR, "notif_depot.json")

# Template “bundlé” dans le repo (même dossier que ce fichier)
BUNDLED_TEMPLATE = os.path.join(os.path.dirname(__file__), "Fichier_Excel_Professeur_Template.xlsm")

# Création des dossiers
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(CLASSES_ROOT, exist_ok=True)
os.makedirs(DEPOSITS_DIR, exist_ok=True)
os.makedirs(REPORTS_DIR, exist_ok=True)
os.makedirs(HISTORY_DIR, exist_ok=True)
if not os.path.exists(NOTIF_PATH):
    with open(NOTIF_PATH, "w", encoding="utf-8") as f:
        json.dump([], f)

# Auto-provision du template au démarrage (si absent dans DATA_DIR)
try:
    if (not os.path.exists(TEMPLATE_PATH)) and os.path.exists(BUNDLED_TEMPLATE):
        shutil.copyfile(BUNDLED_TEMPLATE, TEMPLATE_PATH)
except Exception:
    pass  # l’UI affichera “Template introuvable”

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
.small{ font-size:.92rem; color:#475569; }
</style>
"""

# ---------------- Helpers ----------------
def _slugify(name: str) -> str:
    s = name.lower().strip()
    s = re.sub(r"[^a-z0-9\-_\s]", "", s)
    s = re.sub(r"\s+", "-", s)
    s = re.sub(r"-+", "-", s)
    return s or "classe"

def _password_errors(pwd: str) -> list[str]:
    """Règles: ≥8, au moins 1 majuscule, 1 minuscule."""
    err = []
    if len(pwd or "") < 8: err.append("au moins 8 caractères")
    if not re.search(r"[A-Z]", pwd or ""): err.append("au moins une majuscule")
    if not re.search(r"[a-z]", pwd or ""): err.append("au moins une minuscule")
    return err

def _class_dir(slug: str) -> str: return os.path.join(CLASSES_ROOT, slug)
def _class_meta_path(slug: str) -> str: return os.path.join(_class_dir(slug), "meta.json")
def _class_csv(slug: str) -> str: return os.path.join(_class_dir(slug), "liste_etudiants.csv")
def _class_copies_dir(slug: str) -> str: return os.path.join(_class_dir(slug), "copies_generees")
def _class_hash_log(slug: str) -> str: return os.path.join(_class_dir(slug), f"hash_records_{slug}.csv")

def _ensure_class(slug: str, name: str = None):
    os.makedirs(_class_dir(slug), exist_ok=True)
    os.makedirs(_class_copies_dir(slug), exist_ok=True)
    if name:
        with open(_class_meta_path(slug), "w", encoding="utf-8") as f:
            json.dump({"name": name, "slug": slug}, f, ensure_ascii=False, indent=2)

def _load_classes():
    """Charge d’abord depuis le système de fichiers. Secours : si vide, lit DISTINCT class_name depuis la BD."""
    out = []
    # 1) FS
    try:
        for slug in sorted(os.listdir(CLASSES_ROOT)):
            d = os.path.join(CLASSES_ROOT, slug)
            if not os.path.isdir(d):
                continue
            name = slug
            meta = os.path.join(d, "meta.json")
            if os.path.exists(meta):
                try:
                    with open(meta, "r", encoding="utf-8") as f:
                        name = json.load(f).get("name", slug)
                except Exception:
                    pass
            out.append({"slug": slug, "name": name})
    except Exception:
        out = []

    # 2) Secours BD
    if not out:
        try:
            conn = get_conn()
            rows = conn.execute("""
                SELECT DISTINCT class_name
                FROM users
                WHERE class_name IS NOT NULL AND class_name <> ''
                ORDER BY 1
            """).fetchall()
            out = [{"slug": re.sub(r"[^a-z0-9\\-]+","-", (s or "").lower()).strip("-"), "name": s}
                   for (s,) in rows if s]
        except Exception:
            pass
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
    path = os.path.join(HISTORY_DIR, f"{student_id}.json")
    if os.path.exists(path):
        try:
            os.remove(path); return True
        except Exception:
            return False
    return False

def _delete_all_history() -> int:
    n = 0
    for fname in os.listdir(HISTORY_DIR):
        if fname.lower().endswith(".json"):
            try:
                os.remove(os.path.join(HISTORY_DIR, fname)); n += 1
            except Exception:
                pass
    return n

# ---------------- Suppression de classe ----------------
def _delete_class_local(slug: str) -> tuple[bool, str]:
    """Efface le dossier local /tmp/classes/<slug> entièrement."""
    try:
        shutil.rmtree(_class_dir(slug), ignore_errors=True)
        return True, f"Dossier local supprimé: {_class_dir(slug)}"
    except Exception as e:
        return False, f"Erreur suppression locale: {e}"

def _delete_class_supabase(slug: str) -> list[str]:
    """Supprime les objets dans Storage: copies/<slug>/, classes/<slug>/, backups/<slug>/ (si existe)."""
    logs = []
    if not (_SUPA_OK and callable(delete_prefix)):
        logs.append("Supabase indisponible: saut de la suppression Storage.")
        return logs
    for prefix in [f"copies/{slug}/", f"classes/{slug}/", f"backups/{slug}/"]:
        try:
            ok = delete_prefix(prefix)  # True si au moins un objet supprimé
            logs.append(f"Storage • rm -r {prefix} : {'OK' if ok else 'rien à supprimer'}")
        except Exception as e:
            logs.append(f"Storage • rm -r {prefix} : erreur {e}")
    return logs

def _delete_class_db(class_name: str) -> list[str]:
    """Optionnel: purge BD (users & submissions) pour class_name."""
    logs = []
    try:
        conn = get_conn()
        # submissions liées
        conn.execute("""
            DELETE FROM submissions
            WHERE user_id IN (SELECT id FROM users WHERE class_name = ?)
        """, (class_name,))
        n1 = conn.total_changes
        # comptes
        conn.execute("DELETE FROM users WHERE class_name = ?", (class_name,))
        n2 = conn.total_changes - n1
        conn.commit()
        logs.append(f"BD • submissions supprimées: {n1}")
        logs.append(f"BD • users supprimés: {n2}")
    except Exception as e:
        logs.append(f"BD • erreur purge: {e}")
    return logs

# ---------------- Vue PROF ----------------
def run(user):
    # State d’affichage rapport
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

                # Upload CSV étudiants
                up = st.file_uploader(
                    "Uploader liste_etudiants.csv (colonnes: id, nom, prenom, email)",
                    type=["csv"]
                )
                if up is not None:
                    _ensure_class(chosen)
                    csv_path = _class_csv(chosen)
                    with open(csv_path, "wb") as f:
                        f.write(up.getbuffer())
                    st.success(f"✅ CSV enregistré : {csv_path}")

                # Upload template .xlsm
                st.markdown('<div class="small">Template actuel : '
                            + (f"<code>{TEMPLATE_PATH}</code>" if os.path.exists(TEMPLATE_PATH) else "<b>introuvable</b>")
                            + "</div>", unsafe_allow_html=True)
                tpl_up = st.file_uploader("Uploader le Fichier_Excel_Professeur_Template.xlsm", type=["xlsm"], key="tpl_up")
                if tpl_up is not None:
                    try:
                        with open(TEMPLATE_PATH, "wb") as f:
                            f.write(tpl_up.getbuffer())
                        st.success(f"✅ Template enregistré : {TEMPLATE_PATH}")
                    except Exception as e:
                        st.error(f"❌ Échec enregistrement template : {e}")

                colA, colB, colC = st.columns(3)

                # ======= SYNCHRO + EMAILS =======
                with colA:
                    st.markdown("**Synchroniser vers la BD**")
                    csv_path = _class_csv(chosen)
                    do_reset = st.checkbox(
                        "Réinitialiser le mot de passe pour les étudiants existants",
                        value=False,
                        help="Réécrit le mot de passe initial (ID ou valeur fixée) pour tous les élèves du CSV."
                    )
                    send_creds = st.checkbox(
                        "Envoyer identifiants par email",
                        value=False,
                        help="Envoie aux nouveaux. Si 'Réinitialiser' est coché, envoie à tous."
                    )
                    login_url = st.text_input(
                        "URL de connexion à insérer dans l'email",
                        value=os.getenv("APP_BASE_URL", "")
                    )

                    # --- ⚙️ DIAGNOSTIC EMAIL (voir les variables et tester un envoi) ---
                    with st.expander("⚙️ Diagnostic email"):
                        st.write("SMTP_HOST:", os.getenv("SMTP_HOST"))
                        st.write("SMTP_USER:", os.getenv("SMTP_USER"))
                        st.write("SMTP_PORT:", os.getenv("SMTP_PORT"))
                        st.write("SMTP_TLS:", os.getenv("SMTP_TLS"))
                        st.write("SMTP_FROM:", os.getenv("SMTP_FROM"))
                        st.write("SMTP_PASS présent ?:", "oui" if os.getenv("SMTP_PASS") else "non")
                        st.write("APP_BASE_URL:", os.getenv("APP_BASE_URL"))
                        st.write("RESEND_API_KEY présent ?:", "oui" if os.getenv("RESEND_API_KEY") else "non")

                        test_to = st.text_input(
                            "Tester un envoi (Mailtrap Sandbox) vers :",
                            "etud001@example.com",
                            key="diag_to"
                        )
                        if st.button("📤 Tester l'envoi maintenant", key="diag_send"):
                            try:
                                from mailer import send_credentials_email as _send
                                ok = _send(test_to, "TEST123", "TEST123", login_url or "http://localhost:8501")
                                if ok:
                                    st.success("✅ Envoi OK (regarde la boîte Mailtrap)")
                                else:
                                    st.error("❌ Échec d'envoi : variables SMTP manquantes ou refusées par le serveur.")
                            except Exception as e:
                                st.error(f"Exception Python pendant l'envoi: {e}")
                    # -------------------------------------------------------------------

                    if st.button("🔄 Synchroniser vers la BD", use_container_width=True, key="btn_sync_db"):
                        if not os.path.exists(csv_path):
                            st.error("Aucun CSV pour cette classe.")
                        else:
                            # importante: version d'import qui gère l'email & l'envoi
                            stats = import_students_csv(
                                get_conn(), csv_path, choices[chosen],
                                default_pwd="id",
                                reset_password=do_reset,
                                send_email=send_creds,
                                login_url=login_url or None
                            )
                            st.success(f"✅ Synchro : {stats['created']} créé(s), {stats['updated']} MAJ.")
                            if send_creds:
                                st.info(f"✉️ Emails envoyés : {stats.get('emailed', 0)}")
                # ================================

                # ======= GÉNÉRER =======
                with colB:
                    if st.button("⚡ Générer les copies"):
                        csv_path = _class_csv(chosen)
                        if not os.path.exists(csv_path):
                            st.error("Aucun CSV pour cette classe.")
                        elif not os.path.exists(TEMPLATE_PATH):
                            st.error("Template introuvable. Charge-le via l’uploader ci-dessus ou place-le dans le repo.")
                        else:
                            out_dir = _class_copies_dir(chosen)
                            log_path = _class_hash_log(chosen)
                            try:
                                # 1) Génération locale
                                generate_student_files_csv(
                                    input_csv=csv_path,
                                    template_path=TEMPLATE_PATH,   # .xlsm
                                    output_folder=out_dir,
                                    log_file=log_path
                                )
                                st.success(f"✅ Copies générées dans : {out_dir}")
                                st.info(f"Log des hashs : {log_path}")

                                # 2) Upload Supabase (si dispo)
                                if _SUPA_OK and callable(upload_file):
                                    uploaded = 0
                                    for fname in os.listdir(out_dir):
                                        if fname.lower().endswith(".xlsm"):
                                            local = os.path.join(out_dir, fname)
                                            remote = f"copies/{chosen}/{fname}"
                                            ct = "application/vnd.ms-excel.sheet.macroEnabled.12"
                                            upload_file(local, remote, content_type=ct)
                                            uploaded += 1
                                    # CSV élèves + log hash
                                    try:
                                        upload_file(csv_path, f"classes/{chosen}/liste_etudiants.csv", content_type="text/csv")
                                    except Exception:
                                        pass
                                    try:
                                        upload_file(log_path, f"classes/{chosen}/{os.path.basename(log_path)}", content_type="text/csv")
                                    except Exception:
                                        pass
                                    st.info(f"☁️ {uploaded} copie(s) envoyée(s) dans Supabase (copies/{chosen}/).")
                                else:
                                    st.caption("ℹ️ Upload Supabase désactivé (module indisponible).")

                            except Exception as e:
                                st.error(f"❌ Erreur génération copies : {e}")
                # ========================

                with colC:
                    st.markdown("**Chemins**")
                    st.caption(f"CSV : {_class_csv(chosen)}")
                    st.caption(f"Copies : {_class_copies_dir(chosen)}")
                    st.caption(f"Hash log : {_class_hash_log(chosen)}")
                    st.caption(f"Template : {TEMPLATE_PATH}")

                st.divider()

                # ======= SUPPRIMER LA CLASSE =======
                st.markdown("### 🗑️ Supprimer cette classe")
                col1, col2, col3 = st.columns([1,1,1])
                with col1:
                    also_storage = st.checkbox("Supprimer sur Supabase (Storage)", value=True, help="Efface copies/<slug>/ et classes/<slug>/")
                with col2:
                    also_db = st.checkbox("Purger la base (users + submissions)", value=False,
                                          help="Supprime utilisateurs et dépôts liés à cette classe dans la BD.")
                with col3:
                    confirm = st.text_input("Confirme en tapant le *slug* :", placeholder=chosen)

                if st.button("🧨 Supprimer la classe", key="delete_class", type="primary"):
                    if confirm.strip() != chosen:
                        st.warning(f"Pour confirmer, tape exactement le slug : {chosen}")
                    else:
                        logs = []
                        ok_local, msg_local = _delete_class_local(chosen)
                        logs.append(msg_local)

                        if also_storage:
                            logs += _delete_class_supabase(chosen)

                        if also_db:
                            class_name = dict((v,k) for k,v in {c['slug']:c['name'] for c in _load_classes()}.items()).get(chosen, chosen)
                            logs += _delete_class_db(class_name)

                        # Nettoyer éventuels fichiers notifs obsolètes
                        _save_notifs([f for f in _load_notifs() if not f.startswith(chosen)])

                        st.success("Suppression terminée.")
                        with st.expander("Détails"):
                            for line in logs:
                                st.write("• " + line)
                        st.rerun()
                # ===================================

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
                                mime="application/vnd.ms-excel.sheet.macroEnabled.12",
                                use_container_width=True
                            )
                    else:
                        st.error("❌ Fichier déposé introuvable.")

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
                                        if len(parts) >= 1: txt_path = parts[0]
                                        if len(parts) >= 2: html_path = parts[1]
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

        entries = _history_list()
        if not entries:
            st.info("Aucun historique enregistré pour le moment.")
        else:
            import pandas as pd
            df_hist = pd.DataFrame(entries)[["id", "count", "last_ts"]].rename(
                columns={"id":"ID étudiant", "count":"# snapshots", "last_ts":"Dernier enregistrement"}
            )
            st.dataframe(df_hist, use_container_width=True)

            sid_choices = ["(choisir)"] + [e["id"] for e in entries]
            colA, colB = st.columns([1, 1])
            with colA:
                sid = st.selectbox("Sélectionner un étudiant :", sid_choices)
                if sid != "(choisir)":
                    p = os.path.join(HISTORY_DIR, f"{sid}.json")
                    if os.path.exists(p):
                        with open(p, "rb") as fb:
                            st.download_button("⬇️ Télécharger l'historique (JSON)", fb, file_name=f"{sid}_historique.json")

                    st.write(" ")
                    conf = st.text_input(f"Confirmer la suppression de l'historique de **{sid}** (tape {sid})")
                    if st.button("🗑️ Supprimer l'historique de cet étudiant", key="del_one", use_container_width=True, type="primary"):
                        if conf != sid:
                            st.warning("Pour confirmer, tape exactement l'ID de l'étudiant.")
                        else:
                            ok = _delete_history(sid)
                            if ok:
                                st.success(f"Historique de {sid} supprimé."); st.rerun()
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
                        st.success(f"{n} fichier(s) d'historique supprimé(s)."); st.rerun()

        st.caption("ℹ️ Ces actions ne touchent pas la base des dépôts ni le CSV des modifications. Elles ne suppriment que les snapshots JSON.")

    # -------- 👤 Compte --------
    with tabs[3]:
        st.subheader("🔒 Mettre à jour mon mot de passe (admin/prof)")
        cur = st.text_input("Mot de passe actuel", type="password")
        new1 = st.text_input("Nouveau mot de passe", type="password")
        new2 = st.text_input("Confirmer le nouveau mot de passe", type="password")

        if st.button("Mettre à jour mon mot de passe", key="btn_update_pwd_admin"):
            if not cur or not new1 or not new2:
                st.error("Champs incomplets.")
            elif new1 != new2:
                st.error("La confirmation ne correspond pas.")
            else:
                errs = _password_errors(new1)
                if errs:
                    st.error("Le mot de passe doit contenir : " + ", ".join(errs) + ".")
                else:
                    ok = change_password(get_conn(), user["id"], cur, new1)
                    if ok:
                        st.success("✅ Mot de passe mis à jour.")
                    else:
                        st.error("Mot de passe actuel incorrect.")
