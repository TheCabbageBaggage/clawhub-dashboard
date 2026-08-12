FROM debian:bookworm-slim

# Installiere benötigte Tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    restic \
    rclone \
    rsync \
    openssh-client \
    curl \
    ca-certificates \
    cron \
    tzdata \
    && rm -rf /var/lib/apt/lists/*

# Zeitzone
ENV TZ=Europe/Berlin

# Skripte
COPY scripts/ /usr/local/bin/
RUN chmod +x /usr/local/bin/*.sh

# Cron-Setup
COPY crontab /etc/cron.d/backup-cron
RUN chmod 0644 /etc/cron.d/backup-cron && crontab /etc/cron.d/backup-cron

# Einstiegspunkt: Cron im Vordergrund starten
CMD ["cron", "-f"]
