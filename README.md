# Linkedin_Auto_apply

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python: 3.10+](https://img.shields.io/badge/Python-3.10%2B-brightgreen.svg)](https://www.python.org/)
[![Selenium: Automated](https://img.shields.io/badge/Automation-Selenium-orange.svg)](https://www.selenium.dev/)

An intelligent, production-ready LinkedIn Easy Apply automation bot that runs entirely on your local machine. It navigates job listings matching your exact search criteria, accurately answers repetitive application questions using a deterministic rules engine (with optional AI LLM fallback), and submits applications with your designated resume.

---

## 📋 Table of Contents
1. [Core Features](#-core-features)
2. [Security & Privacy Rules](#-security--privacy-rules)
3. [Prerequisites](#-prerequisites)
4. [Installation & Setup](#-installation--setup)
5. [Configuration Rules](#-configuration-rules)
6. [How the Question-Answering Engine Works](#-how-the-question-answering-engine-works)
7. [Running the Bot](#-running-the-bot)
8. [Recommended Best Practices](#-recommended-best-practices)
9. [Troubleshooting & FAQs](#-troubleshooting--faqs)
10. [Project Structure](#-project-structure)
11. [Disclaimer & License](#-disclaimer--license)

---

## 🌟 Core Features

- **Automated Easy Apply Pipeline**: Applies to targeted jobs in minutes with configurable rate limits.
- **Smart Question-Answering Engine**:
  - Deterministic evaluation for work experience across technologies (Python, SQL, PyTorch, C++, Cloud, MLOps, etc.).
  - Handles numeric fields, experience brackets (e.g. `1-3 years`), notice periods in days/weeks/months, and CTC/salary ranges in Lakhs or monthly terms.
  - Automatically identifies affirmative screening questions (*availability, relocation, comfort with salary, technical competence*) and answers `Yes`, while strictly safeguarding disqualifiers (*visa sponsorship, criminal history, former employee status*) as `No`.
  - Supports `<select>` dropdowns, `<fieldset>` radio buttons, checkboxes, text fields, and numeric inputs.
- **Dual Configuration Modes**:
  - **Web Control Panel**: Browser-based UI (`app.py` / `start.bat`) saving directly to a local, git-ignored `user_config.json`.
  - **Code Configuration**: Direct file-based edits inside the `config/` directory.
- **Anti-Bot & Human Simulation**:
  - Humanized keystroke jitter (`human_type`), natural click gaps, and browser automation evasion using `undetected_chromedriver`.
- **Dry-Run Mode**: Inspect filled applications without actually submitting them (`stop_before_submit = True`).

---

## 🔒 Security & Privacy Rules

> [!IMPORTANT]
> **CRITICAL: NEVER COMMIT SECRETS OR PERSONAL DATA TO GITHUB**

1. **Git-Ignored Files**:
   - `.env`, `.env.*`, and `user_config.json` are **strictly ignored** in `.gitignore`.
   - All resumes (`all resumes/`, `*.pdf`) and activity logs (`logs/`, `*.log`) are ignored.
   - Never remove these rules from `.gitignore`.
2. **Local Execution**:
   - All credentials and sessions run locally on your machine. No data is sent to external servers or third-party cloud services.
3. **Environment Template**:
   - A safe template is provided in [`.env.example`](.env.example). Never store live passwords in tracked files.

---

## 💻 Prerequisites

- **Operating System**: Windows 10/11, macOS, or Linux
- **Python**: Version **3.10** or higher ([python.org](https://www.python.org/downloads/))
- **Google Chrome**: Latest stable version ([google.com/chrome](https://www.google.com/chrome/))
- **Git**: For cloning and updating ([git-scm.com](https://git-scm.com/))

---

## 🚀 Installation & Setup

### 1. Clone the Repository
```bash
git clone https://github.com/kumarankur123/Linkedin_Auto_apply.git
cd Linkedin_Auto_apply
```

### 2. Create and Activate Virtual Environment
```bash
# Windows
python -m venv .venv
.\.venv\Scripts\activate

# macOS / Linux
python3 -m venv .venv
source .venv/bin/activate
```

### 3. Install Dependencies
```bash
pip install --upgrade pip
pip install -r requirements.txt
```

---

## ⚙️ Configuration Rules

You can configure the bot in one of two ways:

### Option A: Web Control Panel (Easiest)
1. Run `start.bat` (Windows) or `python app.py`.
2. Open `http://127.0.0.1:5000` in your web browser.
3. Fill out the tabs:
   - **Account**: LinkedIn login credentials (or leave blank to log in manually in the opened Chrome browser).
   - **Profile**: Personal information, location, contact details.
   - **Search**: Target job titles, search location, experience levels, job type.
   - **Filters & Answers**: Salary expectations, notice period, years of experience, citizenship.
4. Click **Save**. Settings are automatically saved to `user_config.json`.

---

### Option B: Direct Config Files (`config/` folder)

| File | Purpose & Key Parameters |
| :--- | :--- |
| **`config/search.py`** | `search_terms`: List of job titles to search for.<br>`search_location`: Target country or city (e.g. `"India"` or `"United States"`).<br>`experience_level`: `["Entry level", "Associate", "Mid-Senior level"]`.<br>`on_site`: `["Remote", "Hybrid", "On-site"]`.<br>`title_blacklist` & `company_blacklist`: Keywords/companies to skip. |
| **`config/questions.py`** | `years_of_experience`: Total years of experience (e.g. `"2"`).<br>`current_ctc` & `desired_salary`: Annual compensation in INR or USD.<br>`notice_period`: Notice period in days (e.g. `30`).<br>`require_visa`: `"Yes"` or `"No"`.<br>`legally_authorized`: `"Yes"` or `"No"`.<br>`recent_employer`: Name of your most recent employer. |
| **`config/personals.py`** | `first_name`, `last_name`, `phone_number`, `current_city`, `state`, `country`, and Equal Opportunity disclosures. |
| **`config/secrets.py`** | Optional LinkedIn `username` and `password`.<br>`use_AI`: Set to `True` if using an LLM API (OpenAI, Gemini, Ollama) for unclassified free-form questions. |
| **`config/settings.py`** | `stop_before_submit`: Dry-run mode (`True` stops at Review screen; `False` submits).<br>`click_gap`: Delay between browser interactions in seconds.<br>`run_in_background`: Headless/background mode toggle. |

---

## 🧠 How the Question-Answering Engine Works

The bot features a comprehensive question resolution pipeline in [`runAiBot.py`](runAiBot.py):

1. **Experience Questions (Text/Numeric)**:
   - Matches questions like *"How many years of work experience do you have with [Skill]?"* (e.g. Python, SQL, RAG, Node.js, C++, Odoo, PostgreSQL, etc.).
   - During live runs, automatically fills your configured `years_of_experience`.
2. **Joining & Notice Period**:
   - Matches *"In how many days can you join?"*, *"Notice period in days"*, or *"How soon can you join?"* and inputs your `notice_period` (e.g. `30`).
3. **Salary & CTC Handling**:
   - Automatically calculates Lakhs (e.g. `11.00` / `15.00`) or Monthly equivalents (e.g. `91666` / `125000`) based on question phrasing.
4. **Dropdown & Radio Selection**:
   - Matches degree levels (B.Tech / Bachelor's Degree).
   - Resolves numeric experience brackets (e.g. mapping `2` years to `1-3 years`).
   - Automatically answers `Yes` to screening questions (*"Are you comfortable proceeding with the advertised salary?"*, *"Are you available full-time?"*, *"Do you have hands-on experience building POCs?"*).
   - Strictly keeps disqualifying questions (*visa sponsorship requirements, felony/criminal history, past employee status*) as `No`.

---

## 🏃 Running the Bot

### Windows Quick Launcher
Double-click `run_bot.bat` or `run_linkedin_bot.bat`:
```cmd
run_bot.bat
```
This script:
1. Cleans up any orphaned ChromeDriver processes.
2. Activates `.venv`.
3. Launches `runAiBot.py`.

### Command Line
```bash
python runAiBot.py
```

### Stopping the Bot
Double-click `stop_bot.bat` or run:
```cmd
stop_bot.bat
```
This cleanly terminates all background Python and ChromeDriver processes.

---

## 🛡️ Recommended Best Practices

1. **Start with a Dry Run**:
   - Set `stop_before_submit = True` in `config/settings.py` or the control panel for your first 3–5 applications.
   - Verify that your resume, contact info, and answers appear correctly on the final review step.
2. **Daily Application Limits**:
   - Apply to **30–60 jobs per day** to keep your account safe and natural.
   - Avoid aggressive nonstop runs. Use `switch_number = 30` to rotate search queries.
3. **Keep Chrome in the Foreground**:
   - When running without headless mode, let the browser operate in its window without manual interference.
4. **Inspect Application Logs**:
   - Review [`logs/log.txt`](logs/) to verify which jobs were submitted, skipped, or filtered.

---

## ❓ Troubleshooting & FAQs

- **Bot skipped a job with "no answer in config/questions.py"**:
  - Open `logs/log.txt` to find the exact unhandled question label.
  - Add appropriate keywords into `config/questions.py` or `get_profile_pre_answer` in `runAiBot.py`.
- **ChromeDriver version mismatch**:
  - `runAiBot.py` uses `undetected_chromedriver` which auto-manages matching driver binaries.
  - Run `stop_bot.bat` to clear cached driver locks and relaunch.
- **Two-Factor Authentication (2FA) / Captcha**:
  - If LinkedIn prompts for email/SMS OTP or Captcha on first launch, solve it manually in the opened Chrome window.
  - The login session is saved in the persistent Chrome profile directory so you won't need to log in again.

---

## 📁 Project Structure

```plaintext
Linkedin_Auto_apply/
├── config/
│   ├── personals.py        # Legal name, phone, address, equal opportunity
│   ├── questions.py        # Work experience, CTC, notice period, links
│   ├── search.py           # Job titles, locations, blacklist filters
│   ├── secrets.py          # Credentials & AI LLM setup
│   └── settings.py         # Runtime speeds, safe mode, dry-run toggle
├── modules/
│   ├── clickers_and_finders.py  # Selenium interaction primitives
│   ├── helpers.py               # Human typing simulation & logging
│   ├── open_chrome.py           # Undetected ChromeDriver setup
│   └── validator.py             # Configuration integrity validator
├── tests/                  # Automated pytest test suite (258+ tests)
├── .env.example            # Environment variables template
├── .gitignore              # Strict ignore rules for secrets & outputs
├── app.py                  # Web Control Panel Flask application
├── runAiBot.py             # Main application execution engine
├── run_bot.bat             # Windows one-click bot launcher
├── stop_bot.bat            # Clean process terminator
├── requirements.txt        # Production dependencies
└── README.md               # Documentation & usage rules
```

---

## 📜 Disclaimer & License

### Disclaimer
This software is provided for educational and personal automation purposes only. The user assumes full responsibility for complying with LinkedIn's User Agreement and applicable terms of service. The developers are not liable for account restrictions, suspensions, or misrepresentations resulting from the use of this tool.

### License
This project is licensed under the **MIT License** — see the [LICENSE](LICENSE) file for details.
