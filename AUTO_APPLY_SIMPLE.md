# Auto-apply, in plain words

**One line:** You tap **Queue all** on the phone → GitHub saves your request → your PC (every 30 min,
and right after it boots) applies to those jobs with your LinkedIn and Naukri logins → the phone shows
`75% done · 9 applied · 1 needs your answer`.

## The 4 steps

1. **You tap.** Phone → **Jobs** → a report (worldwide search or Naukri scan) → **Queue all** (or tick a few →
   **Queue selected**). Or turn on **Queue → Rules → Auto-queue** once and every new report feeds the queue by itself.
2. **GitHub writes it down.** The tap starts a tiny GitHub Action that saves your request (encrypted) on the site.
   GitHub does *not* apply - it has no login and would get your account flagged.
3. **Your PC does the work.** Every 30 minutes while it is on (lock screen is fine) - and 2 minutes after you log in
   if it was off - the PC reads the queue and applies, a few jobs per board at a time, never over your daily caps.
4. **The phone shows the result.** **Home** has the progress bar; **Queue** has every job with a chip: `applied`,
   `needs your answer`, `company site - apply by hand`, `failed - tap retry`… If a form asked something new, type
   the answer on the phone and the PC re-applies on its next run.

## What you need (once)

* `site\setup_phone.bat` run on the PC, passphrase + GitHub token saved on the phone.
* Naukri screener on the PC with working Naukri and LinkedIn logins.
* `powershell -ExecutionPolicy Bypass -File site\schedule_phone_apply.ps1` run once on the PC.

## Good to know

* LinkedIn Easy Apply and Naukri jobs are applied to for you. Company sites: open them from the list, or set up
  Simplify (see AUTO_APPLY.md) and let it fill the forms.
* PC switched off when you tapped? Nothing is lost - the queue waits and continues when the PC is back.
* Big lists are fine - "Queue all (60)" is spread over hours/days, not fired at once.
* India: add the `APIFY_TOKEN` secret once and searches read Naukri, Indeed and LinkedIn properly.
* Contacts: every report can show recruiters / hiring managers per company (add a Hunter / SignalHire / Apollo key).
* Everything on the site is encrypted with your passphrase; your logins never leave the PC.
* Want the technical version? See [AUTO_APPLY.md](AUTO_APPLY.md).
