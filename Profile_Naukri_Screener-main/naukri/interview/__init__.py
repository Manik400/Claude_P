"""AI interview preparation built on top of the daily job scan.

Independent of naukri.jobs by design - it reads that package's output files
(data/jobs/results-<date>.json) and writes its own (data/interview/), so a
change here cannot break a scan and a failed prep run still leaves you with
today's openings page.

    python main.py --interview-prep          today's Top 10 -> 100 Q&A
    python main.py --interview-prep --date 2026-08-24
"""
