FROM node:22-alpine AS build
WORKDIR /app
ARG VITE_API_URL=http://localhost:8000
ARG VITE_BOT_USERNAME=sportssmatebot
ARG VITE_ENABLE_DEV_AUTH=false
ENV VITE_API_URL=$VITE_API_URL VITE_BOT_USERNAME=$VITE_BOT_USERNAME VITE_ENABLE_DEV_AUTH=$VITE_ENABLE_DEV_AUTH
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
RUN corepack enable && corepack prepare pnpm@11.19.0 --activate && pnpm install --frozen-lockfile
COPY . .
RUN npm run build

FROM nginx:1.27-alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
