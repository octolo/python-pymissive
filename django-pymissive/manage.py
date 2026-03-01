#!/usr/bin/env python
"""Django manage.py with ngrok integration. Self-contained, no qualitybase."""

import os
import sys
import time
from pathlib import Path


def _load_env_file() -> None:
    """Load .env file into os.environ. Uses project root (script dir) or ENVFILE_PATH."""
    project_root = Path(__file__).resolve().parent
    env_path = os.environ.get("ENVFILE_PATH", ".env")
    path = Path(env_path) if Path(env_path).is_absolute() else project_root / env_path
    if not path.exists():
        return
    try:
        from dotenv import load_dotenv

        load_dotenv(path, override=False)
    except ImportError:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, val = line.partition("=")
                    key = key.strip()
                    if key and key not in os.environ:
                        os.environ[key] = val.strip().strip('"').strip("'")


def start_ngrok_tunnel(port: int = 8000) -> str:
    """Start ngrok tunnel for the given port."""
    from pyngrok import ngrok  # type: ignore[import-not-found]

    ngrok_token = os.getenv("NGROK_TOKEN") or os.getenv("NGROK_AUTHTOKEN")
    if ngrok_token:
        ngrok.set_auth_token(ngrok_token)

    tunnel = ngrok.connect(port)
    print(f"\n🌐 Ngrok tunnel active: {tunnel.public_url}\n")
    return tunnel.public_url


def create_superuser() -> None:
    """Creates default superuser if none exists."""
    import django

    django.setup()  # type: ignore[attr-defined]
    from django.contrib.auth.models import User

    if not User.objects.filter(is_superuser=True).exists():
        print("📦 Creating superuser: admin/admin")
        User.objects.create_superuser("admin", "admin@example.com", "admin")
        print("✅ Superuser created successfully!")
        print("   Username: admin")
        print("   Password: admin")
    else:
        print("✅ Superuser already exists")


def main() -> None:
    """Runs administrative tasks."""
    _load_env_file()
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tests.settings")

    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?"
        ) from exc

    if "--ngrok" in sys.argv:
        sys.argv.remove("--ngrok")
        if "runserver" in sys.argv:
            runserver_index = sys.argv.index("runserver")
            raw = (
                sys.argv[runserver_index + 1]
                if len(sys.argv) > runserver_index + 1
                else "8000"
            )
            port = int(raw.split(":")[-1]) if ":" in raw else int(raw)
            public_url = start_ngrok_tunnel(port)
            os.environ["NGROK_PUBLIC_URL"] = public_url
            time.sleep(1)

    if len(sys.argv) > 1 and sys.argv[1] == "migrate":
        execute_from_command_line(sys.argv)
        create_superuser()
        return

    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
