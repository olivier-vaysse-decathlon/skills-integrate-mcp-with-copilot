# Mergington High School Activities API

A FastAPI application for viewing extracurricular activities. Anyone can view
activities and participants; teachers must log in to register or unregister students.

## Getting started

Run these commands from the repository root:

1. Install dependencies:

   ```sh
   python -m pip install -r requirements.txt
   ```

2. Provision each teacher account:

   ```sh
   python -m src.manage_teachers TEACHER_USERNAME
   ```

   Enter and confirm a password when prompted. Passwords must contain at least
   12 characters. Running the command again for the same username changes that
   teacher's password.

3. Start the application:

   ```sh
   uvicorn src.app:app --reload
   ```

4. Open http://localhost:8000. Use the account icon in the top-right corner to
   log in as a teacher. API documentation is available at `/docs`.

Teacher usernames and Argon2 password hashes are stored in `src/teachers.json`,
outside the static directory. The provisioning command creates the file with
owner-only permissions; it is ignored by Git and must not be committed or shared.
There are no default teacher accounts. If the file is missing or invalid, login
is unavailable until an administrator fixes it.

Sessions expire after eight hours and are stored in memory in a single server
process; they are not shared across workers. Restarting the server logs teachers
out. Changing a password or removing its entry from the credential file
invalidates that teacher's existing sessions on their next request. Activity
registrations are also stored in memory and reset on restart.

For a deployed site, use HTTPS and set `TEACHER_COOKIE_SECURE=1` so the session
cookie is sent only over HTTPS, including when TLS terminates at a reverse
proxy. This exercise uses in-memory sessions and has no login rate limiting; it
is not a production authentication deployment.

## API endpoints

| Method | Endpoint | Access |
| ------ | -------- | ------ |
| GET | `/activities` | Public, including participant emails |
| POST | `/auth/login` | Public; accepts JSON `username` and `password` |
| GET | `/auth/session` | Logged-in teacher |
| POST | `/auth/logout` | Logged-in teacher and CSRF token |
| POST | `/activities/{activity_name}/signup?email=student@mergington.edu` | Logged-in teacher and CSRF token |
| DELETE | `/activities/{activity_name}/unregister?email=student@mergington.edu` | Logged-in teacher and CSRF token |

Login sets an HTTP-only session cookie and returns a `csrf_token`. Send that
token in the `X-CSRF-Token` header for logout and registration changes. The
session endpoint returns the token again after a page reload.

## Tests

```sh
python -m pip install -r requirements-dev.txt
python -m unittest discover -s tests -v
```
