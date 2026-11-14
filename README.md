# Thirst Trips

A phone-friendly app for finding water fountains, walking to them with an AR view, adding new
ones, and earning points by scanning NFC tags.

It is two programs that run side by side:

| Program | Folder | Port | What it does |
|---|---|---|---|
| **Node server** | `arthur/home` | 3000 | The website: the map, the AR navigator (`/navigator/`) and the uploader (`/uploader/`). It also starts the Cloudflare tunnel and passes login, account, leaderboard and achievements pages through to Django. |
| **Django server** | `rafay/fountain-finder` | 8000 | The database (SQLite), accounts, check-ins, points, leaderboard, achievements and the admin. |

Other folders: `arthur/navigator` and `arthur/uploader` are the AR and upload apps that the Node server
mounts, `emily` holds the artwork and `ryan` holds NFC notes. API notes are in
`rafay/fountain-finder/docs`. `InteriorDevelopment` collects photos from the navigator (`Pictures`) and turns them
into floor plans (`Python`, see its README).

## What you need

- **Node.js 20.12 or newer** (https://nodejs.org)
- **Python 3.12 or newer** (https://python.org). Tick "Add python.exe to PATH" when installing.
- A **Cloudflare tunnel token** if you want the public addresses (optional for local testing).

All commands below are for **PowerShell** on Windows, run from the repository's top folder (the one
containing this README).

## First-time setup

```powershell
# 1. Django: make its own Python environment and install it
python -m venv .venv-backend
.\.venv-backend\Scripts\python.exe -m pip install -r rafay\fountain-finder\requirements.txt

# 2. Node: install the three apps' packages
foreach ($app in "home", "navigator", "uploader") { npm.cmd install --prefix "arthur\$app" }

# 3. Settings file for the Node server (the real one stays private, it is ignored by Git)
Copy-Item arthur\.env.example arthur\.env
notepad arthur\.env          # paste your Cloudflare tunnel token (see "The public addresses" below)

# 4. Database tables
.\.venv-backend\Scripts\python.exe rafay\fountain-finder\manage.py migrate

# 5. An admin login for http://localhost:8000/admin/ (optional)
.\.venv-backend\Scripts\python.exe rafay\fountain-finder\manage.py createsuperuser
```

The repository includes a ready-made `rafay/fountain-finder/db.sqlite3` with the current fountains and
accounts, so `migrate` only applies anything that is missing.

## Running it

### One command

Double-click **`start.bat`** (or run `.\start.bat` in a terminal). It opens Django and the website with its
tunnel in two separate windows, applies any new database changes, and tells you when both are answering.

| Command | What it does |
|---|---|
| `.\start.bat` | Starts everything. Anything already running is left alone, and a leftover tunnel from a closed window is cleaned up. |
| `.\stop.bat` | Stops Django, the website and the tunnel. |
| `.\start.bat -DryRun` | Shows what would start without starting anything. |

It installs missing Node packages on the first run, uses `.venv-backend` if it exists (otherwise your
normal `python`), and warns if `arthur\.env` is missing. After changing Node code, run `.\stop.bat` and
then `.\start.bat` (Django restarts itself).

### Or by hand, in two windows

Open **two** PowerShell windows in the top folder.

**Window 1: Django**

```powershell
cd rafay\fountain-finder
..\..\.venv-backend\Scripts\python.exe manage.py runserver
```

**Window 2: the website and tunnel**

```powershell
cd arthur\home
npm.cmd run tunnel
```

Wait for `Live at: https://thirsttrips-ua.ca`. Keep both windows open: closing one takes that part
offline. Restart a window after changing code in it. (Django restarts itself; the Node server does not.)

To try it on this PC only, without the tunnel, use `npm.cmd start` instead. It prints
`https://localhost:3000` and your LAN address for phones on the same Wi-Fi. Browsers will warn about the
self-signed certificate; choose to continue.

## The public addresses (Cloudflare)

In Cloudflare Zero Trust, open your named tunnel and add two public hostnames:

| Hostname | Service |
|---|---|
| `thirsttrips-ua.ca` | `http://localhost:3000` |
| `data.thirsttrips-ua.ca` | `http://localhost:8000` |

Put the tunnel's token in `arthur/.env` as `CLOUDFLARE_TUNNEL_TOKEN`. The Node server runs the tunnel
connector, so **both** addresses only work while the Node server is running, and Django must be running on
the same PC. (If Django is on another PC, give that PC its own tunnel.) Without a token you get a
temporary random `trycloudflare.com` address that only shows the Node site.

## Pages

| Address | What it is |
|---|---|
| `/` | Map of all fountains. Tap a fountain to draw the route and show DRINK!. |
| `/navigator/` | AR walk to a fountain (opened by DRINK!). |
| `/uploader/` | Add a new fountain with the camera. You must be logged in. |
| `/login/`, `/signup/` | Log in or create an account. |
| `/account/` | Your points, with links to the leaderboard, achievements and the map. |
| `/leaderboard/` | The top players. |
| `/achievements/` | Locked and unlocked achievements. |
| `/checkin/<id>/` | What an NFC tag opens: log in, then press Claim Points. |
| `/admin/` | Django admin (fountains, users, NFC ids). |

The login, sign-up, account, leaderboard, achievements and check-in pages work on both
`thirsttrips-ua.ca` and `data.thirsttrips-ua.ca`. Point NFC tags at
`https://data.thirsttrips-ua.ca/checkin/<id>/`. The id for each fountain is shown in the admin.

## Interior snapshots (for building indoor maps)

While someone is navigating, the AR page can send a photo from the camera every 2 seconds. Each walk gets its own
folder in `InteriorDevelopment/Pictures` (named by the phone's date and time, like `20261114-031542-k3x9`), and each
photo is saved as two files:

```
InteriorDevelopment/Pictures/20261114-031542-k3x9/0007 53.1023982 -113.2034985 349.jpg
InteriorDevelopment/Pictures/20261114-031542-k3x9/0007 53.1023982 -113.2034985 349.json
```

The file name is `<photo number> <latitude> <longitude> <compass angle>` (angle in degrees from true north, 0 to 359).
The `.json` next to it has the rest: time, GPS accuracy, camera tilt (pitch and roll), compass corrections, picture
size and the assumed field of view. `InteriorDevelopment/Python` reads these and builds floor plans; see its README.

- **It only happens if the person agrees.** The calibration screen asks "Help map building interiors?" with
  Yes / No buttons, and the choice is remembered on that phone. While it is on, a green "Sharing snapshots"
  button at the top of the camera view stops it with one tap. Nothing is sent before the person says yes.
- **Limits:** photos are scaled to at most 1280 pixels wide, a visitor can send at most 45 a minute, and saving
  stops when the folder passes `INTERIOR_MAX_MB` (default 2000 MB).
- **Privacy:** the photos can show people and private rooms. They are ignored by Git on purpose, but the
  repository sits inside OneDrive, so OneDrive will sync that folder. Write a privacy notice that matches what you
  do with the photos, and check what your school or organisation requires before collecting from the public.
## Settings

**`arthur/.env`** (read by the Node server at start-up, see `arthur/.env.example`):

| Name | Meaning |
|---|---|
| `CLOUDFLARE_TUNNEL_TOKEN` | Your tunnel's token. Empty gives a temporary address. |
| `PUBLIC_URL` | Only used for the "Live at" message. |
| `DJANGO_API_URL` | Where Django is. Keep `http://localhost:8000/api/nearby/` when it runs on the same PC. |
| `PORT` | Node port (default 3000). |
| `USE_SAMPLE_DATA` | `1` shows `data/sample-fountains.json` instead of asking Django. |

**Django** reads these from the window it is started in (they are optional). In PowerShell:
`$env:NAME = "value"`, then start `runserver`.

| Name | Meaning |
|---|---|
| `HOME_URL` | The map website address used by the "Back to the map" button (default `https://thirsttrips-ua.ca`). |
| `NGROK_URL` | Only if you use ngrok or another tunnel host (an `https://` address with no path). |
| `CROSS_SITE_COOKIES` | `1` for secure cross-site cookies; automatic when `NGROK_URL` is set. |
| `UPLOAD_TOKEN` | Only for the old token-based upload endpoint. The uploader page does not need it. |

## Tests

```powershell
cd rafay\fountain-finder
..\..\.venv-backend\Scripts\python.exe manage.py test
```

## Troubleshooting

- **`530` or "Error 1033" on the domain:** the Node server (and its tunnel) is not running.
- **"Cannot GET /something/" on `thirsttrips-ua.ca`:** the Node server is running old code. Restart Window 2.
- **"Could not reach Django" in the map:** start Django (Window 1), and check `DJANGO_API_URL` in `arthur/.env`.
- **A phone shows an old version:** reload once. Pages add a version to their files, but a phone can keep
  an old copy of the page itself. Close the tab and reopen it, or clear the site's data.
- **Camera, location or compass will not start:** they only work over `https://`. Use the tunnel address or
  `npm.cmd start`, not `http://`.
- **Port already in use:** an earlier copy is still running. Close its window, or find it with
  `Get-NetTCPConnection -LocalPort 3000,8000 -State Listen`.

## Safety notes

- `arthur/.env` holds your tunnel token. It is ignored by Git. Never paste it into a public place.
- `rafay/fountain-finder/db.sqlite3` is currently committed to Git, so accounts (with password hashes)
  are in the repository history. Stop tracking it (`git rm --cached`) before making the repository public.
- Django runs with `DEBUG = True` and a built-in secret key, which is fine for this project's testing but
  not for a public launch.
