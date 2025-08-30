# hash_generator.py
import openpyxl
import hashlib
import os
import csv
from openpyxl.styles import Protection

def generate_student_files_csv(input_csv="liste_etudiants.csv",
                               template_path="Fichier_Excel_Professeur_Template.xlsx",
                               output_folder="copies_generees",
                               log_file="hash_records.csv"):
    """
    Génère les copies à partir d'un CSV (colonnes: id, nom, prenom),
    remplit Z1/Z2, protège la feuille, log la table des hashs.
    """
    os.makedirs(output_folder, exist_ok=True)

    # Lire les étudiants (détecte le séparateur)
    etudiants = []
    with open(input_csv, newline='', encoding='utf-8') as f:
        try:
            sample = f.read(2048)
            f.seek(0)
            dialect = csv.Sniffer().sniff(sample) if sample else csv.excel
        except csv.Error:
            dialect = csv.excel
        reader = csv.DictReader(f, dialect=dialect)
        for row in reader:
            if not row.get("id"):
                continue
            etudiants.append({
                "id": row["id"].strip(),
                "nom": (row.get("nom") or "").strip(),
                "prenom": (row.get("prenom") or "").strip()
            })

    with open(log_file, "w", newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(["id_etudiant", "nom", "prenom", "hash", "nom_fichier"])

        for etu in etudiants:
            uid = etu["id"]; nom = etu["nom"]; prenom = etu["prenom"]
            wb = openpyxl.load_workbook(template_path)
            ws = wb.active

            ws["Z1"] = uid
            contenu = uid.encode()
            for row in ws.iter_rows(values_only=True):
                for cell in row:
                    if cell is not None:
                        contenu += str(cell).encode()
            h = hashlib.sha256(contenu).hexdigest()
            ws["Z2"] = h

            ws.column_dimensions['Z'].hidden = True
            for row_cells in ws.iter_rows(min_row=2, max_row=ws.max_row, min_col=3, max_col=25):
                for cell in row_cells:
                    cell.protection = Protection(locked=False)
            ws.protection.sheet = True
            ws.protection.enable()

            fname = f"{uid}_{nom}_{prenom}.xlsx"
            wb.save(os.path.join(output_folder, fname))
            writer.writerow([uid, nom, prenom, h, fname])

    return output_folder
