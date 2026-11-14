# Frontend API

## Achievements

### Discovery and one-time notifications

`POST /api/facilities/discover/` uses the logged-in user's session and CSRF token.
It accepts the same facility fields as staff creation, but only type `fountain`.
It credits `discovered_by` from the session (client-supplied contributor fields are
rejected), creates a facility, and returns its fields plus `new_achievements`.
The first submission unlocks `new_fountain` / Fountain Finder. Exact coordinates
and floor matching an existing fountain return 409. This is community submission,
not moderated verification; approximate duplicates are not detected yet.
The shared-token uploader remains compatible but cannot award contributor credit.

`POST /api/achievements/notifications/claim/` with `{}` and CSRF returns
`{"notifications": [...]}` using the achievement entry format below. It atomically
marks notifications consumed for the current account. They never return again,
even on another device. **Delivery is at most once:** navigating away or losing the
response after a successful claim can lose the celebration. The achievement itself
remains visible in GET `/api/achievements/`.

The popup script is included in Django's authenticated pages and the combined
home/map, navigator, and uploader pages. It shows each claim for 6.5 seconds,
uses Matthew's achievement sound, and allows dismissal. Browsers may require a tap
on its sound button before audio can play. It does not replay notifications from
`new_achievements`; that field remains available for other clients.

The combined home server proxies auth, achievement, and discovery API requests to
the Django origin configured by `DJANGO_API_URL`, preserving session cookies and
CSRF. The contributor sign-in form uses that proxy. Run the combined home app for
this integration; standalone navigator/uploader servers do not provide this proxy.

`GET /api/achievements/` requires a logged-in session and returns
`{"achievements": [...]}` for the current user only. This is read-only; clients cannot
assign achievements or select a different user. Each entry contains:

```json
{
  "code": "points_50",
  "name": "Getting Hydrated",
  "description": "Earn 50 points from check-ins.",
  "metric": "earned_points",
  "target": 50,
  "progress": 30,
  "unlocked": false,
  "unlocked_at": null
}
```

Rules: `first_check_in` (First Sip) requires 1 check-in; `points_50`
(Getting Hydrated) requires 50 lifetime check-in points; `fountains_5`
(Fountain Explorer) requires visits to 5 distinct facilities of type `fountain`.
Washroom visits count toward the first check-in and earned points, but not fountain exploration.
Staff balance adjustments do not count toward earned points. Progress is capped at the target.

Successful `POST /api/checkin/` responses now also include `new_achievements`, an array
of entries in this same format, with `unlocked: true` and an ISO timestamp.
Use these for immediate notifications. Repeated same-day confirmation returns an empty array.
Use the GET endpoint for the achievements screen and to recover status after a lost response.
Do not assume a notification will be delivered again if a successful request is retried.

Unlocks are permanent and do not award extra points. Browser NFC check-ins unlock through
the same service; authenticated HTML pages now show the shared celebration popup.
Existing users are evaluated on their next successful new check-in,
including their previous check-in history. GET never creates unlocks.

Images, sounds, and popup presentation belong to the frontend: map each stable `code`
to your chosen assets. No asset URLs are prescribed by the backend yet.
Contributor credit is available through the session-authenticated discovery endpoint above.

Django stores the data in SQLite. Frontends use these HTTP endpoints instead of accessing the database file. Existing HTML pages remain available.

## Hosting and sessions

Recommended: serve the frontend and proxy `/api/` to Django on the same HTTPS domain. This avoids cross-origin cookie issues. The backend allows credentialed API requests from `https://thirsttrips-ua.ca` and trusts that origin for CSRF. Other origins, including www, are not enabled. Having a domain alone does not configure this proxy.

During development, a frontend dev-server proxy can forward `/api/` to `http://localhost:8000` when running on the backend computer, or the backend's ngrok URL for a remote teammate. Preserve cookies, and configure Django's trusted origins for the frontend origin where necessary. Do not put ngrok authtokens in frontend code.

