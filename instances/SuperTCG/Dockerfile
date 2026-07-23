FROM odoo:18

USER root

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    libxml2-dev \
    libxslt-dev \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install --no-cache-dir --break-system-packages \
    fsspec>=2025.3.0 \
    fsspec[s3] \
    python_slugify \
    ebaysdk \
    google-auth \
    packaging

USER odoo
