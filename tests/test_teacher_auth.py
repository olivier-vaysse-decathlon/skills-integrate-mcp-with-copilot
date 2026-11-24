import asyncio
import copy
import json
import secrets
import stat
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import httpx

from src import app, auth, manage_teachers


class TeacherAuthTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.password = secrets.token_urlsafe(24)
        cls.password_hash = auth.password_hasher.hash(cls.password)

    def setUp(self):
        temporary_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temporary_dir.cleanup)
        self.teachers_file = Path(temporary_dir.name) / "teachers.json"
        file_patch = patch.object(auth, "TEACHERS_FILE", self.teachers_file)
        file_patch.start()
        self.addCleanup(file_patch.stop)
        self.teachers_file.write_text(
            json.dumps({"teacher": self.password_hash}), encoding="utf-8"
        )

        original_activities = copy.deepcopy(app.activities)
        self.addCleanup(self.restore_activities, original_activities)
        with auth.sessions_lock:
            auth.sessions.clear()
        self.addCleanup(self.clear_sessions)

    async def asyncSetUp(self):
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app.app), base_url="http://testserver"
        )
        self.addAsyncCleanup(self.client.aclose)

    @staticmethod
    def restore_activities(original):
        app.activities.clear()
        app.activities.update(original)

    @staticmethod
    def clear_sessions():
        with auth.sessions_lock:
            auth.sessions.clear()

    async def login(self):
        response = await self.client.post(
            "/auth/login", json={"username": "teacher", "password": self.password}
        )
        self.assertEqual(response.status_code, 200)
        return response

    async def test_guests_can_browse_but_cannot_change_registrations(self):
        response = await self.client.get("/activities")
        self.assertEqual(response.status_code, 200)
        self.assertIn("michael@mergington.edu", response.json()["Chess Club"]["participants"])

        signup = await self.client.post(
            "/activities/Chess Club/signup", params={"email": "new@example.edu"}
        )
        self.client.cookies.set(auth.SESSION_COOKIE, "forged")
        unregister = await self.client.delete(
            "/activities/Chess Club/unregister",
            params={"email": "michael@mergington.edu"},
        )
        self.assertEqual(signup.status_code, 401)
        self.assertEqual(unregister.status_code, 401)
        participants = (await self.client.get("/activities")).json()["Chess Club"]["participants"]
        self.assertNotIn("new@example.edu", participants)
        self.assertIn("michael@mergington.edu", participants)
        self.assertEqual((await self.client.get("/static/teachers.json")).status_code, 404)

    async def test_invalid_credentials_do_not_create_a_session(self):
        for username, password in [("teacher", "incorrect"), ("unknown", self.password)]:
            with self.subTest(username=username):
                response = await self.client.post(
                    "/auth/login", json={"username": username, "password": password}
                )
                self.assertEqual(response.status_code, 401)
                self.assertEqual(response.json()["detail"], "Invalid username or password")
                self.assertNotIn("set-cookie", response.headers)
        self.assertEqual((await self.client.get("/auth/session")).status_code, 401)

    async def test_teacher_changes_require_session_and_csrf_token(self):
        login = await self.login()
        cookie = login.headers["set-cookie"].lower()
        self.assertIn("httponly", cookie)
        self.assertIn("samesite=strict", cookie)
        self.assertEqual(login.headers["cache-control"], "no-store")
        csrf = login.json()["csrf_token"]
        self.assertEqual((await self.client.get("/auth/session")).json()["csrf_token"], csrf)

        signup_url = "/activities/Chess Club/signup"
        params = {"email": "new@example.edu"}
        self.assertEqual((await self.client.post(signup_url, params=params)).status_code, 403)
        self.assertEqual(
            (await self.client.delete(
                "/activities/Chess Club/unregister",
                params={"email": "michael@mergington.edu"},
                headers={"X-CSRF-Token": "invalid"},
            )).status_code,
            403,
        )

        headers = {"X-CSRF-Token": csrf}
        self.assertEqual(
            (await self.client.post(signup_url, params=params, headers=headers)).status_code, 200
        )
        self.assertEqual(
            (await self.client.post(signup_url, params=params, headers=headers)).status_code, 400
        )
        self.assertEqual(
            (await self.client.delete(
                "/activities/Chess Club/unregister", params=params, headers=headers
            )).status_code,
            200,
        )
        self.assertEqual(
            (await self.client.post(
                "/activities/Unknown/signup", params=params, headers=headers
            )).status_code,
            404,
        )

    async def test_logout_revokes_the_session_even_if_cookie_is_replayed(self):
        login = await self.login()
        token = self.client.cookies[auth.SESSION_COOKIE]
        csrf = login.json()["csrf_token"]
        self.assertEqual((await self.client.post("/auth/logout")).status_code, 403)
        response = await self.client.post(
            "/auth/logout", headers={"X-CSRF-Token": csrf}
        )
        self.assertEqual(response.status_code, 200)
        self.client.cookies.set(auth.SESSION_COOKIE, token)
        self.assertEqual((await self.client.get("/auth/session")).status_code, 401)
        self.assertEqual(
            (await self.client.post(
                "/activities/Chess Club/signup",
                params={"email": "new@example.edu"},
                headers={"X-CSRF-Token": csrf},
            )).status_code,
            401,
        )

    async def test_password_change_invalidates_existing_sessions(self):
        await self.login()
        new_password = secrets.token_urlsafe(24)
        new_hash = await asyncio.to_thread(auth.password_hasher.hash, new_password)
        self.teachers_file.write_text(
            json.dumps({"teacher": new_hash}),
            encoding="utf-8",
        )
        self.assertEqual((await self.client.get("/auth/session")).status_code, 401)
        response = await self.client.post(
            "/auth/login", json={"username": "teacher", "password": new_password}
        )
        self.assertEqual(response.status_code, 200)

    async def test_expired_and_revoked_sessions_cannot_change_registrations(self):
        login = await self.login()
        token = self.client.cookies[auth.SESSION_COOKIE]
        with auth.sessions_lock:
            auth.sessions[token] = replace(
                auth.sessions[token], expires_at=auth.monotonic() - 1
            )
        headers = {"X-CSRF-Token": login.json()["csrf_token"]}
        self.assertEqual(
            (await self.client.delete(
                "/activities/Chess Club/unregister",
                params={"email": "michael@mergington.edu"},
                headers=headers,
            )).status_code,
            401,
        )

        login = await self.login()
        self.teachers_file.write_text("{}", encoding="utf-8")
        self.assertEqual(
            (await self.client.post(
                "/activities/Chess Club/signup",
                params={"email": "new@example.edu"},
                headers={"X-CSRF-Token": login.json()["csrf_token"]},
            )).status_code,
            401,
        )

    async def test_missing_or_invalid_credential_file_fails_closed(self):
        for contents in (None, "not json", "[]", '{"teacher": "not-a-hash"}'):
            with self.subTest(contents=contents):
                if contents is None:
                    self.teachers_file.unlink()
                else:
                    self.teachers_file.write_text(contents, encoding="utf-8")
                with self.assertLogs("src.auth", level="ERROR"):
                    response = await self.client.post(
                        "/auth/login", json={"username": "teacher", "password": self.password}
                    )
                self.assertEqual(response.status_code, 503)
                self.assertEqual(response.json()["detail"], "Teacher authentication is unavailable")
                self.assertEqual((await self.client.get("/activities")).status_code, 200)

    async def test_https_session_cookie_is_secure(self):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app.app), base_url="https://testserver"
        ) as client:
            response = await client.post(
                "/auth/login", json={"username": "teacher", "password": self.password}
            )
            self.assertEqual(response.status_code, 200)
            self.assertIn("secure", response.headers["set-cookie"].lower())

        with patch.dict("os.environ", {"TEACHER_COOKIE_SECURE": "1"}):
            response = await self.client.post(
                "/auth/login", json={"username": "teacher", "password": self.password}
            )
        self.assertEqual(response.status_code, 200)
        self.assertIn("secure", response.headers["set-cookie"].lower())

    async def test_provisioning_preserves_accounts_and_stores_only_hashes(self):
        new_password = secrets.token_urlsafe(24)
        with (
            patch("sys.argv", ["manage_teachers", "another-teacher"]),
            patch("getpass.getpass", side_effect=[new_password, new_password]),
            patch("builtins.print"),
        ):
            await asyncio.to_thread(manage_teachers.main)
        contents = self.teachers_file.read_text(encoding="utf-8")
        teachers = json.loads(contents)
        self.assertEqual(teachers["teacher"], self.password_hash)
        self.assertNotIn(new_password, contents)
        self.assertTrue(
            await asyncio.to_thread(
                auth.password_hasher.verify, new_password, teachers["another-teacher"]
            )
        )
        self.assertEqual(stat.S_IMODE(self.teachers_file.stat().st_mode), 0o600)
        response = await self.client.post(
            "/auth/login",
            json={"username": "another-teacher", "password": new_password},
        )
        self.assertEqual(response.status_code, 200)


if __name__ == "__main__":
    unittest.main()
