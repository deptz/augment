# Kubernetes / Production Deployment

This guide covers deploying **OpenSandbox** (with Kubernetes runtime) and **Augment** (API + workers) on Kubernetes for production. The OpenSandbox SDK abstracts the runtime; **no application code changes are required**—only configuration (env and `config.yaml`).

## Overview

- **OpenSandbox server**: Run with Kubernetes runtime so sandboxes are scheduled as pods in the cluster. See [OpenSandbox Kubernetes](#opensandbox-server-with-kubernetes-runtime) below.
- **Augment**: Run the API server and ARQ workers as Kubernetes Deployments. Workers need `OPENSANDBOX_DOMAIN`, Redis, and `features.sandbox_runtime: kubernetes` (or env `SANDBOX_RUNTIME=kubernetes`).

## 1. OpenSandbox Server with Kubernetes Runtime

OpenSandbox supports Docker and Kubernetes runtimes. For production at scale, use the Kubernetes runtime.

### Where to find OpenSandbox K8s deployment

- **Kubernetes Controller (operator)**  
  [alibaba/OpenSandbox – kubernetes/](https://github.com/alibaba/OpenSandbox/tree/main/kubernetes)  
  - CRDs: `BatchSandbox`, `Pool`  
  - Deploy with: `make install`, `make deploy IMG=... TASK_EXECUTOR_IMG=...`  
  - Prerequisites: Kubernetes 1.22+, see [kubernetes/README.md](https://github.com/alibaba/OpenSandbox/blob/main/kubernetes/README.md)

- **OpenSandbox Server (control plane)**  
  The server can be configured to use a Kubernetes backend. From the [opensandbox-server](https://pypi.org/project/opensandbox-server/) docs:
  - Initialize K8s config:  
    `opensandbox-server init-config ~/.sandbox.toml --example k8s`
  - Requirements: Kubernetes 1.21+, Python 3.10+

Deploy the OpenSandbox server (and optionally the Kubernetes controller) per the official OpenSandbox docs, then expose the server so Augment can reach it (e.g. `OPENSANDBOX_DOMAIN=opensandbox.example.com:443`).

## 2. Augment on Kubernetes

### Required environment (API and workers)

| Variable | Required | Description |
|----------|----------|-------------|
| `OPENSANDBOX_ENABLED` | For Draft PR sandbox path | `true` to use OpenSandbox |
| `OPENSANDBOX_DOMAIN` | When OpenSandbox enabled | OpenSandbox server host:port (e.g. `opensandbox.default.svc.cluster.local:8080` or public URL) |
| `OPENSANDBOX_PROTOCOL` | Optional | `http` or `https` (default: `http`) |
| `OPENSANDBOX_API_KEY` | Optional | If the server requires an API key |
| `SANDBOX_RUNTIME` | For K8s backend | Set to `kubernetes` when OpenSandbox uses Kubernetes runtime; `docker` for local/Docker runtime. **No app code change**—only this config. |
| `USE_SANDBOX` | Optional | `true` to use sandbox for Draft PR pipeline (when OpenSandbox enabled) |
| `REDIS_HOST` | Yes (for workers) | Redis host (e.g. `redis-master` or Redis service in cluster) |
| `REDIS_PORT` | Optional | Default `6379` |
| `REDIS_PASSWORD` | Optional | If Redis is secured |
| `REDIS_DB` | Optional | Default `0` |

Plus the usual JIRA, LLM, and (if needed) Bitbucket/Confluence/OpenCode env vars. See `.env.example` and [Configuration](https://github.com/deptz/augment#configuration) in the main README.

### config.yaml: sandbox runtime

In `config.yaml`, the runtime is driven by env (no code change):

```yaml
features:
  use_sandbox: ${USE_SANDBOX:true}   # default true when using OpenSandbox
  sandbox_runtime: ${SANDBOX_RUNTIME:docker}   # use "kubernetes" for K8s
```

Set `SANDBOX_RUNTIME=kubernetes` (or `features.sandbox_runtime: kubernetes` in config) when the OpenSandbox server uses the Kubernetes runtime.

### Minimal Augment worker Deployment example

A ready-to-customize manifest is in the repo: [deployment/opensandbox-augment-worker-deployment.yaml](../../deployment/opensandbox-augment-worker-deployment.yaml). Below is the same minimal example for reference. Use the same image and env pattern for the API Deployment (and add a Service and Ingress as needed).

- Replace `<IMAGE>` with your Augment image (e.g. `pujitriwibowo/augment:0.1.0`).
- Replace Redis and OpenSandbox host/port to match your cluster (e.g. Redis service name, OpenSandbox service or ingress).

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: augment-worker
  namespace: default
spec:
  replicas: 2
  selector:
    matchLabels:
      app: augment-worker
  template:
    metadata:
      labels:
        app: augment-worker
    spec:
      containers:
        - name: worker
          image: <IMAGE>
          command: ["python", "run_worker.py"]
          env:
            - name: PYTHONPATH
              value: "/app"
            - name: REDIS_HOST
              value: "redis-master"
            - name: REDIS_PORT
              value: "6379"
            - name: OPENSANDBOX_ENABLED
              value: "true"
            - name: OPENSANDBOX_DOMAIN
              value: "opensandbox.default.svc.cluster.local:8080"
            - name: OPENSANDBOX_PROTOCOL
              value: "http"
            - name: SANDBOX_RUNTIME
              value: "kubernetes"
            - name: USE_SANDBOX
              value: "true"
            # Add JIRA, LLM, Bitbucket, etc. via Secret or ConfigMap
            # - name: JIRA_SERVER_URL
            #   valueFrom:
            #     secretKeyRef:
            #       name: augment-secrets
            #       key: JIRA_SERVER_URL
          # Optional: mount config and .env from ConfigMap/Secret
          # volumeMounts:
          #   - name: config
          #     mountPath: /app/config.yaml
          #     subPath: config.yaml
          #   - name: env
          #     mountPath: /app/.env
          #     subPath: .env
      # volumes:
      #   - name: config
      #     configMap:
      #       name: augment-config
      #   - name: env
      #     secret:
      #       secretName: augment-env
```

Store secrets (JIRA, LLM, OpenSandbox API key, etc.) in a Secret and expose as env or as a mounted `.env`/config; do not commit them.

## 3. Summary

- **OpenSandbox**: Deploy the server (and optionally the [Kubernetes Controller](https://github.com/alibaba/OpenSandbox/tree/main/kubernetes)) per Alibaba OpenSandbox docs. Configure the server for Kubernetes runtime (e.g. `opensandbox-server init-config --example k8s`).
- **Augment**: Run API and workers as Deployments; set `OPENSANDBOX_DOMAIN`, Redis, and `SANDBOX_RUNTIME=kubernetes` (and `OPENSANDBOX_ENABLED=true`, `USE_SANDBOX=true` as needed). No application code changes—only configuration.

Existing Docker and local development flows are unchanged; use `SANDBOX_RUNTIME=docker` and local OpenSandbox (or disable OpenSandbox) for local dev.
