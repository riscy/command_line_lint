run:
	python command_line_lint.py

lint:
	flake8 command_line_lint.py
	pylint command_line_lint.py
