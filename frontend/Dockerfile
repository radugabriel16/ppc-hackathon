FROM node:22.14.0-alpine AS build

WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json frontend/.npmrc ./
RUN npm ci
COPY contracts /app/contracts
COPY frontend ./
RUN npm run gen && npm run typecheck && VITE_API_MODE=api npm run build \
    && rm -f dist/mockServiceWorker.js

FROM nginx:1.27.3-alpine

COPY infra/nginx/nginx.conf /etc/nginx/nginx.conf
COPY --from=build /app/frontend/dist /usr/share/nginx/html
EXPOSE 443
