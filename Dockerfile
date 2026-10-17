FROM python:3.15-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Pinned dependencies first, so code changes don't reinstall them
COPY requirements.txt ./
RUN pip install --require-hashes -r requirements.txt

COPY pyproject.toml README.md LICENSE ./
COPY gw2bot ./gw2bot
RUN pip install --no-deps .

# The cog loads GWTwoFont1p1.ttf from the working directory. It isn't
# distributed with GW2Bot, so point at a mountable fonts dir; if the font
# is missing, the cog falls back to Pillow's default font.
RUN useradd --create-home --uid 1000 gw2bot \
    && mkdir -p /app/logs /app/fonts \
    && ln -s fonts/GWTwoFont1p1.ttf /app/GWTwoFont1p1.ttf \
    && chown -R gw2bot:gw2bot /app/logs
USER gw2bot

VOLUME ["/app/logs"]

CMD ["gw2bot"]
