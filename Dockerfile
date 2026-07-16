FROM node:20-alpine

WORKDIR /app

# Copy package files if they exist
COPY dashboard/package*.json ./dashboard/ 2>/dev/null || true

# Install dependencies if package.json exists
RUN if [ -f dashboard/package.json ]; then cd dashboard && npm ci --only=production; fi

# Copy application files
COPY dashboard/ ./dashboard/
COPY status.html ./

# Create data directory
RUN mkdir -p /app/data/research-files

# Expose port
EXPOSE 3001

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
  CMD wget -q --spider http://localhost:3001/api/data || exit 1

# Run the server
CMD ["node", "dashboard/server.js"]
