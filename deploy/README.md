# Bewohnerformular Docker deployment

## Local test

```powershell
docker compose up --build
```

Open http://127.0.0.1:8000/.

## Production server flow

1. Copy `.env.example` to `.env` on the server and fill real secrets.
2. Login to GHCR if the package is private:

```bash
echo YOUR_GITHUB_TOKEN | docker login ghcr.io -u hosseinebi71 --password-stdin
```

3. Run production compose:

```bash
docker compose -f docker-compose.prod.yml pull
docker compose -f docker-compose.prod.yml up -d
```

4. Put Nginx in front of `127.0.0.1:8001` and keep SSL with Let\'s Encrypt, same style as Bewohner App.

## Suggested local validation before commit

```powershell
poetry run python manage.py compilemessages -l de -l en -l fa -l ar -l tr -l fr
poetry run python manage.py check
poetry run pytest
poetry run pre-commit run --all-files
docker compose build
docker compose up
```
