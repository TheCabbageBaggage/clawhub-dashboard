FROM node:20-alpine

WORKDIR /app

# Install build dependencies for better-sqlite3
RUN apk add --no-cache python3 make g++

# Copy package.json and install dependencies
COPY package.json ./
RUN npm install --production && apk del python3 make g++

# Copy application files
COPY server.js ./
COPY kg-engine.js ./
COPY login.html ./
COPY dashboard/ ./dashboard/

# Create data directory
RUN mkdir -p /app/data

# Expose port
EXPOSE 3001

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
  CMD wget -q --spider http://localhost:3001/api/auth-status || exit 1

# Run the server
CMD ["node", "server.js"]
