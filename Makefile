.DEFAULT_GOAL := dev
.PHONY: setup dev api web gen-client test test-hosted lint build smoke smoke-compose site brand check

# Install the server's, the web app's and the Python SDK's dependencies.
setup:
	cd server && uv sync
	cd web && pnpm install
	cd sdk && uv sync

# Run the API (:8000) and the web dev server (:3000) together.
dev:
	$(MAKE) -j2 api web

api:
	cd server && ROWLAB_CORS_ORIGINS=http://localhost:3000 uv run rowlab serve --reload

web:
	cd web && NEXT_PUBLIC_API_URL=http://localhost:8000 pnpm dev

# Regenerate openapi.json, the typed web client and the Python SDK's models. Run after any API change.
gen-client:
	cd server && uv run rowlab openapi > ../openapi.json
	cd web && pnpm gen-client
	cd sdk && uv run datamodel-codegen --input ../openapi.json --input-file-type openapi \
	  --output src/rowlab_sdk/_models.py --output-model-type pydantic_v2.BaseModel \
	  --use-annotated --use-standard-collections --use-union-operator --target-python-version 3.11 \
	  --enum-field-as-literal all --formatters builtin --disable-timestamp

test:
	cd server && uv run pytest
	cd sdk && uv run pytest

# The same tests on a hosted setup: Postgres (ROWLAB_TEST_DATABASE_URL) and datasets on S3 (moto).
test-hosted:
	@test -n "$$ROWLAB_TEST_DATABASE_URL" || { echo "Set ROWLAB_TEST_DATABASE_URL=postgresql://… first."; exit 1; }
	cd server && ROWLAB_TEST_STORAGE=s3 uv run pytest

# What CI checks, apart from the hosted and smoke tests: run before you finish. (CI also checks that
# the openapi.json and web client this regenerates are the committed ones.)
check: lint test build site
	python3 brand/check.py

lint:
	cd server && uv run ruff check . ../scripts ../brand && uv run ruff format --check . ../scripts ../brand
	cd sdk && uv run ruff check . && uv run ruff format --check .
	cd web && pnpm lint && pnpm typecheck

# Build the web UI, bundle it into the Python package, and build the wheel.
build: gen-client
	cd web && pnpm build
	rm -rf server/src/rowlab/static && cp -r web/out server/src/rowlab/static
	cd server && uv build

# End to end, from adding a file to an export, through the API: against the built wheel installed
# fresh (port 8001), or against docker-compose.yml built from this checkout (port 8002). A model is
# asked only with OPENROUTER_API_KEY set; see scripts/smoke.py.
smoke: build
	scripts/smoke-wheel.sh

smoke-compose:
	trap 'docker compose -p rowlab-smoke down -v' EXIT; \
	  ROWLAB_IMAGE=rowlab:smoke ROWLAB_PORT=8002 docker compose -p rowlab-smoke up -d --build --wait && \
	  python3 scripts/smoke.py http://127.0.0.1:8002

# Build the website (rowlab.dev) and the docs (docs.rowlab.dev); see site/README.md.
site:
	cd site/www && pnpm install --frozen-lockfile && pnpm build
	cd site/docs && pnpm install --frozen-lockfile && pnpm build

# Regenerate the icons and social cards of all three sites from brand/mark.svg; see brand/README.md.
brand:
	pnpm --dir site/docs install --frozen-lockfile
	node brand/generate.mjs
