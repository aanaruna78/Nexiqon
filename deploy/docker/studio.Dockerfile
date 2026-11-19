# Studio (Next.js BFF) with the embeddable widget bundle served at /widget/nexiqon-chat.js.
#   docker build -f deploy/docker/studio.Dockerfile -t nexiqon/studio:dev frontend
FROM node:22.20.0-alpine AS build
WORKDIR /app
ENV NEXT_TELEMETRY_DISABLED=1 NEXT_OUTPUT=standalone
COPY . .
RUN npx --yes pnpm@12.15.0 install --frozen-lockfile \
    && npx --yes pnpm@12.15.0 --filter @nexiqon/widget build \
    && mkdir -p apps/studio/public/widget \
    && cp apps/widget/dist/nexiqon-chat.js apps/studio/public/widget/nexiqon-chat.js \
    && npx --yes pnpm@12.15.0 --filter @nexiqon/studio build

FROM node:22.20.0-alpine
# Runtime needs only node: patch OS packages (OpenSSL CVE-2026-31789) and drop npm, npx and
# corepack, whose bundled dependencies (tar, CVE-2026-59873) the server never uses.
RUN apk upgrade --no-cache \
    && rm -rf /usr/local/lib/node_modules /usr/local/bin/npm /usr/local/bin/npx /usr/local/bin/corepack
WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 PORT=3000 HOSTNAME=0.0.0.0
COPY --from=build /app/apps/studio/.next/standalone ./
COPY --from=build /app/apps/studio/.next/static ./apps/studio/.next/static
COPY --from=build /app/apps/studio/public ./apps/studio/public
USER 10001
EXPOSE 3000
CMD ["node", "apps/studio/server.js"]
