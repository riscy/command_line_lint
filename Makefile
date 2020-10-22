.PHONY: run
run:
	python command_line_lint.py

.PHONY: test
test:
	PYTHONPATH=. coverage run -m unittest discover -s test
	coverage report -m
	flake8
	pylint *.py */*.py
