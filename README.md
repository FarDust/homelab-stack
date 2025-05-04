# Homelab Stack

This repository contains a comprehensive Docker Swarm stack for self-hosting various services in a homelab environment. The stack is designed to be modular, secure, and easy to deploy.

## Table of Contents

- [Architecture](#architecture)
  - [Stack Dependencies](#stack-dependencies)
- [System Requirements](#system-requirements)
- [Prerequisites](#prerequisites)
  - [Network Configuration](#network-configuration)
  - [Accounts & API Keys](#accounts--api-keys)
- [Dynamic IP Management](#dynamic-ip-management)
- [Initial Setup](#initial-setup)
- [Security & Authentication](#security--authentication)
- [SSL Certificates with Cloudflare DNS Challenge](#ssl-certificates-with-cloudflare-dns-challenge)
- [Monitoring & Observability](#monitoring--observability)
- [Database Recommendations](#database-recommendations)
- [Specialized Stacks](#specialized-stacks)
- [Custom Stack Development](#custom-stack-development)
- [Backup & Disaster Recovery](#backup--disaster-recovery)
- [Service Access](#service-access)
- [Customization](#customization)
- [LLM Services](#llm-services)
- [LLM Services & Use Cases](#llm-services--use-cases)
- [Step-by-Step Deployment Guide](#step-by-step-deployment-guide)
  - [Manual Deployment](#manual-deployment)
  - [Automated CI/CD Deployment](#automated-cicd-deployment-using-github-actions)
  - [Verification and Troubleshooting](#verification-and-troubleshooting)
  - [Post-Deployment Setup](#post-deployment-setup)

## Architecture

The homelab stack is organized around several core components:

- **Traefik**: Reverse proxy and edge router providing SSL termination, routing, and load balancing
- **Authelia**: Single Sign-On (SSO) authentication for your services
- **Monitoring**: Prometheus and Grafana for metrics collection and visualization
- **Databases**: PostgreSQL, InfluxDB, and Redis for various storage needs
- **LLMs**: Local AI models with Ollama, AnythingLLM, LocalAI, and LiteLLM

The stack is separated into logical service groups:

- `traefik-stack.yml`: Core infrastructure (Traefik, Authelia, Portainer, Prometheus, Grafana)
- `database-stack.yml`: Database services (PostgreSQL, InfluxDB, Redis)
- `dns-stack.yml`: DNS services
- `llms-stack.yml`: Local large language models
- And many more specialized stacks for specific use cases

### Reverse Proxy Architecture

The core of this homelab stack is the Traefik reverse proxy, which provides:

1. **Central Entry Point**: All traffic to services flows through Traefik, allowing for:
   - Unified SSL/TLS termination
   - Consistent authentication via Authelia
   - Standardized routing rules
   - Load balancing across service replicas

2. **Automatic SSL Certificate Management**:
   - Let's Encrypt integration for auto-renewing certificates
   - DNS challenge for wildcard certificates via Cloudflare
   - Certificate management for internal services

3. **Service Discovery**:
   - Docker Swarm integration for automatic service detection
   - Dynamic configuration updates without restarts
   - Health checking and automatic failover

4. **Routing Configuration**:
   Each service in the stack includes Traefik labels that define:
   - Which host/domain the service is available at
   - Whether authentication is required
   - SSL certificate requirements
   - Redirection rules (HTTP to HTTPS)
   - Load balancing configuration

The typical request flow works like this:

```
Client → Traefik (Entry Point) → [Optional: Authelia Auth] → Target Service → Response
```

Key components in this flow:

- **Entry Points**: `web` (HTTP/80) and `websecure` (HTTPS/443)
- **Middlewares**: Authentication, redirections, headers, etc.
- **Routers**: Match the request to the appropriate service
- **Services**: The actual backend services handling requests

Traefik also provides a dashboard for monitoring and managing routes at `dashboard.local.yourdomain.com`.

### Testing Your Deployment with Curl

For those new to homelab setups, here are some useful curl commands to test your deployment:

#### 1. Check if Traefik is Running

```bash
# Test Traefik's health endpoint
curl -kI https://dashboard.local.yourdomain.com/ping
```

A successful response will return a `200 OK` status.

#### 2. Test a Protected Service

```bash
# Try accessing a protected service (will be redirected to Authelia)
curl -kI https://grafana.yourdomain.com
```

You'll see a redirection to the Authelia authentication page.

#### 3. Test an API Service (LLM Stack)

```bash
# Test Ollama API endpoint
curl -k https://ollama.yourdomain.com/api/tags

# Test a basic prompt with Ollama (if models are loaded)
curl -k -X POST https://ollama.yourdomain.com/api/generate -d '{
  "model": "phi4-mini",
  "prompt": "What is Docker Swarm?",
  "stream": false
}'
```

#### 4. Testing with Authentication

```bash
# Store authentication cookies in a file
curl -k -c cookies.txt -X POST https://auth.yourdomain.com/api/firstfactor \
  -H "Content-Type: application/json" \
  -d '{"username":"your_username","password":"your_password"}'

# Use the cookies to access a protected service
curl -k -b cookies.txt https://grafana.yourdomain.com
```

#### Troubleshooting with Curl

If you're having issues with a service, try these commands:

```bash
# Check HTTP status with full headers
curl -kI https://service.yourdomain.com

# Test connections with verbose output
curl -kv https://service.yourdomain.com

# Test with a specific Host header (for virtual hosting)
curl -k -H "Host: service.yourdomain.com" https://your-server-ip
```

### Stack Dependencies

> **IMPORTANT**: The `traefik-stack.yml` is the core foundation required by all other stacks for secure routing and authentication.

Here's how the stacks depend on each other:

1. **Core Requirements**
   - `traefik-stack.yml` - Required by all other stacks
   
2. **Optional Stacks with Dependencies**
   - `database-stack.yml` - Required if not using SaaS database providers
   - All other stacks depend on both Traefik and appropriate database services

## System Requirements

### Minimum Hardware (Core Traefik Stack only)
- CPU: Dual-core CPU (Intel Pentium G4400 or equivalent)
- RAM: 4GB minimum
- Storage: 20GB for Docker images and configuration
- Network: Stable internet connection for SSL certificates

### Recommended Hardware (Full Stack including LLMs)
- CPU: Quad-core CPU or better
- RAM: 16GB minimum (32GB recommended for running multiple LLMs)
- GPU: Dedicated GPU for AI model acceleration (optional but recommended)
- Storage: 100GB+ SSD for Docker images, data, and model storage
- Network: High-speed internet connection

> **Note**: The current deployment is running on an Intel Pentium G4400 (2 cores @ 3.3GHz) with 8GB RAM, which is sufficient for the core services but may struggle with multiple LLM services running simultaneously.

## Prerequisites

### Required

- A server or computer meeting minimum hardware requirements
- Docker and Docker Compose installed
- Docker Swarm initialized
- A domain name you own (for proper SSL certificates and service routing)
- A Cloudflare account with your domain managed through it (for DNS validation)
- Either:
  - Tailscale VPN + NextDNS setup (for local domain access), or
  - Public DNS records pointing to your server

### Network Configuration

For local domain access, this setup uses:
- **Tailscale VPN**: Provides secure remote access to your homelab
- **NextDNS**: Custom DNS configuration for local domain resolution

Alternative methods include:
- Local DNS server (e.g., Pi-hole)
- Split-horizon DNS
- Host file modifications

### Accounts & API Keys

- Cloudflare API tokens:
  - DNS API token with Zone:DNS:Edit permissions
  - Zone API token with Zone:Zone:Read permissions
- (Optional) SendGrid account for email notifications
- (Optional) Google OAuth credentials for Grafana authentication
- (Optional) SaaS Database providers:
  - Supabase, Amazon RDS, or Digital Ocean for PostgreSQL
  - InfluxDB Cloud for time-series data
  - Redis Labs for Redis

## Dynamic IP Management

For homelab setups without a static IP address (which is common), you'll need a way to keep your domain pointing to your changing IP address.

### Recommended Solution: FreeMyIP with Cloudflare

This stack works well with [FreeMyIP](https://freemyip.com/) which provides free dynamic DNS updates that integrate with Cloudflare:

1. **Register and Set Up FreeMyIP**:
   - Create an account on FreeMyIP.com
   - Add your domain and get an update key
   - Configure a scheduled task to update your IP address

2. **Cloudflare Configuration**:
   - Create a CNAME record for your domain pointing to your FreeMyIP subdomain
   - Or use FreeMyIP to directly update your Cloudflare A records

3. **Example Docker Service**:

```yaml
services:
  freemyip-updater:
    image: alpine/curl:latest
    command: sh -c "while true; do curl -s 'https://freemyip.com/update?token=YOUR_TOKEN&domain=YOUR_DOMAIN.freemyip.com'; sleep 300; done"
    restart: always
```

### Alternative Solutions

- **DuckDNS**: Another free dynamic DNS provider
- **Cloudflare API Scripts**: Direct updates using the Cloudflare API
- **Dynamic DNS Client**: Use a DDNS client like ddclient
- **Tailscale/ZeroTier**: For VPN-based access without public DNS

> **Note**: When using dynamic DNS solutions, you may experience brief periods of unavailability during IP changes. Services like Cloudflare offer a proxy feature that can help mitigate this issue by caching the connection.

## Initial Setup

### 1. Clone the Repository

```bash
git clone https://github.com/yourusername/homelab-stack.git
cd homelab-stack
```

### 2. Create Required Networks

```bash
# Create the main Traefik networks
docker network create -d overlay --attachable traefik
docker network create -d overlay --attachable traefik-public

# Create DNSCrypt network (if using DNS services)
docker network create -d overlay --attachable --subnet=<subnet CIDR BLOCK> --ip-range=10.0.9.0/28 dnscrypt-network
```

### 3. Set Up Secrets

Create the necessary secrets files in the `secrets/` directory. Each service requires specific secrets:

```bash
# Example for creating Cloudflare API token secrets
echo "your-dns-api-token" > secrets/cloudflare/dns_api_token
echo "your-zone-api-token" > secrets/cloudflare/zone_api_token

# Set up Authelia secrets
echo "your-secure-password" > secrets/authelia/postgres_password
# ... and other required secrets
```

### 4. Configure Environment Variables

Create a `.env` file at the root of the repository with your domain and other configurations:

```
DOMAIN_NAME=yourdomain.com
LOCAL_DOMAIN=home.yourdomain.com
MAINTAINER_EMAIL=your-email@example.com
TRUSTED_IPS=127.0.0.1/32,10.0.0.0/8
CONFIG_VERSION=1
# ... other required variables
```

### 5. Deploy Core Services

Before deploying the Traefik stack, deploy the database stack:

```bash
docker stack deploy -c source/database-stack.yml db
```

> **Note**: The database-stack is only required if you are NOT using SaaS database providers like Supabase, Amazon RDS, etc. If you are using external SaaS database services, you can skip this step.

Start with the core infrastructure:

```bash
docker stack deploy -c source/traefik-stack.yml traefik
```

Then deploy additional stacks as needed:

```bash
# Example: Deploy LLM stack
docker stack deploy -c source/llms-stack.yml llms
```

## Security & Authentication

The stack uses Authelia for Single Sign-On (SSO) and Multi-Factor Authentication (MFA). This provides a centralized authentication layer for services that:

1. Are exposed to the public internet
2. Have higher permissions over the host (like Portainer)

### Authentication Methods

The following authentication methods are configured:

- **First Factor**: Username/password authentication against a file-based user database
- **Second Factor**: 
  - Duo Push mobile notifications (default)
  - TOTP (Time-based One-Time Password)
  - WebAuthn (hardware security keys)

### Security Recommendations

For production deployment, follow these security best practices:

1. **Authentication Policies**:
   - Use two-factor authentication for all internet-exposed services
   - Use at least one-factor for internal services with sensitive data
   - Consider using bypass policy only for non-sensitive internal tools

2. **User Management**:
   - Create individual user accounts for each person
   - Assign appropriate access levels using Authelia's access control rules
   - Regularly audit user access and remove unused accounts

3. **MFA Setup**:
   - Enroll at least two second-factor methods per user (e.g., Duo Push + TOTP)
   - Use security keys (WebAuthn) for maximum security where available
   - Set a short inactivity timeout (default is 15 minutes)

4. **Advanced Settings**:
   - Enforce strong password policies using the built-in zxcvbn scoring
   - Configure brute force protection (max 3 retries with 5 minute ban time)
   - Use secure cookies with appropriate SameSite settings

### Example Authelia Configuration

The stack includes a pre-configured Authelia setup with:
- PostgreSQL database backend for storage
- Redis for session management
- SendGrid SMTP for notifications
- Default two-factor authentication policy
- Integration with Traefik for route protection

## SSL Certificates with Cloudflare DNS Challenge

This stack uses Traefik's Let's Encrypt integration with Cloudflare DNS challenge for SSL certificates. This configuration allows:

1. **Wildcard Certificates**: Cover all subdomains with a single certificate
2. **Internal/Private Services**: Generate valid certificates for non-public services
3. **No Port 80 Exposure**: No need to open port 80 to the internet for HTTP challenges

### Required Cloudflare Permissions

For the DNS challenge to work properly, you need two separate Cloudflare API tokens:

1. **DNS API Token** (Zone:DNS:Edit permissions):
   - Used by Traefik to create and clean up TXT records for Let's Encrypt validation
   - Store in `secrets/cloudflare/dns_api_token`

2. **Zone API Token** (Zone:Zone:Read permissions):
   - Used by Traefik to get information about your domain zones
   - Store in `secrets/cloudflare/zone_api_token`

### Configuration Notes

- Set the `CF_DNS_API_TOKEN_FILE` and `CF_ZONE_API_TOKEN_FILE` environment variables in the Traefik service
- Use the `--certificatesResolvers.le-dns.acme.dnschallenge.provider=cloudflare` Traefik parameter
- For each service, set `traefik.http.routers.[service-name].tls.certresolver=le-dns` to use DNS challenge
- Internal services should use the LOCAL_DOMAIN setting with the DNS challenge to generate valid certificates

> **Note**: Cloudflare is the recommended provider, but Traefik supports many other DNS providers if needed.

## Monitoring & Observability

The stack includes a robust monitoring solution based on Prometheus and Grafana to help you keep track of your homelab's health and performance. This is especially important when running multiple stacks with varying resource requirements.

> **Note**: While basic monitoring is included in the traefik-stack, deploying the dedicated monitoring-stack.yml is highly recommended to squeeze the full potential of Grafana with additional data sources, collectors, and specialized dashboards.

### Key Metrics Monitored

The monitoring stack is configured to track:

1. **Docker Resource Usage by Stack**:
   - Container CPU and memory usage
   - Container states and health
   - Volume utilization
   - Network I/O by service

2. **System Performance**:
   - Host CPU, memory, and disk usage
   - System load averages
   - Network throughput
   - Swap usage

3. **Traefik Performance**:
   - Request counts and rates by entrypoint and router
   - Response times and status codes
   - TLS handshake metrics
   - Error rates and types

### Dashboard Setup

The monitoring stack includes pre-configured dashboards for:

- **Traefik Dashboard**: Visualize request flow, response times, and error rates
- **Docker Overview**: Monitor container health and resource usage across all stacks
- **System Performance**: Track system-wide metrics to identify bottlenecks
- **Network Performance**: Monitor internet connectivity and internal network metrics

### Alert Configuration

Prometheus is configured with alerting rules for common failure scenarios:

- High system load (>80% CPU for >5 minutes)
- Memory pressure (>90% usage)
- Container failures or restarts
- Disk space warnings (>85% usage)
- Traefik error rate spikes

### Accessing Monitoring

- **Grafana**: https://grafana.yourdomain.com (protected by Authelia)
- **Prometheus**: https://prometheus.yourdomain.com (internal access only)

### Resource Considerations

The monitoring stack itself is designed to be lightweight:

- Prometheus uses efficient time-series compression
- Data retention is set to 15 days by default
- Grafana dashboards use minimal browser resources

For resource-constrained systems, consider:
- Reducing the scrape frequency in prometheus.yml
- Limiting the metrics collected from less critical services
- Adjusting retention periods for long-term storage

### Tips for Effective Monitoring

1. **Resource Allocation Monitoring**:
   - Track resource usage patterns over time to identify opportunities for optimization
   - Monitor for resource contention between stacks, especially when running LLM services

2. **Performance Troubleshooting**:
   - Use the Traefik dashboard to identify slow services or routing issues
   - Correlate system load with specific service deployments or updates

3. **Health Checks**:
   - Monitor container restart counts to identify unstable services
   - Set up alerts for persistent failures

4. **Storage Monitoring**:
   - Track volume growth rates to forecast storage needs
   - Monitor backup job performance and completion

By keeping an eye on these metrics, you can ensure your homelab runs smoothly and proactively address issues before they impact service availability.

## Database Recommendations

While the included database stack is suitable for testing and development, for production use consider:

- **PostgreSQL**: Use a managed service like Supabase, Amazon RDS, or Digital Ocean Managed Databases
- **InfluxDB**: Consider InfluxDB Cloud for time-series data
- **Redis**: Look at Redis Labs or other managed Redis offerings

> **IMPORTANT**: The database-stack becomes a requirement if you are not using SaaS database providers. For production use, it's highly recommended to migrate to managed database services for better reliability, backups, and scaling capabilities.

## Specialized Stacks

The repository includes several specialized stacks tailored for specific use cases, allowing you to pick and choose which components to deploy based on your needs.

### Financial Services (`financial-stack.yml`)

A collection of services for personal finance management and automation:

- **Firefly III**: Open-source personal finance manager for tracking expenses, income, and budgets
- Helps automate financial record-keeping with importing capabilities
- Connects with various banking APIs (with proper configuration)
- Provides visualization and reporting of financial data

> **Note**: This stack is a work in progress and provides basic functionality. It's designed for personal finance tracking and can be extended based on individual needs.

### Business Intelligence (`bi-stack.yml`)

Leverages data engineering tools to provide analytics capabilities:

- Includes services to convert standard SQL databases into analytics engines
- Useful for data professionals who want to analyze data from various sources
- Supports transformation and visualization of complex datasets
- Integrates with the database stack for persistent data storage

### Home Automation (`home-stack.yml`)

Contains services related to home automation and IoT:

- **Home Assistant**: Central hub for smart home control and automation
- **Mosquitto**: MQTT broker for IoT device communication
- Enables monitoring and control of smart home devices
- Provides dashboards for visualizing home data

### Programming Tools (`programming-stack.yml`)

Development environments and tools for programming:

- Code servers and development environments
- Tools for continuous integration and testing
- Documentation and knowledge management systems

### Connectivity Options

All specialized stacks:
- Integrate with the core Traefik infrastructure for secure routing
- Can be accessed via the Tailscale VPN for remote usage
- Leverage the authentication system when appropriate
- Use the database stack for persistent storage

## Custom Stack Development

You can create your own specialized stacks by:

1. Creating a new YAML file in the `source/` directory
2. Defining the required services, networks, and volumes
3. Adding appropriate Traefik labels for routing
4. Including any necessary configurations or secrets

Example of a minimal custom stack:

```yaml
version: "3.7"
services:
  my-custom-service:
    image: service-image:latest
    networks:
      - traefik
    volumes:
      - my-data:/data
    deploy:
      labels:
        - traefik.enable=true
        - traefik.http.routers.my-service.rule=Host(`service.${LOCAL_DOMAIN}`)
        - traefik.http.routers.my-service.entrypoints=websecure
        - traefik.http.routers.my-service.tls=true
        - traefik.http.routers.my-service.tls.certresolver=le-dns
        - traefik.http.services.my-service.loadbalancer.server.port=8080
networks:
  traefik:
    external: true
volumes:
  my-data: {}
```

## Backup & Disaster Recovery

The homelab stack requires proper backup and recovery strategies to ensure data persistence and quick recovery in case of failures. Below are the recommended approaches for managing backups and implementing disaster recovery.

### Recommended Backup Strategy

#### Configuration Files
For read-only configuration files, the recommended approach is:

1. **Google Cloud Storage (GCS) Mounted Buckets**:
   - Store all configuration files in GCS buckets
   - Mount these buckets to your Docker hosts
   - Set appropriate access controls and versioning
   - Example mount configuration:
   ```yaml
   volumes:
     - type: volume
       source: gcs-configs
       target: /configs
       volume:
         driver: rclone
         driver_opts:
           type: google cloud storage
           remote: gcs-homelab-config:/configs
   ```

#### Database Data
For databases with write loads:

1. **Distributed Compatible Drivers**:
   - For scalable setups, use FileStore from GCP or equivalent
   - Configure regular automated backups to cloud storage
   - Implement point-in-time recovery options

2. **Database-Specific Backup Solutions**:
   - PostgreSQL: Use `pg_dump` with scheduled execution
   - InfluxDB: Use the built-in backup utility
   - Redis: Configure RDB snapshots and AOF persistence

#### Secrets Management

The stack is designed to be forked and maintained with secrets managed through:

1. **GCP Secret Manager Integration**:
   - Store all sensitive credentials in GCP Secret Manager
   - Configure GitHub Actions to access secrets securely
   - Rotate secrets regularly

2. **Security Best Practices**:
   - Keep the forked repository public for community contributions
   - Use tools like GitGuardian to prevent accidental credential exposure
   - Implement secret scanning in CI/CD pipelines

### Disaster Recovery Procedures

In case of system failure, follow these steps to restore your homelab:

1. **Full System Recovery**:
   - Reinstall the base OS (Ubuntu recommended)
   - Install Docker and initialize a swarm
   - Clone your forked repository
   - Restore configuration from GCS buckets
   - Deploy core stacks in the correct order (traefik-stack first)
   - Restore database volumes from backups

2. **Partial Recovery**:
   - For service-specific issues, redeploy the affected stack
   - For database corruption, restore from the latest backup
   - For configuration issues, revert to a previous version from GCS

## Service Access

Once deployed, your services will be available at the following URLs:

- Traefik Dashboard: https://dashboard.yourdomain.com
- Portainer: https://portainer.yourdomain.com
- Grafana: https://grafana.yourdomain.com

All secured services will require authentication through Authelia at https://auth.yourdomain.com and would be redirected to the appropriate service after successful login.

## Customization

The stack is designed to be modular. You can:

1. Add new services by creating additional stack files
2. Modify existing services by editing the YAML files
3. Configure Traefik routing by adding the appropriate labels to your services

## LLM Services

The included LLM stack provides:

- **Ollama**: Local inference server with various models
- **AnythingLLM**: Document-based chatbot with knowledge base capabilities
- **LiteLLM**: Proxy to standardize access to various LLM providers
- **LocalAI**: A drop-in replacement for OpenAI API

These services require significant resources, especially RAM and GPU for larger models. With limited hardware:

- Limit yourself to smaller models (1B-7B parameters)
- Avoid running CPU-intensive tasks concurrently with LLM services

## LLM Services & Use Cases

The stack includes several powerful local AI model services that allow you to self-host and run LLMs without relying on external cloud APIs. This enables:

- **Data Privacy**: Process sensitive or personal data without sending it to third-party services
- **Experimentation**: Test different models and configurations in a safe environment
- **Edge Device Testing**: Prototype edge AI deployments before deploying to constrained devices

### Available LLM Services

The LLM stack provides several complementary services:

#### Ollama
- **Description**: High-performance interface for running local models
- **Available Models**: gemma3, llama3.2, phi4-mini, mistral, neural-chat, and more
- **Hardware Recommendation**: 4GB+ RAM, ideally with GPU acceleration
- **Best For**: 
  - Quick personal assistants without data leaving your network
  - Document analysis and content generation
  - Code completion and debugging assistance
  - Running optimized smaller models (1B-7B parameters)

#### AnythingLLM
- **Description**: Document-based chatbot with knowledge base and RAG capabilities
- **Integration**: Connects to both Ollama (direct) and LiteLLM (proxy) for flexible model usage
- **Best For**:
  - Creating chatbots from your personal documents (PDFs, text files)
  - Building searchable knowledge bases from private data
  - Setting up specialized assistants for specific domains

#### LocalAI
- **Description**: Drop-in replacement for OpenAI API with local model execution
- **Key Features**: Marketplace for models, TTS/STT capabilities, and more
- **Best For**:
  - Text-to-speech experiments with lightweight models
  - Running experiments with models that can work in WebAssembly
  - Edge device deployment testing

#### LiteLLM
- **Description**: API standardization layer that provides a unified interface
- **Integration**: Works with Ollama, OpenAI, and many other model providers
- **Best For**:
  - Creating a consistent API interface across different model providers
  - Managing access to models through API keys
  - A/B testing between different models

### Resource Management Tips

When working with limited hardware resources:

1. **Model Selection**:
   - Prioritize smaller models (1B-7B parameters) for better performance
   - Use quantized models (GGUF format) to reduce memory requirements
   - Consider specialized models (like code-specific or embedding-specific)

2. **Service Configuration**:
   - Adjust context lengths to limit memory usage
   - Use environment variables to limit number of CPU threads
   - Consider running just one LLM service at a time

3. **Hardware Optimization**:
   - Add swap space if RAM is limited
   - Use SSD storage for faster model loading
   - Consider upgrading RAM before CPU for most LLM workloads

For more information on specific models and configurations, refer to each project's documentation:
- [Ollama Documentation](https://github.com/ollama/ollama)
- [AnythingLLM Documentation](https://github.com/Mintplex-Labs/anything-llm)
- [LocalAI Documentation](https://localai.io/basics/try/)
- [LiteLLM Documentation](https://docs.litellm.ai/docs/)

## Step-by-Step Deployment Guide

This guide provides detailed instructions to deploy the entire homelab stack from scratch. The stack can be deployed either manually or via CI/CD pipelines.

### Manual Deployment

#### Prerequisites Setup

1. **Domain & DNS Configuration**:
   - Register a domain or use an existing one
   - Add domain to Cloudflare for DNS management
   - Create API tokens in Cloudflare with appropriate permissions:
     - DNS API token with Zone:DNS:Edit permissions
     - Zone API token with Zone:Zone:Read permissions

2. **Server Preparation**:
   - Install Ubuntu Server (24.04 LTS recommended)
   - Update the system: `sudo apt update && sudo apt upgrade -y`
   - Install Docker: 
     ```bash
     curl -fsSL https://get.docker.com -o get-docker.sh
     sudo sh get-docker.sh
     ```
   - Add your user to Docker group: `sudo usermod -aG docker $USER`
   - Log out and back in for changes to take effect

3. **Initialize Docker Swarm**:
   ```bash
   docker swarm init --advertise-addr $(hostname -I | awk '{print $1}')
   ```

#### Initial Configuration

1. **Clone Repository**:
   ```bash
   git clone https://github.com/fardust/homelab-stack.git
   cd homelab-stack
   ```

2. **Set Up Environment Variables**:
   ```bash
   # Copy the example environment file
   cp .env.example .env
   
   # Edit .env with your actual settings
   nano .env
   
   # Source the environment file to make variables available to your shell
   source .env
   ```

3. **Create Required Secret Files**:
   
   Create directories for secrets:
   ```bash
   mkdir -p secrets/{authelia,cloudflare,grafana,postgres,sendgrid,google,pihole,watchtower,fireflyiii}
   ```

   Set up essential secrets (using secure random values):
   ```bash
   # Cloudflare Tokens (required for DNS challenge validation)
   echo "your-dns-api-token" > secrets/cloudflare/dns_api_token
   echo "your-zone-api-token" > secrets/cloudflare/zone_api_token

   # Authelia secrets
   echo "$(openssl rand -hex 64)" > secrets/authelia/jwt_secret
   echo "$(openssl rand -hex 64)" > secrets/authelia/session_secret
   echo "$(openssl rand -hex 64)" > secrets/authelia/encryption_key
   echo "$(openssl rand -hex 32)" > secrets/authelia/redis_password
   echo "securepassword" > secrets/authelia/postgres_password
   
   # Create a default users file for Authelia
   cat > secrets/authelia/users.yml << EOL
   users:
     admin:
       displayname: Admin User
       password: \$argon2id\$v=19\$m=65536,t=3,p=4\$secure-hash-replace-this
       email: admin@yourdomain.com
       groups:
         - admins
   EOL

   # Other required secrets
   echo "securepassword" > secrets/postgres/postgres_db_password
   echo "apikey" > secrets/sendgrid/smtp_password
   echo "securepassword" > secrets/grafana/admin_password
   ```

4. **Create Required Networks**:
   ```bash
   docker network create -d overlay --attachable traefik
   docker network create -d overlay --attachable traefik-public
   
   # Optional: Create DNSCrypt network if using DNS services
   docker network create -d overlay --attachable --subnet=10.10.0.0/24 --ip-range=10.10.0.0/28 dnscrypt-network
   ```

#### Deployment Sequence

Follow this sequence to deploy the stacks in the correct order:

1. **Deploy Core Traefik Stack**:
   This is the foundation and must be deployed first.
   ```bash
   # Make sure environment variables are loaded
   source .env
   
   # Set a config version (using git commit hash or increment manually)
   export CONFIG_VERSION=$(git rev-parse --short HEAD)
   
   # Deploy the stack
   docker stack deploy -c source/traefik-stack.yml traefik
   ```
   
   Verify deployment:
   ```bash
   docker service ls | grep traefik
   ```

   Wait for all traefik services to show as 1/1 REPLICAS before continuing.

2. **Deploy Database Stack** (if not using SaaS providers):
   ```bash
   # Ensure environment variables are still loaded
   source .env
   
   # Deploy the database stack
   docker stack deploy -c source/database-stack.yml db
   ```
   
   Verify deployment:
   ```bash
   docker service ls | grep db
   ```

3. **Deploy Additional Stacks Based on Your Needs**:

   Remember to source your environment variables before each deployment command:
   ```bash
   source .env
   
   # LLM Stack (for AI capabilities)
   docker stack deploy -c source/llms-stack.yml llms
   
   # DNS Stack (for local DNS resolution)
   docker stack deploy -c source/dns-stack.yml dns
   
   # Web Services Stack
   docker stack deploy -c source/web-stack.yml web
   
   # Additional specialized stacks
   docker stack deploy -c source/financial-stack.yml finance
   docker stack deploy -c source/bi-stack.yml bi
   docker stack deploy -c source/home-stack.yml home
   docker stack deploy -c source/programming-stack.yml programming
   ```

4. **Important Note About Environment Variables**:
   Every time you make changes to your `.env` file, you need to:
   - Either source it again in your current shell session with `source .env`
   - Or start a new shell session and source it there
   - Services deployed before the changes won't automatically pick up new environment values until redeployed

### Automated CI/CD Deployment (Using GitHub Actions)

This repository includes a GitHub Actions workflow for automated deployment. This approach is recommended for production environments.

#### Prerequisites

1. **Set up GitHub Repository**:
   - Fork this repository
   - Add required secrets to your GitHub repository settings

2. **Required GitHub Secrets**:
   - `SSH_PRIVATE_KEY`: SSH key for connecting to your server
   - `SSH_USERNAME`: Username for SSH connection
   - `SSH_PORT`: SSH port (usually 22)
   - `TS_DEPLOY_HOST`: Hostname or IP of your deployment target
   - `TS_OAUTH_CLIENT_SECRET`: Tailscale OAuth client secret
   - `GCP_AUTH_PROVIDER`: Google Cloud Workload Identity Provider
   - `GCP_SERVICE_ACCOUNT`: Google Cloud Service Account
   - `GCP_PROJECT_ID`: Google Cloud Project ID
   - `DOPPLER_TOKEN`: Token for Doppler secrets management

3. **Set up Google Cloud Secrets**:
   Store your secrets in Google Cloud Secret Manager with these names:
   - `authelia-duo_integration_key`
   - `authelia-duo_secret_key`
   - `authelia-jwt_secret`
   - `authelia-postgres_password`
   - `authelia-redis_password`
   - `authelia-session_secret`
   - `authelia-encryption_key`
   - `authelia-users`
   - `cloudflare-dns_api_token`
   - `cloudflare-zone_api_token`
   - `grafana-admin_password`
   - `google-google_oauth_token`
   - `sendgrid-smtp_password`

4. **Set up Doppler Project**:
   - Create a `personal-docker-stack` project in Doppler
   - Create a `prd_traefik_stack` config with your environment variables

#### Deployment Process

1. Push changes to the `main` branch
2. GitHub Actions will automatically:
   - Check out the code
   - Install Doppler CLI
   - Set up Tailscale for secure connections
   - Authenticate with Google Cloud
   - Retrieve secrets from GCP Secret Manager
   - Set up SSH connection to your server
   - Copy files to your server
   - Deploy the stack with the current git SHA as the config version

The workflow includes:
- SSH key cleanup after use
- Tailscale cleanup after deployment
- Temporary file cleanup on the remote server

### Verification and Troubleshooting

After deployment (either manual or automated), verify your services:

1. **Check Deployed Services**:
   ```bash
   docker service ls
   ```

2. **View Service Logs**:
   ```bash
   docker service logs traefik_traefik
   docker service logs db_postgres
   ```

3. **Common Issues and Solutions**:

   **a. Certificate Issues**:
   - Check Cloudflare API tokens are correct
   - Verify DNS records are properly configured
   - Check logs: `docker service logs traefik_traefik | grep certificate`

   **b. Database Connection Problems**:
   - Verify passwords in secrets match environment variables
   - Check connectivity: `docker exec -it $(docker ps -q -f name=db_postgres) psql -U postgres -c "SELECT 1;"`

   **c. Network Connectivity Issues**:
   - Verify networks are created correctly: `docker network ls`
   - Check service is attached to correct network: `docker service inspect <service_name> --format '{{json .Spec.TaskTemplate.Networks}}'`

   **d. LLM Service Issues**:
   - Check if API keys are correctly set: `docker service logs llms_litellm | grep API`
   - Verify resource limits aren't being exceeded: `docker stats`

### Post-Deployment Setup

1. **Access Portainer** (container management UI):
   - Navigate to https://portainer.yourdomain.com
   - Complete initial setup and password configuration

2. **Set Up Authelia Users**:
   - Navigate to https://auth.yourdomain.com
   - Log in with credentials from users.yml
   - Set up 2FA methods (TOTP, WebAuthn, or Duo Push)

3. **Configure Additional Services**:
   - Set up Grafana datasources and dashboards
   - Configure PGAdmin to connect to your PostgreSQL instance
   - Set up AnythingLLM with your preferred document collections

## Important Licensing Notes

**DISCLAIMER**: This project is intended for personal homelab use only and is not designed or tested for production environments. Many of the included open-source services may require commercial licenses for business or production use.

Key points to understand:

- **Personal Use Only**: This stack is designed for personal experimentation, learning, and home use
- **Not For Commercial Use**: Using these services in a commercial environment may require purchasing appropriate licenses
- **License Compliance**: It is your responsibility to comply with the license terms of each included software
- **No Warranty**: This project is provided "as is" under the MIT License without any warranty or guarantee of functionality

This repository is licensed under the MIT License. See the [LICENSE](LICENSE) file in the repository root for the full license text. Note that this license applies only to the configuration and documentation within this repository, not to the third-party software included in the Docker images.




