FROM node:20-alpine

WORKDIR /app

# Copy dashboard files
COPY dashboard/ ./dashboard/
COPY status.html ./

# Install dependencies if package.json exists
RUN if [ -f dashboard/package.json ]; then cd dashboard && npm ci --only=production; fi

# Create data directory
RUN mkdir -p /app/data/research-files

# Expose port
EXPOSE 3001

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
  CMD wget -q --spider http://localhost:3001/ || exit 1

# Run the server
CMD ["node", "dashboard/server.js"]