Requests use session cookies and CSRF protection. First fetch a CSRF token. Send JSON and the token on POST/PATCH/DELETE. Login and registration return a new token because Django rotates it. Error responses from Django middleware (including CSRF rejection) may be HTML; inspect status before assuming a JSON response.

```javascript
// Use an empty string with a same-domain /api proxy, or the backend origin.
const API_ORIGIN = 'https://data.thirsttrips-ua.ca';
let csrfToken;

async function initCsrf() {
  const response = await fetch(API_ORIGIN + '/api/auth/csrf/', { credentials: 'include' });
  if (!response.ok) throw new Error('Cannot initialize session');
  csrfToken = (await response.json()).csrfToken;
}

async function api(path, method = 'GET', data) {
  const response = await fetch(API_ORIGIN + '/api/' + path, {
    method,
    credentials: 'include',
    headers: {
      ...(data !== undefined ? { 'Content-Type': 'application/json' } : {}),
      ...(['POST', 'PATCH', 'DELETE'].includes(method)
        ? { 'X-CSRFToken': csrfToken } : {}),
    },
    ...(data !== undefined ? { body: JSON.stringify(data) } : {}),
  });
  const isJson = response.headers.get('content-type')?.includes('application/json');
  const result = isJson ? await response.json() : { error: await response.text() };
  if (!response.ok) throw new Error(JSON.stringify(result));
  if (result.csrfToken) csrfToken = result.csrfToken;
  return result;
}

await initCsrf();
// Call these from the relevant user actions:
// await api('auth/register/', 'POST', {
//   username: 'visitor', password1: 'user-entered-password',
//   password2: 'user-entered-password',
// });
// await api('auth/login/', 'POST', { username, password });
// const profile = await api('me/');
// const facilities = await api('facilities/');
```

## Routes

| Method | Path | Access / body |
| --- | --- | --- |
| GET | `/api/auth/csrf/` | Public; returns `csrfToken` and sets CSRF cookie |
| POST | `/api/auth/register/` | Public; `username`, `password1`, `password2`; creates account, profile, and session |
| POST | `/api/auth/login/` | `username`, `password`; starts session |
| POST | `/api/auth/logout/` | Logged in; body `{}` |
| GET | `/api/me/` | Logged in; current user's `id`, `username`, `total_points`, `is_staff` |
| GET | `/api/profile/` | Existing endpoint; login redirect when anonymous |
| GET | `/api/facilities/` | Public; returns `{facilities: [...]}` |
| POST | `/api/facilities/` | Staff only; creates facility |
| GET | `/api/facilities/<id>/` | Public; one facility |
| PATCH | `/api/facilities/<id>/` | Staff only; partial update |
| DELETE | `/api/facilities/<id>/` | Staff only; fails with 409 if check-ins reference facility |
| GET | `/api/nearby/?lat=53.52&lon=-113.53` | Existing public endpoint; sorted by straight-line distance |
| POST | `/api/checkin/` | Logged in; `{"token": "NFC-UUID"}`; awards server-defined points once per UTC day |
| POST | `/api/users/<id>/points/` | Staff only; `{"delta": 10}` adds points; negative delta subtracts |

Facility creation example (staff session):

```javascript
await api('facilities/', 'POST', {
  name: 'Library fountain',
  facility_type: 'fountain', // or 'washroom'; defaults to fountain
  building: 'Library',
  floor: '1', // optional
  latitude: 53.52,
  longitude: -113.53,
  accessible: true, // optional, defaults to false
});
```

Only the fields above are writable. Coordinates must be finite numbers within latitude/longitude ranges. NFC identifiers are generated by Django and are not included in public facility responses. Copy the tag URL/token from the facility's admin page.

Check-in response: `check_in_id`, `created`, `points_awarded`, `total_points`. First success returns 201; repeat same-day confirmation returns 200 and awards zero additional points. Points cannot be supplied by the client.

