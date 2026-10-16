FROM python:3.15-slim

# Toothy is the bot platform GW2Bot runs on. Pinned for reproducible builds;
# override with --build-arg TOOTHY_REF=<branch|tag|commit>.
ARG TOOTHY_REPO=https://github.com/Maselkov/Toothy.git
ARG TOOTHY_REF=329c6ebe4c8ce4ba267a3c24e6aafc7095bbda1a

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# git is needed to fetch Toothy and its git-based discord.py dependency
RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

RUN git init -q . \
    && git remote add origin "$TOOTHY_REPO" \
    && git fetch -q --depth 1 origin "$TOOTHY_REF" \
    && git checkout -q FETCH_HEAD \
    && rm -rf .git \
    && cp settings/config-example.json config-example.json \
    && pip install -r requirements.txt

COPY requirements.txt /tmp/gw2bot-requirements.txt
RUN pip install -r /tmp/gw2bot-requirements.txt

COPY guildwars2 /app/cogs/guildwars2
COPY docker/entrypoint.py /usr/local/bin/gw2bot-entrypoint

# The cog loads GWTwoFont1p1.ttf from the working directory. It isn't
# distributed with GW2Bot, so point at a mountable fonts dir; if the font
# is missing, the cog falls back to Pillow's default font.
RUN useradd --create-home --uid 1000 toothy \
    && mkdir -p /app/settings /app/logs /app/fonts \
    && ln -s fonts/GWTwoFont1p1.ttf /app/GWTwoFont1p1.ttf \
    && chown -R toothy:toothy /app/settings /app/logs
USER toothy

VOLUME ["/app/settings", "/app/logs"]

ENTRYPOINT ["python", "/usr/local/bin/gw2bot-entrypoint"]
