# Upload endpoint for the Django project

Adds `POST /api/facilities/create/`, which the uploader calls to save a new fountain.
The id is assigned here (existing entries + 1, under a lock, with the database's unique
primary key as a backstop), so two uploads at once can never get the same id.

## Install (on the machine that runs the Django server)

1. Copy `upload.py` to `locations/upload.py`.
2. In `locations/urls.py` add the import and the route:

   ```python
   from .upload import create_facility

   urlpatterns = [
       path("nearby/", nearby_facilities),
       path("facilities/create/", create_facility),
   ]
   ```

3. Pick a secret and set it before starting Django (PowerShell shown):

   ```powershell
   $env:UPLOAD_TOKEN = "choose-a-long-random-string"
   python manage.py runserver
   ```

   Without `UPLOAD_TOKEN` the endpoint answers 503 and saves nothing. This stops strangers who
   find the public ngrok URL from writing to the database.

4. Start the home or uploader app with the same secret:

   ```powershell
   $env:DJANGO_UPLOAD_TOKEN = "choose-a-long-random-string"
   npm.cmd run tunnel
   ```

If the Django server address changes, also set `DJANGO_API_URL` (the `/api/nearby/` address); the
upload address is worked out from it. Set `DJANGO_UPLOAD_URL` only if the endpoint lives elsewhere.

## Notes

- `floor` must be a text column (the live server already returns floors like `"L1"`). The older
  copy of the project has `IntegerField`, which cannot store `M2`.
- Fine as-is on SQLite. On PostgreSQL, saving rows with explicit ids leaves the id counter behind,
  so use the auto-generated id there instead.
