.PHONY: drift test eval

drift:
	driftwatch check --base origin/main

test:
	python -m pytest

eval:
	python eval/run_eval.py