Manual points adjustment accepts an integer delta from -1,000,000 to 1,000,000. Resulting balances must remain between 0 and 2,147,483,647. This administrative operation is additive; retrying it will apply it again. It does not create a check-in or an audit ledger.

Only administrators should mark trusted accounts as staff using Django admin. Registration never grants staff access. No public user listing or arbitrary user-edit endpoint is provided. Account creation is one user per request; there is no bulk import.

JSON endpoints generally return 400 for validation, 401 for missing login, 403 for insufficient permissions, and 415 for a non-JSON write body. Form validation errors are returned under `errors`. Check-ins still use a static NFC token and do not prove physical presence.

## data.thirsttrips-ua.ca (Cloudflare tunnel)

Django is published at `https://data.thirsttrips-ua.ca` through a Cloudflare tunnel whose public hostname forwards to the service `http://localhost:8000`. The hostname is already in `ALLOWED_HOSTS` and `CSRF_TRUSTED_ORIGINS` (`PUBLIC_URL` in `backend/settings.py`), and `SECURE_PROXY_SSL_HEADER` makes Django trust cloudflared's `X-Forwarded-Proto`. No environment variable is needed for this host.

### Using a different tunnel (e.g. ngrok)

Restart Django with `NGROK_URL` set to the actual HTTPS backend tunnel URL. This enables Secure, SameSite=None cookies for the cross-site connection. Frontend requests must use `credentials: 'include'` and the CSRF token returned by `/api/auth/csrf/`, then use the replacement token returned after login or signup. Never try to read the backend cookie from frontend JavaScript.

For a different HTTPS backend without NGROK_URL, set `CROSS_SITE_COOKIES=1` and configure its hostname in ALLOWED_HOSTS. DNS/hosting and reverse proxy configuration are separate from Django CORS settings.

Some browsers block third-party cookies even with these settings. For reliable login, proxy `/api/` through https://thirsttrips-ua.ca so frontend and backend share an origin. Cross-site ngrok sessions need real browser verification. Staff permissions remain required for facility writes and manual point adjustments.

## Trusted uploader endpoint

`POST /api/facilities/create/` uses a separate server-to-server shared secret, not a Django staff session. Set `UPLOAD_TOKEN` in Django's environment before starting the server. Without it, uploads return 503; an incorrect or missing `X-Upload-Token` header returns 401.

The uploader server uses the same value as `DJANGO_UPLOAD_TOKEN` and sends it in `X-Upload-Token`. Keep both environment values private; never embed them in browser code. This endpoint is CSRF-exempt because it authenticates every request using the explicit token rather than cookies.

JSON body:

```json
{"latitude":53.52,"longitude":-113.53,"building":"Library","floor":"M2","accessible":true}
```

Building is required, with a maximum of 200 characters. Floor is required: digits, optionally preceded by one letter; it is trimmed and uppercased. Integer floors also work. Coordinates are required, finite, and range-checked. `accessible` defaults to false and is true only for JSON `true`. Other fields, including client-supplied IDs and names, are rejected.

Returns 201 with the facility fields including its assigned `id` and generated name `f<id>`. IDs are database-generated and may contain gaps. The auto-increment primary key prevents duplicate IDs across successful concurrent inserts without a process-local lock. SQLite may still return database-lock errors under heavy concurrent writes; retry policy and upload deduplication are not implemented. Retrying a successful request creates another facility.

macOS Django terminal:

```bash
source ../venv/bin/activate
export UPLOAD_TOKEN="your-long-random-secret"
python manage.py runserver
```

Uploader machine (PowerShell):

```powershell
$env:DJANGO_UPLOAD_TOKEN = "your-long-random-secret"
$env:DJANGO_API_URL = "https://data.thirsttrips-ua.ca/api/nearby/"
npm.cmd run tunnel
```

The uploader application itself lives outside this Django repository and has not been exercised by Django's tests.
