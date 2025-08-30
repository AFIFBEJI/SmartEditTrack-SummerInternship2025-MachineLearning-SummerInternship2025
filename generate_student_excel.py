import openpyxl
import hashlib
import os
import csv
from openpyxl.styles import Protection

# === CONFIGURATION ===
template_path = "Fichier_Excel_Professeur_Template.xlsx"
students_csv = "liste_etudiants.csv"
output_folder = "copies_etudiants"
log_file = "hash_records.csv"

# === ASSURER DOSSIER DE SORTIE ===
os.makedirs(output_folder, exist_ok=True)

# === CHARGER LISTE DES ÉTUDIANTS ===
etudiants = []
with open(students_csv, newline='', encoding='utf-8') as f:
    reader = csv.DictReader(f)
    for row in reader:
        etudiants.append({
            "id": row["id"].strip(),
            "nom": row["nom"].strip(),
            "prenom": row["prenom"].strip()
        })

# === PRÉPARER FICHIER LOG HASHS ===
with open(log_file, "w", newline='', encoding='utf-8') as f:
    writer = csv.writer(f)
    writer.writerow(["id_etudiant", "nom", "prenom", "hash", "nom_fichier"])

    # === POUR CHAQUE ÉTUDIANT ===
    for etudiant in etudiants:
        id_etudiant = etudiant["id"]
        nom = etudiant["nom"]
        prenom = etudiant["prenom"]

        # Charger le modèle
        wb = openpyxl.load_workbook(template_path)
        ws = wb.active

        # Écrire ID étudiant en cellule Z1
        ws["Z1"] = id_etudiant

        # Calculer hash basé sur ID + contenu (pour unicité)
        contenu_concatene = id_etudiant.encode()

        for row in ws.iter_rows(values_only=True):
            for cell in row:
                if cell:
                    contenu_concatene += str(cell).encode()

        hash_etudiant = hashlib.sha256(contenu_concatene).hexdigest()

        # Écrire le hash en Z2
        ws["Z2"] = hash_etudiant

        # === AJOUT : Masquer la colonne Z ===
        ws.column_dimensions['Z'].hidden = True

        # === AJOUT : Protéger la feuille, mais laisser modifiable colonnes C à Y ===
        # Déverrouiller colonnes C(3) à Y(25)
        for row_cells in ws.iter_rows(min_row=2, max_row=ws.max_row, min_col=3, max_col=25):
            for cell in row_cells:
                cell.protection = Protection(locked=False)

        # Verrouiller la feuille
        ws.protection.sheet = True
        ws.protection.enable()

        # Sauvegarder le fichier personnalisé
        nom_fichier = f"{id_etudiant}_{nom}_{prenom}.xlsx"
        chemin_sortie = os.path.join(output_folder, nom_fichier)
        wb.save(chemin_sortie)

        # Écrire dans le log
        writer.writerow([id_etudiant, nom, prenom, hash_etudiant, nom_fichier])

        print(f"✅ Copie générée pour {id_etudiant} : {nom_fichier}")
