# Deploy SecurityOS: Azure API + Entra External ID + Vercel web app

```
 Phone / browser ──► Vercel (apps/web, React)
                         │  sign-in: Entra External ID (MSAL)
                         │  Bearer token
                         ▼
                 Azure Container Apps (backend, FastAPI)  ──►  Azure PostgreSQL 16
```

Time: about 45 minutes the first time. You need the Azure CLI (`az`), owner rights on
an Azure subscription, and admin on the GitHub repo and Vercel project.

---

## Step 1 — Entra External ID (sign-in)

1. **Create an external tenant.** Entra admin center → *Overview → Manage tenants →
   Create → External*. Note its **subdomain** (e.g. `securityos` →
   `securityos.ciamlogin.com`) and **Tenant ID**.

2. **Register the API** (in the external tenant): *App registrations → New registration*
   - Name `SecurityOS API`, single tenant, no redirect URI.
   - *Expose an API* → set Application ID URI (accept `api://<api-client-id>`) →
     *Add a scope* `access_as_user` (admins and users, enabled).
   - *Manifest* → set `"accessTokenAcceptedVersion": 2` (on the newer manifest view:
     `"api": { "requestedAccessTokenVersion": 2 }`).
   - *Token configuration → Add optional claim → Access* → `email`, `given_name`,
     `family_name`. (Names and emails show up in the app and the audit log.)
   - Note the API's **Application (client) ID**.

3. **Register the web app**: *New registration*
   - Name `SecurityOS Web`, platform **Single-page application**, redirect URIs:
     `http://localhost:5173` and your Vercel production URL (e.g. `https://<app>.vercel.app`).
   - *API permissions → Add → My APIs → SecurityOS API → access_as_user* → **Grant admin consent**.
   - Note the web app's **Application (client) ID**.

4. **User flow**: *External Identities → User flows → New user flow* (sign up and sign in,
   Email with password). Under *Applications*, add **SecurityOS Web**.

5. **Values you now have**

   | Name | Example |
   |---|---|
   | Authority (web) | `https://securityos.ciamlogin.com/` |
   | Issuer (API) | `https://<tenant-id>.ciamlogin.com/<tenant-id>/v2.0` |
   | Audience (API) | `<api-client-id>` |
   | Scope (web) | `api://<api-client-id>/access_as_user` |
   | Web client ID | `<web-client-id>` |

   **Confirm issuer and audience before deploying:** sign in once (step 5), copy an
   access token from the browser's network tab, paste it into <https://jwt.ms>, and check
   `iss` and `aud` match. If `aud` shows `api://...` instead of a GUID, use that as the
   audience.

---

## Step 2 — Build the API image

Push to `main` (or run **Actions → Deploy API to Azure → Run workflow**). The workflow
runs the test suite against Postgres, then pushes
`ghcr.io/dell-cloudthat/securityos-api:latest`. The Azure deploy job is skipped until
step 4.

If the package is private (GitHub → your profile → Packages → `securityos-api`), either
make it public or give Bicep a token with `read:packages` (see the param file).

---

## Step 3 — Create the Azure resources

```bash
az login
az group create -n rg-securityos -l centralus

# Fill in authIssuer, authAudience, corsOrigins in infra/azure/main.bicepparam first.
export SECURITYOS_PG_PASSWORD='<12+ chars, mixed case, digit, symbol>'
az deployment group create -g rg-securityos \
  -f infra/azure/main.bicep -p infra/azure/main.bicepparam \
  --query properties.outputs
```

Output includes `apiUrl` (e.g. `https://securityos-api.<id>.centralus.azurecontainerapps.io`).
Check it: `curl $apiUrl/health/ready` → `{"status":"ok","database":"postgresql"}`.

What gets created: Log Analytics workspace, Container Apps environment, the
`securityos-api` container app (HTTPS, scales 0–3), PostgreSQL 16 Flexible Server
(Burstable B1ms, TLS required, 7-day backups) with a `securityos` database. Migrations run
automatically each time the container starts.

