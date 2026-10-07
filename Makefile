.PHONY: check-hooks

# Claude Code hook tests (stdlib only, no setup needed)
check-hooks:
	python3 -m unittest discover -s .claude/hooks -v
