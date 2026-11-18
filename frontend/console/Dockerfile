FROM node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npx ng build --configuration production

FROM nginxinc/nginx-unprivileged:1.27-alpine
COPY --from=build /app/dist/console/browser /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY docker-entrypoint.sh /docker-entrypoint.d/40-omnilink-config.sh
USER root
RUN chmod +x /docker-entrypoint.d/40-omnilink-config.sh && chown -R 101:101 /usr/share/nginx/html
USER 101
EXPOSE 8080
