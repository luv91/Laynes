"""WSGI entry point for Railway deployment."""
from app.web import create_app

app = create_app()

if __name__ == "__main__":
    app.run()
