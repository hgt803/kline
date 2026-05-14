.PHONY: venv upgrade-pip install activate verify

venv:
	python3 -m venv .venv

upgrade-pip:
	.venv/bin/python -m pip install --upgrade pip setuptools wheel

install: venv upgrade-pip
	.venv/bin/python -m pip install -r requirements.txt

activate:
	@echo "Run: source scripts/activate.sh"

verify:
	.venv/bin/python -c "import akshare; print('akshare', akshare.__version__)"
