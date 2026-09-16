# Auto-apply, in plain words

**One line:** You tap **auto-apply** on the phone → GitHub saves your request → your PC (every 30 min)
applies to those LinkedIn jobs with your login → the phone shows what happened.

## The 4 steps

1. **You tap.** Phone → Reports → a report → **auto-apply** → *Apply to all* (or tick a few → *Apply to selected*).
2. **GitHub writes it down.** The tap starts a tiny GitHub Action that saves your request (encrypted) on the site.
   GitHub does *not* apply - it has no LinkedIn login and would get your account flagged.
3. **Your PC does the work.** Every 30 minutes (while it is on - lock screen is fine) the PC reads the request and
   applies on LinkedIn with your real login, a few jobs at a time, never over your daily cap.
4. **The phone shows the result.** Each job gets a chip: `applied`, `needs your answer`, `apply on company site`, `error`…
   If a form asked something new, type the answer on the phone and the PC re-applies on its next check.

## What you need (once)

* `site\setup_phone.bat` run on the PC, passphrase + GitHub token saved on the phone.
* Naukri screener on the PC with a working LinkedIn login.
* `powershell -ExecutionPolicy Bypass -File site\schedule_phone_apply.ps1` run once on the PC.

## Good to know

* Only LinkedIn jobs are auto-applied. Others: open the report and tap Apply yourself.
* Big lists are fine - "Apply to all (60)" is spread over hours/days, not fired at once.
* Everything on the site is encrypted with your passphrase; LinkedIn cookies never leave the PC.
* Want the technical version? See [AUTO_APPLY.md](AUTO_APPLY.md).
