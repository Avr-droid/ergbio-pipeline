import os
import io
import json
import time
import tempfile
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

# --- Google Drive API setup ---
# Requires: pip install google-api-python-client google-auth
# Add GOOGLE_SERVICE_ACCOUNT_JSON to your .env — path to your service account key file
# The service account must have Viewer access to the INPUT_FOLDER_ID folder

try:
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaIoBaseDownload
    from google.oauth2 import service_account
    HAS_GOOGLE = True
except ImportError:
    HAS_GOOGLE = False

INPUT_FOLDER_ID = os.getenv("INPUT_FOLDER_ID")
SERVICE_ACCOUNT_JSON = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")

# Local file to track which Drive file IDs have already been processed
PROCESSED_LOG = Path(__file__).parent.parent / "processed_files.json"

POLL_INTERVAL_SECONDS = 300  # Check every 5 minutes


def _load_processed() -> set:
    """Load the set of already-processed Drive file IDs from disk."""
    if PROCESSED_LOG.exists():
        with open(PROCESSED_LOG) as f:
            return set(json.load(f))
    return set()


def _save_processed(processed: set):
    """Persist the set of processed file IDs to disk."""
    with open(PROCESSED_LOG, "w") as f:
        json.dump(list(processed), f, indent=2)


def _build_drive_service():
    """Authenticate and return a Google Drive API service object."""
    if not HAS_GOOGLE:
        raise RuntimeError(
            "Google API client not installed. Run: pip install google-api-python-client google-auth"
        )
    if not SERVICE_ACCOUNT_JSON:
        raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON not set in .env")
    if not INPUT_FOLDER_ID:
        raise RuntimeError("INPUT_FOLDER_ID not set in .env")

    creds = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_JSON,
        scopes=["https://www.googleapis.com/auth/drive.readonly"],
    )
    return build("drive", "v3", credentials=creds)


def _list_new_files(service) -> list:
    """
    List .xlsx and .csv files in INPUT_FOLDER_ID that haven't been processed yet.
    Returns a list of dicts with id, name, mimeType.
    """
    processed = _load_processed()

    query = (
        f"'{INPUT_FOLDER_ID}' in parents "
        f"and trashed = false "
        f"and (name contains '.xlsx' or name contains '.csv')"
    )
    result = service.files().list(
        q=query,
        fields="files(id, name, mimeType, createdTime)",
        orderBy="createdTime desc",
    ).execute()

    all_files = result.get("files", [])
    new_files = [f for f in all_files if f["id"] not in processed]
    return new_files


def _download_file(service, file_id: str, file_name: str) -> str:
    """
    Download a file from Drive to a local temp directory.
    Returns the local file path.
    """
    tmp_dir = Path(tempfile.gettempdir()) / "ergbio_hplc"
    tmp_dir.mkdir(exist_ok=True)
    local_path = tmp_dir / file_name

    request = service.files().get_media(fileId=file_id)
    with io.FileIO(local_path, "wb") as fh:
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()

    return str(local_path)


def watch_and_trigger(run_pipeline_fn):
    """
    Main loop. Polls Drive every POLL_INTERVAL_SECONDS for new HPLC files.
    When a new file is found, downloads it and calls run_pipeline_fn(file_path).

    Args:
        run_pipeline_fn: callable that accepts a local file path string
                         and runs the full agent pipeline on it.
    """
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Drive watcher started. "
          f"Polling every {POLL_INTERVAL_SECONDS // 60} minutes.")

    service = _build_drive_service()
    processed = _load_processed()

    while True:
        try:
            new_files = _list_new_files(service)

            if new_files:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] "
                      f"Found {len(new_files)} new file(s).")

                for file_info in new_files:
                    file_id   = file_info["id"]
                    file_name = file_info["name"]

                    print(f"  → Processing: {file_name}")
                    try:
                        local_path = _download_file(service, file_id, file_name)
                        run_pipeline_fn(local_path)
                        processed.add(file_id)
                        _save_processed(processed)
                        print(f"  ✓ Done: {file_name}")
                    except Exception as e:
                        print(f"  ✗ Failed on {file_name}: {e}")
            else:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] No new files.")

        except Exception as e:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Watcher error: {e}")

        time.sleep(POLL_INTERVAL_SECONDS)


# --- Run directly to start the watcher ---
if __name__ == "__main__":
    # Import the orchestrator's run function
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from agent import root_agent

    def run_pipeline(file_path: str):
        root_agent.run(file_path)

    watch_and_trigger(run_pipeline)
