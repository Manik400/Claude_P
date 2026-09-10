# How to Use It

Here's how to use each project, with and without Claude.

---

## 1. job-hunt (jobs worldwide)

### Without Claude

1. Double-click `job-hunt\jobhunt.bat`.
2. Answer the questions: job title, years of experience, countries, and your resume file.
3. Wait a few minutes. The report opens in your browser.
4. Click **Apply** on the jobs you like.

Or type one line:

```bash
python job-hunt\scripts\job_bot.py run --role "software engineer" --experience 0-2 --resume "C:\path\cv.pdf" --open
```

### With Claude

It's already installed as a Claude skill, so just ask in plain words:

- *"Find software engineer jobs in Germany and India, 2 years' experience."*
- *"Here's my resume at C:\...\cv.pdf. Find matching jobs in Japan."*
- *"Search only remote jobs posted this week."*

Claude runs the search, also checks sites that block bots (Naukri, Indeed, Glassdoor), and tells you the best matches.

---

## 2. Naukri Screener (your Naukri profile and jobs)

> All commands run from inside the `Profile_Naukri_Screener-main` folder.

### Without Claude

**Every day:**

- Double-click `daily_refresh.bat`. It bumps your profile so recruiters see you higher.
- Double-click `jobs_scan.bat`. It finds new jobs and makes an Excel sheet plus a tracker page.

**When you want:**

| Command | What it does |
| --- | --- |
| `.venv\Scripts\python.exe main.py --jobs` | Shows the matching jobs. It sends nothing. |
| `.venv\Scripts\python.exe main.py --jobs --yes --limit 3` | Really applies to up to 3 jobs. |

**If it says "session expired":**

```bash
.venv\Scripts\python.exe main.py --login
```

This asks you to sign in again.

### With Claude

Ask Claude in this project folder, for example:

- *"Run a Naukri scan and show me the top jobs."*
- *"Rewrite my Naukri headline and summary."* Claude reads your profile, writes better text, shows you a preview, then updates Naukri only after you say yes.
- *"Make an Excel sheet of jobs in Gurugram, Noida and Delhi."*
- *"Prepare me for interviews."* This turns today's top 10 jobs into 100 interview questions with answers. It uses Claude behind the scenes.
- *"Schedule the scan to run every day."*

---

## Quick Tip

| Way | How it works |
| --- | --- |
| **Without Claude** | Double-click the `.bat` files. Easy, but you read the results yourself. |
| **With Claude** | Just talk. Claude runs the commands, explains the results, and fixes errors. Nothing is applied or updated on Naukri until you say yes. |
