FROM node:22-alpine AS dependencies
WORKDIR /app
COPY app/frontend/package.json app/frontend/package-lock.json* ./
RUN npm install

FROM node:22-alpine AS builder
WORKDIR /app
COPY --from=dependencies /app/node_modules ./node_modules
COPY app/frontend ./
ARG NEXT_PUBLIC_API_URL=/api
ARG PASARPULSE_INTERNAL_API_URL=http://backend:8000
ENV NEXT_PUBLIC_API_URL=${NEXT_PUBLIC_API_URL}
ENV PASARPULSE_INTERNAL_API_URL=${PASARPULSE_INTERNAL_API_URL}
RUN npm run build

FROM node:22-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production
ENV PORT=3000
ENV PASARPULSE_INTERNAL_API_URL=http://backend:8000
COPY --from=builder /app/public ./public
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static
EXPOSE 3000
CMD ["node", "server.js"]
