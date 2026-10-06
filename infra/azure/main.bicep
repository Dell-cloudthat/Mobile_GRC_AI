// SecurityOS API on Azure — Container Apps + PostgreSQL Flexible Server.
//
// Deploy (see docs/deploy-azure.md for the full walkthrough):
//   az group create -n rg-securityos -l centralus
//   az deployment group create -g rg-securityos -f infra/azure/main.bicep -p infra/azure/main.bicepparam
//
// Creates:
//   - Log Analytics workspace (container logs)
//   - Container Apps environment + the API container app (HTTPS ingress)
//   - PostgreSQL 16 Flexible Server (TLS required) + the `securityos` database
//
// The API container runs migrations on start, then serves on port 8000.

targetScope = 'resourceGroup'

@description('Short name used to derive resource names, e.g. "securityos".')
@minLength(3)
@maxLength(16)
param namePrefix string = 'securityos'

@description('Azure region. Defaults to the resource group region.')
param location string = resourceGroup().location

@description('Container image for the API, e.g. ghcr.io/dell-cloudthat/securityos-api:latest')
param apiImage string

@description('Registry server for apiImage. Leave registryUsername empty for a public image.')
param registryServer string = 'ghcr.io'

@description('Registry username (for GHCR: your GitHub username). Empty = public image.')
param registryUsername string = ''

@description('Registry password (for GHCR: a token with read:packages). Empty = public image.')
@secure()
param registryPassword string = ''

@description('PostgreSQL administrator login name.')
param postgresAdminLogin string = 'securityosadmin'

@description('PostgreSQL administrator password (12+ chars, 3 of: upper, lower, digit, symbol).')
@secure()
@minLength(12)
param postgresAdminPassword string

@description('PostgreSQL compute SKU. Burstable B1ms suits a pilot; move to General Purpose for production load.')
param postgresSkuName string = 'Standard_B1ms'

@allowed([ 'Burstable', 'GeneralPurpose', 'MemoryOptimized' ])
param postgresSkuTier string = 'Burstable'

@description('Database storage in GiB.')
param postgresStorageGb int = 32

@description('OIDC issuer for access tokens (Entra External ID: https://<tenant-id>.ciamlogin.com/<tenant-id>/v2.0).')
param authIssuer string

@description('Expected token audience — the API app registration client ID (or its App ID URI).')
param authAudience string

@description('Optional JWKS URL override. Leave empty to discover it from authIssuer.')
param authJwksUrl string = ''

@description('Comma-separated browser origins allowed to call the API, e.g. https://app.example.com')
param corsOrigins string

@description('Optional regex for preview origins, e.g. ^https://mobile-grc-[a-z0-9-]+-orculx\\.vercel\\.app$')
param corsOriginRegex string = ''

@description('Minimum replicas. 0 = scale to zero when idle (cheapest; first request after idle is slower).')
@minValue(0)
param minReplicas int = 0

@minValue(1)
param maxReplicas int = 3

var suffix = uniqueString(resourceGroup().id)
var pgServerName = toLower('${namePrefix}-pg-${suffix}')
var databaseName = 'securityos'
var useRegistryAuth = !empty(registryUsername)

// ── Logs ──────────────────────────────────────────────────────────────────────

resource logs 'Microsoft.OperationalInsights/workspaces@2022-10-01' = {
  name: '${namePrefix}-logs-${suffix}'
  location: location
  properties: {
    sku: { name: 'PerGB2018' }
    retentionInDays: 30
  }
}

// ── PostgreSQL ────────────────────────────────────────────────────────────────

resource postgres 'Microsoft.DBforPostgreSQL/flexibleServers@2022-12-01' = {
  name: pgServerName
  location: location
  sku: {
    name: postgresSkuName
    tier: postgresSkuTier
  }
  properties: {
    version: '16'
    administratorLogin: postgresAdminLogin
    administratorLoginPassword: postgresAdminPassword
    storage: { storageSizeGB: postgresStorageGb }
    backup: {
      backupRetentionDays: 7
      geoRedundantBackup: 'Disabled'
    }
    highAvailability: { mode: 'Disabled' }
    // No delegated subnet → public access (restricted by the firewall rule below).
  }
}

