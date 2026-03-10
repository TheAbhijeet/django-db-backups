# Django DB Backup

A database backup and restore utility for Django applications. It supports SQLite and PostgreSQL, with storage backends for the Local Filesystem and Dropbox.

<img width="1473" height="344" alt="image" src="https://github.com/user-attachments/assets/535619cf-ec6d-471f-9749-4e74dcf56891" />


## Core Features

*   **Atomic Restores:** Uses PostgreSQL single-transaction mode and automatic pre-restore safety snapshots to prevent data loss during failures.
*   **Checksum Validation:** Cryptographically verifies backup file integrity (SHA-256) before attempting a restore.
*   **Audit Logging:** Tracks every restore operation with detailed, step-by-step console logs visible in the Django Admin.
*   **Docker Ready:** Can automatically execute database dumps inside a running Docker container from the host.
*   **Chunked Uploads:** Safely uploads multi-gigabyte databases to Dropbox using chunked sessions to prevent memory exhaustion and timeouts.
*   **Async Admin UI:** Upload and restore large backups in the background without browser timeouts.

---

⚠️ **Caution**

This package is a **very minimal implementation** intended to solve a simple backup and restore workflow that works for my personal use case.

Database backups and restores are a **complex and critical subject**, and different environments may require additional safeguards, validation, and testing. This package may **not be production-ready for every project**.

Before using it in your project, please **review the code carefully, test it thoroughly, and ensure it meets your reliability and recovery requirements**.

Use this package **at your own risk**. I am not responsible for any data loss, corruption, or other issues that may occur from its use.

---

## Installation

1. Install the package:
```bash
pip install django-db-backups
```

2. Add to your `INSTALLED_APPS` in `settings.py`:
```python
INSTALLED_APPS = [
    # ... other apps ...
    'django_db_backups',
]
```

3. Run migrations to create the audit log tables:
```bash
python manage.py migrate
```

---

## Configuration Scenarios

Add the `DJANGO_DB_BACKUP` dictionary to your `settings.py`. Below are the three most common configurations.

### Scenario 1: SQLite Only (Local Storage)
This is the simplest setup. It requires no external dependencies.

```python
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

DJANGO_DB_BACKUP = {
    "BACKUP_DIR": BASE_DIR / "backups",
    "RETENTION_MAX_COUNT": 5,         # Keep the last 5 backups
    "RETENTION_MAX_AGE_DAYS": 30,     # Delete backups older than 30 days
    "SQLITE_COMPRESS": True,          # Zip the sqlite dump
}
```

### Scenario 2: PostgreSQL Only (Local Storage)
This requires the PostgreSQL client tools to be installed on your server (see the Binary Paths section below).

```python
DJANGO_DB_BACKUP = {
    "BACKUP_DIR": BASE_DIR / "backups",
    "RETENTION_MAX_COUNT": 10,
    "DATABASES": ["default"],         # List of database aliases to backup
    "PG_DUMP_FORMAT": "c",            # 'c' for custom format (required for pg_restore)
}
```

### Scenario 3: PostgreSQL with Dropbox
This is the recommended production setup. It creates the backup locally, uploads it to Dropbox, and then cleans up the local file.

```python
import os

DJANGO_DB_BACKUP = {
    "BACKUP_DIR": BASE_DIR / "backups", # Used temporarily during the upload process
    "DATABASES": ["default"],
    
    # Dropbox OAuth2 Refresh Flow (Recommended for Production)
    "DROPBOX_APP_KEY": os.getenv("DROPBOX_APP_KEY"),
    "DROPBOX_APP_SECRET": os.getenv("DROPBOX_APP_SECRET"),
    "DROPBOX_REFRESH_TOKEN": os.getenv("DROPBOX_REFRESH_TOKEN"),
    "DROPBOX_FOLDER": "/production-database-backups",
    "DROPBOX_RETENTION_MAX_COUNT": 14,  # Keep 2 weeks of daily backups
}
```

## Dropbox Setup (Easy Way)

This package includes a helper command to generate your Refresh Token automatically.

