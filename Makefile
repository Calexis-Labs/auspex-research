LAB      := lab
REMOTE   := ~/netagent

.PHONY: test sync test-remote lab-deploy lab-destroy lab-health run-batch

test:
	uv run pytest

sync:
	rsync -az --delete \
		--exclude .venv --exclude .git --exclude traces/ \
		--exclude __pycache__ --exclude .pytest_cache --exclude .env \
		--exclude "._*" --exclude .DS_Store --exclude lab/build/ \
		--exclude dataset/ --exclude dataset_local/ --exclude train/.venv \
		./ $(LAB):$(REMOTE)/

test-remote: sync
	ssh $(LAB) 'cd $(REMOTE) && uv sync -q && uv run pytest'

lab-deploy: sync
	ssh $(LAB) 'cd $(REMOTE) && uv sync -q && uv run python -m lab.deploy deploy'

lab-destroy:
	ssh $(LAB) 'cd $(REMOTE) && uv run python -m lab.deploy destroy'

lab-health:
	ssh $(LAB) 'cd $(REMOTE) && uv run python -m lab.deploy health'

run-batch: sync
	ssh $(LAB) 'cd $(REMOTE) && uv run python -m datagen.run_batch --k 3'
