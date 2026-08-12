FROM debian:bookworm-slim

# Installiere rclone + Tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    rclone \
    openssh-client \
    ca-certificates \
    cron \
    tzdata \
    && rm -rf /var/lib/apt/lists/*

ENV TZ=Europe/Berlin

# Skripte
COPY scripts/ /usr/local/bin/
RUN chmod +x /usr/local/bin/*.sh

# Cron-Setup
COPY crontab /etc/cron.d/drive-sync-cron
RUN chmod 0644 /etc/cron.d/drive-sync-cron && crontab /etc/cron.d/drive-sync-cron

# Einstiegspunkt: Cron im Vordergrund
CMD ["cron", "-f"]