> Security note: Postgres allows connections from Azure services via a firewall rule,
> because Container Apps egress IPs aren't fixed. Before production customers, move the
> API and database into a VNet and turn off public access.

---

## Step 4 — Automatic deploys from GitHub

Let GitHub roll out new images with OpenID Connect (no stored Azure passwords):

```bash
SUB=$(az account show --query id -o tsv)
APP=$(az ad app create --display-name securityos-github-deploy --query appId -o tsv)
az ad sp create --id $APP
az role assignment create --assignee $APP --role Contributor \
  --scope /subscriptions/$SUB/resourceGroups/rg-securityos
az ad app federated-credential create --id $APP --parameters '{
  "name": "github-main",
  "issuer": "https://token.actions.githubusercontent.com",
  "subject": "repo:Dell-cloudthat/Mobile_GRC_AI:environment:production",
  "audiences": ["api://AzureADTokenExchange"]
}'
echo "AZURE_CLIENT_ID=$APP  AZURE_TENANT_ID=$(az account show --query tenantId -o tsv)  AZURE_SUBSCRIPTION_ID=$SUB"
```

In GitHub → *Settings → Environments* create `production`. Then *Settings → Secrets and
variables → Actions → Variables* add: `AZURE_CLIENT_ID`, `AZURE_TENANT_ID`,
`AZURE_SUBSCRIPTION_ID`, `AZURE_RESOURCE_GROUP=rg-securityos`,
`AZURE_CONTAINERAPP_NAME=securityos-api`.

(`AZURE_TENANT_ID` here is your **Azure subscription's** tenant, not the external
sign-in tenant.)

---

## Step 5 — Point the Vercel app at the API

Vercel → your project → *Settings → Environment Variables* (Production and Preview):

| Variable | Value |
|---|---|
| `VITE_API_BASE_URL` | the `apiUrl` from step 3 |
| `VITE_AUTH_MODE` | `entra` |
| `VITE_ENTRA_CLIENT_ID` | web client ID |
| `VITE_ENTRA_AUTHORITY` | `https://<subdomain>.ciamlogin.com/` |
| `VITE_ENTRA_API_SCOPE` | `api://<api-client-id>/access_as_user` |

Redeploy. Without `VITE_API_BASE_URL` the app runs in **demo mode** (data stays in the
browser), so existing previews keep working.

Preview deployments get a new URL each time. They can call the API thanks to
`corsOriginRegex`, but Entra only redirects to registered URIs, so sign in on the
production URL or add a stable preview alias as a redirect URI.

---

## Step 6 — First sign-in

1. Open the Vercel URL → **Sign in** → create an account.
2. Create your organization (you become **admin**; tick "I run this business" to also
   become **executive**).
3. *Settings → Team* → invite engineers and an executive. Each invite is a single-use
   link that expires in 7 days.
4. Verify the audit chain any time: `GET /api/v1/securityos/organizations/<org-id>/audit/verify`.

---

## Run everything locally (no Azure, no Entra)

```bash
openssl genrsa -out backend/dev_key.pem 2048
docker compose up --build                      # Postgres + API with dev sign-in
cd apps/web && cp .env.example .env.local && npm install && npm run dev
```

Open <http://localhost:5173> and sign in with any name (dev mode only; the dev sign-in
endpoint does not exist when `ENV=prod`).

## Troubleshooting

| Symptom | Fix |
|---|---|
| API returns 401 "Token signature verification failed" | Issuer or audience mismatch: compare `iss`/`aud` at jwt.ms with `AUTH_ISSUER`/`AUTH_AUDIENCE`. If discovery fails, set `authJwksUrl` to `https://<subdomain>.ciamlogin.com/<tenant-id>/discovery/v2.0/keys`. |
| Browser shows a CORS error | Add the exact origin to `corsOrigins` and redeploy step 3. |
| `/health/ready` → `migrations pending` | Restart the revision; the entrypoint migrates on start. |
| Container won't start, log says `DATABASE_URL must be set` | The `database-url` secret is missing; rerun step 3. |
