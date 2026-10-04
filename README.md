# 🚀 Job Auto-Apply Bot

Automatically applies to jobs on **LinkedIn** (Easy Apply) and **Naukri** while you sleep.

## Quick Start

### macOS
```bash
# 1. Open Terminal, navigate to this folder
cd job-auto-apply

# 2. Run setup (one time)
chmod +x *.sh
bash setup_mac.sh

# 3. Edit config.yaml with YOUR credentials
#    - LinkedIn email/password
#    - Naukri email/password  
#    - Your resume path

# 4. First login (saves browser session)
bash run_login.sh

# 5. Test with 3 jobs
bash run_test.sh

# 6. Daily run (50 jobs)
bash run_daily.sh
```

### Windows
```cmd
REM 1. Open Command Prompt, navigate to this folder
cd job-auto-apply

REM 2. Run setup (one time)
setup_windows.bat

REM 3. Edit config.yaml with YOUR credentials

REM 4. First login
run_login.bat

REM 5. Test with 3 jobs
run_test.bat

REM 6. Daily run
run_daily.bat
```

## ⚙️ Configuration

Edit `config.yaml` before first run:

```yaml
# Your credentials
credentials:
  linkedin:
    email: "your@email.com"
    password: "your_password"
  naukri:
    email: "your@email.com"  
    password: "your_password"

# Your profile
profile:
  name: "Your Name"
  email: "your@email.com"
  phone: "+91 XXXXXXXXXX"
  resume_path: "resume/Your_Resume.pdf"

# Screening answers (auto-filled in forms)
screening:
  years_of_experience: "2"
  expected_ctc: "12 LPA"
  current_ctc: "5 LPA"
  notice_period: "15 days"
```

## 📁 Files

| File | Purpose |
|---|---|
| `main.py` | Main bot entry point |
| `config.yaml` | All your settings & credentials |
| `linkedin_apply.py` | LinkedIn Easy Apply automation |
| `naukri_apply.py` | Naukri apply automation |
| `scraper.py` | Job scraping via Apify |
| `filter.py` | Job filtering (title/location/duplicates) |
| `tracker.py` | SQLite tracker (prevents re-applying) |
| `utils.py` | Shared utilities |
| `login_setup.py` | First-time browser session setup |

## 🛡️ Safety Features

- **Anti-detection**: Random delays, human-like scrolling, mouse movements
- **Verified posts only**: Skips unverified/suspicious job posts
- **Session persistence**: Saves browser session to avoid repeated logins
- **Duplicate check**: SQLite tracker prevents applying to same job twice
- **Rate limiting**: Configurable pauses between applications

## 📊 Check Stats

```bash
# macOS
bash check_stats.sh

# Windows
check_stats.bat
```

## ⚠️ Important Notes

1. **Resume**: Place your PDF resume in the `resume/` folder
2. **First login**: Run `run_login` first to save browser session
3. **Headed mode**: The bot runs with a visible browser (`--headed`) for reliability
4. **CAPTCHA**: If LinkedIn shows a CAPTCHA, you have 30 seconds to solve it manually
5. **Session expiry**: Re-run `run_login` if sessions expire (~10 days)
