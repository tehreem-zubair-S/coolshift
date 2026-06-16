# Deployment Guide

## Upload to GitHub

```powershell
cd "C:\Users\Hp\OneDrive\Documents\CoolerShift"
git init
git add .
git commit -m "Build CoolShift hackathon project"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/coolshift.git
git push -u origin main
```

Create the empty GitHub repository first, then replace `YOUR_USERNAME`.

## Deploy Option: Render

Render works well for this project because it can run the Python backend and serve the frontend from the same app.

1. Go to Render and create a new Web Service.
2. Connect your GitHub repository.
3. Use these settings:

```text
Environment: Python
Build Command: pip install -r requirements.txt
Start Command: python backend/app.py
```

Render automatically provides the `PORT` environment variable. The app is already configured to use it.

## Deploy Option: Railway

1. Create a new Railway project from GitHub.
2. Select this repository.
3. Railway should detect the Python app.
4. If needed, set the start command:

```text
python backend/app.py
```

## Important Files for Judges

- `README.md`
- `DEPLOYMENT.md`
- `docs/method.md`
- `docs/architecture.md`
- `outputs/public_results.csv`
- `outputs/summary_results.csv`
- `data/coolshift.sqlite`

Keep `data/coolshift.sqlite` and `outputs/` in the repository for the hackathon demo so the deployed app works immediately without re-importing the ZIP file.

