# ---- build stage ----
FROM node:22-alpine AS build
WORKDIR /app

# install deps (cached on lockfile)
RUN corepack enable
COPY package.json pnpm-lock.yaml* ./
RUN pnpm install --frozen-lockfile || pnpm install

# build the SPA in live mode (calls same-origin /api/* which nginx proxies)
COPY . .
ENV VITE_API_MODE=live
RUN pnpm build

# ---- serve stage ----
FROM nginx:1.27-alpine AS serve
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 8085
CMD ["nginx", "-g", "daemon off;"]
