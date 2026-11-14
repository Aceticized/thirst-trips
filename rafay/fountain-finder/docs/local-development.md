# Local development on Windows

Run commands from the repository root. The checked-in `.venv` may be incomplete;
use a separate environment for this backend:

```powershell
python -m venv .venv-backend
./.venv-backend/Scripts/python.exe -m pip install -r rafay/fountain-finder/requirements.txt
```

Install Node dependencies once in each application folder:

```powershell
Push-Location arthur/home
npm.cmd install
Pop-Location
Push-Location arthur/navigator
npm.cmd install
Pop-Location
Push-Location arthur/uploader
npm.cmd install
Pop-Location
```

Start the frontend first in its own terminal. Override the obsolete default ngrok
address so its server requests go to local Django:

```powershell
$env:DJANGO_API_URL = "http://127.0.0.1:8000/api/nearby/"
# Optional: set this to the same private secret as Django's UPLOAD_TOKEN.
# $env:DJANGO_UPLOAD_TOKEN = "your-private-secret"
Set-Location arthur/home
npm.cmd run tunnel
```

Open the HTTPS address printed by Cloudflare. Keep that terminal open.
Then start Django from the repository root in a second terminal:

```powershell
# Optional: required only for uploader submissions.
# $env:UPLOAD_TOKEN = "your-private-secret"
Set-Location rafay/fountain-finder
../../.venv-backend/Scripts/python.exe manage.py migrate
../../.venv-backend/Scripts/python.exe manage.py runserver
```

The frontend can read local Django without a separate backend tunnel, because Node
makes those requests on the server. Direct browser login/check-in API access from
a remote phone still needs a reachable backend or a configured proxy; the home
server does not proxy Django's authentication or achievement endpoints.

Run backend verification from the Django project folder:

```powershell
../../.venv-backend/Scripts/python.exe manage.py test
../../.venv-backend/Scripts/python.exe manage.py makemigrations --check --dry-run
```

Do not commit virtual environments, node_modules, or private `.env` files.
