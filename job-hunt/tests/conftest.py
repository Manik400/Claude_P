import os

# Scores in tests must not depend on the learned model on whichever PC runs them
# (Profile_Naukri_Screener-main/data/metrics/learned.json).
os.environ["JOBHUNT_LEARNING"] = "0"

# Nor on whether an Ollama server happens to be running there: with one up, the suite sent
# real prompts to the local model (212 s instead of seconds, and different results per PC).
# Port 9 refuses at once; tests that exercise the Ollama path replace `requests` themselves.
os.environ["OLLAMA_HOST"] = "http://127.0.0.1:9"
