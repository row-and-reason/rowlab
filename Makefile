.PHONY: dev api web gen-client test test-hosted lint build site

# Run the API (:8000) and the web dev server (:3000) together.
dev:
	$(MAKE) -j2 api web

api:
	cd server && ROWLAB_CORS_ORIGINS=http://localhost:3000 uv run rowlab serve --reload

web:
	cd web && NEXT_PUBLIC_API_URL=http://localhost:8000 pnpm dev

# Regenerate openapi.json and the typed web client. Run after any API change.
gen-client:
	cd server && uv run rowlab openapi > ../openapi.json
	cd web && pnpm gen-client

test:
	cd server && uv run pytest

# The same tests on a hosted setup: Postgres (ROWLAB_TEST_DATABASE_URL) and datasets on S3 (moto).
test-hosted:
	cd server && ROWLAB_TEST_STORAGE=s3 uv run pytest

lint:
	cd server && uv run ruff check && uv run ruff format --check
	cd web && pnpm lint && pnpm typecheck

# Build the web UI, bundle it into the Python package, and build the wheel.
build: gen-client
	cd web && pnpm build
	rm -rf server/src/rowlab/static && cp -r web/out server/src/rowlab/static
	cd server && uv build

# Build the website (rowlab.dev) and the docs (docs.rowlab.dev); see site/README.md.
site:
	cd site/www && pnpm install && pnpm build
	cd site/docs && pnpm install && pnpm build
