// Parameter file for infra/azure/main.bicep — fill in the <...> values.
// Secrets are read from environment variables so they never land in git:
//   export SECURITYOS_PG_PASSWORD='...'      # 12+ chars, mixed case + digit + symbol
//   export SECURITYOS_GHCR_TOKEN='...'       # only if the GHCR image is private
using './main.bicep'

param namePrefix = 'securityos'

// Built and pushed by .github/workflows/deploy-api-azure.yml
param apiImage = 'ghcr.io/dell-cloudthat/securityos-api:latest'
param registryUsername = ''                       // set to your GitHub username if the image is private
param registryPassword = readEnvironmentVariable('SECURITYOS_GHCR_TOKEN', '')

param postgresAdminPassword = readEnvironmentVariable('SECURITYOS_PG_PASSWORD')

// From your Entra External ID tenant (docs/deploy-azure.md, step 1)
param authIssuer = 'https://<tenant-id>.ciamlogin.com/<tenant-id>/v2.0'
param authAudience = '<api-app-client-id>'

// Your Vercel production domain, plus local dev
param corsOrigins = 'https://<your-app>.vercel.app,http://localhost:5173'
param corsOriginRegex = '^https://mobile-grc-[a-z0-9-]+-orculx\\.vercel\\.app$'

param minReplicas = 0
