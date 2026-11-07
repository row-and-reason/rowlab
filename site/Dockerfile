# Both static sites in one nginx image: rowlab.dev from site/www, docs.rowlab.dev from site/docs.
# Build from the repository root, so the docs can read openapi.json:
#   docker build -f site/Dockerfile --build-arg PUBLIC_POSTHOG_TOKEN=phc_… -t rowlab-site .

FROM node:24-alpine AS build
ARG PUBLIC_POSTHOG_TOKEN
ARG PUBLIC_POSTHOG_HOST
ENV PUBLIC_POSTHOG_TOKEN=$PUBLIC_POSTHOG_TOKEN PUBLIC_POSTHOG_HOST=$PUBLIC_POSTHOG_HOST
RUN corepack enable
WORKDIR /src
COPY openapi.json .
COPY site/www site/www
COPY site/docs site/docs
RUN cd site/www && pnpm install --frozen-lockfile && pnpm build
RUN cd site/docs && pnpm install --frozen-lockfile && pnpm build

FROM nginx:1.29-alpine
COPY site/nginx.conf /etc/nginx/nginx.conf
COPY --from=build /src/site/www/dist /usr/share/nginx/html/www
COPY --from=build /src/site/docs/dist /usr/share/nginx/html/docs
EXPOSE 8080
