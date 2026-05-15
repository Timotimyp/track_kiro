# TaskFlow — Team Task Manager

A Notion-styled, single-team task manager built from the original
`SmartTaskManagerDEMO` HTML mock. Visuals are intentionally a 1:1
port of the demo — same dark surfaces, badges, sidebar, dashboard,
filters, and modal flow.

The project is split into two services:

- `backend/` — FastAPI REST API backed by **Azure Cosmos DB** (NoSQL
  Core API). Falls back to an in-memory store when Cosmos is not
  configured, so local dev and tests work with no Azure account.
- `frontend/` — React + Vite + TypeScript SPA.

There is no authentication yet — the API is open and the UI assumes
a single "You (Owner)" user. Auth is intentionally deferred.

A Gemini-powered voice assistant is bundled — see
[Voice / AI assistant](#voice--ai-assistant) below.

## Quick start

### Backend

```bash
cd backend
uv sync
uv run uvicorn app.main:app --reload --port 8000
```

If `COSMOS_ENDPOINT` is not set, the backend uses an **in-memory** task
repository — perfect for local hacking. On first launch the store is
seeded with 8 example tasks plus the project/user reference data.
The in-memory repo is reset every time the process restarts.

To run against a real Cosmos DB, see
[Azure Cosmos DB setup](#azure-cosmos-db-setup) below.

Run the test suite:

```bash
uv run pytest
uv run ruff check .
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

The dev server proxies `/api/*` to `http://localhost:8000` (override
with `VITE_API_TARGET`). Run lint/build with:

```bash
npm run lint
npm run build
```

## REST API

| Method | Path                  | Purpose                                         |
| ------ | --------------------- | ----------------------------------------------- |
| GET    | `/api/health`         | Liveness probe                                  |
| GET    | `/api/projects`       | Reference list of projects                      |
| GET    | `/api/users`          | Reference list of assignees                     |
| GET    | `/api/tasks`          | List all tasks                                  |
| POST   | `/api/tasks`          | Create a task                                   |
| GET    | `/api/tasks/{id}`     | Read a task                                     |
| PATCH  | `/api/tasks/{id}`     | Partially update a task                         |
| DELETE | `/api/tasks/{id}`     | Delete a task                                   |
| POST   | `/api/assistant`      | Parse a free-form command into a task suggestion |

`Task` schema:

```
{
  id: str,                // UUIDv4 hex (Cosmos document id)
  title: str,
  desc: str,
  status: "todo" | "inprog" | "done",
  priority: "high" | "medium" | "low",
  tag: "dev" | "design" | "qa" | "pm",
  assignee: str,          // user code, e.g. "AK"
  due: date | null,
  due_time: str | null,   // optional "HH:MM" (24-hour)
  proj: str,              // project name (also the partition key)
  created_at: datetime,
  updated_at: datetime
}
```

> **Breaking change vs. the legacy SQLite version:** `id` is now a
> string instead of an integer. Cosmos DB requires string document
> ids; we use `uuid.uuid4().hex`.

## Azure Cosmos DB setup

The backend uses the **Cosmos DB NoSQL (Core) API**. Tasks are stored
as JSON documents in a single container partitioned by `/proj`
(project name) — the natural shard for this app since most queries
are scoped to a project.

### Create the account

```bash
RG=taskflow-rg
LOCATION=westeurope
ACCOUNT=taskflow-cosmos-$RANDOM

az group create -n $RG -l $LOCATION

az cosmosdb create \
  -g $RG \
  -n $ACCOUNT \
  --kind GlobalDocumentDB \
  --locations regionName=$LOCATION failoverPriority=0 isZoneRedundant=False \
  --default-consistency-level Session

# Database + container are also auto-created on first launch by the
# backend, but you can pre-create them:
az cosmosdb sql database create -g $RG -a $ACCOUNT -n taskflow
az cosmosdb sql container create -g $RG -a $ACCOUNT -d taskflow \
  -n tasks --partition-key-path "/proj" --throughput 400
```

### Configure the backend

Two auth modes are supported:

**Option A — Primary key (simplest, good for local dev):**

```bash
ENDPOINT=$(az cosmosdb show -g $RG -n $ACCOUNT --query documentEndpoint -o tsv)
KEY=$(az cosmosdb keys list -g $RG -n $ACCOUNT --query primaryMasterKey -o tsv)

export COSMOS_ENDPOINT="$ENDPOINT"
export COSMOS_KEY="$KEY"
export COSMOS_DATABASE=taskflow      # optional, default "taskflow"
export COSMOS_CONTAINER=tasks        # optional, default "tasks"

uv run uvicorn app.main:app --reload --port 8000
```

**Option B — Microsoft Entra ID (recommended for production):**

When the backend runs in Azure Container Apps with a managed identity
(or any environment where `DefaultAzureCredential` resolves), set:

```bash
export COSMOS_ENDPOINT="https://<account>.documents.azure.com:443/"
export COSMOS_USE_AAD=1
```

Grant the identity the **Cosmos DB Built-in Data Contributor** role on
the account:

```bash
PRINCIPAL_ID=<managed-identity-principal-id>
az cosmosdb sql role assignment create \
  -g $RG -a $ACCOUNT \
  --role-definition-id 00000000-0000-0000-0000-000000000002 \
  --principal-id $PRINCIPAL_ID \
  --scope "/"
```

No keys live in environment variables this way — auth is via federated
identity tokens.

### Local development without Cosmos

If neither `COSMOS_ENDPOINT` nor `COSMOS_USE_AAD` is set, the backend
falls back to `InMemoryTaskRepository`. You'll see a log line like:

```
WARNING  Using InMemoryTaskRepository — set COSMOS_ENDPOINT + COSMOS_KEY (or COSMOS_USE_AAD=1) to enable Azure Cosmos DB.
```

This is intentional: tests and quick local runs don't need an Azure
account, and the API surface is identical.

## Feature parity with the demo

The React app reproduces every interaction from `SmartTaskManagerDEMO`:

- Sidebar with **Dashboard / My Tasks / All / Overdue** plus the four
  hardcoded projects (Website Redesign, Backend API, Mobile App,
  Operations).
- Dashboard with four stat cards and an overall progress bar.
- Task table with checkbox, category/priority/status badges, assignee
  avatar, due date + optional time (red when overdue) and edit/delete
  row actions.
- New / edit task modal with priority, category, assignee, due date,
  optional time (`HH:MM`), and project.
- Filters (`All / To Do / In Progress / Done / High`) and sort
  (Due / Priority / Status).
- Global search across title and project name (`Ctrl/Cmd + K`).
- CSV export of all tasks.
- Toast notifications and `Esc` to close the modal.

No drag-and-drop. No hierarchical pages. Add them later.

## Voice / AI assistant

The top bar has a **🎙 AI** button. Click it, pick a language
(`Русский` / `English`), press **Запи́сать / Record**, and dictate
a free-form command like:

- _«Срочно почини баг с таймаутом оплаты на чекауте, поручи Beth, к пятнице»_
- _"Add a QA regression run for the mobile app v2.4 release next Wednesday, assign to Dana, medium priority"_

The browser does the speech-to-text via the Web Speech API
(Chrome / Edge work out of the box — Firefox/Safari fall back to text
input). The transcript is POSTed to `/api/assistant`, which prompts
Gemini with a strict JSON schema and returns:

```json
{
  "recommendation": "short explanation in user's language",
  "task": {
    "title": "...",
    "priority": "high|medium|low",
    "tag": "dev|design|qa|pm",
    "assignee": "AK|BL|CJ|DM|YO",
    "due": "YYYY-MM-DD" | null,
    "due_time": "HH:MM" | null,
    "proj": "Website Redesign|Backend API|Mobile App|Operations",
    ...
  },
  "conflict": null | {
    "conflicts": [{"id": str, "title": str, "due": "YYYY-MM-DD", "due_time": "HH:MM"}],
    "alternatives": [{"due": "YYYY-MM-DD", "due_time": "HH:MM"}]
  }
}
```

The frontend then opens the regular Task modal pre-filled with the
suggestion plus a recommendation banner — the user reviews and clicks
**Add Task**, so nothing is created without confirmation.

### Schedule-conflict detection

After Gemini returns a candidate task with both a date and a time, the
backend queries the task store for any existing task that occupies the
same `due` + `due_time` slot (exact HH:MM match — tasks have no
duration). With Cosmos DB this is a parameterised SQL query against the
container; with the in-memory repo it's a Python filter. If a clash is
found, the response carries a `conflict` block with up to 3
deterministically-computed free alternatives (`+1h`, `-1h`, `+2h`,
`-2h`, next day same time, …). The modal shows an ⚠️ banner with the
conflicting task(s) and a row of pill buttons — clicking one replaces
the form's date+time. The user can also press "Игнорировать и
сохранить как есть" to keep the original slot.

To enable Gemini, export your key before starting the backend:

```bash
export GEMINI_API_KEY=...   # https://aistudio.google.com/apikey
export GEMINI_MODEL=gemini-flash-latest   # optional override
uv run uvicorn app.main:app --reload --port 8000
```

Without the env var the backend returns `502` with a clear error
message; the rest of the app keeps working.

## Microsoft Azure integration

TaskFlow integrates with Azure in three optional ways. Each is wired
behind feature flags / env vars, so the app keeps working unchanged
when Azure isn't configured.

### Architecture

```
   Browser ──┬─ MSAL.js → login.microsoftonline.com ──► Entra ID
             │            (returns access token, ~1h)
             │
             ├─ axios with Authorization: Bearer <token>
             │            │
             ▼            ▼
   FastAPI backend ──────► Microsoft Graph
   (/api/assistant)        /me/calendarView
        │                  /me/events
        │
        └────────────────► Azure Cosmos DB (NoSQL Core API)
                           container: tasks, partition key: /proj
```

A single **App Registration** in Microsoft Entra ID provides the
`client_id` + `tenant_id` used by the SPA. The frontend uses the
SPA + PKCE flow (no client secret), gets a delegated access token,
and forwards it to the backend on every request that may need
calendar data. The backend never validates the token itself — it
forwards it to Graph, which is the ultimate authority. Tokens are
short-lived; there is no session storage or refresh logic on the
backend, which stays stateless.

### 1. Sign in with Microsoft

The topbar shows a "MS Sign in" button when `VITE_AZURE_CLIENT_ID` is
set. Click it → standard Microsoft consent popup → user is signed in
with their work or personal account.

```bash
# frontend/.env.local
VITE_AZURE_CLIENT_ID=00000000-0000-0000-0000-000000000000
VITE_AZURE_TENANT_ID=common   # or your tenant GUID
```

App Registration setup (one-time, ~5 min in
[https://portal.azure.com](https://portal.azure.com)):

1. **Microsoft Entra ID → App registrations → + New registration**
2. Name `TaskFlow`, *Supported account types* = "Accounts in any
   organizational directory and personal Microsoft accounts"
3. *Redirect URI* → **Single-page application (SPA)** →
   `http://localhost:5173`
4. After creation, copy `Application (client) ID` →
   `VITE_AZURE_CLIENT_ID`
5. **API permissions → Add a permission → Microsoft Graph →
   Delegated permissions**:
   - `User.Read` (default)
   - `Calendars.Read` (calendar conflict checks)
   - `Calendars.ReadWrite` (only needed for "Add to Outlook")
6. Click **Grant admin consent** if you have admin rights — otherwise
   each user consents on first sign-in.

### 2. Outlook Calendar — conflict detection

When the user is signed in, every call to `POST /api/assistant`
carries `Authorization: Bearer <graph-token>`. The backend reads it,
calls Graph's `/me/calendarView` over the slot's ±4h window, and
merges the returned events with TaskFlow's own occupied slots. The
response's `conflict.conflicts` array now contains both sources
distinguished by a `source` field (`"taskflow"` or `"outlook"`).
Alternatives are computed against both sources too, so a free slot
in TaskFlow that's already booked in Outlook will not be suggested.

Outlook events use real intervals (`start` / `end`); a TaskFlow task
is treated as a 60-minute point-in-time slot for overlap arithmetic.

No additional code is needed in the frontend — once a user signs in,
this just turns on.

### 3. Add to Outlook on save

The Task modal exposes a `📅 Also add to my Outlook Calendar`
checkbox when:

- The user is signed in with Microsoft, and
- The form has both a date and a time, and
- The user is creating a new task (not editing).

Ticking the box and clicking **Save Task** triggers
`POST /api/tasks?add_to_outlook=true` with the access token. The
backend creates a 60-minute event in the user's Outlook calendar
(subject = task title, body = description). Calendar creation is
best-effort: failures don't prevent the task from being saved.

### 4. Deploy to Azure (Static Web Apps + Container Apps)

The repo ships with `.github/workflows/deploy.yml`. On every push to
`main`, it:

1. Builds `frontend/dist` (env: `VITE_AZURE_CLIENT_ID`,
   `VITE_AZURE_TENANT_ID`, `VITE_API_BASE`) and publishes to **Azure
   Static Web Apps** (free tier).
2. Builds a Docker image from `backend/Dockerfile`, pushes to **Azure
   Container Registry**, and `az containerapp update`s the running
   **Azure Container App** with the new image, wiring up the Cosmos
   DB env vars.

OIDC federated identity is used for auth — no publish profiles or
service principal secrets in the repo. Required GitHub secrets and
vars are listed at the top of the workflow file.

First-time setup (manual, ~15 min):

```bash
RG=taskflow-rg
LOCATION=westeurope

az group create -n $RG -l $LOCATION

# Cosmos DB (see "Azure Cosmos DB setup" above for details)
az cosmosdb create -g $RG -n taskflow-cosmos-$RANDOM \
  --kind GlobalDocumentDB \
  --locations regionName=$LOCATION failoverPriority=0 isZoneRedundant=False \
  --default-consistency-level Session

# Backend
az acr create -n taskflowacr$RANDOM -g $RG --sku Basic --admin-enabled true
az containerapp env create -n taskflow-env -g $RG -l $LOCATION
az containerapp create -n taskflow-backend -g $RG \
  --environment taskflow-env \
  --image mcr.microsoft.com/azuredocs/containerapps-helloworld:latest \
  --ingress external --target-port 8000

# Frontend
az staticwebapp create -n taskflow-frontend -g $RG -l $LOCATION --sku Free

# OIDC federated identity (so GitHub Actions can deploy without secrets)
# Follow: https://learn.microsoft.com/azure/developer/github/connect-from-azure
```

After that, push the listed values into GitHub Actions
secrets/variables and the workflow takes over.

### CORS

The backend reads `CORS_ALLOW_ORIGINS` (comma-separated). For local
dev `*` is fine; in production set it to your Static Web App URL,
e.g. `https://taskflow-frontend.azurestaticapps.net`.
