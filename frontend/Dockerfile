# OPTIONAL ONLY — used by infra/docker-compose.optional.yml.
# NOT used in the primary (no-Docker) setup. Fahad: do not build this.
FROM node:20-alpine
WORKDIR /app
COPY package.json .
RUN npm install
COPY . .
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0", "--port", "3000"]
