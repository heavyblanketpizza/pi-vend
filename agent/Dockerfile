FROM node:22-slim

WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --omit=dev
COPY src ./src

ENV NODE_ENV=production \
    AGENT_HOST=0.0.0.0
EXPOSE 3001
# Node >= 22.18 runs TypeScript directly (type stripping), so there is no build step.
CMD ["node", "src/server.ts"]
