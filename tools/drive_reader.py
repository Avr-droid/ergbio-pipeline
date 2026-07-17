import os
import io
import json
from dotenv import load_dotenv

load_dotenv()

SHARED_FOLDER_ID     = os.getenv("SHARED_FOLDER_ID")
SERVICE_ACCOUNT_JSON = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")

try:
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaIoBaseDownload
    from google.oauth2 import service_account
    HAS_GOOGLE = True
except ImportError:
    HAS_GOOGLE = False


def _drive_service():
    if not HAS_GOOGLE:
        raise RuntimeError("Run: pip install google-api-python-client google-auth")
    if not SERVICE_ACCOUNT_JSON:
        raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON not set in .env")
    creds = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_JSON,
        scopes=["https://www.googleapis.com/auth/drive.readonly"],
    )
    return build("drive", "v3", credentials=creds)


def load_all_runs() -> list:
    """
    Load all run JSON files from the shared Drive folder.
    Returns a list of run dicts, sorted newest first (by run id).
    Used by the Streamlit app for Run History and Compare tabs.
    """
    if not SHARED_FOLDER_ID:
        raise RuntimeError("SHARED_FOLDER_ID not set in .env")

    service = _drive_service()
    query   = f"'{SHARED_FOLDER_ID}' in parents and trashed = false and mimeType = 'application/json'"
    result  = service.files().list(
        q=query,
        fields="files(id, name, createdTime)",
        orderBy="createdTime desc",
    ).execute()

    runs = []
    for f in result.get("files", []):
        try:
            request  = service.files().get_media(fileId=f["id"])
            fh       = io.BytesIO()
            downloader = MediaIoBaseDownload(fh, request)
            done = False
            while not done:
                _, done = downloader.next_chunk()
            run = json.loads(fh.getvalue().decode("utf-8"))
            run["_driveFileId"] = f["id"]
            runs.append(run)
        except Exception:
            pass  # skip malformed files

    # Sort newest first by run id (timestamp)
    runs.sort(key=lambda r: r.get("id", 0), reverse=True)
    return runs


def load_run_by_id(drive_file_id: str) -> dict:
    """Load a single run by its Drive file ID."""
    service = _drive_service()
    request = service.files().get_media(fileId=drive_file_id)
    fh      = io.BytesIO()
    downloader = MediaIoBaseDownload(fh, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    return json.loads(fh.getvalue().decode("utf-8"))


def delete_run(drive_file_id: str) -> bool:
    """Delete a run file from Drive. Returns True on success."""
    try:
        service = _drive_service()
        service.files().delete(fileId=drive_file_id).execute()
        return True
    except Exception:
        return False
