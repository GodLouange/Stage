"""
sync_gdrive.py
--------------
Synchronise les fichiers CSV du dossier Google Drive vers le dossier local data/.

Configuration :
  - GDRIVE_FOLDER_ID : ID du dossier Google Drive (extrait de l'URL de partage)
  - DATA_DIR         : dossier local de destination

Prérequis :
  pip install google-auth google-auth-oauthlib google-api-python-client

Authentification :
  Au premier lancement, une fenêtre de navigateur s'ouvrira pour autoriser l'accès.
  Un fichier token.json sera créé pour les prochains lancements.

  Télécharge credentials.json depuis :
    https://console.cloud.google.com/apis/credentials
  (crée une application "Desktop app" avec l'API Google Drive activée)
"""

import os
import io
import sys
import json

# ─── Configuration ──────────────────────────────────────────────────────────

GDRIVE_FOLDER_ID = "1fqHroE4sUsSVjgV6fkWA8uF54ksQ4mX-"

# Dossier local de destination (relatif à ce script)
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")

# Fichiers d'authentification Google
CREDENTIALS_FILE = os.path.join(os.path.dirname(__file__), "credentials.json")
TOKEN_FILE        = os.path.join(os.path.dirname(__file__), "token.json")

# Scopes requis (lecture seule)
SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]

# ─── Authentification ────────────────────────────────────────────────────────

def _get_credentials():
    """Charge ou crée les credentials Google OAuth2."""
    try:
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError:
        print("❌  Dépendances manquantes. Lance :")
        print("    pip install google-auth google-auth-oauthlib google-api-python-client")
        sys.exit(1)

    creds = None

    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists(CREDENTIALS_FILE):
                print("❌  Fichier credentials.json manquant.")
                print("   Télécharge-le depuis : https://console.cloud.google.com/apis/credentials")
                print(f"   Place-le ici : {CREDENTIALS_FILE}")
                sys.exit(1)
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)

        with open(TOKEN_FILE, "w") as token:
            token.write(creds.to_json())

    return creds


def _build_service():
    """Construit le client Google Drive API."""
    try:
        from googleapiclient.discovery import build
    except ImportError:
        print("❌  Dépendances manquantes.")
        sys.exit(1)
    creds = _get_credentials()
    return build("drive", "v3", credentials=creds)


# ─── Listage des fichiers du dossier Drive ───────────────────────────────────

def list_folder_csv(service) -> list[dict]:
    """Retourne la liste des fichiers CSV dans le dossier Drive."""
    query = (
        f"'{GDRIVE_FOLDER_ID}' in parents "
        f"and mimeType = 'text/csv' "
        f"and trashed = false"
    )
    results = service.files().list(
        q=query,
        fields="files(id, name, size, modifiedTime)",
        pageSize=100,
    ).execute()
    return results.get("files", [])


# ─── Téléchargement ──────────────────────────────────────────────────────────

def download_file(service, file_id: str, dest_path: str):
    """Télécharge un fichier Drive vers dest_path."""
    try:
        from googleapiclient.http import MediaIoBaseDownload
    except ImportError:
        sys.exit(1)

    request = service.files().get_media(fileId=file_id)
    with io.FileIO(dest_path, "wb") as fh:
        downloader = MediaIoBaseDownload(fh, request, chunksize=4 * 1024 * 1024)
        done = False
        while not done:
            status, done = downloader.next_chunk()
            pct = int(status.progress() * 100)
            print(f"\r     {pct}%", end="", flush=True)
    print()


# ─── Point d'entrée ──────────────────────────────────────────────────────────

def main():
    os.makedirs(DATA_DIR, exist_ok=True)

    print(f"\n{'='*55}")
    print(f"  RUGBY — Sync Google Drive → data/")
    print(f"{'='*55}")
    print(f"  Dossier Drive : {GDRIVE_FOLDER_ID}")
    print(f"  Destination   : {DATA_DIR}")
    print()

    service = _build_service()

    files = list_folder_csv(service)
    if not files:
        print("  Aucun fichier CSV trouvé dans le dossier Drive.")
        return

    print(f"  {len(files)} fichier(s) trouvé(s) :\n")

    synced = 0
    skipped = 0

    for f in files:
        name     = f["name"]
        fid      = f["id"]
        size_mb  = int(f.get("size", 0)) / 1_000_000
        mod_time = f.get("modifiedTime", "")
        dest     = os.path.join(DATA_DIR, name)

        # Vérifier si le fichier local est déjà à jour (même taille)
        if os.path.exists(dest):
            local_size = os.path.getsize(dest)
            remote_size = int(f.get("size", 0))
            if local_size == remote_size:
                print(f"  ⏭  {name} ({size_mb:.1f} Mo) — déjà à jour, ignoré")
                skipped += 1
                continue

        print(f"  ↓  {name} ({size_mb:.1f} Mo) — téléchargement…")
        download_file(service, fid, dest)
        print(f"  ✓  Sauvegardé → {dest}")
        synced += 1

    print(f"\n{'='*55}")
    print(f"  Terminé : {synced} téléchargé(s), {skipped} ignoré(s)")
    print(f"{'='*55}\n")


if __name__ == "__main__":
    main()
