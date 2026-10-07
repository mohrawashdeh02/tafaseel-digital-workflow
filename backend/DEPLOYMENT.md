# Deployment

## Docker Compose

Set a production `JWT_SECRET` in `.env`, then start the stack with:

```sh
docker compose up --build -d
```

The API and Arabic web interface are served on port 8000. Put a reverse proxy with TLS in front of the API in production and restrict database access to the application network. Startup ensures the built-in roles, approved departments, request types, and default workflows. Provision an administrator account before using the interface.

## Migration workflow

Generate migrations after model changes:

```sh
docker compose exec api alembic revision --autogenerate -m "describe change"
docker compose exec api alembic upgrade head
```

For a production deployment, run `alembic upgrade head` as a release step before starting the new app version.
