# Simplicity Indexer Security Configuration Guide

**Default configuration is secure:**
- All services (API, DB, Redis) bind to localhost by default.
- No ports are exposed to the public internet unless explicitly configured.
- For production, use a reverse proxy (e.g., nginx) and firewall rules.
- Never expose PostgreSQL or Redis directly.

For more, see deployment and Docker Compose examples.

---

## 🎯 **Network Access Control**

### **API_HOST=0.0.0.0 vs 127.0.0.1**

## 📋 **Configuration Breakdown**

### **1. Container Binding (Inside Docker)**
```bash
# Inside container (.env file)
API_HOST=0.0.0.0    # Required for Docker host-to-container communication
```

### **2. Host Exposure (Docker Port Mapping)**
```yaml
# docker-compose.yml - Controls REAL access
ports:
  - "127.0.0.1:8080:8080"  # ✅ LOCALHOST ONLY (secure default)
  - "8080:8080"            # ❌ ALL INTERFACES (potential security risk)
```

## 🛡️ **Security Levels**

### **🔒 Level 1: Localhost Only (Default)**
```yaml
# docker-compose.yml
ports:
  - "127.0.0.1:8080:8080"  # API only accessible from your machine
  - "127.0.0.1:5432:5432"  # PostgreSQL only accessible locally
  - "127.0.0.1:6379:6379"  # Redis only accessible locally
```

**Result**: API accessible at `http://localhost:8080` but NOT from network.

### **🌐 Level 2: Network Access (When Needed)**
```yaml
# docker-compose.yml
ports:
  - "8080:8080"      # API accessible from network
  - "5432:5432"      # Database accessible from network (dangerous!)
  - "6379:6379"      # Redis accessible from network (dangerous!)
```

**Result**: API accessible from `http://your-ip:8080` from other machines.

## 🔧 **Current Secure Configuration**

### **Environment Files**
- `.env.example` - For local development (`API_HOST=127.0.0.1`)
- `.env.docker.example` - For Docker deployment (`API_HOST=0.0.0.0`)

### **Docker Compose Security**
```yaml
services:
  indexer:
    ports:
      - "127.0.0.1:8080:8080"  # ✅ Localhost only
  postgres:
    ports:
      - "127.0.0.1:5432:5432"  # ✅ Localhost only
  redis:
    ports:
      - "127.0.0.1:6379:6379"  # ✅ Localhost only
```

## 🚀 **Deployment Scenarios**

### **Scenario 1: Development (Secure Default)**
```bash
# Uses .env.docker.example
docker-compose up -d

# API accessible at:
curl http://localhost:8080/v1/indexer/brc20/health  # ✅ Works
curl http://192.168.1.100:8080/...                 # ❌ Rejected
```

### **Scenario 2: Local Network Access**
```yaml
# Edit docker-compose.yml
services:
  indexer:
    ports:
      - "8080:8080"  # Remove 127.0.0.1 prefix
```

### **Scenario 3: Production Deployment**
Use a reverse proxy (nginx) with proper security:
```yaml
# docker-compose.yml
services:
  indexer:
    ports: []  # No direct exposure
    expose:
      - "8080"  # Only accessible to other containers
  
  nginx:
    ports:
      - "80:80"
      - "443:443"
```

## 🔍 **Verification Commands**

### **Check Current Access**
```bash
# Local access test
curl -s http://localhost:8080/v1/indexer/brc20/health

# Network access test (should fail with default config)
curl -s http://$(hostname -I | awk '{print $1}'):8080/v1/indexer/brc20/health
```

### **Check Open Ports**
```bash
# See what's actually listening
sudo netstat -tlnp | grep :8080
```

## ⚙️ **Configuration Examples**

### **Local Development Only**
```bash
# .env
API_HOST=127.0.0.1  # Local development
API_PORT=8080

# No Docker needed
python run.py
```

### **Docker Development (Secure)**
```bash
# .env (from .env.docker.example)
API_HOST=0.0.0.0    # Required inside container

# docker-compose.yml
ports:
  - "127.0.0.1:8080:8080"  # Localhost only

docker-compose up -d
```

### **Docker Production**
```bash
# Use reverse proxy, no direct exposure
# API only accessible through nginx/traefik
```

## 🛡️ **Security Best Practices**

### **✅ DO**
- Use `127.0.0.1:8080:8080` for development (default)
- Use reverse proxy for production
- Keep database and Redis localhost-only always
- Regularly audit open ports

### **❌ DON'T**
- Expose database with `5432:5432` 
- Expose Redis with `6379:6379`
- Use `0.0.0.0:8080:8080` unless network access required
- Skip firewall configuration in production

## 🔧 **Quick Fixes**

### **Make More Restrictive (Default)**
```yaml
# docker-compose.yml
ports:
  - "127.0.0.1:8080:8080"  # Localhost only
```

### **Allow Network Access (When Needed)**
```yaml
# docker-compose.yml  
ports:
  - "8080:8080"  # All interfaces
```

### **Production Setup**
```yaml
# docker-compose.yml
services:
  indexer:
    expose:
      - "8080"  # No ports mapping = container-only access
```

---

## 🎯 **Summary**

**Your setup is SECURE by default:**
- ✅ `API_HOST=0.0.0.0` inside container (required for Docker)
- ✅ `127.0.0.1:8080:8080` port mapping (localhost only)
- ✅ Database and Redis also localhost-only
- ✅ No accidental internet exposure

**The API is only accessible from your local machine**, not from the internet or local network, unless you specifically change the port mapping. 