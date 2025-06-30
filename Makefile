.PHONY: setup-sparse-submodule setup-supabase-db-sparse

SUBMODULE ?=
SPARSE_PATH ?=

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

setup-supabase-db-sparse:
	@echo "🚀 Quick setup for Supabase DB sparse-checkout..."
	$(MAKE) setup-sparse-submodule SUBMODULE="stacks/main/configs/supabase" SPARSE_PATH="docker/volumes/db"
