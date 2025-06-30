# --- Ensure .env is present and source it ---
.PHONY: require-dotenv
require-dotenv:
	@if [ ! -f .env ]; then \
		echo '❌ .env file not found! Please create one with all required environment variables.'; \
		exit 1; \
	fi

.PHONY: setup-deps
setup-deps:
	@echo "🦄 Installing yq v4+ for max YAML vibes..."
	sudo wget -O /usr/local/bin/yq https://github.com/mikefarah/yq/releases/latest/download/yq_linux_amd64
	sudo chmod +x /usr/local/bin/yq
	yq --version
	@echo "✨ yq is ready. Go touch some YAML!"
.PHONY: deploy-service setup-sparse-submodule setup-supabase-db-sparse

SUBMODULE ?=
SPARSE_PATH ?=

# --- Deploy a single service from a compose file as a stack ---
deploy-service:
	@echo "🔥 Yo, extracting '$(SERVICE_NAME)' from '$(COMPOSE_FILE)' for stack '$(STACK_NAME)'..."
	@if [ -z "$(SERVICE_NAME)" ] || [ -z "$(COMPOSE_FILE)" ] || [ -z "$(STACK_NAME)" ]; then \
		echo "❌ Bruh, you're missing args. Try: COMPOSE_FILE=<path> STACK_NAME=<stack_name> SERVICE_NAME=<service_name>"; \
		exit 1; \
	fi
	$(MAKE) require-dotenv
	TMP_DIR=$$(dirname $(COMPOSE_FILE)); \
	TMP_FILE="$${TMP_DIR}/.tmp_service_deploy_$(SERVICE_NAME).yml"; \
	set -a; . ./.env; set +a; \
	echo "(yq) extracting service and dependencies to temp file..."; \
	yq e '{ "version": (.version // "3.8"), "services": {env(SERVICE_NAME): .services[env(SERVICE_NAME)]}, "networks": (.networks // {}), "volumes": (.volumes // {}), "configs": (.configs // {}), "secrets": (.secrets // {}) }' "$(COMPOSE_FILE)" > "$$TMP_FILE" 2>/dev/null; \
	set -a; . ./.env; set +a; \
	docker stack deploy -c "$$TMP_FILE" "$(STACK_NAME)" --detach=false; \
	if [ -n "$$TMP_FILE" ] && [ "$$TMP_FILE" != "/" ] && echo "$$TMP_FILE" | grep -q '/.tmp_service_deploy_'; then \
		rm -f "$$TMP_FILE"; \
	else \
		echo "[WARN] Not removing suspicious TMP_FILE: '$$TMP_FILE'"; \
	fi
	@echo "✅ Service '$(SERVICE_NAME)' deployed. Easy. Now clean that mess."

# --- Sparse submodule setup ---
setup-sparse-submodule:
	@echo "🧠 Setting up sparse-checkout..."
	@if [ -z "$(SUBMODULE)" ]; then \
		echo "❌ Error: SUBMODULE is not defined."; \
		exit 1; \
	fi
	@if [ -z "$(SPARSE_PATH)" ]; then \
		echo "❌ Error: SPARSE_PATH is not defined."; \
		exit 1; \
	fi
	@if [ ! -d "$(SUBMODULE)" ]; then \
		echo "❌ Error: Submodule '$(SUBMODULE)' doesn't exist. Did you run 'git submodule update --init --recursive' yet?"; \
		exit 1; \
	fi
	cd "$(SUBMODULE)" && \
	git sparse-checkout init && \
	git sparse-checkout set "$(SPARSE_PATH)" && \
	git read-tree -m -u HEAD
	@echo "✅ Sparse-checkout configured for '$(SUBMODULE)/$(SPARSE_PATH)'"

# --- Supabase DB sparse shortcut ---
setup-supabase-db-sparse:
	@echo "🚀 Quick setup for Supabase DB sparse-checkout..."
	$(MAKE) setup-sparse-submodule SUBMODULE="stacks/main/configs/supabase" SPARSE_PATH="docker/volumes/db"
