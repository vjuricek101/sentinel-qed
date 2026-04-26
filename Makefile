.PHONY: clean gui demo

# Run the Streamlit GUI dashboard
gui:
	python3 -m streamlit run app.py

# Run the CLI terminal demo
demo:
	python3 main.py

# Clean all generated JSON flight recorder snapshots
clean:
	@echo "Cleaning up SDC snapshot files..."
	rm -f SDC_SNAPSHOT_*.json
	@echo "Clean complete."