1.  Create an App in the [Dropbox Console](https://www.dropbox.com/developers/apps).
2.  Run the helper command:
    ```bash
    python manage.py get_dropbox_token
    ```
3.  Follow the prompts. It will print the exact configuration you need to copy into `settings.py`.


### Automated Scheduling (Linux/Mac)

The package can automatically manage the OS crontab for you.

1.  Set the interval in `settings.py`:
    ```python
    DJANGO_DB_BACKUP = {
        "AUTO_BACKUP_INTERVAL_DAYS": 7, # Backup every 7 days
    }
    ```

2.  Run the update command:
    ```bash
    python manage.py update_backup_cron
    ```
    This adds a daily job to your crontab that runs `dbbackup --auto`. The command itself handles the 7-day logic.

3.  To remove the job:
    ```bash
    python manage.py update_backup_cron --remove
    ```


---

## Understanding PostgreSQL Binary Paths

To backup and restore PostgreSQL, this package relies on the `pg_dump` and `pg_restore` command-line utilities. 

### 1. Standard Linux / Ubuntu Servers
If your Django application runs directly on a Linux server, you must install the client tools:
```bash
sudo apt-get update
sudo apt-get install postgresql-client
```
**Configuration needed:** None. The package automatically searches the system `$PATH`. On Ubuntu, the installation places the binaries in `/usr/bin/pg_dump`, which Python will find automatically.

### 2. Django on Host, Postgres in Docker (Local Development)
If you are developing on Windows or Mac, and your database runs inside a Docker container, you do not need to install PostgreSQL on your host machine. Tell the package your container's name, and it will route commands through `docker exec`.
```python
DJANGO_DB_BACKUP = {
    # ...
    "POSTGRES_CONTAINER_NAME": "my_postgres_container", 
}
```

### 3. Custom Installation Paths (Windows)
PostgreSQL is typically installed in Program Files. You must use raw strings (r"...") to handle backslashes.
```python
DJANGO_DB_BACKUP = {
    # ...
    # Adjust the version number (16) to match your installation
    "PG_DUMP_PATH": r"C:\Program Files\PostgreSQL\16\bin\pg_dump.exe",
    "PG_RESTORE_PATH": r"C:\Program Files\PostgreSQL\16\bin\pg_restore.exe",
}
```

### 4. Custom Installation Paths (Ubuntu / Linux Users)
If you installed via apt, the binaries are usually in /usr/bin/ or /usr/lib/postgresql/.

```python
DJANGO_DB_BACKUP = {
   # ...
    # Standard location for apt-installed postgresql-client
    "PG_DUMP_PATH": "/usr/bin/pg_dump",
    "PG_RESTORE_PATH": "/usr/bin/pg_restore",
    
    # OR if using a specific version (e.g., Postgres 14)
    # "PG_DUMP_PATH": "/usr/lib/postgresql/14/bin/pg_dump",
    # "PG_RESTORE_PATH": "/usr/lib/postgresql/14/bin/pg_restore",
}
```

---

## Usage Instructions

### Management Commands (CLI)
Ideal for Cron jobs or CI/CD pipelines.

```bash
# Create a backup of all configured databases
python manage.py dbbackup

# Restore a specific backup file
python manage.py dbrestore path/to/backup.zip
```

### Django Admin Interface
1. Navigate to **Database Backups** > **Backup Logs**.
2. **Trigger Backup:** Click the button in the top right to safely generate a backup in the background.
3. **Upload & Restore:** Click the button to upload a `.zip` file from your computer. The system synchronously validates the checksum, then replaces the database asynchronously.
4. Navigate to **Restore Logs** to view detailed audit trails of every restore operation.

---

## Dropbox Setup: Manual Guide (Refresh Token Flow)

Dropbox access tokens expire after 4 hours. For automated backups, you must use a Refresh Token.

1. Go to the Dropbox App Console [https://www.dropbox.com/developers/apps] and create a new app.
2. Grant the app `files.content.write` and `files.content.read` permissions.
3. Get your App Key and App Secret.
4. Generate an authorization code by visiting this URL in your browser (replace `YOUR_APP_KEY`):
   `https://www.dropbox.com/oauth2/authorize?client_id=YOUR_APP_KEY&token_access_type=offline&response_type=code`
5. Click "Allow" and copy the provided code.
6. Exchange the code for a Refresh Token using your terminal:
   ```bash
   curl https://api.dropbox.com/oauth2/token \
       -d code=THE_CODE_YOU_COPIED \
       -d grant_type=authorization_code \
       -u YOUR_APP_KEY:YOUR_APP_SECRET
   ```
7. The JSON response will contain a `refresh_token`. Save this in your environment variables.

---


##  Media Backups

In addition to database backups, this package can safely backup and restore your entire `MEDIA_ROOT` directory. This is perfect for migrating a complete site (like a blog with uploaded images) to a new server.

**Important:** Media backups are handled completely separately from database backups to prevent massive image folders from causing database timeouts.

### 1. Media Management Commands (CLI)
```bash
# Create a zip backup of your MEDIA_ROOT
python manage.py mediabackup

# Force a local-only media backup (bypasses Dropbox)
python manage.py mediabackup --local

# Restore media from a specific zip file
python manage.py mediarestore path/to/media_backup.zip
```

### 2. Media Admin Interface
- **Navigate:** `Database Backups → Media Backup Logs`

- **Trigger Backup:**  
  Click **"Local Media Backup"** or **"Cloud Media Backup"** at the top right.

- **Upload & Restore:**  
  Click the **red button** to upload a media `.zip` file.

> **Safety Note:**  
> Restoring media will completely wipe your current `MEDIA_ROOT` and replace it with the contents of the zip file.  
> The system automatically creates a safety backup of your current media before the wipe occurs.



## Local Development Guide (For Maintainers)

This project uses `uv` for fast, reliable dependency management and virtual environments.

### Initial Setup
```bash
# Clone the repository
git clone <repository-url>
cd django_DJANGO_DB_BACKUP

# Create a virtual environment and sync dependencies using uv
uv venv
uv sync

# Activate the virtual environment
# On Windows:
.venv\Scripts\activate
# On Linux/Mac:
source .venv/bin/activate
```

### Running the Test Suite
The test suite uses `pytest` and `pytest-django`. It is designed to adapt to the database configured in `testproject/settings.py`.

```bash
# Run all tests with verbose output
uv run pytest -v

# Run a specific test file
uv run pytest tests/test_restore.py -v
```

### Testing the Admin UI Locally
A dummy Django project (`testproject`) is included to test the Admin interface and management commands.

```bash
# Apply migrations to the local SQLite test database
uv run python manage.py migrate

# Create a superuser to access the admin panel
uv run python manage.py createsuperuser

# Start the development server
uv run python manage.py runserver
```
Visit `http://127.0.0.1:8000/admin/` to test the UI.

### Building and Publishing
To release a new version to PyPI:

```bash
# Build the source distribution and wheel
uv run python -m build

# Upload to PyPI (requires credentials)
uv run twine upload dist/*
```
