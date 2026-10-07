# TAFASEEL Digital Workflow

Internal Arabic-first workflow system for leave/departure, vehicle mileage, and overtime requests. Department managers can submit leave/departure, overtime, and vehicle mileage (fuel) requests; their requests go to the Executive Manager and then HR. HR users can also submit requests, which go to the Executive Manager for final approval. Drawing employee requests are reviewed by the Production department manager and then HR. Factory Technician leave and overtime requests continue to require Drawing approval before HR review.

HR users can open the request archive to review approved requests submitted by employees and department managers in submission-date order, including their form data and decision history.

Each user sees only their latest notification; a new notification replaces the previous one, while the request and its history remain available in the request list.

Administrators can reset an active account's password from user management. The generated password is shown only in the reset response and is stored as a hash, never as plaintext.

## Run locally

1. Copy `.env.example` to `.env` and change the secret values.
2. Run `docker compose up --build`.
3. Open `http://localhost:8000`.

To run the API with a local Python environment instead, create the project environment, install the backend dependencies, and launch Uvicorn from the repository root:

```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
.\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --reload
```

The local command uses a SQLite database at `backend/tafaseel.db`, so PostgreSQL or Docker is not required for development. Docker Compose continues to use PostgreSQL through the `DATABASE_URL` in `.env`.

The API documentation is available at `/docs`. On first start with SQLite, the application creates the schema and ensures the built-in roles, eight approved departments, request types, and default workflows. Assign and activate a department manager for Production before Drawing employees submit requests; their requests require that manager's approval. The application does not create an administrator account.

For a SQLite database created by an older version of the app without Alembic tracking, apply the additive approval-route migration once before using the updated request flow:

```powershell
.\.venv\Scripts\python.exe -m alembic -c backend\alembic.ini stamp 20260921_0001
.\.venv\Scripts\python.exe -m alembic -c backend\alembic.ini upgrade head
```

## Architecture

- `app/modules/auth`: JWT authentication and password hashing
- `app/modules/users`: users, roles, departments, RBAC
- `app/modules/requests`: dynamic form definitions and request lifecycle
- `app/modules/workflows`: configurable approval steps
- `app/modules/approvals`: approval decisions
- `app/modules/notifications`: in-app notifications
- `app/modules/audit`: immutable request history

Form fields and approval steps are stored in PostgreSQL. Adding a request type or changing its workflow does not require a database redesign.
