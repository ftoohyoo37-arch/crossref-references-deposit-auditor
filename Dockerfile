# Crossref Auditor — pre-submission audit + cleanup for Crossref deposit XML
# https://github.com/justalewis/crossref-references-deposit-auditor

FROM python:3.12-slim

# System packages: lxml needs libxml2/libxslt headers at install time
RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc \
        libxml2-dev \
        libxslt-dev \
        curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps first so this layer caches between code edits
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the source
COPY . ./

# First-run setup pulls the Crossref XSDs into config/crossref_xsd/.
# Runs at container start rather than build time so the container
# stays portable even if Crossref publishes new schema versions.
RUN python fetch_xsds.py || echo "XSD fetch deferred to first run"

EXPOSE 5001

# Bind to 0.0.0.0 so the port is reachable from outside the container.
ENV FLASK_RUN_HOST=0.0.0.0
CMD ["python", "app.py"]