resource database 'Microsoft.DBforPostgreSQL/flexibleServers/databases@2022-12-01' = {
  parent: postgres
  name: databaseName
  properties: {
    charset: 'UTF8'
    collation: 'en_US.utf8'
  }
}

// Allows connections from Azure services (Container Apps egress IPs are not fixed).
// For production, move both resources into a VNet and disable public access.
resource allowAzure 'Microsoft.DBforPostgreSQL/flexibleServers/firewallRules@2022-12-01' = {
  parent: postgres
  name: 'AllowAzureServices'
  properties: {
    startIpAddress: '0.0.0.0'
    endIpAddress: '0.0.0.0'
  }
}

resource requireTls 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2022-12-01' = {
  parent: postgres
  name: 'require_secure_transport'
  properties: {
    value: 'on'
    source: 'user-override'
  }
}

var databaseUrl = 'postgresql://${postgresAdminLogin}:${uriComponent(postgresAdminPassword)}@${postgres.properties.fullyQualifiedDomainName}:5432/${databaseName}?sslmode=require'

// ── Container Apps ────────────────────────────────────────────────────────────

resource environment 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: '${namePrefix}-env-${suffix}'
  location: location
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logs.properties.customerId
        sharedKey: logs.listKeys().primarySharedKey
      }
    }
  }
}

resource api 'Microsoft.App/containerApps@2024-03-01' = {
  name: '${namePrefix}-api'
  location: location
  properties: {
    managedEnvironmentId: environment.id
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: {
        external: true
        targetPort: 8000
        transport: 'auto'
        allowInsecure: false
      }
      secrets: concat(
        [ { name: 'database-url', value: databaseUrl } ],
        useRegistryAuth ? [ { name: 'registry-password', value: registryPassword } ] : []
      )
      registries: useRegistryAuth ? [
        {
          server: registryServer
          username: registryUsername
          passwordSecretRef: 'registry-password'
        }
      ] : []
    }
    template: {
      containers: [
        {
          name: 'api'
          image: apiImage
          resources: {
            cpu: json('0.5')
            memory: '1Gi'
          }
          env: [
            { name: 'ENV', value: 'prod' }
            { name: 'PORT', value: '8000' }
            { name: 'DATABASE_URL', secretRef: 'database-url' }
            { name: 'AUTH_ISSUER', value: authIssuer }
            { name: 'AUTH_AUDIENCE', value: authAudience }
            { name: 'AUTH_JWKS_URL', value: authJwksUrl }
            { name: 'CORS_ORIGINS', value: corsOrigins }
            { name: 'CORS_ORIGIN_REGEX', value: corsOriginRegex }
          ]
          probes: [
            {
              type: 'Startup'
              httpGet: { path: '/health', port: 8000 }
              initialDelaySeconds: 5
              periodSeconds: 5
              failureThreshold: 24
            }
            {
              type: 'Liveness'
              httpGet: { path: '/health', port: 8000 }
              periodSeconds: 30
            }
            {
              type: 'Readiness'
              httpGet: { path: '/health/ready', port: 8000 }
              periodSeconds: 15
            }
          ]
        }
      ]
      scale: {
        minReplicas: minReplicas
        maxReplicas: maxReplicas
        rules: [
          {
            name: 'http'
            http: { metadata: { concurrentRequests: '50' } }
          }
        ]
      }
    }
  }
  dependsOn: [ database, allowAzure, requireTls ]
}

output apiUrl string = 'https://${api.properties.configuration.ingress.fqdn}'
output apiAppName string = api.name
output postgresServer string = postgres.properties.fullyQualifiedDomainName
