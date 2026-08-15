.PHONY: install dev run mcp review test lint clean uninstall

# Install Memento as an isolated uv tool (provides the `memento` command).
install:
	uv tool install --force .

# Editable dev environment (creates .venv, installs deps + dev group).
dev:
	uv sync

run:
	uv run memento capture

mcp:
	uv run memento mcp

review:
	uv run memento review

test:
	uv run --group dev pytest -q

clean:
	rm -rf build dist *.egg-info .venv

uninstall:
	- memento stop
	uv tool uninstall memento-memory
