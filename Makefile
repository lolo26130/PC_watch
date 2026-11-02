UV ?= uv

.PHONY: install test demo run

install:
	./install.sh

test:
	$(UV) run --with pytest --with textual --with rich --with psutil python -m pytest -q

demo:
	./pcwatch.py --demo

run:
	./pcwatch.py
