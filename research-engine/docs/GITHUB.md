# Publishing the source on GitHub

The project is prepared for a repository but has not been published by this
delivery. Publication needs a GitHub account/repository connection. Keep runtime
data on your PC. GitHub Pages serves static content and cannot run this Python
backend: <https://docs.github.com/en/pages/getting-started-with-github-pages/creating-a-github-pages-site>.

## Export source without personal data

The user delivery includes a ready source-only archive at
`dist/oraculum-source.zip`. After making source edits, regenerate it with:

```powershell
python tools/export_source.py
```

This creates `dist/oraculum-source.zip` using an explicit source/documentation
allowlist. It excludes `data`, reports, virtual environments, credentials, local
logs and the user-delivery checksum manifest. It includes the fictional test
fixtures. The user-delivery `Oraculum.zip` also contains your preserved old
database; publish the **source export**, not that entire user ZIP.

The project does not have a newly assigned open-source license. Choose a license
before granting reuse rights; do not assume making a repository public sets one.

## Publish with Git locally

From the project root, after installing Git:

```powershell
git init
git add .github .gitignore .gitattributes README.md CHANGELOG.md pyproject.toml oraculum tests examples config docs handoffs tools run.cmd start.cmd demo.cmd research.cmd repair.cmd run-daily.cmd install-schedule.cmd remove-schedule.cmd
git status --short
git commit -m "Add local Oraculum research and paper workflows"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/oraculum.git
git push -u origin main
```

Create an empty repository in your account first and replace `YOUR_USERNAME`.
Choose public/private visibility deliberately. The listed `git add` paths exclude
runtime data; also inspect the status before committing. `.gitignore` protects
common runtime/credential paths, but never intentionally force-add them.
Authenticate through your normal GitHub/Git setup; do not paste tokens into
source files, commands here, chat, or the repository URL.

If the folder already has Git history, inspect `git status` and `git remote -v`
and use that repository's workflow instead of reinitializing/removing remotes.

The included Actions workflow runs the offline unittest suite on Linux and
Windows with Python 3.12/3.14. It has no market-data scraping, deployment,
AI secrets or real-money operations. It has been prepared locally, not executed
on GitHub. Review your account's Actions availability/limits before enabling it.

Alternatively, extract `dist/oraculum-source.zip` and upload those source files
through GitHub's website. Do not upload the ZIP as a substitute for a browsable
source tree if you want CI and code review to work.
