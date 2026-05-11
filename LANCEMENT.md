# 🏉 Rugby Analytics Dashboard — Lancement

## 1. Prérequis
Python 3.9+ installé sur ta machine.  
Vérifier : `python --version`

## 2. Installation (une seule fois)
```bash
cd rugby_dashboard
pip install -r requirements.txt
```

## 3. Lancer l'application
```bash
streamlit run app.py
```
→ Le navigateur s'ouvre automatiquement sur http://localhost:8501

## 4. Utilisation
1. Dans le panneau latéral, clique sur **"Charger des fichiers CSV"**
2. Sélectionne un ou plusieurs fichiers CSV (ex: MDM-AURI.csv)
3. Navigue entre les pages via le menu latéral :
   - 📊 Vue d'ensemble
   - ⚔️ Comparaison équipes
   - 👤 Analyse joueurs
   - 🔄 Rucks & Contacts
   - 🦵 Jeu au pied & Passes
   - 🕐 Par quart-temps

## 5. Ajouter plusieurs matchs
Tu peux charger plusieurs CSV en même temps.  
Un menu déroulant permet de basculer d'un match à l'autre.

## Format CSV compatible
- Encodage : UTF-16-LE
- Séparateur : virgule
- Structure : format Dartfish / Stats Perform
