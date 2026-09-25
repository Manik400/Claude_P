import os

# Scores in tests must not depend on the learned model on whichever PC runs them
# (Profile_Naukri_Screener-main/data/metrics/learned.json).
os.environ["JOBHUNT_LEARNING"] = "0"
