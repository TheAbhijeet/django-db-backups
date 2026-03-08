import webbrowser
import requests
from django.core.management.base import BaseCommand

class Command(BaseCommand):
    help = 'Helper to generate a Dropbox Refresh Token for your settings.py'

    def handle(self, *args, **options):
        self.stdout.write(self.style.WARNING("This command helps you generate a Dropbox Refresh Token."))
        self.stdout.write("You need an App Key and App Secret from the Dropbox Developer Console.")
        self.stdout.write("Go to: https://www.dropbox.com/developers/apps\n")

        app_key = input("Enter your App Key: ").strip()
        if not app_key:
            self.stderr.write("App Key is required.")
            return

        app_secret = input("Enter your App Secret: ").strip()
        if not app_secret:
            self.stderr.write("App Secret is required.")
            return

        auth_url = (
            f"https://www.dropbox.com/oauth2/authorize"
            f"?client_id={app_key}"
            f"&response_type=code"
            f"&token_access_type=offline"
        )

        self.stdout.write(f"\nOpening browser to authorize: {auth_url}")
        webbrowser.open(auth_url)
        
        self.stdout.write("\nIf the browser did not open, click the link above.")
        self.stdout.write("Allow access, then copy the 'code' provided by Dropbox.")
        
        code = input("\nPaste the authorization code here: ").strip()
        
        token_url = "https://api.dropbox.com/oauth2/token"
        data = {
            "code": code,
            "grant_type": "authorization_code",
            "client_id": app_key,
            "client_secret": app_secret,
        }

        try:
            r = requests.post(token_url, data=data)
            r.raise_for_status()
            resp = r.json()
            
            refresh_token = resp.get("refresh_token")
            
            if not refresh_token:
                self.stderr.write(self.style.ERROR("\nError: No refresh token returned. Did you already authorize this app?"))
                self.stderr.write("Try creating a new App in Dropbox or revoking access first.")
                return

            self.stdout.write(self.style.SUCCESS("\nSUCCESS! Here is your configuration for settings.py:\n"))
            
            config_block = (
                f"DJANGO_DB_BACKUP = {{\n"
                f"    'BACKUP_DIR': BASE_DIR / 'backups',\n"
                f"    'DROPBOX_APP_KEY': '{app_key}',\n"
                f"    'DROPBOX_APP_SECRET': '{app_secret}',\n"
                f"    'DROPBOX_REFRESH_TOKEN': '{refresh_token}',\n"
                f"    # ... other settings ...\n"
                f"}}"
            )
            print(config_block)
            
        except requests.exceptions.HTTPError as e:
            self.stderr.write(self.style.ERROR(f"\nHTTP Error: {e}"))
            self.stderr.write(f"Response: {r.text}")
        except Exception as e:
            self.stderr.write(self.style.ERROR(f"\nError: {str(e)}"))