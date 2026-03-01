# Augment sandbox image: OpenSandbox code-interpreter + OpenCode CLI + pytest + ruff
# Build: docker build -t augment/sandbox:latest -f images/augment-sandbox/Dockerfile .
FROM opensandbox/code-interpreter:v1.0.1

# Pre-install OpenCode CLI (saves ~30-90s per sandbox at runtime)
RUN npm install -g @opencodeai/cli@latest

# Pre-install common verification tools
RUN pip install pytest ruff

# Pre-install common build tools
RUN pip install build setuptools wheel
