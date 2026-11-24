import argparse
import getpass
import json
import os
import tempfile

from . import auth


def main():
    parser = argparse.ArgumentParser(description="Add or update a teacher login")
    parser.add_argument("username", help="Teacher username")
    args = parser.parse_args()
    username = args.username.strip()
    if not username or len(username) > 128:
        parser.error("The username must contain 1 to 128 characters")

    password = getpass.getpass("Teacher password: ")
    confirmation = getpass.getpass("Confirm password: ")
    if password != confirmation:
        parser.error("Passwords do not match")
    if not 12 <= len(password) <= 1024:
        parser.error("The password must contain 12 to 1024 characters")

    try:
        teachers = auth.read_teachers()
    except FileNotFoundError:
        teachers = {}
    except (OSError, UnicodeError, ValueError) as error:
        parser.exit(1, f"Could not read the teacher credential file: {error}\n")

    teachers[username] = auth.password_hasher.hash(password)
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=auth.TEACHERS_FILE.parent,
            prefix=".teachers-", suffix=".tmp", delete=False
        ) as file:
            temporary_path = file.name
            json.dump(teachers, file, indent=2)
            file.write("\n")
        os.replace(temporary_path, auth.TEACHERS_FILE)
    except OSError as error:
        parser.exit(1, f"Could not save the teacher credential file: {error}\n")
    finally:
        if temporary_path and os.path.exists(temporary_path):
            os.unlink(temporary_path)

    print(f"Teacher login saved for {username}.")


if __name__ == "__main__":
    main()
