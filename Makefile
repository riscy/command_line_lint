.PHONY: run
run:
	python command_line_lint.py

.PHONY: test
test:
	PYTHONPATH=. python -m unittest discover -s test
	flake8 command_line_lint.py
	pylint command_line_lint.py
