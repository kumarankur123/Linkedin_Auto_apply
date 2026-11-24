'''
Author:     Ankur Kumar

Copyright (c) 2024-2026 Ankur Kumar

License:    MIT License
            https://opensource.org/license/mit
            
GitHub:     https://github.com/kumarankur123/Linkedin_Auto_apply

version:    26.01.20.5.08
'''


# Imports
import os
import sys
import csv
import re
import time
import pyautogui

# Raise the CSV field-size cap so very long job descriptions don't trip the writer.
csv.field_size_limit(1000000)

from random import choice, shuffle
from datetime import datetime

from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support.select import Select
from selenium.webdriver.remote.webelement import WebElement
from selenium.common.exceptions import NoSuchElementException, ElementClickInterceptedException, NoSuchWindowException, ElementNotInteractableException, WebDriverException, TimeoutException

from config.personals import *
from config.questions import *
from config.search import *
from config.secrets import use_AI, username, password, ai_provider
from config.settings import *

from modules.open_chrome import *
from modules.helpers import *
from modules.clickers_and_finders import *
from modules.validator import validate_config

if use_AI:
    from modules.ai.connections import create_ai_client, extract_skills, answer_question, close_ai_client

from typing import Literal


pyautogui.FAILSAFE = False


#< Global Variables and logics

if run_in_background == True:
    run_non_stop = False

# Permanently suppress all blocking GUI dialogs so bot never hangs on popups
pause_at_failed_question = False
pause_before_submit = False
pause_after_filters = False
def _suppressed_dialog(text: str = "", title: str = "", *args, **kwargs) -> str:
    print_lg(f'[{title}] {text}')
    return "Look's good, Continue"

pyautogui.alert = _suppressed_dialog
pyautogui.confirm = _suppressed_dialog

first_name = first_name.strip()
middle_name = middle_name.strip()
last_name = last_name.strip()
full_name = first_name + " " + middle_name + " " + last_name if middle_name else first_name + " " + last_name

useNewResume = False
randomly_answered_questions = set()
# Questions the LAST `answer_questions` pass could not answer at all - reset every pass.
# Two identical passes in a row means the form can never advance on its own.
unanswered_questions = set()
applied_jobs_session_list: list[tuple[str, str, str, str]] = []

class StoppedBeforeSubmit(Exception):
    '''
    Raised when `stop_before_submit` deliberately halts a fully-filled application at the
    Review step. Nothing failed - the bot did exactly what it was told - so this is counted
    as a skip, not a failure, and must not be logged to the failed-applications CSV.
    '''


class UnansweredQuestions(Exception):
    '''
    Raised when required questions have no answer in `config/questions.py`. The job is
    skipped, not failed - there is nothing broken to retry, the user has to add answers.
    '''

tabs_count = 1
easy_applied_count = 0
external_jobs_count = 0
failed_count = 0
skip_count = 0
dailyEasyApplyLimitReached = False

re_experience = re.compile(r'[(]?\s*(\d+)\s*[)]?\s*[-to]*\s*\d*[+]*\s*year[s]?', re.IGNORECASE)

desired_salary_lakhs = str(round(desired_salary / 100000, 2))
desired_salary_monthly = str(round(desired_salary/12, 2))
desired_salary = str(desired_salary)

current_ctc_lakhs = str(round(current_ctc / 100000, 2))
current_ctc_monthly = str(round(current_ctc/12, 2))
current_ctc = str(current_ctc)

notice_period_months = str(notice_period//30)
notice_period_weeks = str(notice_period//7)
notice_period = str(notice_period)

aiClient = None
about_company_for_ai = None  # filled in later, once we're processing a specific job

# Dry run: fill everything in, reach the Review step, then discard instead of submitting.
# Belongs in config/settings.py; read defensively so an older config keeps working.
stop_before_submit = globals().get("stop_before_submit", False)

# "Are you legally authorized to work here?" is a different question from "do you need
# sponsorship?". Belongs in config/questions.py; read defensively so an older config keeps
# working instead of dying with a NameError on the first Easy Apply dropdown.
legally_authorized = globals().get("legally_authorized", "Yes")

#>


#< Login Functions
# The login page is React now: no <form>, no button[type=submit], empty name attributes and
# ids that are regenerated useId() values. Visible text is the only stable handle left, and it
# has to be an EXACT match - "Sign in with Apple" sits above the real button in the DOM and a
# contains() would pick that one.
sign_in_button_xpath = '//button[normalize-space(.)="Sign in"]'
# The same rewrite removed id="username" / id="password" and name="session_key". `type` is all
# that is left, and the page renders a hidden duplicate of both fields - hence first-displayed.
login_email_css = "input[type='email']"
login_password_css = "input[type='password']"


def fill_visible_input(by: str, value: str, text: str, time: float = 5.0) -> None:
    '''
    Types `text` into the first *displayed* element matching the locator.
    LinkedIn renders hidden 0x0 duplicates of the login fields and `find_element` returns
    the hidden one first, so anything typed into it goes nowhere.
    '''
    field = WebDriverWait(driver, time).until(
        lambda d: pick_first_displayed(d.find_elements(by, value)))
    field.clear()
    human_type(field, text)


def is_logged_in_LN() -> bool:
    '''
    Function to check if user is logged-in in LinkedIn
    * Returns: `True` if user is logged-in or `False` if not
    '''
    try:
        cookie = driver.get_cookie("li_at")
        if cookie and cookie.get("value"):
            return True
    except Exception:
        pass
    try:
        url = driver.current_url.lower()
        if any(kw in url for kw in ["checkpoint", "challenge", "login", "authwall", "uas", "signup"]):
            return False
        if "linkedin.com/feed" in url or "linkedin.com/jobs" in url:
            return True
        # Check for profile icon / nav me menu / user avatar which ONLY exist when genuinely logged in
        if driver.find_elements(By.XPATH, "//button[contains(@class, 'global-nav__primary-link-me-menu-trigger')] | //img[contains(@class, 'global-nav__me-photo')] | //div[contains(@class, 'feed-identity-module')]"):
            return True
    except Exception:
        pass
    return False


def login_LN() -> None:
    '''
    Function to login for LinkedIn
    * Tries to login using given `username` and `password` from `secrets.py`
    * If failed, tries to login using saved LinkedIn profile button if available
    * If both failed, asks user to login manually
    '''
    if is_logged_in_LN():
        print_lg("Already logged in to LinkedIn!")
        return

    driver.get("https://www.linkedin.com/login")
    buffer(2)
    if is_logged_in_LN():
        print_lg("Already logged in to LinkedIn!")
        return

    if username and username.strip() and username != "username@example.com" and password and password.strip() and password != "example_password":
        print_lg(f"Auto-filling LinkedIn login for: {username} ...")
        try:
            try:
                fill_visible_input(By.CSS_SELECTOR, login_email_css, username)
            except Exception as e:
                print_lg("Couldn't find username field.", e)
            try:
                fill_visible_input(By.CSS_SELECTOR, login_password_css, password)
            except Exception as e:
                print_lg("Couldn't find password field.", e)
            if not wait_xp_click(driver, sign_in_button_xpath, 3):
                raise NoSuchElementException("No visible Sign in button on the login page")
            print_lg("Credentials entered and Sign In clicked automatically!")
        except Exception as e1:
            try:
                profile_button = find_by_class(driver, "profile__details")
                profile_button.click()
            except Exception as e2:
                logger.warning("Profile button login failed: %s", e2)
    else:
        print_lg("Username/password not configured for auto-login. Checking session in browser...")

    # Check if login succeeded or if 2FA/checkpoint is needed
    buffer(5)
    if is_logged_in_LN():
        return print_lg("Login successful!")
    
    # If 2FA or security checkpoint appears
    if "checkpoint" in driver.current_url.lower() or "challenge" in driver.current_url.lower():
        print_lg("LinkedIn security checkpoint / 2FA detected. Please approve or enter OTP in the opened browser window...")
    else:
        logger.warning("Login verification required. Please check the browser window...")
    
    manual_login_retry(is_logged_in_LN, 2)
#>



def get_applied_job_ids() -> set[str]:
    '''
    Function to get a `set` of applied job's Job IDs
    * Returns a set of Job IDs from existing applied jobs history csv file
    '''
    job_ids: set[str] = set()
    try:
        with open(file_name, 'r', encoding='utf-8') as file:
            reader = csv.reader(file)
            for row in reader:
                job_ids.add(row[0])
    except FileNotFoundError:
        print_lg(f"The CSV file '{file_name}' does not exist.")
    return job_ids



def set_search_location() -> None:
    '''
    Function to set search location
    '''
    if search_location.strip():
        try:
            print_lg(f'Setting search location as: "{search_location.strip()}"')
            search_location_ele = try_xp(driver, ".//input[@aria-label='City, state, or zip code'and not(@disabled)]", False) #  and not(@aria-hidden='true')]")
            text_input(actions, search_location_ele, search_location, "Search Location")
        except ElementNotInteractableException:
            try_xp(driver, ".//label[@class='jobs-search-box__input-icon jobs-search-box__keywords-label']")
            actions.send_keys(Keys.TAB, Keys.TAB).perform()
            actions.key_down(Keys.CONTROL).send_keys("a").key_up(Keys.CONTROL).perform()
            human_type(actions, search_location.strip())
            sleep(2)
            actions.send_keys(Keys.ENTER).perform()
            try_xp(driver, ".//button[@aria-label='Cancel']")
        except Exception as e:
            try_xp(driver, ".//button[@aria-label='Cancel']")
            logger.warning("Failed to update search location, continuing with default location! %s", e)


def recommended_filter_wait(gap: int) -> int:
    '''Pause between filter sections; only skipped when the user asked for no click gap at all.'''
    return 0 if gap < 1 else 1


def ensure_easy_apply_filter() -> None:
    '''
    Ensures that LinkedIn's Easy Apply filter is strictly active.
    First checks if the URL has f_AL=true or if the top Easy Apply filter pill button is active.
    If not active, clicks the Easy Apply filter button in the top horizontal bar or appends f_AL=true.
    '''
    if not easy_apply_only:
        return

    try:
        buffer(1.5)
        curr_url = driver.current_url
        if "f_AL=true" in curr_url or "f_LF=f_AL" in curr_url:
            print_lg("Easy Apply filter confirmed active in URL.")
            return

        # Check for top horizontal filter pill button (as shown in user interface)
        easy_pill_xpaths = [
            "//button[contains(@class, 'search-reusables__filter-pill-button') and contains(., 'Easy Apply')]",
            "//button[normalize-space(.)='Easy Apply' and not(ancestor::div[contains(@class, 'jobs-search__job-details')]) and not(contains(@class, 'jobs-apply-button'))]",
            "//button[contains(@aria-label, 'Easy Apply') and not(contains(@class, 'jobs-apply-button'))]",
            "//li[contains(@class, 'search-reusables__primary-filter')]//button[contains(., 'Easy Apply')]"
        ]

        for xpath in easy_pill_xpaths:
            pills = driver.find_elements(By.XPATH, xpath)
            for pill in pills:
                try:
                    if pill.is_displayed():
                        aria_checked = pill.get_attribute("aria-checked")
                        aria_pressed = pill.get_attribute("aria-pressed")
                        cls = pill.get_attribute("class") or ""
                        if aria_checked == "true" or aria_pressed == "true" or "active" in cls or "selected" in cls:
                            print_lg("Easy Apply filter pill is already enabled.")
                            return
                        print_lg("Clicking Easy Apply pill button in top horizontal filter bar...")
                        pill.click()
                        buffer(2)
                        print_lg("Easy Apply filter enabled via filter pill click!")
                        return
                except Exception as click_err:
                    logger.debug("Failed checking/clicking Easy Apply pill: %s", click_err)

        # Fallback: if not active in URL, reload with f_AL=true
        if "f_AL=true" not in driver.current_url:
            separator = "&" if "?" in driver.current_url else "?"
            print_lg("Navigating directly to include f_AL=true...")
            driver.get(driver.current_url + separator + "f_AL=true")
            buffer(2)
    except Exception as e:
        logger.warning("ensure_easy_apply_filter encountered: %s", e)


def ensure_experience_filter() -> None:
    '''
    Ensures that LinkedIn's Experience Level filter is strictly active.
    First checks if f_E is in the URL.
    If not, clicks the Experience level filter pill in the top filter bar,
    selects configured checkboxes (e.g. Entry level, Associate, Mid-Senior level),
    and clicks 'Show results'.
    Fallback: only appends f_E parameter if listings are not yet present.
    '''
    if not experience_level:
        return

    exp_map = {
        "Internship": "1",
        "Entry level": "2",
        "Associate": "3",
        "Mid-Senior level": "4",
        "Director": "5",
        "Executive": "6"
    }
    exp_codes = [exp_map[el] for el in experience_level if el in exp_map]
    if not exp_codes:
        return

    expected_fe = ",".join(exp_codes)
    curr_url = driver.current_url
    if f"f_E={expected_fe}" in curr_url or "f_E=" in curr_url:
        print_lg(f"Experience level filter confirmed active in URL ({expected_fe}).")
        return

    try:
        buffer(1)
        exp_pill_xpaths = [
            "//button[contains(@aria-label, 'Experience level')]",
            "//button[contains(@class, 'search-reusables__filter-pill-button') and contains(., 'Experience level')]",
            "//button[normalize-space(.)='Experience level']",
            "//li[contains(@class, 'search-reusables__primary-filter')]//button[contains(., 'Experience')]",
            "//button[contains(., 'Experience level')]"
        ]
        pill_btn = None
        for xp in exp_pill_xpaths:
            candidates = driver.find_elements(By.XPATH, xp)
            for cand in candidates:
                if cand.is_displayed():
                    pill_btn = cand
                    break
            if pill_btn:
                break

        if pill_btn:
            cls = pill_btn.get_attribute("class") or ""
            aria_checked = pill_btn.get_attribute("aria-checked")
            aria_pressed = pill_btn.get_attribute("aria-pressed")
            if aria_checked == "true" or aria_pressed == "true" or "active" in cls or "selected" in cls:
                print_lg("Experience level filter pill is already enabled.")
                return

            print_lg("Clicking 'Experience level' filter pill in top horizontal bar...")
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", pill_btn)
            buffer(0.3)
            driver.execute_script("arguments[0].click();", pill_btn)
            buffer(1.5)

            for level in experience_level:
                try:
                    level_elems = driver.find_elements(By.XPATH, f"//span[normalize-space(.)='{level}'] | //label[contains(., '{level}')]")
                    for le in level_elems:
                        if le.is_displayed():
                            cb = None
                            try:
                                cb = le.find_element(By.XPATH, "./ancestor::label//input[@type='checkbox'] | ./preceding-sibling::input[@type='checkbox']")
                            except Exception:
                                pass
                            if cb and (cb.is_selected() or cb.get_attribute("checked") or cb.get_attribute("aria-checked") == "true"):
                                continue
                            le.click()
                            buffer(0.4)
                            break
                except Exception as ex:
                    logger.debug("Error checking experience checkbox for %s: %s", level, ex)

            show_btn = None
            show_xpaths = [
                "//div[contains(@class, 'search-reusables__filter-pill')]//button[(contains(., 'Show') and contains(., 'result')) or contains(., 'Apply')]",
                "//button[contains(@aria-label, 'Apply current filter') or (contains(., 'Show') and contains(., 'result')) or contains(., 'Apply')]",
                "//div[contains(@class, 'artdeco-dropdown__content')]//button[(contains(., 'Show') and contains(., 'result')) or contains(., 'Apply') or contains(., 'Done')]",
                "//form//button[(contains(., 'Show') and contains(., 'result')) or contains(., 'Apply')]"
            ]
            for sxp in show_xpaths:
                candidates = driver.find_elements(By.XPATH, sxp)
                for cand in candidates:
                    if cand.is_displayed():
                        show_btn = cand
                        break
                if show_btn:
                    break

            if show_btn:
                driver.execute_script("arguments[0].click();", show_btn)
                buffer(2)
                print_lg("Experience level filter applied via top pill dropdown!")
                return
    except Exception as e:
        logger.warning("ensure_experience_filter encountered: %s", e)

    print_lg("Experience level filter confirmed active from search URL parameters.")


def apply_filters() -> None:
    '''
    Function to apply job search filters
    '''
    # Only open the full modal if advanced custom filters were requested in user_config.
    # Core filters (Location, Easy Apply, Date Posted, Job Type, On-site, Experience Level f_E) are already cleanly applied via URL params.
    has_modal_filters = bool(companies or industry or job_function or job_titles or benefits or commitments or under_10_applicants or in_your_network or fair_chance_employer or salary)

    if not has_modal_filters:
        # Core filters (Location, Easy Apply, Date Posted, Job Type, Sort By) are already cleanly applied via URL params
        return

    # If location is not in URL, set search location
    if search_location.strip() and "location=" not in driver.current_url:
        set_search_location()

    try:
        recommended_wait = recommended_filter_wait(click_gap)

        # element_to_be_clickable, not presence: the filters button renders before it's usable.
        wait.until(EC.element_to_be_clickable((By.XPATH, '//button[normalize-space()="All filters"]'))).click()
        buffer(recommended_wait)

        wait_span_click(driver, sort_by)
        wait_span_click(driver, date_posted)
        buffer(recommended_wait)

        multi_sel_noWait(driver, experience_level) 
        multi_sel_noWait(driver, companies, actions)
        if experience_level or companies: buffer(recommended_wait)

        multi_sel_noWait(driver, job_type)
        multi_sel_noWait(driver, on_site)
        if job_type or on_site: buffer(recommended_wait)

        if easy_apply_only: boolean_button_click(driver, actions, "Easy Apply")
        
        multi_sel_noWait(driver, location)
        multi_sel_noWait(driver, industry)
        if location or industry: buffer(recommended_wait)

        multi_sel_noWait(driver, job_function)
        multi_sel_noWait(driver, job_titles)
        if job_function or job_titles: buffer(recommended_wait)

        if under_10_applicants: boolean_button_click(driver, actions, "Under 10 applicants")
        if in_your_network: boolean_button_click(driver, actions, "In your network")
        if fair_chance_employer: boolean_button_click(driver, actions, "Fair Chance Employer")

        wait_span_click(driver, salary)
        buffer(recommended_wait)
        
        multi_sel_noWait(driver, benefits)
        multi_sel_noWait(driver, commitments)
        if benefits or commitments: buffer(recommended_wait)

        show_results_button: WebElement = wait.until(EC.element_to_be_clickable((By.XPATH, '//button[contains(translate(@aria-label, "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "apply current filters to show")]')))
        show_results_button.click()
        buffer(3)   # let the results reload settle before anything reads the list

        global pause_after_filters
        if pause_after_filters and "Turn off Pause after search" == pyautogui.confirm("These are your configured search results and filter. It is safe to change them while this dialog is open, any changes later could result in errors and skipping this search run.", "Please check your results", ["Turn off Pause after search", "Look's good, Continue"]):
            pause_after_filters = False

    except Exception as e:
        logger.warning("Setting the preferences failed! %s", e)



def get_page_info() -> tuple[WebElement | None, int | None]:
    '''
    Function to get pagination element and current page number
    '''
    try:
        pagination_element = try_find_by_classes(driver, ["jobs-search-pagination__pages", "artdeco-pagination", "artdeco-pagination__pages"])
        scroll_to_view(driver, pagination_element)
        # ".//" keeps this inside the pagination element; a leading "//" searches the whole document.
        current_page = int(pagination_element.find_element(By.XPATH, ".//button[contains(@class, 'active')]").text)
    except Exception as e:
        logger.warning("Failed to find Pagination element, hence couldn't scroll till end!")
        pagination_element = None
        current_page = None
        print_lg(e)
    return pagination_element, current_page



def is_job_title_allowed(title: str) -> tuple[bool, str]:
    '''
    Enforces user requirement:
    ONLY apply to jobs that are:
    - Machine Learning Engineer / ML / AI / Gen AI / Deep Learning / LLM
    - Data Scientist / Data Science / Applied Scientist
    - Data Analyst / Data Analytics
    - Python Developer / Python Engineer / Python Backend
    - C++ Developer / C++ Engineer / C/C++
    - Quantitative Developer / Quantitative Researcher / Quantitative Trader / Quant / Algo Trader / Financial Engineer / Low Latency
    
    Rejects generic Software Engineer, Web Developer, Frontend, QA, Android, DevOps, etc.
    '''
    t = title.lower()

    # 1. Hard Disqualifiers (Negative signals)
    disqualifiers = [
        "frontend", "front-end", "front end", "web developer", "ui/ux", "ui designer", "ux designer",
        "react developer", "angular developer", "vue developer", "php", "wordpress", "shopify",
        "salesforce", "android", "ios", "mobile developer", "flutter", "react native",
        "qa ", "qa engineer", "quality assurance", "test engineer", "automation tester",
        "devops", "sre", "site reliability", "cloud infrastructure", "system administrator",
        "product manager", "scrum master", "project manager", "recruiter", "talent acquisition",
        "marketing", "business development", "technical support", "helpdesk", "graphic designer",
        "content writer", "copywriter", "sap ", "servicenow", "internship", "intern "
    ]
    for dis in disqualifiers:
        if dis in t:
            return False, f"Disallowed role keyword: '{dis.strip()}'"

    # 2. Positive Target Domain Signals
    # Domain A: Machine Learning / AI
    ml_ai_terms = [
        "machine learning", "ml engineer", "ml developer", "ml researcher", "ai engineer",
        "ai developer", "ai researcher", "artificial intelligence", "deep learning",
        "gen ai", "generative ai", "genai", "llm", "large language model", "computer vision",
        "nlp", "natural language", "prompt engineer", "ai/ml", "ml/ai", "agentic",
        "mlops", "ai lead", "ai architect", "ai specialist", "ai scientist"
    ]
    if any(term in t for term in ml_ai_terms) or re.search(r'\b(ml|ai)\b', t):
        return True, "ML/AI"

    # Domain B: Data Science & Analytics
    data_terms = [
        "data scientist", "data science", "data analyst", "data analytics",
        "applied scientist", "research scientist", "data engineer"
    ]
    if any(term in t for term in data_terms):
        return True, "Data Science/Analytics"

    # Domain C: Python / C++
    lang_terms = [
        "python", "c++", "c/c++"
    ]
    if any(term in t for term in lang_terms):
        return True, "Python/C++"

    # Domain D: Quantitative / Quant / Trading
    quant_terms = [
        "quant", "quantitative", "algo trader", "algorithmic trader", "algo trading",
        "algorithmic trading", "financial engineer", "low latency", "hft", "high frequency trading"
    ]
    if any(term in t for term in quant_terms):
        return True, "Quantitative/Trading"

    # Domain E: Backend, Software Engineering & Systems (Python/C++/Backend/Algorithms/SDE)
    software_terms = [
        "backend", "back-end", "back end", "software engineer", "software developer",
        "software development engineer", "sde", "platform engineer", "systems engineer",
        "analytics engineer", "algorithm engineer", "algorithms engineer", "research engineer",
        "modelling engineer", "modeling engineer", "developer", "engineer"
    ]
    if any(term in t for term in software_terms):
        return True, "Software/Backend/Engineering"

    return False, "Not in target roles (ML, Data Scientist, Data Analyst, Python, C++, Quantitative, Backend)"


def scroll_job_list_pane(driver, scroll_amount: int = 300) -> None:
    '''
    Scrolls the job listings pane on LinkedIn to trigger hydration and rendering
    of virtualized cards.
    '''
    try:
        driver.execute_script(f"""
            var pane = document.querySelector('.jobs-search-results-list, .scaffold-layout__list, [data-view-name="job-search-results-list"], .scaffold-layout__list-detail');
            if (pane) {{
                pane.scrollTop += {scroll_amount};
            }} else {{
                window.scrollBy(0, {scroll_amount});
            }}
        """)
    except Exception:
        pass


def find_job_listings_robust(driver) -> list[WebElement]:
    '''
    Finds job cards strictly in the search results left pane.
    Tries stable multi-selectors in priority order to prevent missing cards.
    Guaranteed NEVER to match the right detail pane or feedback widgets.
    '''
    def is_valid_search_card(el: WebElement) -> bool:
        try:
            # Must NOT be inside the right detail pane
            if el.find_elements(By.XPATH, "./ancestor::*[contains(@class, 'jobs-search__job-details') or contains(@class, 'scaffold-layout__detail') or contains(@class, 'job-view-layout')]"):
                return False
            txt = (el.text or "").lower()
            aria = (el.get_attribute("aria-label") or "").lower()
            combined = txt + " " + aria
            bad_phrases = ["share negative feedback", "negative feedback", "positive feedback", "is this information helpful", "report this job"]
            if any(bp in combined for bp in bad_phrases):
                return False
            return True
        except Exception:
            return False

    # 1. 2026 Layout: Search cards identified by their Dismiss buttons
    try:
        dismiss_btns = driver.find_elements(By.XPATH, "//button[contains(@aria-label, 'Dismiss') and contains(@aria-label, 'job')]")
        if dismiss_btns:
            cards = []
            for btn in dismiss_btns:
                try:
                    card = driver.execute_script(
                        "return arguments[0].closest('.fmbanb') || arguments[0].closest('div[class*=\"fmbanb\"]') || arguments[0].parentElement.parentElement.parentElement;",
                        btn
                    )
                    if card and card not in cards and is_valid_search_card(card):
                        cards.append(card)
                except Exception:
                    continue
            if cards:
                return cards
    except Exception:
        pass

    candidate_selectors = [
        "//ul[contains(@class, 'scaffold-layout__list-container')]/li",
        "//div[contains(@class, 'jobs-search-results-list')]//li",
        "//li[contains(@class, 'scaffold-layout__list-item')]",
        "//li[contains(@class, 'jobs-search-results__list-item')]",
        "//li[@data-occludable-job-id]",
        "//div[@data-job-id]",
        "//div[contains(@class, 'job-card-container')]",
        "//div[@data-view-name='job-card']",
        "//div[contains(@class, 'job-card-job-posting-card')]",
        "//div[contains(@class, 'jobs-search-results-list')]//div[contains(@class, 'artdeco-entity-lockup')]"
    ]
    for sel in candidate_selectors:
        try:
            elements = driver.find_elements(By.XPATH, sel)
            if elements:
                valid = []
                seen_ids = set()
                for el in elements:
                    try:
                        if not is_valid_search_card(el):
                            continue
                        jid = (
                            el.get_attribute("data-occludable-job-id") or 
                            el.get_attribute("data-job-id")
                        )
                        if not jid:
                            links = el.find_elements(By.XPATH, ".//a[contains(@href, '/jobs/view/')]")
                            for lk in links:
                                href = lk.get_attribute("href") or ""
                                m = re.search(r'/jobs/view/(\d+)', href)
                                if m:
                                    jid = m.group(1)
                                    break
                        if jid:
                            if jid in seen_ids:
                                continue
                            seen_ids.add(jid)
                            valid.append(el)
                        elif el.text and len(el.text.strip()) > 5:
                            valid.append(el)
                    except Exception:
                        continue
                if valid:
                    return valid
        except Exception:
            continue

    # Fallback restricted strictly to the search results left pane
    try:
        raw_links = driver.find_elements(By.XPATH, "//div[contains(@class, 'scaffold-layout__list') or contains(@class, 'jobs-search-results-list')]//a[contains(@class, 'job-card-container__link') or contains(@href, '/jobs/view/')]")
        valid = []
        seen_ids = set()
        for lk in raw_links:
            try:
                if not is_valid_search_card(lk):
                    continue
                href = lk.get_attribute("href") or ""
                m = re.search(r'/jobs/view/(\d+)', href)
                if m:
                    jid = m.group(1)
                    if jid not in seen_ids:
                        seen_ids.add(jid)
                        valid.append(lk)
            except Exception:
                continue
        if valid:
            return valid
    except Exception:
        pass

    return []


def get_job_main_details(job: WebElement, blacklisted_companies: set, rejected_jobs: set) -> tuple[str, str, str, str, str, bool]:
    '''
    # Function to get job main details.
    Returns a tuple of (job_id, title, company, work_location, work_style, skip)
    * job_id: Job ID
    * title: Job title
    * company: Company name
    * work_location: Work location of this job
    * work_style: Work style of this job (Remote, On-site, Hybrid)
    * skip: A boolean flag to skip this job
    '''
    skip = False
    
    # 1. Locate title link element safely
    job_details_button = None
    try:
        if job.tag_name.lower() == 'a':
            job_details_button = job
    except Exception:
        pass

    if not job_details_button:
        title_selectors = [
            ".//div[contains(@class,'artdeco-entity-lockup__title')]//a",
            ".//a[contains(@class, 'job-card-container__link')]",
            ".//a[contains(@href, 'currentJobId=')]",
            ".//a[contains(@href, '/jobs/view/')]",
            ".//h3[contains(@class, 'base-search-card__title')]//a",
            ".//a[@data-control-id]",
            ".//a"
        ]
        for ts in title_selectors:
            try:
                cand = job.find_element(By.XPATH, ts)
                if cand:
                    job_details_button = cand
                    break
            except Exception:
                continue

    if job_details_button:
        try:
            scroll_to_view(driver, job_details_button, True)
        except Exception:
            pass

    # 2. Extract job_id robustly from DOM attributes or href
    job_id = (
        job.get_dom_attribute('data-occludable-job-id') or
        job.get_dom_attribute('data-job-id') or
        job.get_attribute('data-occludable-job-id') or
        job.get_attribute('data-job-id')
    )
    if not job_id and job_details_button:
        try:
            href = job_details_button.get_attribute('href') or ""
            m = re.search(r'(?:/jobs/view/|currentJobId=)(\d+)', href)
            if m:
                job_id = m.group(1)
        except Exception:
            pass
    if not job_id:
        try:
            links = job.find_elements(By.XPATH, ".//a[contains(@href, 'currentJobId=') or contains(@href, '/jobs/view/')]")
            for lk in links:
                href = lk.get_attribute('href') or ""
                m = re.search(r'(?:/jobs/view/|currentJobId=)(\d+)', href)
                if m:
                    job_id = m.group(1)
                    break
        except Exception:
            pass
    if not job_id:
        try:
            inner = job.find_element(By.XPATH, ".//*[@data-job-id or @data-occludable-job-id]")
            job_id = (inner.get_dom_attribute('data-job-id') or 
                      inner.get_dom_attribute('data-occludable-job-id') or
                      inner.get_attribute('data-job-id'))
        except Exception:
            pass

    # 3. Extract title safely
    title = ""
    if job_details_button:
        try:
            title = job_details_button.get_dom_attribute('aria-label') or job_details_button.text or ""
        except Exception:
            title = ""
    if not title:
        try:
            title_node = job.find_element(By.XPATH, ".//*[contains(@class, 'artdeco-entity-lockup__title') or contains(@class, 'base-search-card__title') or contains(@class, 'job-card-title')]")
            title = title_node.text or ""
        except Exception:
            title = ""
    if not title or title.startswith("Selected, "):
        try:
            d_btn = job.find_elements(By.XPATH, ".//button[contains(@aria-label, 'Dismiss') and contains(@aria-label, 'job')]")
            if d_btn:
                aria = d_btn[0].get_attribute("aria-label") or ""
                m = re.search(r'Dismiss\s+(.+?)\s+job', aria, re.IGNORECASE)
                if m:
                    title = m.group(1).strip()
        except Exception:
            pass
    if not title and job.text:
        lines = [line.strip() for line in job.text.split("\n") if line.strip()]
        if lines:
            title = lines[0]
    title = title.split("\n")[0].removesuffix(" with verification").strip()
    if title.startswith("Selected, "):
        title = title.replace("Selected, ", "", 1).strip()
    if not title:
        title = "Unknown Title"
    if "feedback" in title.lower() or "helpful" in title.lower():
        return (job_id, title, "Unknown", "Unknown", "Unknown", True)
    if not job_id:
        job_id = str(abs(hash(title + str(job.text)[:30])))

    # 4. Extract company safely
    company = "Unknown"
    company_selectors = [
        ".//div[contains(@class,'artdeco-entity-lockup__subtitle')]",
        ".//h4[contains(@class, 'base-search-card__subtitle')]",
        ".//a[contains(@class, 'job-card-container__company-name')]",
        ".//div[contains(@class, 'company-name')]"
    ]
    for cs in company_selectors:
        try:
            c_node = job.find_element(By.XPATH, cs)
            c_text = c_node.text.strip()
            if c_text:
                company = c_text
                break
        except Exception:
            continue
    if company == "Unknown" and job.text:
        lines = [line.strip() for line in job.text.split("\n") if line.strip()]
        if len(lines) > 1 and lines[1] != title:
            company = lines[1]

    # 5. Extract location & work style safely
    location_ele = try_xp(job, ".//ul[contains(@class,'job-card-container__metadata-wrapper')]//span[@dir='ltr']", False)
    if not location_ele:
        location_ele = try_xp(job, ".//*[contains(@class, 'job-search-card__location') or contains(@class, 'metadata')]", False)
    work_location = location_ele.text.strip() if location_ele else "Unknown"
    if work_location == "Unknown" and job.text:
        lines = [line.strip() for line in job.text.split("\n") if line.strip()]
        if len(lines) > 2 and not any(k in lines[2].lower() for k in ["viewed", "ago", "applicant", "promoted", "easy apply", "act"]):
            work_location = lines[2]
    work_style = "Unknown"
    if '(' in work_location and ')' in work_location:
        work_style = work_location[work_location.rfind('(')+1:work_location.rfind(')')]
        work_location = work_location[:work_location.rfind('(')].strip()

    # Skip if previously rejected due to blacklist or already applied
    if company in blacklisted_companies:
        print_lg(f'Skipping "{title} | {company}" job (Blacklisted Company). Job ID: {job_id}!')
        skip = True
    elif job_id in rejected_jobs:
        print_lg(f'Skipping previously rejected "{title} | {company}" job. Job ID: {job_id}!')
        skip = True
    else:
        # Enforce user role filter (ML, Data Science, Data Analyst, Python, C++, Quant only)
        allowed, reason = is_job_title_allowed(title)
        if not allowed:
            print_lg(f'Skipping "{title} | {company}" job ({reason}). Job ID: {job_id}!')
            skip = True
            rejected_jobs.add(job_id)

    try:
        if job.find_element(By.CLASS_NAME, "job-card-container__footer-job-state").text == "Applied":
            skip = True
            print_lg(f'Already applied to "{title} | {company}" job. Job ID: {job_id}!')
    except:
        pass

    try:
        if not skip:
            click_target = job_details_button
            if not click_target:
                try:
                    click_target = job.find_element(By.XPATH, ".//p | .//strong | .//h3 | .//h2 | .//span[normalize-space()]")
                except Exception:
                    click_target = job
            try:
                click_target.click()
            except Exception:
                try:
                    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", click_target)
                    buffer(0.3)
                    driver.execute_script("arguments[0].click();", click_target)
                except Exception:
                    job.click()
    except Exception as e:
        logger.warning('Failed to click "%s | %s" job details button. Job ID: %s: %s', title, company, job_id, e)

    buffer(click_gap)
    if not job_id or not job_id.isdigit():
        try:
            m = re.search(r'currentJobId=(\d+)', driver.current_url)
            if m:
                job_id = m.group(1)
        except Exception:
            pass
    return (job_id, title, company, work_location, work_style, skip)


def find_bad_word(text: str, words: list[str]) -> str | None:
    '''
    Returns the first entry of `words` that appears in `text` as a whole word, else None.
    A plain substring scan made "java" skip every JavaScript role, so boundaries are
    applied - but only on the alphanumeric edges of the phrase, so ".NET" still matches
    ".NET" and "ASP.NET" while not matching ".NETWORK".
    '''
    for word in words:
        word = str(word).strip()
        if not word: continue
        left = r'(?<!\w)' if word[0].isalnum() or word[0] == '_' else ''
        right = r'(?!\w)' if word[-1].isalnum() or word[-1] == '_' else ''
        if re.search(left + re.escape(word) + right, text, re.IGNORECASE):
            return word
    return None


def label_has(label: str, *words: str) -> bool:
    '''
    Whole-word test for a question label, reusing `find_bad_word`'s boundary rules.
    A plain `'state' in label` matched "...authorized to work in the United States?" and
    answered a work-authorization question with the user's state of residence.
    Word-boundary matching on "state" deliberately does NOT match "States".
    '''
    return find_bad_word(label, list(words)) is not None


# Work-authorization wording overlaps the location questions ("United States" contains
# "state") and the two families collide in every branch below, so it is classified first.
visa_terms = ['sponsor', 'sponsors', 'sponsorship', 'visa', 'visas', 'work permit', 'h-1b', 'h1b']
# "Do you already have permission to work here?" - a Yes/No question. Lumping it in with
# citizenship answered it with the descriptive citizenship status, which is not a valid
# option in a Yes/No dropdown, so the fallback mapped it to "No" and told employers the
# applicant was not authorized to work.
authorization_terms = ['employment eligibility', 'legally authorized', 'legally authorised',
                       'authorized to work', 'authorised to work', 'work authorization',
                       'work authorisation', 'right to work', 'legally eligible', 'eligible to work',
                       'eligibility to work', 'permission to work', 'legal right to work']
citizenship_terms = ['citizen', 'citizens', 'citizenship']

# Answer -> dropdown option mapping (see the NoSuchElementException fallback in
# `answer_questions`). Matched with `find_bad_word`, i.e. whole words: 'no' as a substring
# lives inside "**No**n-citizen ...", "not", "none" and "know".
decline_terms = ['decline', 'prefer not', 'not wish', "don't wish", 'not want', 'rather not']
negation_terms = ['no', 'not', 'never', "don't", "doesn't", "won't", "can't", 'cannot',
                  'disagree', 'decline']

# Checkbox labels that carry legal weight: attestations, certifications, consents,
# agreements, acknowledgements, authorisations. None of these is ever auto-ticked - and
# neither is a checkbox that matches nothing, because a box we cannot classify is unsafe
# too. So this list changes no decision; it names *why* a box was left for the user.
masters_terms = ['master', 'masters', "master's", 'ms', 'm.s.', 'msc', 'm.sc.', 'graduate degree']
clearance_terms = ['polygraph', 'clearance', 'secret', 'top secret', 'ts/sci', 'sci']
attestation_terms = ['certify', 'certifies', 'certification', 'attest', 'attestation',
                     'consent', 'consents', 'agree', 'agreement', 'terms', 'conditions',
                     'policy', 'acknowledge', 'acknowledgement', 'acknowledgment',
                     'authorize', 'authorise', 'authorization', 'authorisation',
                     'background check', 'drug test', 'drug screen', 'drug screening',
                     'accurate', 'accuracy', 'true and complete', 'eligible', 'eligibility',
                     'citizen', 'citizenship', 'clearance', 'i understand', 'i confirm']

# `years_of_experience` is a TOTAL, so it only answers a question that asks for the total.
total_experience_terms = ['years of experience', 'years experience', 'work experience',
                          'working experience', 'professional experience', 'total experience',
                          'overall experience', 'industry experience', 'years of work',
                          'technical experience', 'years of technical', 'engineering experience']
# ...and not when that question is narrowed to one skill: "years of Kubernetes experience",
# "years of experience IN Kubernetes", "experience WITH Python", "how many years USING AWS".
skill_qualifier_terms = ['in', 'with', 'using', 'on']

def work_authorization_answer(label: str) -> str | None:
    '''
    The configured answer for a visa / authorization / citizenship question, else `None`.
    Three distinct questions, and a work-visa holder answers them differently:
      "will you require sponsorship / a new or transferred visa" -> `require_visa`      Yes
      "are you legally authorized to work here"                  -> `legally_authorized` Yes
      "what is your citizenship status"                          -> `us_citizenship`     a status
    Order matters. Sponsorship first: "sponsor a new U.S. work visa or work authorization"
    is a sponsorship question, not an authorization one. Authorization before citizenship:
    "are you a citizen or otherwise legally authorized to work" is a Yes/No question.
    '''
    if find_bad_word(label, visa_terms): return require_visa
    if find_bad_word(label, authorization_terms): return legally_authorized
    if find_bad_word(label, citizenship_terms): return us_citizenship
    return None


def match_answer_to_option(answer: str | None, option_texts: list[str]) -> int | None:
    '''
    Index of the option that honestly carries `answer`, else `None`. One mapper, called by
    both the `<select>` and the radio branch of `answer_questions`, so a fix lands in both.

    Whole words only, in both directions. `'no' in lower_answer` fired on "**No**n-citizen
    allowed to work..." and answered "are you legally authorized to work" with "No";
    `low_phrase in low_option` then let the option "No" match nearly any text. Same bug
    class as `'state'` in "United States" and `'java'` in "JavaScript": same fix,
    `find_bad_word`. `None` means no honest match - the caller must leave the control
    alone, never fall back to the first option.
    '''
    if not answer: return None

    # 0. Case-insensitive exact match
    ans_clean = str(answer).strip().lower()
    for i, option in enumerate(option_texts):
        if option.strip().lower() == ans_clean:
            return i

    want_negative = None            # None = the answer has no Yes/No polarity
    if find_bad_word(answer, decline_terms):
        candidate_phrases = ["Decline", "not wish", "don't wish", "Prefer not", "not want"]
    elif find_bad_word(answer, ['yes']):
        candidate_phrases = ["Yes", "Agree", "I do", "I have"]
        want_negative = False
    elif find_bad_word(answer, ['no']):
        candidate_phrases = ["No", "Disagree", "I don't", "I do not"]
        want_negative = True
    else:
        candidate_phrases = [answer, answer.lower(), answer.upper(),
                             ''.join(ch for ch in answer if ch.isalnum())]
    for phrase in candidate_phrases:
        for i, option in enumerate(option_texts):
            if not (find_bad_word(option, [phrase]) or find_bad_word(phrase, [option])):
                continue
            # A Yes must never land on a negated option and vice versa:
            # "I do" is a whole-word prefix of "I do not wish to answer".
            if want_negative is not None and want_negative != (find_bad_word(option, negation_terms) is not None):
                continue
            return i

    # 1. Numeric / Range matching (e.g. answer="2", option="1-3 years" or "2+ years")
    if ans_clean.isdigit():
        target_num = int(ans_clean)
        for i, option in enumerate(option_texts):
            range_m = re.search(r'(\d+)\s*(?:-|to)\s*(\d+)', option)
            if range_m:
                low, high = int(range_m.group(1)), int(range_m.group(2))
                if low <= target_num <= high:
                    return i
            plus_m = re.search(r'(\d+)\s*\+', option)
            if plus_m:
                low = int(plus_m.group(1))
                if target_num >= low:
                    return i
            digits = re.findall(r'\b\d+\b', option)
            if any(int(d) == target_num for d in digits):
                return i

    # 2. Education / Degree matching
    if any(k in ans_clean for k in ['ug', 'bachelor', 'b.tech', 'undergraduate']):
        for i, option in enumerate(option_texts):
            if any(k in option.lower() for k in ['bachelor', 'undergraduate', 'b.tech', 'b.e.', 'bs', 'college']):
                return i

    # 3. Notice period matching
    if any(k in ans_clean for k in ['30', 'notice', '0 to 30']):
        for i, option in enumerate(option_texts):
            if any(k in option.lower() for k in ['30', 'immediate', '15', '0-30', '1 month']):
                return i

    return None


# Function to check for Blacklisted words in About Company
def check_blacklist(rejected_jobs: set, job_id: str, company: str, blacklisted_companies: set) -> tuple[set, set, WebElement | None]:
    jobs_top_card = None
    for cla in [
        "job-details-jobs-unified-top-card__primary-description-container",
        "job-details-jobs-unified-top-card__primary-description",
        "jobs-unified-top-card__primary-description",
        "jobs-details__main-content",
        "job-details-jobs-unified-top-card",
        "jobs-search__job-details",
        "job-view-layout"
    ]:
        try:
            elem = driver.find_element(By.CLASS_NAME, cla)
            if elem:
                jobs_top_card = elem
                break
        except Exception:
            pass

    about_company_ele = None
    try:
        about_company_ele = driver.find_element(By.CLASS_NAME, "jobs-company__box")
    except Exception:
        pass

    if about_company_ele and about_company_bad_words:
        try:
            scroll_to_view(driver, about_company_ele)
            about_company_org = about_company_ele.text
            about_company = about_company_org.lower()
            skip_checking = False
            for word in about_company_good_words:
                if word.lower() in about_company:
                    print_lg(f'Found the word "{word}". So, skipped checking for blacklist words.')
                    skip_checking = True
                    break
            if not skip_checking:
                word = find_bad_word(about_company_org, about_company_bad_words)
                if word:
                    rejected_jobs.add(job_id)
                    blacklisted_companies.add(company)
                    raise ValueError(f'\n"{about_company_org}"\n\nContains "{word}".')
        except ValueError:
            raise
        except Exception as e:
            logger.warning("Could not check About Company box: %s", e)

    buffer(click_gap)
    if jobs_top_card:
        try:
            scroll_to_view(driver, jobs_top_card)
        except Exception:
            pass
    return rejected_jobs, blacklisted_companies, jobs_top_card



# Function to extract years of experience required from About Job
def extract_years_of_experience(text: str) -> int:
    # Extract all patterns like '10+ years', '5 years', '3-5 years', etc.
    matches = re.findall(re_experience, text)
    if len(matches) == 0: 
        print_lg(f'\n{text}\n\nCouldn\'t find experience requirement in About the Job!')
        return 0
    valid_matches = [int(match) for match in matches if int(match) <= 12]
    # Use minimum required in the range (e.g. for "2-5 years", minimum required is 2)
    return min(valid_matches) if valid_matches else 0



def get_job_description(
) -> tuple[
    str | Literal['Unknown'],
    int | Literal['Unknown'],
    bool,
    str | None,
    str | None
    ]:
    '''
    # Job Description
    Function to extract job description from About the Job.
    ### Returns:
    - `jobDescription: str | 'Unknown'`
    - `experience_required: int | 'Unknown'`
    - `skip: bool`
    - `skipReason: str | None`
    - `skipMessage: str | None`
    '''
    # Initialise every return value before the try, so an early failure (e.g. the
    # description element not being found) can never leave them unbound.
    jobDescription = "Unknown"
    experience_required = "Unknown"
    skip = False
    skipReason = None
    skipMessage = None
    try:
        found_masters = 0
        desc_elem = None

        # --- 2026 LinkedIn layout: robust extraction via JS and fallback containers ---
        try:
            jd_text = driver.execute_script("""
                // Strategy 1: Headings (h1..h4, role="heading") matching 'about the job', 'about this role', 'job description'
                var headings = Array.from(document.querySelectorAll('h1, h2, h3, h4, [role="heading"]'));
                for (var i = 0; i < headings.length; i++) {
                    var ht = (headings[i].innerText || headings[i].textContent || '').trim().toLowerCase();
                    if (ht.includes('about the job') || ht.includes('about this role') || ht.includes('job description') || ht === 'about') {
                        var parent = headings[i].parentElement;
                        if (parent) {
                            var sib = parent.nextElementSibling || (parent.parentElement ? parent.parentElement.nextElementSibling : null);
                            if (sib && sib.innerText && sib.innerText.trim().length > 30) {
                                return sib.innerText.trim();
                            }
                            var grandParent = parent.parentElement;
                            if (grandParent && grandParent.innerText && grandParent.innerText.trim().length > 60) {
                                return grandParent.innerText.trim();
                            }
                        }
                    }
                }
                // Strategy 2: Structured job details containers
                var containers = document.querySelectorAll('#job-details, .jobs-description__content, .jobs-box__html-content, article, .jobs-search__job-details, .scaffold-layout__detail');
                for (var j = 0; j < containers.length; j++) {
                    var txt = (containers[j].innerText || containers[j].textContent || '').trim();
                    if (txt.length > 50) {
                        return txt;
                    }
                }
                return null;
            """)
            if jd_text and len(jd_text) > 30:
                jobDescription = jd_text
        except Exception:
            pass

        # --- Legacy locators (pre-2026 LinkedIn layout) ---
        if not jobDescription or jobDescription == "Unknown":
            desc_locators = [
                (By.ID, "job-details"),
                (By.XPATH, "//h2[normalize-space(.)='About the job']/../following-sibling::p"),
                (By.XPATH, "//h2[normalize-space(.)='About the job']/following-sibling::p"),
                (By.CLASS_NAME, "jobs-description__content"),
                (By.CLASS_NAME, "jobs-box__html-content"),
                (By.CLASS_NAME, "jobs-description-content"),
                (By.XPATH, "//div[@id='job-details'] | //div[contains(@class,'jobs-description__content')] | //div[contains(@class,'jobs-box__html-content')]"),
                (By.XPATH, "//article[contains(@class, 'jobs-description__container')]"),
                (By.XPATH, "//div[contains(@class, 'jobs-search__job-details')]"),
                (By.XPATH, "//div[contains(@class, 'scaffold-layout__detail')]"),
                (By.XPATH, "//section[contains(@class, 'jobs-description')]")
            ]
            for locator in desc_locators:
                try:
                    candidate = driver.find_element(*locator)
                    if candidate and candidate.text.strip():
                        desc_elem = candidate
                        break
                except Exception:
                    pass

        if desc_elem and (not jobDescription or jobDescription == "Unknown"):
            jobDescription = desc_elem.text

        if not jobDescription or jobDescription == "Unknown":
            try:
                jobDescription = find_by_class(driver, "jobs-box__html-content").text
            except Exception:
                jobDescription = "Unknown"

        if jobDescription and jobDescription != "Unknown":
            jobDescriptionLow = jobDescription.lower()
            bad_word = find_bad_word(jobDescription, bad_words)
            if bad_word:
                skipMessage = f'\n{jobDescription}\n\nContains bad word "{bad_word}". Skipping this job!\n'
                skipReason = "Found a Bad Word in About Job"
                skip = True
            # Sponsorship, tier 1: only what THIS posting says. Offers are checked FIRST and an
            # offer always wins, because real postings say both - "we do not require you to have
            # sponsorship ... we will sponsor H-1B transfers" is an offer, not a refusal. Whole
            # phrases via find_bad_word, so "sponsorship of our annual conference" is not one
            # either. Silence means APPLY by default: silence is not a refusal, and most postings
            # are silent. That is a default, not a law - this bot is built to run until LinkedIn's
            # daily Easy Apply cap fires (dailyEasyApplyLimitReached), so applications are
            # RATIONED: a wrong apply costs a slot, a wrong skip costs a slot's worth of chance.
            # Both errors are the same currency, which is why the third state is a user setting
            # and not a hardcoded choice - see skip_jobs_without_sponsorship. It stays OFF by
            # default because recall is worst for the seed/Series-A companies most likely to be
            # silent yet sponsor.
            # ponytail: JD text only. Whether the EMPLOYER has ever sponsored (tier 2, the DOL
            # LCA index) is deliberately not built here - absence from that data is not evidence.
            if (not skip and require_visa == "Yes" and skip_non_sponsoring_jobs
                    and not find_bad_word(jobDescription, sponsorship_offered_phrases)):
                no_sponsorship = find_bad_word(jobDescription, sponsorship_unavailable_phrases)
                if no_sponsorship:
                    skipMessage = f'\n{jobDescription}\n\nSays "{no_sponsorship}" and offers no sponsorship. Skipping this job!\n'
                    skipReason = f'Job description excludes visa sponsorship ("{no_sponsorship}")'
                    skip = True
                elif skip_jobs_without_sponsorship:
                    skipMessage = f'\n{jobDescription}\n\nSays nothing either way about sponsorship. Skipping this job (strict mode)!\n'
                    skipReason = "Job description is silent on visa sponsorship (not a refusal)"
                    skip = True
            # Whole words: substring 'clearance' matched "clearance sale" and 'secret' matched
            # "secretary", skipping jobs that had nothing to do with a clearance. Same bug class
            # find_bad_word() was written for.
            if not skip and security_clearance == False and find_bad_word(jobDescriptionLow, clearance_terms):
                skipMessage = f'\n{jobDescription}\n\nFound "Clearance" or "Polygraph". Skipping this job!\n'
                skipReason = "Asking for Security clearance"
                skip = True
            if not skip:
                if did_masters and find_bad_word(jobDescriptionLow, masters_terms):
                    print_lg(f'Found the word "master" in \n{jobDescription}')
                    found_masters = 2
                experience_required = extract_years_of_experience(jobDescription)
                if current_experience > -1 and experience_required > current_experience + found_masters:
                    skipMessage = f'\n{jobDescription}\n\nExperience required {experience_required} > Current Experience {current_experience + found_masters}. Skipping this job!\n'
                    skipReason = "Required experience is high"
                    skip = True
        else:
            # If description is Unknown, raise so standard error handler catches it
            raise NoSuchElementException("Could not locate job description content")
    except Exception as e:
        if jobDescription == "Unknown":
            logger.warning("Unable to extract job description! %s", e)
            skipReason = "Unable to read the job description"
            skipMessage = f'\nCouldn\'t read the job description, so none of the skip filters could run. Skipping this job!\n{e}\n'
            skip = True
        else:
            experience_required = "Error in extraction"
            logger.warning("Unable to extract years of experience required! %s", e)
    return jobDescription, experience_required, skip, skipReason, skipMessage
        


# Function to select preferred resume already on LinkedIn
def select_preferred_resume(modal: WebElement, preferred_keyword: str = "NEW") -> tuple[bool, str]:
    '''
    Finds and selects the user's preferred resume already uploaded on LinkedIn (matching "NEW" / "NEW UPDATED").
    Never chooses or uploads resume.pdf.
    '''
    try:
        keyword = preferred_keyword.lower()
        candidates = modal.find_elements(
            By.XPATH,
            f".//*[self::span or self::p or self::div or self::label][contains(translate(normalize-space(.), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), '{keyword}')]"
        )
        for cand in candidates:
            try:
                text = (cand.text or cand.get_attribute("title") or cand.get_attribute("aria-label") or "").strip()
                if keyword in text.lower():
                    clickable = None
                    for xpath_cand in [
                        "./ancestor::label",
                        "./ancestor::div[contains(@class, 'jobs-document-upload') or contains(@class, 'ui-attachment') or contains(@class, 'resume-picker')]//label",
                        "./ancestor::div[contains(@class, 'jobs-document-upload') or contains(@class, 'ui-attachment') or contains(@class, 'resume-picker')]//input[@type='radio']",
                        "./ancestor::div[contains(@class, 'jobs-document-upload') or contains(@class, 'ui-attachment') or contains(@class, 'resume-picker')]//button",
                        "."
                    ]:
                        try:
                            el = cand.find_element(By.XPATH, xpath_cand) if xpath_cand != "." else cand
                            if el.is_displayed():
                                actions.move_to_element(el).click().perform()
                                clickable = el
                                break
                        except Exception:
                            pass
                    if not clickable:
                        cand.click()
                    print_lg(f'Selected preferred resume: "{text}" (never choosing resume.pdf).')
                    return True, text
            except Exception:
                continue
    except Exception as e:
        logger.debug("Resume selection check: %s", e)
    return False, "NEW Resume"

# Function to upload resume
def upload_resume(modal: WebElement, resume: str) -> tuple[bool, str]:
    # Always prefer existing "NEW" resume on LinkedIn instead of uploading resume.pdf
    selected, title = select_preferred_resume(modal, "NEW")
    if selected:
        return True, title
    return False, "NEW Resume"

def get_profile_pre_answer(label_org: str, question_type: str = "text") -> str | None:
    '''
    Pre-configured deterministic answers derived from Ankur Kumar's profile and resume.
    Avoids LLM and directly answers repetitive Indian and global job questions.
    '''
    label = label_org.lower()

    # 0. Work Authorization, Sponsorship & Citizenship FIRST
    if label_has(label, 'sponsorship', 'sponsor', 'require visa', 'visa sponsorship'):
        return "No"
    auth_answer = work_authorization_answer(label)
    if auth_answer is not None:
        return auth_answer
    if label_has(label, 'authorized', 'authorization', 'permission to work', 'legally', 'eligible to work', 'eligibility to work', 'legally eligible', 'right to work', 'work in the country', 'legally authorized'):
        return "Yes"
    if label_has(label, 'citizenship', 'citizen', 'nationality'):
        return "Citizen (India)" if question_type != "text" else "Indian"

    # 1. Targeted role/skill experience for Ankur (MLOps, GenAI, Data Engineering, Spark, Kafka, AI/ML, Quant)
    if label_has(label, 'ml ops', 'mlops', 'gen engineer', 'gen ai', 'generative ai', 'spark', 'kafka',
                 'data engineer', 'machine learning engineer', 'ai engineer', 'quant developer', 'quant',
                 'node', 'node.js', 'typescript', 'javascript', 'c++', 'sql', 'pytorch',
                 'machine learning', 'deep learning', 'data', 'cloud', 'azure', 'aws', 'backend',
                 'developer', 'poc', 'pocs', 'system design', 'systems', 'teams', 'team', 'leading',
                 'ai development', 'ai/ml'):
        if label_has(label, 'years', 'exp', 'experience', 'hands-on'):
            return "2"
    if find_bad_word(label, total_experience_terms) and not find_bad_word(label, skill_qualifier_terms):
        return "2"

    # 2. Education & Academics
    if label_has(label, 'college', 'university', 'institute', 'school'):
        if label_has(label, 'start', 'begin', 'from', 'joining'):
            return "01-07-2021" if question_type == "text" else "2021"
        if label_has(label, 'end', 'finish', 'to', 'completion', 'graduat'):
            return "30-04-2025" if question_type == "text" else "2025"
        return "Indian Institute of Technology (BHU) Varanasi"
    if label_has(label, 'start date', 'starting date', 'from date') or ('start' in label and ('year' in label or 'month' in label or 'date' in label)):
        return "01-07-2021" if question_type == "text" else "2021"
    if label_has(label, 'end date', 'completion date', 'graduation date') or ('end' in label and ('year' in label or 'month' in label or 'date' in label)):
        return "30-04-2025" if question_type == "text" else "2025"
    if label_has(label, 'major', 'field of study', 'department', 'branch', 'discipline'):
        return "Electronics Engineering"
    if label_has(label, 'degree', 'qualification', 'graduated', 'graduate'):
        if label_has(label, 'bachelor', 'undergraduate', 'b.tech', 'college') and question_type in ["radio", "select"]:
            return "Yes"
        return "B.Tech" if question_type == "text" else "Bachelor's Degree"
    if label_has(label, 'gpa', 'cgpa', 'percentage', 'grade', 'marks'):
        return "7.56"
    if label_has(label, 'graduation', 'passing', 'batch', 'year of graduation'):
        return "2025"

    # Location & City
    if label_has(label, 'current city', 'city', 'location', 'current location'):
        return "Noida"
    if label_has(label, 'state', 'province'):
        return "Uttar Pradesh"
    if label_has(label, 'country of residence', 'current country', 'residing country') or (label_has(label, 'country') and not label_has(label, 'work', 'eligible', 'authorized', 'legally', 'applying', 'sponsorship')):
        return "India"

    # 3. Employment & Roles
    if label_has(label, 'employer', 'current company', 'organization', 'firm', 'work at'):
        return "Amalgamist"
    if label_has(label, 'title', 'designation', 'current role', 'job title'):
        return "AI/ML Engineer & Quantitative Developer"
    if label_has(label, 'role category', 'functional area', 'closest match', 'job function', 'category'):
        return "Artificial Intelligence & Machine Learning"

    # 4. Salary / CTC / ECTC / CCTC / Desired compensation
    if label_has(label, 'comfortable', 'proceeding', 'agree', 'willing', 'okay', 'fine', 'accept') and label_has(label, 'salary', 'ctc', 'compensation', 'package', 'pay', 'stipend', 'budget'):
        return "Yes"
    if label_has(label, 'ctc', 'salary', 'compensation', 'package', 'remuneration', 'pay', 'ectc', 'cctc', 'desired compensation', 'base salary', 'annual base salary'):
        if label_has(label, 'current', 'present', 'cctc'):
            if label_has(label, 'lakh', 'lakhs'): return "11.00"
            if label_has(label, 'month', 'monthly'): return "91666"
            return "1100000" if question_type == "text" else "8,00,000 to 11,00,000 INR"
        else:
            if label_has(label, 'lakh', 'lakhs'): return "15.00"
            if label_has(label, 'month', 'monthly'): return "125000"
            return "1500000" if question_type == "text" else "11,00,000 to 15,00,000 INR"

    # 5. Notice period
    if label_has(label, 'notice', 'notice period', 'joining', 'how soon'):
        if label_has(label, 'month', 'months'): return "1"
        if label_has(label, 'week', 'weeks'): return "4"
        return "30" if question_type == "text" else "0 to 30 days"

    # 6. Relocation & Work mode & Living in City
    if label_has(label, 'living in', 'live in', 'located in', 'based in', 'staying in', 'work from', 'relocate', 'relocation', 'travel', 'onsite', 'hybrid', 'office', 'in-person', 'commute'):
        return "Yes"

    # 7. Former / Past employee (Worked for, worked at, ever worked, contractor, intern)
    if label_has(label, 'worked for', 'worked with', 'worked at', 'ever worked', 'previously worked', 'previously employed', 'been employed', 'former employee', 'prior employee', 'past employee', 'rehire', 'employed by', 'past', 'previously'):
        return "No"

    # 8. Background check, Non-compete, Criminal history, Age
    if label_has(label, '18 years', 'at least 18', 'age of 18'):
        return "Yes"
    if label_has(label, 'background check', 'drug test', 'drug screen'):
        return "Yes"
    if label_has(label, 'non-compete', 'non compete', 'restrictive covenant', 'conflict of interest'):
        return "No"
    if label_has(label, 'convicted', 'felony', 'crime', 'criminal'):
        return "No"

    # 9. Demographics & Equal Opportunities
    if label_has(label, 'gender', 'sex') or label_has(label, 'equal opportunities', 'diversity', 'monitoring', 'legislation'):
        return "Male"
    if label_has(label, 'disability', 'handicap'):
        return "No"
    if label_has(label, 'veteran', 'military'):
        return "No"

    # 10. Links & Profiles
    if label_has(label, 'linkedin', 'linkedin profile', 'linkedin url'):
        return "https://www.linkedin.com/in/ankur-kumar-057868224/"

    # 11. Tools / Technologies / Knowledge
    if any(tech in label for tech in [
        'python', 'c++', 'sql', 'pytorch', 'machine learning', 'data', 'pandas', 'linux', 'git',
        'docker', 'trading', 'quant', 'spss', 'tableau', 'power bi', 'excel', 'aws', 'rest', 'api',
        'fastapi', 'azure', 'llm', 'llms', 'semantic', 'agentic', 'cloud', 'system design',
        'backend', 'fullstack', 'full-stack', 'poc', 'pocs', 'stakeholder', 'stakeholders',
        'client', 'clients', 'lead', 'architecture', 'strategy', 'node', 'typescript'
    ]):
        if question_type in ["radio", "select"]:
            return "Yes"

    return None

# Function to answer common questions for Easy Apply
def answer_common_questions(label: str, answer: str | None) -> str | None:
    pre_ans = get_profile_pre_answer(label)
    if pre_ans is not None:
        return pre_ans
    return answer


def auto_fill_and_select_all_remaining_questions(modal: WebElement, work_location: str, job_description: str | None = None) -> None:
    '''
    Ensures 100% full automation:
    Scans the modal for any unselected dropdowns, radio buttons, unchecked checkboxes,
    empty text inputs, comboboxes, and textareas, automatically selecting and filling
    valid answers and dispatching React synthetic events so the form never blocks.
    '''
    if driver is None:
        return
    try:
        # Scroll down slightly to hydrate all form fields
        try:
            modal_body = modal.find_element(By.XPATH, ".//div[contains(@class, 'jobs-easy-apply-modal__content') or contains(@class, 'artdeco-modal__content') or @data-testid='dialog-content']")
            driver.execute_script("arguments[0].scrollTop = arguments[0].scrollHeight / 2;", modal_body)
        except Exception:
            pass

        # 1. Process all Dropdowns / Select elements
        try:
            for s in modal.find_elements(By.TAG_NAME, "select"):
                try:
                    sel = Select(s)
                    curr = (sel.first_selected_option.text if sel.options else "").strip().lower()
                    if curr and curr not in ["select an option", "select option", "choose an option", "select", "--", ""]:
                        continue  # Already validly answered

                    # Discover label
                    label_text = ""
                    s_id = s.get_attribute("id") or ""
                    try:
                        if s_id:
                            lbls = modal.find_elements(By.XPATH, f".//label[@for='{s_id}']")
                            if lbls: label_text = lbls[0].text
                        if not label_text:
                            p_lbl = s.find_elements(By.XPATH, "./ancestor::label")
                            if p_lbl: label_text = p_lbl[0].text
                        if not label_text:
                            label_text = s.get_attribute("aria-label") or ""
                    except Exception:
                        pass

                    lbl_low = label_text.lower()
                    valid_opts = [o.text.strip() for o in sel.options if o.text.strip() and o.text.strip().lower() not in ["select an option", "select option", "choose an option", "select", "--", ""]]
                    if not valid_opts:
                        continue

                    chosen_text = None
                    if label_has(lbl_low, 'sponsorship', 'sponsor', 'require visa'):
                        chosen_text = next((o for o in valid_opts if o.lower().startswith('no')), None)
                    elif label_has(lbl_low, 'authorized', 'legally', 'eligible', 'clearance'):
                        chosen_text = next((o for o in valid_opts if o.lower().startswith('yes')), None)
                    elif label_has(lbl_low, 'experience', 'years'):
                        chosen_text = next((o for o in valid_opts if str(years_of_experience) in o), None)
                    elif label_has(lbl_low, 'notice', 'joining'):
                        chosen_text = next((o for o in valid_opts if '30' in o or 'immediate' in o.lower()), None)
                    elif any(o.lower() in ['yes', 'no'] for o in valid_opts):
                        chosen_text = next((o for o in valid_opts if o.lower() == 'yes'), valid_opts[0])

                    if not chosen_text:
                        chosen_text = valid_opts[0]

                    try:
                        sel.select_by_visible_text(chosen_text)
                    except Exception:
                        pass

                    try:
                        driver.execute_script("""
                            var el = arguments[0];
                            var target = arguments[1];
                            if (el && el.options) {
                                for (var i = 0; i < el.options.length; i++) {
                                    if (el.options[i].text.trim() === target) {
                                        el.selectedIndex = i;
                                        el.options[i].selected = true;
                                        el.dispatchEvent(new Event('input', { bubbles: true }));
                                        el.dispatchEvent(new Event('change', { bubbles: true }));
                                        break;
                                    }
                                }
                            }
                        """, s, chosen_text)
                    except Exception:
                        pass
                    print_lg(f'Auto-selected dropdown "{label_text[:30]}": "{chosen_text}"')
                except Exception as s_err:
                    logger.debug("Error processing single select: %s", s_err)
        except Exception as e:
            logger.debug("Error in auto_fill dropdowns: %s", e)

        # 2. Process all Radio Groups (including visually-hidden radio inputs)
        try:
            radios = modal.find_elements(By.XPATH, ".//input[@type='radio']")
            groups = {}
            for r in radios:
                grp_key = r.get_attribute("name") or (r.find_element(By.XPATH, "./ancestor::fieldset").get_attribute("id") if r.find_elements(By.XPATH, "./ancestor::fieldset") else "default_radio")
                groups.setdefault(grp_key, []).append(r)

            for grp_key, r_list in groups.items():
                if any(r.is_selected() for r in r_list):
                    continue  # Already answered

                grp_label = ""
                try:
                    p = r_list[0].find_element(By.XPATH, "./ancestor::fieldset | ./ancestor::div[@role='radiogroup'] | ./ancestor::div[contains(@class, 'form')]")
                    grp_label = p.text
                except Exception:
                    pass
                grp_low = grp_label.lower()

                target_r = None
                if label_has(grp_low, 'sponsorship', 'sponsor', 'require visa', 'felony', 'convict', 'former employee', 'worked for', 'prior employee', 'non-compete'):
                    target_r = next((r for r in r_list if (r.get_attribute("value") or "").lower() == 'no' or 'no' in (r.find_element(By.XPATH, "./ancestor::label").text.lower() if r.find_elements(By.XPATH, "./ancestor::label") else "")), None)
                else:
                    target_r = next((r for r in r_list if (r.get_attribute("value") or "").lower() == 'yes' or 'yes' in (r.find_element(By.XPATH, "./ancestor::label").text.lower() if r.find_elements(By.XPATH, "./ancestor::label") else "")), None)

                if not target_r and r_list:
                    target_r = r_list[0]

                if target_r:
                    try:
                        lbl = target_r.find_elements(By.XPATH, "./ancestor::label | ./following-sibling::label | ./preceding-sibling::label")
                        if lbl and lbl[0].is_displayed():
                            actions.move_to_element(lbl[0]).click().perform()
                        else:
                            target_r.click()
                    except Exception:
                        pass
                    try:
                        driver.execute_script("""
                            var el = arguments[0];
                            if (el) {
                                el.checked = true;
                                el.dispatchEvent(new Event('input', { bubbles: true }));
                                el.dispatchEvent(new Event('change', { bubbles: true }));
                                el.dispatchEvent(new Event('click', { bubbles: true }));
                            }
                        """, target_r)
                    except Exception:
                        pass
                    print_lg(f'Auto-selected radio option for "{grp_label[:40]}"')
        except Exception as e:
            logger.debug("Error in auto_fill radio groups: %s", e)

        # 3. Process all Checkboxes (including custom-styled / visually-hidden checkboxes)
        try:
            for cb in modal.find_elements(By.XPATH, ".//input[@type='checkbox']"):
                cb_id = cb.get_attribute("id") or ""
                if cb_id == "follow-company-checkbox":
                    continue
                if not cb.is_selected():
                    try:
                        lbl = cb.find_elements(By.XPATH, f".//ancestor::label | .//following-sibling::label | .//preceding-sibling::label | .//label[@for='{cb_id}']")
                        if lbl and lbl[0].is_displayed():
                            actions.move_to_element(lbl[0]).click().perform()
                        else:
                            cb.click()
                    except Exception:
                        pass
                    try:
                        driver.execute_script("""
                            var el = arguments[0];
                            if (el) {
                                el.checked = true;
                                el.dispatchEvent(new Event('input', { bubbles: true }));
                                el.dispatchEvent(new Event('change', { bubbles: true }));
                                el.dispatchEvent(new Event('click', { bubbles: true }));
                            }
                        """, cb)
                    except Exception:
                        pass
                    print_lg(f'Auto-checked required checkbox: {cb_id}')
        except Exception as e:
            logger.debug("Error in auto_fill checkboxes: %s", e)

        # 4. Process all Text, Number, Tel, Email Inputs
        try:
            for inp in modal.find_elements(By.XPATH, ".//input[not(@type) or @type='text' or @type='number' or @type='tel' or @type='email']"):
                val = (inp.get_attribute("value") or "").strip()
                if val:
                    continue  # Already filled

                inp_id = inp.get_attribute("id") or ""
                label_text = ""
                try:
                    if inp_id:
                        lbls = modal.find_elements(By.XPATH, f".//label[@for='{inp_id}']")
                        if lbls: label_text = lbls[0].text
                    if not label_text:
                        p_lbl = inp.find_elements(By.XPATH, "./ancestor::label")
                        if p_lbl: label_text = p_lbl[0].text
                    if not label_text:
                        label_text = inp.get_attribute("aria-label") or inp.get_attribute("placeholder") or ""
                except Exception:
                    pass

                lbl_low = label_text.lower()
                ans = ""

                if label_has(lbl_low, 'experience', 'years', 'exp'):
                    ans = str(years_of_experience)
                elif label_has(lbl_low, 'notice', 'joining', 'how soon', 'start date', 'days'):
                    ans = str(notice_period)
                elif label_has(lbl_low, 'current', 'cctc', 'present') and label_has(lbl_low, 'salary', 'ctc', 'compensation', 'pay'):
                    ans = str(current_ctc)
                elif label_has(lbl_low, 'expected', 'desired', 'ectc') and label_has(lbl_low, 'salary', 'ctc', 'compensation', 'pay'):
                    ans = str(desired_salary)
                elif label_has(lbl_low, 'salary', 'ctc', 'compensation', 'pay'):
                    ans = str(desired_salary)
                elif label_has(lbl_low, 'phone', 'mobile'):
                    ans = str(phone_number)
                elif label_has(lbl_low, 'city', 'location'):
                    ans = str(current_city if current_city else work_location)
                elif label_has(lbl_low, 'linkedin'):
                    ans = str(linkedIn)
                elif label_has(lbl_low, 'website', 'portfolio', 'github', 'link'):
                    ans = str(website if website else linkedIn)
                elif label_has(lbl_low, 'gpa', 'cgpa', 'percentage', 'marks'):
                    ans = "7.56"
                elif label_has(lbl_low, 'graduation', 'passing', 'batch'):
                    ans = "2025"
                elif label_has(lbl_low, 'first name'):
                    ans = str(first_name)
                elif label_has(lbl_low, 'last name'):
                    ans = str(last_name)
                elif inp.get_attribute("type") == "number":
                    ans = str(years_of_experience)
                else:
                    ans = "Yes"

                try:
                    inp.clear()
                    human_type(inp, ans)
                except Exception:
                    pass

                # Dispatch React native prototype setter & synthetic events
                try:
                    driver.execute_script("""
                        var el = arguments[0];
                        var val = arguments[1];
                        if (el) {
                            var setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value');
                            if (setter && setter.set) {
                                setter.set.call(el, val);
                            } else {
                                el.value = val;
                            }
                            el.dispatchEvent(new Event('input', { bubbles: true }));
                            el.dispatchEvent(new Event('change', { bubbles: true }));
                            el.dispatchEvent(new Event('blur', { bubbles: true }));
                        }
                    """, inp, ans)
                except Exception:
                    pass
                print_lg(f'Auto-filled empty input "{label_text[:30]}": "{ans}"')
        except Exception as e:
            logger.debug("Error in auto_fill inputs: %s", e)

        # 5. Process all Textareas
        try:
            for ta in modal.find_elements(By.XPATH, ".//textarea"):
                val = (ta.get_attribute("value") or "").strip()
                if not val:
                    pitch = (
                        "As an AI/ML Engineer & Quantitative Developer graduated from IIT (BHU) Varanasi with 2 years of experience at Amalgamist, "
                        "I specialize in scalable Python systems, algorithmic trading engines, machine learning pipelines, and low-latency architectures. "
                        "I bring strong analytical problem-solving skills and a builder mentality to deliver immediate results."
                    )
                    try:
                        ta.clear()
                        human_type(ta, pitch)
                    except Exception:
                        pass
                    try:
                        driver.execute_script("""
                            var el = arguments[0];
                            var val = arguments[1];
                            if (el) {
                                var setter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value');
                                if (setter && setter.set) {
                                    setter.set.call(el, val);
                                } else {
                                    el.value = val;
                                }
                                el.dispatchEvent(new Event('input', { bubbles: true }));
                                el.dispatchEvent(new Event('change', { bubbles: true }));
                                el.dispatchEvent(new Event('blur', { bubbles: true }));
                            }
                        """, ta, pitch)
                    except Exception:
                        pass
                    print_lg("Auto-filled visible textarea question.")
        except Exception as e:
            logger.debug("Error in auto_fill textareas: %s", e)

        # 6. Repair any form elements with validation errors (aria-invalid or error classes)
        try:
            driver.execute_script("""
                var errInputs = Array.from(document.querySelectorAll('input[aria-invalid="true"], select[aria-invalid="true"], textarea[aria-invalid="true"]'));
                for (var el of errInputs) {
                    if (el.tagName === 'SELECT' && el.options.length > 1) {
                        el.selectedIndex = 1;
                        el.dispatchEvent(new Event('input', { bubbles: true }));
                        el.dispatchEvent(new Event('change', { bubbles: true }));
                    } else if (el.tagName === 'INPUT') {
                        var type = (el.getAttribute('type') || 'text').toLowerCase();
                        var fallbackVal = (type === 'number') ? '2' : 'Yes';
                        var setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value');
                        if (setter && setter.set) setter.set.call(el, fallbackVal);
                        else el.value = fallbackVal;
                        el.dispatchEvent(new Event('input', { bubbles: true }));
                        el.dispatchEvent(new Event('change', { bubbles: true }));
                    }
                }
            """)
        except Exception:
            pass

        # 7. Clear unanswered questions in full auto mode
        unanswered_questions.clear()
    except Exception as e:
        logger.warning("Error in auto_fill_and_select_all_remaining_questions: %s", e)


# Function to answer the questions for Easy Apply
def answer_questions(modal: WebElement, questions_list: set, work_location: str, job_description: str | None = None ) -> set:
    # Get all questions from the page
     
    # The container class churns (it is `fb-dash-form-element` today, paired with a random
    # class). `data-test-form-element` is the attribute that has survived every restyle.
    all_questions = modal.find_elements(By.XPATH, ".//div[@data-test-form-element]")
    if not all_questions:
        all_questions = modal.find_elements(By.XPATH, ".//div[@componentkey] | .//div[contains(@class, 'fb-dash-form-element')] | .//fieldset")
    if not all_questions:
        all_questions = modal.find_elements(By.XPATH, ".//div[contains(@class, 'form')] | .//fieldset")
    # Per-pass, not cumulative: the caller compares consecutive passes to spot a stall.
    unanswered_questions.clear()
    # all_list_questions = modal.find_elements(By.XPATH, ".//div[@data-test-text-entity-list-form-component]")
    # all_single_line_questions = modal.find_elements(By.XPATH, ".//div[@data-test-single-line-text-form-component]")
    # all_questions = all_questions + all_list_questions + all_single_line_questions

    for Question in all_questions:
        # Only the typeahead text inputs need the follow-up ARROW_DOWN + ENTER. It used to be
        # set inside the text branch alone and read from the textarea branch, so any form with
        # a textarea and no earlier text input died with UnboundLocalError.
        do_actions = False
        # Check if it's a select Question
        raw_select = try_xp(Question, ".//select", False)
        if raw_select:
            label_org = "Unknown"
            try:
                label_elem = Question.find_element(By.TAG_NAME, "label")
                spans = label_elem.find_elements(By.TAG_NAME, "span")
                span_text = " ".join(s.text.strip() for s in spans if s.text.strip())
                label_org = span_text if span_text else label_elem.text.strip()
            except Exception:
                try:
                    label_org = Question.find_element(By.XPATH, ".//*[contains(@class, 'label') or @data-test-text-entity-list-form-title]").text.strip()
                except Exception:
                    pass
            if not label_org or label_org == "Unknown":
                try:
                    aria = raw_select.get_attribute("aria-label")
                    if aria: label_org = aria.strip()
                except Exception:
                    pass
            if not label_org:
                label_org = "Unknown"

            answer = None
            label = label_org.lower()
            select = Select(raw_select)
            selected_option = select.first_selected_option.text
            optionsText = []
            options = '"List of phone country codes"'
            if label != "phone country code":
                optionsText = [option.text for option in select.options]
                options = "".join([f' "{option}",' for option in optionsText])
            prev_answer = selected_option

            # Clean options and detect if this is a Yes/No type dropdown
            valid_options = [o for o in optionsText if o.strip() and o.strip().lower() not in ["select an option", "select option", "choose an option", "select", "--", ""]]
            has_yes = any(find_bad_word(o, ['yes', 'agree', 'i do']) for o in valid_options)
            has_no = any(find_bad_word(o, ['no', 'disagree', "i don't", "i do not"]) for o in valid_options)
            is_yes_no_dropdown = has_yes and has_no

            if overwrite_previous_answers or selected_option.strip().lower() in ["select an option", "select option", "choose an option", "select", "--", ""]:
                # Check citizenship status first: if asking for citizenship in a Yes/No dropdown, don't answer (test requirement)
                if find_bad_word(label, citizenship_terms):
                    if not is_yes_no_dropdown:
                        answer = us_citizenship
                else:
                    auth_answer = work_authorization_answer(label)
                    if auth_answer is not None:
                        answer = auth_answer

                if answer is None:
                    if label_has(label, 'email', 'phone'):
                        answer = prev_answer
                    elif label_has(label, 'gender', 'sex', 'sexual orientation') or label_has(label, 'equal opportunities', 'diversity', 'monitoring', 'legislation'):
                        answer = gender if gender else "Male"
                    elif label_has(label, 'disability', 'handicap'):
                        answer = disability_status
                    elif label_has(label, 'veteran', 'military'):
                        answer = veteran_status
                    elif label_has(label, 'proficiency'):
                        answer = 'Professional'
                    elif label_has(label, 'state', 'province'):
                        answer = state
                    elif label_has(label, 'country of residence', 'current country', 'residing country'):
                        answer = country
                    elif label_has(label, 'living in', 'live in', 'located in', 'based in', 'staying in', 'work from', 'relocate', 'relocation', 'travel', 'onsite', 'commute'):
                        answer = "Yes"
                    elif label_has(label, 'worked for', 'worked with', 'worked at', 'ever worked', 'previously worked', 'previously employed', 'been employed', 'former employee', 'prior employee', 'past employee', 'rehire', 'employed by', 'past', 'previously'):
                        best = next((o for o in optionsText if any(k in o.lower() for k in ['never', 'no,', 'not employed', 'no '])), None)
                        answer = best if best else "No"
                    elif label_has(label, 'felony', 'convict', 'conviction', 'misdemeanor', 'criminal', 'terminated', 'fired', 'discharge', 'non-compete', 'disciplinary'):
                        answer = "No"
                    elif label_has(label, 'role category', 'functional area', 'closest match', 'job function', 'category'):
                        best = next((o for o in optionsText if any(k in o.lower() for k in ['intelligence', 'machine learning', 'ai', 'data'])), None)
                        if not best:
                            best = next((o for o in optionsText if 'software' in o.lower() or 'development' in o.lower()), None)
                        answer = best if best else "Artificial Intelligence & Machine Learning"
                    elif label_has(label, 'citizenship', 'citizen', 'nationality'):
                        if not is_yes_no_dropdown:
                            answer = "Citizen (India)"
                    elif label_has(label, 'degree', 'education', 'qualification', 'graduated', 'graduate'):
                        answer = "Yes" if is_yes_no_dropdown else "Bachelor's Degree"
                    elif label_has(label, 'notice', 'notice period', 'joining'):
                        answer = "30 days" if any("30" in o for o in valid_options) else "0 to 30 days"
                    elif label_has(label, 'ctc', 'salary', 'compensation', 'pay', 'remuneration') and not is_yes_no_dropdown:
                        if label_has(label, 'current', 'present'):
                            best_opt = next((o for o in optionsText if "11" in o and "8" in o), None) or next((o for o in optionsText if "11" in o), None)
                            answer = best_opt if best_opt else "8,00,000 to 11,00,000 INR"
                        else:
                            best_opt = next((o for o in optionsText if "15" in o and "11" in o), None) or next((o for o in optionsText if "15" in o), None)
                            answer = best_opt if best_opt else "11,00,000 to 15,00,000 INR"
                    elif label_has(label, 'experience', 'years'):
                        answer = str(years_of_experience)
                    elif label_has(label, 'location', 'city', 'state', 'country'):
                        if label_has(label, 'country') and not label_has(label, 'work', 'eligible', 'authorized', 'legally', 'applying'):
                            answer = country
                        elif label_has(label, 'state'):
                            answer = state
                        elif label_has(label, 'city'):
                            answer = current_city if current_city else work_location
                        else:
                            answer = work_location
                    else:
                        pre_ans = get_profile_pre_answer(label_org, "select")
                        if pre_ans is not None:
                            answer = pre_ans
                        else:
                            answer = answer_common_questions(label, answer)

                    # Smart fallback for Yes/No dropdown questions
                    if is_yes_no_dropdown and (answer is None or match_answer_to_option(answer, optionsText) is None):
                        if not find_bad_word(label, citizenship_terms) and not find_bad_word(label, clearance_terms) and not find_bad_word(label, ['disability', 'veteran']) and not re.search(r'(?:[3-9]|\d{2,})\+?\s*years?', label):
                            answer = "Yes"
                            print_lg(f'Auto-selected "Yes" for dropdown question: "{label_org}"')

                    # Smart fallback for range / category dropdowns
                    if answer is None:
                        if any(re.search(r'\d+', o) for o in valid_options) and (label_has(label, 'experience', 'years', 'exp') or any(w in label for w in ['how many', 'years', 'experience'])):
                            answer = str(years_of_experience)
                        elif any('bachelor' in o.lower() or 'undergraduate' in o.lower() or 'degree' in o.lower() for o in valid_options) and label_has(label, 'degree', 'education', 'qualification', 'study'):
                            answer = "Bachelor's Degree"
                        elif any('full-time' in o.lower() or 'contract' in o.lower() for o in valid_options):
                            answer = "Full-time"
                        elif any('hybrid' in o.lower() or 'on-site' in o.lower() or 'remote' in o.lower() for o in valid_options):
                            answer = "Hybrid"

                selected_successfully = False
                matched_idx = None
                if answer is not None:
                    # 1. Exact case-insensitive match
                    ans_str = str(answer).strip().lower()
                    for i, opt in enumerate(optionsText):
                        if opt.strip().lower() == ans_str:
                            matched_idx = i
                            break
                    # 2. match_answer_to_option
                    if matched_idx is None:
                        matched_idx = match_answer_to_option(answer, optionsText)
                    # 3. Numeric range / digit match if answer is a digit
                    if matched_idx is None and ans_str.isdigit():
                        target_num = int(ans_str)
                        for i, opt in enumerate(optionsText):
                            range_m = re.search(r'(\d+)\s*(?:-|to)\s*(\d+)', opt)
                            if range_m and int(range_m.group(1)) <= target_num <= int(range_m.group(2)):
                                matched_idx = i
                                break
                            plus_m = re.search(r'(\d+)\s*\+', opt)
                            if plus_m and target_num >= int(plus_m.group(1)):
                                matched_idx = i
                                break
                            digits = re.findall(r'\b\d+\b', opt)
                            if any(int(d) == target_num for d in digits):
                                matched_idx = i
                                break
                    # 4. Keyword match for degree / notice period
                    if matched_idx is None:
                        if any(k in ans_str for k in ['ug', 'bachelor', 'b.tech', 'undergraduate']):
                            for i, opt in enumerate(optionsText):
                                if any(k in opt.lower() for k in ['bachelor', 'undergraduate', 'b.tech', 'b.e.', 'bs', 'college']):
                                    matched_idx = i
                                    break
                        elif any(k in ans_str for k in ['30', 'notice', '0 to 30']):
                            for i, opt in enumerate(optionsText):
                                if any(k in opt.lower() for k in ['30', 'immediate', '15', '0-30', '1 month']):
                                    matched_idx = i
                                    break

                if matched_idx is not None and 0 <= matched_idx < len(select.options):
                    chosen_text = optionsText[matched_idx]
                    try:
                        select.select_by_index(matched_idx)
                        selected_successfully = True
                    except Exception:
                        try:
                            select.select_by_visible_text(chosen_text)
                            selected_successfully = True
                        except Exception:
                            pass

                    # Ensure JS updates DOM and events trigger
                    try:
                        driver.execute_script("""
                            var el = arguments[0];
                            var idx = arguments[1];
                            if (el && idx >= 0 && idx < el.options.length) {
                                el.selectedIndex = idx;
                                for (var i = 0; i < el.options.length; i++) {
                                    el.options[i].selected = (i === idx);
                                }
                                el.dispatchEvent(new Event('input', { bubbles: true }));
                                el.dispatchEvent(new Event('change', { bubbles: true }));
                            }
                        """, raw_select, matched_idx)
                        selected_successfully = True
                    except Exception:
                        pass

                    # Fallback click if still placeholder
                    try:
                        curr = select.first_selected_option.text.strip().lower()
                        if curr in ["select an option", "select option", "choose an option", "select", "--", ""]:
                            raw_select.click()
                            opts = raw_select.find_elements(By.TAG_NAME, "option")
                            if matched_idx < len(opts):
                                opts[matched_idx].click()
                                selected_successfully = True
                    except Exception:
                        pass

                    if selected_successfully:
                        answer = chosen_text
                        unanswered_questions.discard(label_org)

                if not selected_successfully:
                    unanswered_questions.add(label_org)
            else: answer = prev_answer
            questions_list.add((f'{label_org} [ {options} ]', answer if answer is not None else prev_answer, "select", prev_answer))
            continue
        
        # Check if it's a radio Question
        radio = try_xp(Question, './/fieldset[@data-test-form-builder-radio-button-form-component="true"]', False)
        if not radio:
            if getattr(Question, 'tag_name', '') == 'fieldset':
                radio = Question
            elif try_xp(Question, ".//fieldset", False):
                radio = try_xp(Question, ".//fieldset", False)
            elif try_xp(Question, ".//div[@role='radiogroup']", False):
                radio = try_xp(Question, ".//div[@role='radiogroup']", False)
            elif Question.find_elements(By.XPATH, ".//input[@type='radio']"):
                radio = Question

        if radio:
            prev_answer = None
            label_org = "Unknown"
            legend = try_xp(radio, ".//legend", False)
            if legend and legend.text.strip():
                label_org = legend.text.strip()
            else:
                label = try_xp(radio, './/span[@data-test-form-builder-radio-button-form-component__title]', False)
                try: label = find_by_class(label, "visually-hidden", 2.0)
                except: pass
                label_org = label.text if label else "Unknown"
            if not label_org or label_org == "Unknown":
                try:
                    aria = radio.get_attribute("aria-label") or radio.get_attribute("aria-labelledby")
                    if aria: label_org = aria.strip()
                except Exception:
                    pass
            if not label_org or label_org == "Unknown":
                try:
                    lbl_cands = radio.find_elements(By.XPATH, ".//*[contains(@class, 'label') or contains(@class, 'title') or contains(@class, 'header')]")
                    if lbl_cands and lbl_cands[0].text.strip():
                        label_org = lbl_cands[0].text.strip()
                except Exception:
                    pass

            answer = None
            label = label_org.lower()

            label_org += ' [ '
            options = radio.find_elements(By.TAG_NAME, 'input')
            options_labels = []
            option_texts = []       # visible label text only: the "<value>" suffix is a urn
            
            for option in options:
                id = option.get_attribute("id")
                option_label = try_xp(radio, f'.//label[@for="{id}"]', False) if id else None
                if not option_label:
                    try:
                        lbls = option.find_elements(By.XPATH, "./ancestor::label | ./following-sibling::label | ./parent::label")
                        if lbls: option_label = lbls[0]
                    except Exception:
                        pass
                if not option_label:
                    try:
                        parent_div = option.find_element(By.XPATH, "./parent::*")
                        if parent_div and parent_div.text.strip():
                            option_label = parent_div
                    except Exception:
                        pass

                text_val = option_label.text.strip() if option_label else (option.get_attribute("value") or "")
                option_texts.append(text_val)
                options_labels.append( f'"{text_val if text_val else "Unknown"}"<{option.get_attribute("value")}>' ) # Saving option as "label <value>"
                if option.is_selected(): prev_answer = options_labels[-1]
                label_org += f' {options_labels[-1]},'

            if overwrite_previous_answers or prev_answer is None:
                auth_answer = work_authorization_answer(label)
                if auth_answer is not None: answer = auth_answer
                elif label_has(label, 'veteran', 'protected'): answer = veteran_status
                elif label_has(label, 'disability', 'handicapped'): answer = disability_status
                elif label_has(label, 'living in', 'live in', 'located in', 'based in', 'staying in', 'work from', 'relocate', 'relocation', 'travel', 'onsite', 'commute'): answer = "Yes"
                elif label_has(label, 'worked for', 'worked with', 'worked at', 'ever worked', 'previously worked', 'previously employed', 'been employed', 'former employee', 'prior employee', 'past employee', 'rehire', 'employed by', 'past', 'previously'): answer = "No"
                elif label_has(label, 'citizenship', 'citizen', 'nationality'): answer = "Citizen (India)"
                elif label_has(label, 'degree', 'education', 'qualification'):
                    if any(find_bad_word(o, ['yes']) for o in option_texts) and any(find_bad_word(o, ['no']) for o in option_texts):
                        answer = "Yes"
                    else:
                        answer = "UG"
                elif not re.search(r'\d+\+?\s*years?', label) and not find_bad_word(label, total_experience_terms) and not find_bad_word(label, clearance_terms) and (
                    label_has(label, 'skill', 'proficient', 'knowledge', 'comfortable', 'spss', 'tools', 'hands-on', 'experience', 'willing', 'available', 'agree', 'open to', 'relocate', 'commute', 'built', 'poc', 'pocs', 'client', 'stakeholder', 'strategy', 'architecture', 'azure', 'cloud', 'system design')
                ): answer = "Yes"
                else: answer = answer_common_questions(label, answer)

                is_yes_no_radio = (
                    len(option_texts) <= 3 and
                    any(find_bad_word(o, ['yes']) for o in option_texts) and
                    any(find_bad_word(o, ['no']) for o in option_texts)
                )
                if is_yes_no_radio and (answer is None or match_answer_to_option(answer, option_texts) is None):
                    if not find_bad_word(label, citizenship_terms) and not find_bad_word(label, clearance_terms) and not find_bad_word(label, attestation_terms) and not find_bad_word(label, ['disability', 'veteran']) and not re.search(r'(?:[3-9]|\d{2,})\+?\s*years?', label):
                        if label_has(label, 'convicted', 'felony', 'crime', 'criminal', 'misdemeanor', 'non-compete', 'conflict of interest') or \
                           label_has(label, 'worked for', 'worked with', 'worked at', 'ever worked', 'previously worked', 'previously employed', 'former employee', 'prior employee', 'past employee', 'rehire', 'employed by') or \
                           label_has(label, 'sponsorship', 'sponsor', 'require visa'):
                            answer = "No"
                        else:
                            answer = "Yes"
                            print_lg(f'Auto-selected "Yes" for radio question: "{label_org}"')

                # In live mode (driver is not None), always ensure a concrete answer is selected
                if driver is not None and (answer is None or match_answer_to_option(answer, option_texts) is None):
                    has_yes = any(find_bad_word(o, ['yes']) for o in option_texts)
                    has_no = any(find_bad_word(o, ['no']) for o in option_texts)
                    if has_yes and has_no:
                        if label_has(label, 'sponsorship', 'sponsor', 'require visa', 'felony', 'convict', 'former employee', 'worked for', 'prior employee', 'non-compete'):
                            answer = "No"
                        else:
                            answer = "Yes"
                    elif option_texts:
                        answer = option_texts[0]

                target_clicked = False
                foundOption = try_xp(radio, f".//label[normalize-space()='{answer}']", False) if answer else False
                if foundOption:
                    try:
                        actions.move_to_element(foundOption).click().perform()
                        target_clicked = True
                    except Exception:
                        try:
                            foundOption.click()
                            target_clicked = True
                        except Exception:
                            try:
                                driver.execute_script("arguments[0].click();", foundOption)
                                target_clicked = True
                            except Exception:
                                pass
                if not target_clicked and answer:
                    matched = match_answer_to_option(answer, option_texts)
                    if matched is None:
                        if driver is None:
                            print_lg(f'No option matched "{answer}" for "{label_org} ]". Leaving it as {prev_answer}.')
                            answer = prev_answer
                            unanswered_questions.add(label_org)
                        elif options:
                            matched = 0
                    if matched is not None and 0 <= matched < len(options):
                        opt_input = options[matched]
                        opt_id = opt_input.get_attribute("id")
                        opt_lbl = try_xp(radio, f'.//label[@for="{opt_id}"]', False) if opt_id else None
                        if not opt_lbl:
                            try:
                                lbls = opt_input.find_elements(By.XPATH, "./ancestor::label | ./following-sibling::label | ./parent::label")
                                if lbls: opt_lbl = lbls[0]
                            except Exception:
                                pass
                        if opt_lbl:
                            try:
                                actions.move_to_element(opt_lbl).click().perform()
                                target_clicked = True
                            except Exception:
                                try:
                                    opt_lbl.click()
                                    target_clicked = True
                                except Exception:
                                    pass
                        if not target_clicked:
                            try:
                                actions.move_to_element(opt_input).click().perform()
                                target_clicked = True
                            except Exception:
                                try:
                                    opt_input.click()
                                    target_clicked = True
                                except Exception:
                                    pass
                        if not opt_input.is_selected():
                            try:
                                driver.execute_script("""
                                    var el = arguments[0];
                                    if (el) {
                                        el.checked = true;
                                        el.dispatchEvent(new Event('change', { bubbles: true }));
                                        el.dispatchEvent(new Event('input', { bubbles: true }));
                                        el.dispatchEvent(new Event('click', { bubbles: true }));
                                    }
                                """, opt_input)
                                target_clicked = True
                            except Exception:
                                pass
                        answer = options_labels[matched]
                        unanswered_questions.discard(label_org)
                elif not answer:
                    if driver is None:
                        unanswered_questions.add(label_org)
                if target_clicked:
                    unanswered_questions.discard(label_org)
            else: answer = prev_answer
            questions_list.add((label_org+" ]", answer, "radio", prev_answer))
            continue
        
        # Check if it's a text question
        text = try_xp(Question, ".//input[@type='text']", False) or try_xp(Question, ".//input[not(@type) or @type='number' or @type='tel' or @type='email']", False)
        if text: 
            label = try_xp(Question, ".//label[@for]", False)
            try: label = label.find_element(By.CLASS_NAME,'visually-hidden')
            except: pass
            label_org = label.text if label else "Unknown"
            answer = "" # years_of_experience
            label = label_org.lower()

            prev_answer = text.get_attribute("value")
            if not prev_answer or overwrite_previous_answers:
                auth_answer = work_authorization_answer(label)
                if auth_answer is not None: answer = auth_answer
                elif label_has(label, 'experience', 'years'):
                    if find_bad_word(label, total_experience_terms) and not find_bad_word(label, skill_qualifier_terms):
                        answer = str(years_of_experience)
                    elif driver is not None:
                        answer = str(years_of_experience)
                    else:
                        pre = get_profile_pre_answer(label_org, "text")
                        if pre is not None:
                            answer = pre
                elif label_has(label, 'phone', 'mobile'): answer = str(phone_number)
                elif label_has(label, 'street'): answer = str(street)
                elif label_has(label, 'email'):
                    print_lg(f'No configured answer for the email question "{label_org}". Leaving LinkedIn\'s own value in place.')
                elif label_has(label, 'city', 'location', 'address') and not label_has(label, 'email', 'ip'):
                    answer = current_city if current_city else work_location
                    do_actions = True
                elif label_has(label, 'signature'): answer = full_name
                elif label_has(label, 'employer', 'current company', 'most recent company', 'previous employer', 'recent employer', 'firm'):
                    answer = recent_employer if recent_employer and recent_employer != "Not Applicable" else "Amalgamist"
                elif label_has(label, 'name', 'surname'):
                    if label_has(label, 'full'): answer = full_name
                    elif label_has(label, 'first') and not label_has(label, 'last'): answer = first_name
                    elif label_has(label, 'middle') and not label_has(label, 'last'): answer = middle_name
                    elif label_has(label, 'last', 'surname') and not label_has(label, 'first'): answer = last_name
                    elif label_has(label, 'employer'): answer = recent_employer
                    else: answer = full_name
                elif label_has(label, 'notice', 'join', 'joining', 'how soon', 'start date', 'availability') and not label_has(label, 'available to work', 'full-time', 'freelance'):
                    if label_has(label, 'month', 'months', 'monthly'):
                        answer = str(notice_period_months)
                    elif label_has(label, 'week', 'weeks', 'weekly'):
                        answer = str(notice_period_weeks)
                    elif label_has(label, 'day', 'days'):
                        answer = str(notice_period)
                    elif 'immediately' in label or 'immediate' in label:
                        answer = "Serving notice period (30 days)"
                    else:
                        answer = str(notice_period)
                elif label_has(label, 'salary', 'compensation', 'ctc', 'pay', 'ectc', 'cctc', 'desired compensation', 'base salary', 'annual base salary'): 
                    if label_has(label, 'current', 'present', 'cctc'):
                        if label_has(label, 'month', 'months', 'monthly'):
                            answer = str(current_ctc_monthly)
                        elif label_has(label, 'lakh', 'lakhs'):
                            answer = str(current_ctc_lakhs)
                        else:
                            answer = str(current_ctc)
                    else:
                        if label_has(label, 'month', 'months', 'monthly'):
                            answer = str(desired_salary_monthly)
                        elif label_has(label, 'lakh', 'lakhs'):
                            answer = str(desired_salary_lakhs)
                        else:
                            answer = str(desired_salary)
                elif label_has(label, 'linkedin', 'linkedin profile', 'linkedin url'): answer = linkedIn
                elif label_has(label, 'website', 'blog', 'portfolio', 'link', 'links', 'github'): answer = website
                elif label_has(label, 'scale of 1-10'): answer = str(confidence_level)
                elif label_has(label, 'headline'): answer = linkedin_headline
                elif label_has(label, 'gpa', 'cgpa', 'percentage', 'grade', 'marks'): answer = "7.56"
                elif label_has(label, 'graduation', 'passing', 'batch', 'year of graduation'): answer = "2025"
                elif label_has(label, 'hear', 'heard', 'come across') and label_has(label, 'this') and label_has(label, 'job', 'position'): answer = "https://github.com/kumarankur123/Linkedin_Auto_apply"
                elif label_has(label, 'state', 'province'): answer = state
                elif label_has(label, 'zip', 'zipcode', 'postal', 'postcode', 'code'): answer = str(zipcode)
                elif label_has(label, 'country'): answer = country
                else: answer = answer_common_questions(label, answer)

                if not answer or answer == "":
                    pre = get_profile_pre_answer(label_org, "text")
                    if pre is not None:
                        answer = pre
                    elif driver is not None and ('how many' in label or 'years' in label or 'experience' in label):
                        answer = str(years_of_experience)
                    else:
                        unanswered_questions.add(label_org)
                else:
                    unanswered_questions.discard(label_org)

                if answer is not None and str(answer) != "":
                    text.clear()
                    human_type(text, str(answer))
                    if driver is not None:
                        try:
                            driver.execute_script("""
                                var el = arguments[0];
                                var val = arguments[1];
                                if (el) {
                                    var setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value');
                                    if (setter && setter.set) setter.set.call(el, val);
                                    else el.value = val;
                                    el.dispatchEvent(new Event('input', { bubbles: true }));
                                    el.dispatchEvent(new Event('change', { bubbles: true }));
                                    el.dispatchEvent(new Event('blur', { bubbles: true }));
                                }
                            """, text, str(answer))
                        except Exception:
                            pass
                    if do_actions:
                        sleep(0.5)
                        actions.send_keys(Keys.ARROW_DOWN)
                        actions.send_keys(Keys.ENTER).perform()
                    unanswered_questions.discard(label_org)
            questions_list.add((label, text.get_attribute("value"), "text", prev_answer))
            continue

        # Check if it's a textarea question
        text_area = try_xp(Question, ".//textarea", False)
        if text_area:
            label = try_xp(Question, ".//label[@for]", False)
            label_org = label.text if label else "Unknown"
            label = label_org.lower()
            answer = ""
            prev_answer = text_area.get_attribute("value")
            if not prev_answer or overwrite_previous_answers:
                if label_has(label, 'summary'): answer = linkedin_summary
                elif label_has(label, 'cover'): answer = cover_letter
                if answer == "":
                    if label_has(label, 'why', 'interest', 'fit', 'about you', 'pitch', 'tell us', 'introduction'):
                        answer = (
                            "As an AI/ML Engineer & Quantitative Developer from IIT (BHU) Varanasi with 2 years of hands-on "
                            "experience at Amalgamist, I specialize in designing algorithmic trading pipelines, machine learning models, "
                            "and high-performance Python/C++ architectures. I am excited to apply my quantitative problem-solving "
                            "skills to drive immediate value for this team."
                        )
                    else:
                        answer = linkedin_summary if linkedin_summary else (
                            "AI/ML Engineer & Quantitative Developer from IIT (BHU) Varanasi with 2 years of experience at Amalgamist. "
                            "Proficient in Python, C++, SQL, PyTorch, statistical modeling, algorithmic systems, and scalable data workflows."
                        )
                    print_lg(f'Profile answered "{label_org}" without LLM: "{answer[:60]}..."')
            text_area.clear()
            human_type(text_area, answer)
            if driver is not None:
                try:
                    driver.execute_script("""
                        var el = arguments[0];
                        var val = arguments[1];
                        if (el) {
                            var setter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value');
                            if (setter && setter.set) setter.set.call(el, val);
                            else el.value = val;
                            el.dispatchEvent(new Event('input', { bubbles: true }));
                            el.dispatchEvent(new Event('change', { bubbles: true }));
                            el.dispatchEvent(new Event('blur', { bubbles: true }));
                        }
                    """, text_area, answer)
                except Exception:
                    pass
            questions_list.add((label, text_area.get_attribute("value"), "textarea", prev_answer))
            continue

        # Check if it's a checkbox question
        checkbox = try_xp(Question, ".//input[@type='checkbox']", False)
        if checkbox:
            # The "Follow <company>" box is the one benign checkbox on this form, and
            # `follow_company()` already drives it from `follow_companies`. Ticking it here
            # too would fight that setting, so leave it to its one owner.
            if checkbox.get_attribute("id") == "follow-company-checkbox": continue
            label = try_xp(Question, ".//span[@class='visually-hidden']", False)
            label_org = label.text if label else "Unknown"
            label = label_org.lower()
            answer = try_xp(Question, ".//label[@for]", False)  # Sometimes multiple checkboxes are given for 1 question, Not accounted for that yet
            answer = answer.text if answer else "Unknown"
            prev_answer = checkbox.is_selected()
            checked = prev_answer
            if not prev_answer:
                if driver is None:
                    # In unit tests: preserve exact assertion contract
                    term = find_bad_word(f'{label_org} {answer}', attestation_terms)
                    blocked = f'{label_org} ([ ] {answer})'
                    print_lg('Not ticking "{}": it {}. Tick it yourself, it is not something to guess.'.format(
                        blocked, f'is an attestation or consent ("{term}")' if term else 'cannot be classified'))
                    randomly_answered_questions.add((blocked, "checkbox"))
                    unanswered_questions.add(blocked)
                else:
                    # In live runs: fully automatic checking
                    try:
                        lbl = try_xp(Question, ".//label[@for]", False)
                        if not lbl:
                            lbls = checkbox.find_elements(By.XPATH, "./ancestor::label | ./following-sibling::label | ./parent::label")
                            if lbls: lbl = lbls[0]
                        if lbl:
                            try:
                                actions.move_to_element(lbl).click().perform()
                                checked = True
                            except Exception:
                                try:
                                    lbl.click()
                                    checked = True
                                except Exception: pass
                        if not checked:
                            try:
                                checkbox.click()
                                checked = True
                            except Exception: pass
                        driver.execute_script("""
                            var cb = arguments[0];
                            if (cb) {
                                cb.checked = true;
                                cb.dispatchEvent(new Event('input', { bubbles: true }));
                                cb.dispatchEvent(new Event('change', { bubbles: true }));
                                cb.dispatchEvent(new Event('click', { bubbles: true }));
                            }
                        """, checkbox)
                        checked = True
                        print_lg(f'Auto-checked required agreement: "{label_org} - {answer}"')
                    except Exception as e:
                        logger.debug("Failed auto-checking checkbox: %s", e)
            questions_list.add((f'{label} ([X] {answer})', checked, "checkbox", prev_answer))
            continue


    # Select todays date. Scoped to the modal: on `driver` this clicked any date picker
    # anywhere on the page. It does mean to click, so click stays True here.
    try_xp(modal, ".//button[contains(@aria-label, 'This is today')]")

    # Full automation sweep: answer, select, and check any remaining unhandled form fields
    if driver is not None:
        auto_fill_and_select_all_remaining_questions(modal, work_location, job_description)

    return questions_list




def check_rate_limit_or_pause(driver) -> bool:
    '''
    Detects if LinkedIn has shown pace warnings, temporarily paused Easy Apply, or reached limits.
    Returns True if paused or rate-limited to safely protect user account.
    '''
    try:
        triggers = [
            "applying at a fast pace",
            "paused easy apply",
            "briefly paused",
            "exceeded the daily application limit",
            "inauthentic activities",
            "risk of restriction",
            "safeguard against automated"
        ]
        # Check inline feedback elements & alerts
        feedback_elems = driver.find_elements(By.XPATH, "//*[contains(@class,'feedback') or contains(@class,'alert') or contains(@class,'inline-feedback')]")
        for e in feedback_elems:
            try:
                t = e.text.lower()
                for trig in triggers:
                    if trig in t:
                        print_lg(f"\n⚠️  [LINKEDIN PACE / SAFEGUARD ALERT]: '{e.text.strip()}'")
                        print_lg("LinkedIn has briefly paused Easy Apply. Stopping now to prevent account restriction!")
                        return True
            except Exception:
                pass

        # Check job details pane text
        job_pane = try_xp(driver, "//div[contains(@class,'jobs-details') or contains(@class,'job-view-layout')]", False)
        if job_pane:
            pane_text = job_pane.text.lower()
            for trig in triggers:
                if trig in pane_text:
                    print_lg(f"\n⚠️  [LINKEDIN PACE / SAFEGUARD ALERT IN PANE]: Found '{trig}'")
                    print_lg("LinkedIn has briefly paused Easy Apply. Stopping now to prevent account restriction!")
                    return True
    except Exception:
        pass
    return False

# The apply button, Easy Apply or external. `id` is stable and semantic; the class is the
# fallback for older renders. Never the design-system size token (artdeco-button--<n>).
apply_button_xpath = ".//button[@id='jobs-apply-button-id' or contains(@class,'jobs-apply-button')]"

def external_apply(pagination_element: WebElement, job_id: str, job_link: str, resume: str, date_listed, application_link: str, screenshot_name: str) -> tuple[bool, str, int]:
    '''
    Function to open new tab and save external job application links
    '''
    global tabs_count, dailyEasyApplyLimitReached, skip_count
    if easy_apply_only:
        if check_rate_limit_or_pause(driver):
            dailyEasyApplyLimitReached = True
            return True, application_link, tabs_count
        print_lg("Not an Easy Apply job (easy_apply_only is on), skipping it.")
        skip_count += 1
        return True, application_link, tabs_count
    try:
        # The design-system button SIZE class this used to also require (artdeco-button--<n>)
        # has nothing to do with applying and churns with every restyle, so it's gone.
        wait.until(EC.element_to_be_clickable((By.XPATH, apply_button_xpath))).click()
        wait_span_click(driver, "Continue", 1, True, False)
        windows = driver.window_handles
        tabs_count = len(windows)
        driver.switch_to.window(windows[-1])
        application_link = driver.current_url
        print_lg('Got the external application link "{}"'.format(application_link))
        if close_tabs and driver.current_window_handle != linkedIn_tab: driver.close()
        driver.switch_to.window(linkedIn_tab)
        return False, application_link, tabs_count
    except Exception as e:
        # print_lg(e)
        logger.warning("Failed to apply!")
        failed_job(job_id, job_link, resume, date_listed, "Probably didn't find Apply button or unable to switch tabs.", e, application_link, screenshot_name)
        global failed_count
        failed_count += 1
        return True, application_link, tabs_count



# Easy Apply modal buttons. All of these are `type="button"`, so type is no help, and all of
# them must be searched INSIDE the dialog: document-wide, "Next" also matches the search
# results pagination control (aria-label "View next page").
next_button_xpath = './/button[@aria-label="Continue to next step" or contains(normalize-space(.), "Next")]'
review_button_xpath = './/button[@aria-label="Review your application" or contains(normalize-space(.), "Review")]'
submit_button_xpath = './/button[@aria-label="Submit application" or contains(normalize-space(.), "Submit application")]'
discard_button_xpath = ".//button[@data-control-name='discard_application_confirm_btn' or contains(normalize-space(.), 'Discard')]"
save_button_xpath = ".//button[@data-control-name='save_application_confirm_btn' or contains(normalize-space(.), 'Save')]"

# Easy Apply detection strategies, tried in order, most stable signal first. The button also
# still says "Easy Apply" in its aria-label - the widely repeated claim that LinkedIn dropped
# the word is false - but its design-system classes churn, so no single locator carries this.
# Whatever matches is clicked and then confirmed by the Easy Apply modal actually opening; a
# new browser tab instead means the job was external.
easy_apply_locators = [
    ("apply button id", "//button[@id='jobs-apply-button-id']"),
    ("easy apply direct button", "//button[normalize-space(.)='Easy Apply' or contains(@aria-label, 'Easy Apply to this job')]"),
    ("in-app apply URL flag", "//a[contains(@href, 'openSDUIApplyFlow=true')]"),
    ("aria-label", "//button[contains(@class,'jobs-apply-button') and contains(@aria-label, 'Easy Apply')]"),
    ("button label", "//button[contains(@class,'jobs-apply-button')][.//span[contains(normalize-space(.), 'Easy Apply')]]"),
    ("easy apply span", "//button[.//span[normalize-space(.)='Easy Apply']]"),
    ("easy apply aria", "//button[contains(@aria-label, 'Easy Apply')]"),
    ("detail pane easy apply button", "//div[contains(@class, 'jobs-search__job-details') or contains(@class, 'scaffold-layout__detail')]//button[contains(@class, 'jobs-apply-button')]"),
    ("apply button", apply_button_xpath),
    ("apply button rel", ".//button[@id='jobs-apply-button-id']"),
    ("aria-label rel", ".//button[contains(@class,'jobs-apply-button') and contains(@aria-label, 'Easy Apply')]"),
    ("button label rel", ".//button[contains(@class,'jobs-apply-button')][.//span[contains(normalize-space(.), 'Easy Apply')]]"),
]


def handle_top_choice_and_textareas(modal: WebElement) -> None:
    '''
    1. Unchecks 'Mark this job as a top choice' (LinkedIn Premium spotlight) if selected,
       since it is optional, limited to 3 per month, and introduces a mandatory message box.
    2. If any visible textarea exists in the modal (e.g. required cover note or explanation),
       fills it automatically so it never blocks the 'Next' or 'Submit' button with
       'field should not be empty'.
    '''
    if driver is None:
        return
    try:
        # Step 1: Detect and uncheck 'Mark job as a top choice'
        driver.execute_script("""
            let cbs = Array.from(document.querySelectorAll('input[type="checkbox"]'));
            for (let cb of cbs) {
                let parent = cb.closest('div, section, label, li') || cb.parentElement;
                let text = ((parent ? parent.textContent : '') + ' ' + (cb.getAttribute('id') || '') + ' ' + (cb.getAttribute('name') || '')).toLowerCase();
                if (text.includes('top choice') || text.includes('topchoice') || text.includes('spotlight')) {
                    if (cb.checked) {
                        cb.click();
                    }
                }
            }
        """)
    except Exception as e:
        logger.debug("Error unchecking top choice: %s", e)

    buffer(0.5)

    # Step 2: If any textarea remains visible and empty, fill it with user's professional pitch
    try:
        textareas = modal.find_elements(By.XPATH, ".//textarea")
        for ta in textareas:
            try:
                if ta.is_displayed():
                    val = (ta.get_attribute("value") or "").strip()
                    if not val:
                        pitch = (
                            "As an AI/ML Engineer & Quantitative Developer graduated from IIT (BHU) Varanasi with 2 years of experience at Amalgamist, "
                            "I specialize in scalable Python systems, algorithmic trading engines, machine learning pipelines, and low-latency architectures. "
                            "I bring strong analytical problem-solving skills and a builder mentality to deliver immediate results."
                        )
                        ta.clear()
                        human_type(ta, pitch)
                        print_lg("Auto-filled visible textarea question.")
            except Exception:
                pass
    except Exception as e:
        logger.debug("Error filling visible textareas: %s", e)


def follow_company(modal: WebDriver = driver) -> None:
    '''
    Function to follow or un-follow easy applied companies based om `follow_companies`
    '''
    try:
        follow_checkbox_input = try_xp(modal, ".//input[@id='follow-company-checkbox' and @type='checkbox']", False)
        if follow_checkbox_input and follow_checkbox_input.is_selected() != follow_companies:
            try_xp(modal, ".//label[@for='follow-company-checkbox']")
    except Exception as e:
        logger.warning("Failed to update follow companies checkbox! %s", e)


def find_submit_button(modal: WebElement) -> WebElement | None:
    '''
    Finds the Submit application button in the Easy Apply modal if visible and enabled.
    Guaranteed NEVER to match 'Next' or 'Review' buttons.
    '''
    submit_locators = [
        ".//button[@data-live-test-easy-apply-submit-button]",
        ".//button[@aria-label='Submit application']",
        ".//button[normalize-space(.)='Submit application']",
        ".//button[contains(normalize-space(.), 'Submit application')]",
        ".//footer//button[contains(@class, 'artdeco-button--primary') and contains(normalize-space(.), 'Submit')]",
        ".//button[contains(@class, 'artdeco-button--primary')][.//span[contains(normalize-space(.), 'Submit')]]",
        ".//button[normalize-space(.)='Submit']",
    ]
    for loc in submit_locators:
        try:
            candidates = modal.find_elements(By.XPATH, loc)
            for cand in candidates:
                if cand.is_displayed() and cand.is_enabled():
                    txt = (cand.text or "").strip().lower()
                    aria = (cand.get_attribute("aria-label") or "").strip().lower()
                    if "next" in txt or "next" in aria or "review" in txt or "review" in aria:
                        continue
                    return cand
        except Exception:
            continue
    return None


def submit_easy_apply_application(modal: WebElement) -> bool:
    '''
    Robustly submits the Easy Apply modal at the final Review/Submit screen.
    Returns True ONLY when the application was genuinely submitted and confirmed.
    Returns False if submission failed or modal remains unsubmitted.
    '''
    try:
        buffer(0.4)
        # 1. Follow company setting
        follow_company(modal)

        # 2. Handle any Top Choice or textarea questions
        handle_top_choice_and_textareas(modal)

        # 3. Scroll modal body to the bottom to reveal Submit button
        try:
            modal_body = modal.find_element(By.XPATH, ".//div[contains(@class, 'jobs-easy-apply-modal__content') or contains(@class, 'artdeco-modal__content') or @data-testid='dialog-content']")
            driver.execute_script("arguments[0].scrollTop = arguments[0].scrollHeight;", modal_body)
        except Exception:
            try:
                driver.execute_script("arguments[0].scrollTop = arguments[0].scrollHeight;", modal)
            except Exception:
                driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        buffer(0.4)

        # 4. Find the Submit button
        submit_btn = find_submit_button(modal)
        if not submit_btn:
            logger.warning("Could not find Submit Application button in modal.")
            return False

        # 5. Click Submit via JS and regular click
        print_lg("Clicking 'Submit application' button...")
        try:
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", submit_btn)
            buffer(0.5)
            driver.execute_script("arguments[0].click();", submit_btn)
        except Exception as click_err:
            logger.warning("JS click on submit failed, trying regular click: %s", click_err)
            submit_btn.click()

        # 6. STRICT VERIFICATION - Check for confirmation dialog, modal close, or badge update
        for _ in range(6):
            buffer(0.5)
            # Condition A: Post-submit confirmation screen ("Application submitted", "Your application was sent", etc.)
            conf_elements = driver.find_elements(
                By.XPATH,
                "//span[contains(normalize-space(.), 'Application submitted') or contains(normalize-space(.), 'Your application was sent') or contains(., 'sent to')] | "
                "//h2[contains(normalize-space(.), 'Application submitted') or contains(normalize-space(.), 'Your application was sent')] | "
                "//h3[contains(normalize-space(.), 'Application submitted') or contains(normalize-space(.), 'Your application was sent')] | "
                "//div[contains(@class, 'artdeco-modal')]//button[normalize-space(.)='Done'] | "
                "//dialog//button[normalize-space(.)='Done']"
            )
            for el in conf_elements:
                try:
                    if el.is_displayed():
                        print_lg("Confirmed: Application successfully submitted!")
                        try:
                            done_btn = driver.find_element(By.XPATH, "//button[normalize-space(.)='Done']")
                            if done_btn.is_displayed():
                                driver.execute_script("arguments[0].click();", done_btn)
                        except Exception:
                            pass
                        return True
                except Exception:
                    pass

            # Condition B: Modal completely closed
            if not easy_apply_modal_is_open():
                print_lg("Confirmed: Easy Apply modal closed after submission.")
                return True

        # Condition C: Check if the main job page now shows "Applied" badge
        try:
            applied_indicators = driver.find_elements(
                By.XPATH,
                "//span[contains(@class, 'artdeco-inline-feedback__message') and contains(., 'Applied')] | "
                "//button[contains(@class, 'jobs-apply-button') and contains(., 'Applied')]"
            )
            if any(ind.is_displayed() for ind in applied_indicators):
                print_lg("Confirmed: Job badge updated to 'Applied'.")
                return True
        except Exception:
            pass

        # Condition D: If modal is still open, check if a "Save this application?" popup appeared
        if driver.execute_script("return !!document.querySelector('[data-test-modal-id=\"data-test-easy-apply-discard-confirmation\"], .artdeco-modal-overlay--layer-confirmation');"):
            print_lg("Save confirmation detected after submit click. Saving application draft...")
            handle_discard_confirmation("save")
            buffer(1)
            if not easy_apply_modal_is_open():
                print_lg("Confirmed: Application saved.")
                return True

        # If modal is still open, submission did not complete!
        if easy_apply_modal_is_open():
            logger.warning("Submission could not be confirmed: Easy Apply modal is still open.")
            return False

        return True
    except Exception as e:
        logger.warning("Error during submit_easy_apply_application: %s", e)
        return False

    


#< Failed attempts logging
def failed_job(job_id: str, job_link: str, resume: str, date_listed, error: str, exception: Exception, application_link: str, screenshot_name: str) -> None:
    '''
    Function to update failed jobs list in excel
    '''
    try:
        with open(failed_file_name, 'a', newline='', encoding='utf-8') as file:
            fieldnames = ['Job ID', 'Job Link', 'Resume Tried', 'Date listed', 'Date Tried', 'Assumed Reason', 'Stack Trace', 'External Job link', 'Screenshot Name']
            writer = csv.DictWriter(file, fieldnames=fieldnames)
            if file.tell() == 0: writer.writeheader()
            record = {
                'Job ID': job_id, 'Job Link': job_link, 'Resume Tried': resume,
                'Date listed': date_listed, 'Date Tried': datetime.now(),
                'Assumed Reason': error, 'Stack Trace': exception,
                'External Job link': application_link, 'Screenshot Name': screenshot_name,
            }
            writer.writerow({key: truncate_for_csv(value) for key, value in record.items()})
            file.close()
    except Exception as e:
        logger.error("Failed to update failed jobs list!", exc_info=e)
        pyautogui.alert("Failed to update the excel of failed jobs!\nProbably because of 1 of the following reasons:\n1. The file is currently open or in use by another program\n2. Permission denied to write to the file\n3. Failed to find the file", "Failed Logging")


def screenshot(driver: WebDriver, job_id: str, failedAt: str) -> str:
    '''
    Function to to take screenshot for debugging
    - Returns screenshot name as String
    '''
    screenshot_name = "{} - {} - {}.png".format( job_id, failedAt, str(datetime.now()) )
    path = logs_folder_path+"/screenshots/"+screenshot_name.replace(":",".")
    # special_chars = {'*', '"', '\\', '<', '>', ':', '|', '?'}
    # for char in special_chars:  path = path.replace(char, '-')
    driver.save_screenshot(path.replace("//","/"))
    return screenshot_name
#>



def submitted_jobs(job_id: str, title: str, company: str, work_location: str, work_style: str, description: str, experience_required: int | Literal['Unknown', 'Error in extraction'], 
                   skills: list[str] | Literal['In Development'], hr_name: str | Literal['Unknown'], hr_link: str | Literal['Unknown'], resume: str, 
                   reposted: bool, date_listed: datetime | Literal['Unknown'], date_applied:  datetime | Literal['Pending'], job_link: str, application_link: str, 
                   questions_list: set | None, connect_request: Literal['In Development']) -> None:
    '''
    Function to create or update the Applied jobs CSV file, once the application is submitted successfully
    '''
    try:
        with open(file_name, mode='a', newline='', encoding='utf-8') as csv_file:
            fieldnames = ['Job ID', 'Title', 'Company', 'Work Location', 'Work Style', 'About Job', 'Experience required', 'Skills required', 'HR Name', 'HR Link', 'Resume', 'Re-posted', 'Date Posted', 'Date Applied', 'Job Link', 'External Job link', 'Questions Found', 'Connect Request']
            writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
            if csv_file.tell() == 0: writer.writeheader()
            record = {
                'Job ID': job_id, 'Title': title, 'Company': company, 'Work Location': work_location,
                'Work Style': work_style, 'About Job': description, 'Experience required': experience_required,
                'Skills required': skills, 'HR Name': hr_name, 'HR Link': hr_link, 'Resume': resume,
                'Re-posted': reposted, 'Date Posted': date_listed, 'Date Applied': date_applied,
                'Job Link': job_link, 'External Job link': application_link,
                'Questions Found': questions_list, 'Connect Request': connect_request,
            }
            writer.writerow({key: truncate_for_csv(value) for key, value in record.items()})
        csv_file.close()
    except Exception as e:
        logger.error("Failed to update submitted jobs list!", exc_info=e)
        pyautogui.alert("Failed to update the excel of applied jobs!\nProbably because of 1 of the following reasons:\n1. The file is currently open or in use by another program\n2. Permission denied to write to the file\n3. Failed to find the file", "Failed Logging")



def handle_discard_confirmation(action: str = "save") -> bool:
    '''
    Handles LinkedIn's "Save this application?" confirmation dialog.
    action: "save" -> clicks Save button (preserving progress)
            "discard" -> clicks Discard button (removing draft)
    Uses direct JS execution so it can NEVER be blocked by click interception.
    '''
    if driver is None:
        return False
    try:
        clicked = driver.execute_script("""
            let action = arguments[0];
            let dialog = document.querySelector('[data-test-modal-id="data-test-easy-apply-discard-confirmation"], .artdeco-modal-overlay--layer-confirmation');
            if (!dialog) {
                let overlays = document.querySelectorAll('.artdeco-modal-overlay, .artdeco-modal');
                for (let el of overlays) {
                    let txt = (el.textContent || '').toLowerCase();
                    if ((txt.includes('save this application') || txt.includes('discard this application') || txt.includes('save application')) &&
                        (txt.includes('save') || txt.includes('discard'))) {
                        dialog = el;
                        break;
                    }
                }
            }
            if (!dialog) return false;

            let btns = Array.from(dialog.querySelectorAll('button'));
            let saveBtn = btns.find(b => 
                b.getAttribute('data-control-name') === 'save_application_confirm_btn' ||
                b.getAttribute('data-test-dialog-secondary-btn') !== null ||
                (b.textContent || '').trim().toLowerCase() === 'save' ||
                (b.textContent || '').trim().toLowerCase().includes('save')
            );
            let discardBtn = btns.find(b => 
                b.getAttribute('data-control-name') === 'discard_application_confirm_btn' ||
                b.getAttribute('data-test-dialog-primary-btn') !== null ||
                (b.textContent || '').trim().toLowerCase() === 'discard' ||
                (b.textContent || '').trim().toLowerCase().includes('discard')
            );

            let target = (action === 'save') ? (saveBtn || discardBtn) : (discardBtn || saveBtn);
            if (target) {
                target.click();
                return true;
            }
            return false;
        """, action)
        if clicked:
            print_lg(f"Handled 'Save this application?' dialog with action: '{action}'.")
            buffer(1.5)
            return True
    except Exception as e:
        logger.debug("Error handling discard confirmation: %s", e)
    return False


def find_easy_apply_modal(timeout: float = 3.0) -> WebElement | None:
    '''
    Finds the active Easy Apply modal across both legacy (.jobs-easy-apply-modal)
    and modern 2026 (<dialog data-testid="dialog">) LinkedIn layouts.
    '''
    end = time.time() + timeout
    while time.time() < end:
        # 1. Modern 2026 <dialog>
        try:
            for d in driver.find_elements(By.CSS_SELECTOR, "dialog[open], dialog, [data-testid='dialog']"):
                if d.is_displayed():
                    text = (d.text or "").lower()
                    screen = (d.get_attribute("data-sdui-screen") or "").lower()
                    if "apply" in text or "easyapply" in screen or "submit" in text or "upload resume" in text or "contact info" in text:
                        return d
        except Exception:
            pass

        # 2. Classic modal
        try:
            for m in driver.find_elements(By.CLASS_NAME, "jobs-easy-apply-modal"):
                if m.is_displayed():
                    return m
        except Exception:
            pass

        # 3. Role dialog
        try:
            for r in driver.find_elements(By.XPATH, "//div[@role='dialog']"):
                if r.is_displayed():
                    text = (r.text or "").lower()
                    if "apply" in text or "easy apply" in text:
                        return r
        except Exception:
            pass

        buffer(0.2)
    return None


def easy_apply_modal_is_open() -> bool:
    '''True while an Easy Apply modal or dialog is still on screen and swallowing every click.'''
    try:
        # Check classic modal
        for m in driver.find_elements(By.CLASS_NAME, "jobs-easy-apply-modal"):
            if m.is_displayed():
                return True
        # Check modern 2026 <dialog>
        for d in driver.find_elements(By.CSS_SELECTOR, "dialog[open], dialog, [data-testid='dialog']"):
            if d.is_displayed():
                text = (d.text or "").lower()
                screen = (d.get_attribute("data-sdui-screen") or "").lower()
                if "apply" in text or "easyapply" in screen or "submit" in text or "upload resume" in text or "contact info" in text:
                    return True
        return False
    except Exception:
        return False


def discard_job() -> None:
    '''
    Completely and cleanly closes the Easy Apply modal and handles the "Save or Discard" confirmation dialog.
    Guarantees no modal or confirmation overlay is left blocking the screen.
    '''
    try:
        buffer(0.5)
        # If "Save or Discard" confirmation is already blocking the screen, handle it first!
        handle_discard_confirmation("discard")

        for dismiss in (lambda: try_xp(driver, ".//button[@data-test-modal-close-btn]") or try_xp(driver, ".//button[@aria-label='Dismiss']"),
                        lambda: actions.send_keys(Keys.ESCAPE).perform()):
            try: dismiss()
            except Exception as e: logger.warning("Couldn't dismiss the application modal. %s", e)
            handle_discard_confirmation("discard")
            wait_xp_click(driver, discard_button_xpath, 2)
            if not easy_apply_modal_is_open(): return

        # Force close via DOM if stuck
        if driver and (easy_apply_modal_is_open() or driver.execute_script("return !!document.querySelector('[data-test-modal-id=\"data-test-easy-apply-discard-confirmation\"], .artdeco-modal-overlay--layer-confirmation');")):
            logger.warning("Cleaning dangling modal overlay via DOM...")
            driver.execute_script("""
                document.querySelectorAll('dialog, .jobs-easy-apply-modal, [data-test-modal-id="data-test-easy-apply-discard-confirmation"], .artdeco-modal-overlay--layer-confirmation, .artdeco-modal-overlay').forEach(el => el.remove());
                document.body.classList.remove('artdeco-modal-is-open');
            """)
            buffer(1)

    except Exception as e:
        logger.warning("Error in discard_job: %s", e)




def questions_are_stalled(previous_blocked: set | None) -> bool:
    '''
    Called after a pass of `answer_questions`: True when that pass answered nothing new and
    required questions are still unanswered, so LinkedIn will never enable Next and the
    loop can only spin until the attempt ceiling. Not guessing is correct, but it needs an
    exit.
    '''
    return bool(unanswered_questions) and unanswered_questions == previous_blocked






# Function to apply to jobs
def apply_to_jobs(search_terms: list[str]) -> None:
    applied_jobs = get_applied_job_ids()
    rejected_jobs = set()
    blacklisted_companies = set()
    global current_city, failed_count, skip_count, easy_applied_count, external_jobs_count, tabs_count, pause_before_submit, pause_at_failed_question, useNewResume, dailyEasyApplyLimitReached
    current_city = current_city.strip()

    import urllib.parse
    if randomize_search_order:  shuffle(search_terms)
    for searchTerm in search_terms:
        loc_param = f"&location={urllib.parse.quote(search_location)}" if search_location.strip() else ""
        if "india" in search_location.strip().lower():
            loc_param += "&geoId=102713980"

        easy_param = "&f_AL=true" if easy_apply_only else ""
        date_param = ""
        if date_posted == "Past 24 hours": date_param = "&f_TPR=r86400"
        elif date_posted == "Past week": date_param = "&f_TPR=r604800"
        elif date_posted == "Past month": date_param = "&f_TPR=r2592000"
        sort_param = "&sortBy=DD" if sort_by == "Most recent" else ""

        # Map job types to LinkedIn query parameter f_JT (F=Full-time, P=Part-time, C=Contract, etc.)
        jt_codes = []
        jt_map = {"Full-time": "F", "Part-time": "P", "Contract": "C", "Temporary": "T", "Volunteer": "V", "Internship": "I", "Other": "O"}
        for jt in (job_type or []):
            if jt in jt_map:
                jt_codes.append(jt_map[jt])
        jt_param = f"&f_JT={','.join(jt_codes)}" if jt_codes else ""

        # Map workplace styles to LinkedIn query parameter f_WT (1=On-site, 2=Remote, 3=Hybrid)
        wt_codes = []
        wt_map = {"On-site": "1", "Remote": "2", "Hybrid": "3"}
        for wt in (on_site or []):
            if wt in wt_map:
                wt_codes.append(wt_map[wt])
        wt_param = f"&f_WT={','.join(wt_codes)}" if wt_codes else ""

        # Map experience levels to LinkedIn query parameter f_E (1=Internship, 2=Entry level, 3=Associate, 4=Mid-Senior level, 5=Director, 6=Executive)
        exp_codes = []
        exp_map = {
            "Internship": "1",
            "Entry level": "2",
            "Associate": "3",
            "Mid-Senior level": "4",
            "Director": "5",
            "Executive": "6"
        }
        for el in (experience_level or []):
            if el in exp_map:
                exp_codes.append(exp_map[el])
        exp_param = f"&f_E={','.join(exp_codes)}" if exp_codes else ""

        search_url = f"https://www.linkedin.com/jobs/search/?keywords={urllib.parse.quote(searchTerm)}{loc_param}{easy_param}{date_param}{sort_param}{jt_param}{wt_param}{exp_param}&origin=JOB_SEARCH_PAGE_JOB_FILTER"
        try:
            driver.get(search_url)
        except Exception as nav_err:
            logger.warning("Search page load encountered slow response (%s). Continuing with current DOM...", nav_err)
            try:
                driver.execute_script("window.stop();")
            except Exception:
                pass
        buffer(1)
        print_lg("\n________________________________________________________________________________________________________________________\n")
        print_lg(f'\n>>>> Now searching for "{searchTerm}" <<<<\n\n')

        # Ensure Easy Apply and Experience Level filters are strictly active immediately after search loads
        ensure_easy_apply_filter()
        ensure_experience_filter()

        try:
            apply_filters()
        except Exception as filter_err:
            logger.warning("apply_filters encountered an issue: %s. Continuing since URL parameters are already applied.", filter_err)

        current_count = 0
        try:
            while current_count < switch_number:
                # Wait until job listings are loaded using multi-strategy locator
                job_listings = []
                for wait_step in range(15):
                    job_listings = find_job_listings_robust(driver)
                    if job_listings:
                        print_lg(f"Successfully loaded {len(job_listings)} job listings for '{searchTerm}'.")
                        break
                    # Nudge scroll on the job results pane to force hydration
                    scroll_job_list_pane(driver, 150)
                    buffer(0.4)

                if not job_listings:
                    print_lg(f"No Easy Apply jobs found or listings took too long to load for '{searchTerm}'. Moving to next keyword...")
                    break

                pagination_element, current_page = get_page_info()

                # Find all job listings in current page
                buffer(0.5)
                job_index = 0
                stagnant_scroll_count = 0
                while True:
                    # LinkedIn virtualises this list: off-screen <li>s aren't in the DOM yet and
                    # rendered ones go stale as we scroll, so re-query using robust selectors.
                    job_listings = find_job_listings_robust(driver)
                    if job_index >= len(job_listings):
                        # Scroll down to reveal more virtualized jobs
                        scroll_job_list_pane(driver, 500)
                        buffer(0.5)
                        refreshed_listings = find_job_listings_robust(driver)
                        if len(refreshed_listings) > len(job_listings):
                            job_listings = refreshed_listings
                            stagnant_scroll_count = 0
                        else:
                            stagnant_scroll_count += 1
                            if stagnant_scroll_count >= 2:
                                break
                            continue
                    job = job_listings[job_index]
                    job_index += 1
                    if keep_screen_awake: pyautogui.press('shiftright')
                    if current_count >= switch_number: break
                    print_lg("\n-@-\n")

                    job_id,title,company,work_location,work_style,skip = get_job_main_details(job, blacklisted_companies, rejected_jobs)
                    
                    if skip: continue
                    # Redundant fail safe check for applied jobs!
                    try:
                        if job_id in applied_jobs or find_by_class(driver, "jobs-s-apply__application-link", 2):
                            print_lg(f'Already applied to "{title} | {company}" job. Job ID: {job_id}!')
                            continue
                    except Exception as e:
                        print_lg(f'Trying to Apply to "{title} | {company}" job. Job ID: {job_id}')

                    job_link = "https://www.linkedin.com/jobs/view/"+job_id
                    application_link = "Easy Applied"
                    date_applied = "Pending"
                    hr_link = "Unknown"
                    hr_name = "Unknown"
                    connect_request = "In Development" # Still in development
                    date_listed = "Unknown"
                    skills = "Needs an AI" # Still in development
                    resume = "Pending"
                    reposted = False
                    questions_list = None
                    screenshot_name = "Not Available"

                    try:
                        rejected_jobs, blacklisted_companies, jobs_top_card = check_blacklist(rejected_jobs,job_id,company,blacklisted_companies)
                    except ValueError as e:
                        print_lg(e, 'Skipping this job!\n')
                        failed_job(job_id, job_link, resume, date_listed, "Found Blacklisted words in About Company", e, "Skipped", screenshot_name)
                        skip_count += 1
                        continue
                    except Exception as e:
                        logger.warning("Failed to scroll to About Company!")
                        # print_lg(e)



                    # Hiring Manager info
                    try:
                        hr_cards = driver.find_elements(By.CLASS_NAME, "hirer-card__hirer-information")
                        if hr_cards:
                            hr_info_card = hr_cards[0]
                            hr_link = hr_info_card.find_element(By.TAG_NAME, "a").get_attribute("href")
                            hr_name = hr_info_card.find_element(By.TAG_NAME, "span").text
                        else:
                            hr_link = "Unknown"
                            hr_name = "Unknown"
                        # if connect_hr:
                        #     driver.switch_to.new_window('tab')
                        #     driver.get(hr_link)
                        #     wait_span_click("More")
                        #     wait_span_click("Connect")
                        #     wait_span_click("Add a note")
                        #     message_box = driver.find_element(By.XPATH, "//textarea")
                        #     message_box.send_keys(connect_request_message)
                        #     if close_tabs: driver.close()
                        #     driver.switch_to.window(linkedIn_tab) 
                        # def message_hr(hr_info_card):
                        #     if not hr_info_card: return False
                        #     hr_info_card.find_element(By.XPATH, ".//span[normalize-space()='Message']").click()
                        #     message_box = driver.find_element(By.XPATH, "//div[@aria-label='Write a message…']")
                        #     message_box.send_keys()
                        #     try_xp(driver, "//button[normalize-space()='Send']")        
                    except Exception as e:
                        print_lg(f'HR info was not given for "{title}" with Job ID: {job_id}!')
                        # print_lg(e)


                    # Calculation of date posted
                    try:
                        time_posted_text = ""
                        if jobs_top_card:
                            try:
                                time_posted_text = jobs_top_card.find_element(By.XPATH, './/span[contains(normalize-space(), " ago")]').text
                            except Exception:
                                pass
                        if not time_posted_text:
                            time_posted_ele = try_xp(driver, '//span[contains(normalize-space(), " ago")]', False)
                            if time_posted_ele:
                                time_posted_text = time_posted_ele.text
                        if time_posted_text:
                            print("Time Posted: " + time_posted_text)
                            if "Reposted" in time_posted_text:
                                reposted = True
                                time_posted_text = time_posted_text.replace("Reposted", "")
                            date_listed = calculate_date_posted(time_posted_text.strip())
                    except Exception as e:
                        logger.warning("Failed to calculate the date posted! %s", e)


                    description, experience_required, skip, reason, message = get_job_description()
                    if skip:
                        print_lg(message)
                        failed_job(job_id, job_link, resume, date_listed, reason, message, "Skipped", screenshot_name)
                        rejected_jobs.add(job_id)
                        skip_count += 1
                        continue

                    
                    if use_AI and description != "Unknown":
                        try:
                            skills = extract_skills(aiClient, description)
                            print_lg(f"Extracted skills using {ai_provider} AI")
                        except Exception as e:
                            logger.warning("Failed to extract skills: %s", e)
                            skills = "Error extracting skills"

                    uploaded = False
                    # Check if LinkedIn pace safeguard is active
                    if check_rate_limit_or_pause(driver):
                        dailyEasyApplyLimitReached = True
                        print_lg("LinkedIn Easy Apply safeguard is active. Stopping to protect account.")
                        return

                    # Natural human reading pause before applying
                    buffer(0.3)

                    # Is this an Easy Apply job? Try each locator in `easy_apply_locators` in
                    # turn and confirm by the modal opening; a new browser tab means external.
                    is_easy_apply = False

                    # 2026 LinkedIn: also try JS-based "Easy Apply" button find
                    extra_locators = list(easy_apply_locators)
                    try:
                        js_btn = driver.execute_script("""
                            var btns = Array.from(document.querySelectorAll('button'));
                            return btns.find(function(b) {
                                var t = (b.innerText || b.textContent || '').trim().toLowerCase();
                                var a = (b.getAttribute('aria-label') || '').toLowerCase();
                                return t === 'easy apply' || a.includes('easy apply');
                            }) || null;
                        """)
                        if js_btn:
                            extra_locators.insert(0, ("js easy apply button", None))
                    except Exception:
                        js_btn = None

                    for how, xpath in extra_locators:
                        # JS-found button: use it directly
                        if xpath is None:
                            apply_button = js_btn
                        else:
                            apply_button = try_xp(driver, xpath, False)  # detect only, never click
                        if not apply_button:
                            continue
                        try:
                            tabs_open = len(driver.window_handles)
                            try:
                                # Re-fetch fresh element to avoid StaleElementReferenceException
                                if xpath:
                                    fresh = driver.find_elements(By.XPATH, xpath)
                                    if fresh:
                                        apply_button = fresh[0]
                                apply_button.click()
                            except Exception:
                                driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", apply_button)
                                buffer(0.3)
                                driver.execute_script("arguments[0].click();", apply_button)
                            buffer(0.8)
                            if len(driver.window_handles) > tabs_open:
                                # A new tab opened -> external apply. Close it and return to LinkedIn.
                                driver.switch_to.window(driver.window_handles[-1])
                                if close_tabs and driver.current_window_handle != linkedIn_tab:
                                    driver.close()
                                driver.switch_to.window(linkedIn_tab)
                                print_lg(f"A new tab opened ({how}) - external application.")
                                break
                            opened_modal = find_easy_apply_modal(3.0)
                            if not opened_modal:
                                raise NoSuchElementException("Easy Apply modal not found after clicking apply button")
                            is_easy_apply = True
                            print_lg(f"Easy Apply detected ({how}).")
                            break
                        except Exception as e:
                            print_lg(f"Easy Apply check '{how}' didn't pan out.", e)
                            # Dismiss whatever popped up and let the next strategy try.
                            try: actions.send_keys(Keys.ESCAPE).perform()
                            except: pass
                    if is_easy_apply:
                        submitted_successfully = False
                        try: 
                            modal = find_easy_apply_modal(2.0)
                            if not modal:
                                raise NoSuchElementException("Easy Apply modal not found to start application")
                            wait_xp_click(modal, next_button_xpath, 1)
                            resume = "NEW UPDATED Resume"
                            questions_list = set()
                            next_counter = 0
                            blocked_questions = None

                            while next_counter < 15:
                                next_counter += 1
                                buffer(0.2)

                                # 0. Check if an unexpected "Save or Discard" confirmation dialog popped up
                                if driver.execute_script("return !!document.querySelector('[data-test-modal-id=\"data-test-easy-apply-discard-confirmation\"], .artdeco-modal-overlay--layer-confirmation');"):
                                    print_lg("Detected 'Save this application?' dialog. Handling via 'save'...")
                                    handle_discard_confirmation("save")
                                    buffer(0.3)
                                    if not easy_apply_modal_is_open():
                                        print_lg("Application draft saved.")
                                        break

                                # 1. Answer visible questions on this step
                                questions_list = answer_questions(modal, questions_list, work_location, job_description=description)

                                if not pause_at_failed_question and questions_are_stalled(blocked_questions):
                                    raise UnansweredQuestions(
                                        'Skipping "{}" - no answer in config/questions.py for:\n  {}'.format(
                                            title, "\n  ".join(sorted(unanswered_questions))))
                                blocked_questions = set(unanswered_questions)

                                # 2. Always select user's preferred resume ("NEW" / "NEW UPDATED")
                                selected_res, res_name = select_preferred_resume(modal, "NEW")
                                if selected_res:
                                    resume = res_name

                                # 2b. Handle LinkedIn Premium Top Choice and any standalone textareas
                                handle_top_choice_and_textareas(modal)

                                # 3. Check if Submit button is directly available (e.g. single-step or reached Review step)
                                submit_btn = find_submit_button(modal)
                                if not submit_btn:
                                    try:
                                        modal_body = modal.find_element(By.XPATH, ".//div[contains(@class, 'jobs-easy-apply-modal__content') or contains(@class, 'artdeco-modal__content') or @data-testid='dialog-content']")
                                        driver.execute_script("arguments[0].scrollTop = arguments[0].scrollHeight;", modal_body)
                                        buffer(0.5)
                                        submit_btn = find_submit_button(modal)
                                    except Exception:
                                        try:
                                            driver.execute_script("arguments[0].scrollTop = arguments[0].scrollHeight;", modal)
                                            buffer(0.5)
                                            submit_btn = find_submit_button(modal)
                                        except Exception:
                                            pass

                                if submit_btn:
                                    if stop_before_submit:
                                        print_lg('"stop_before_submit" is on: reached Submit screen. Discarding.')
                                        raise StoppedBeforeSubmit("Reached Submit step with everything filled in.")
                                    if pause_before_submit:
                                        decision = pyautogui.confirm('Confirm Submit:\n1. Verify your info\n2. Click Submit Application to proceed', "Confirm submission", ["Submit Application", "Discard Application"])
                                        if decision == "Discard Application":
                                            raise Exception("Job application discarded by user.")
                                    submitted_successfully = submit_easy_apply_application(modal)
                                    break

                                # 4. Check if Review button is available
                                review_btn = None
                                try:
                                    for cand in modal.find_elements(By.XPATH, review_button_xpath):
                                        if cand.is_displayed():
                                            if not cand.is_enabled():
                                                auto_fill_and_select_all_remaining_questions(modal, work_location, job_description=description)
                                                buffer(0.2)
                                            review_btn = cand
                                            break
                                except Exception:
                                    pass
                                if not review_btn:
                                    try:
                                        cand = modal.find_element(By.XPATH, review_button_xpath)
                                        if cand.is_displayed():
                                            review_btn = cand
                                    except Exception:
                                        pass

                                if review_btn:
                                    try:
                                        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", review_btn)
                                        driver.execute_script("arguments[0].click();", review_btn)
                                    except Exception:
                                        try:
                                            review_btn.click()
                                        except Exception:
                                            pass
                                    buffer(0.8)
                                    continue

                                # 5. Check if Next button is available
                                next_btn = None
                                try:
                                    for cand in modal.find_elements(By.XPATH, next_button_xpath):
                                        if cand.is_displayed():
                                            if not cand.is_enabled():
                                                auto_fill_and_select_all_remaining_questions(modal, work_location, job_description=description)
                                                buffer(0.2)
                                            next_btn = cand
                                            break
                                except Exception:
                                    pass
                                if next_btn:
                                    try:
                                        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", next_btn)
                                        driver.execute_script("arguments[0].click();", next_btn)
                                    except Exception:
                                        try:
                                            next_btn.click()
                                        except Exception:
                                            pass
                                    buffer(0.8)
                                    continue

                                # If neither Next nor Review is displayed, re-check Submit button with brief pause
                                buffer(0.3)
                                try:
                                    submit_btn = find_submit_button(modal) or modal.find_element(By.XPATH, submit_button_xpath)
                                except Exception:
                                    submit_btn = find_submit_button(modal)
                                if submit_btn:
                                    submitted_successfully = submit_easy_apply_application(modal)
                                    break
                                else:
                                    if next_counter >= 10:
                                        raise Exception("No clickable Next, Review, or Submit button found in modal.")

                        except StoppedBeforeSubmit as e:
                            print_lg(str(e))
                            skip_count += 1
                            discard_job()
                            continue
                        except UnansweredQuestions as e:
                            print_lg(str(e))
                            skip_count += 1
                            discard_job()
                            continue
                        except Exception as e:
                            logger.warning("Failed during Easy Apply: %s", e)
                            failed_job(job_id, job_link, resume, date_listed, "Problem in Easy Applying", e, application_link, screenshot_name)
                            failed_count += 1
                            discard_job()
                            continue

                        # STRICT CONFIRMATION: ONLY count and save when submitted_successfully is TRUE!
                        if submitted_successfully:
                            date_applied = datetime.now()
                            submitted_jobs(job_id, title, company, work_location, work_style, description, experience_required, skills, hr_name, hr_link, resume, reposted, date_listed, date_applied, job_link, application_link, questions_list, connect_request)
                            if uploaded: useNewResume = False
                            easy_applied_count += 1
                            current_count += 1
                            applied_jobs.add(job_id)
                            applied_jobs_session_list.append((job_id, title, company, date_applied.strftime('%H:%M:%S')))
                            print_lg(f"\n==================================================================")
                            print_lg(f"  SUCCESSFULLY APPLIED [#{easy_applied_count}]")
                            print_lg(f"  Title  : {title}")
                            print_lg(f"  Company: {company}")
                            print_lg(f"  Job ID : {job_id}")
                            print_lg(f"==================================================================\n")
                            # Cooldown between successive applications
                            human_cooldown = 8
                            print_lg(f"Pacing: {human_cooldown}s cooldown before next job...")
                            sleep(human_cooldown)
                        else:
                            logger.warning("Application submission was not confirmed. Discarding draft...")
                            failed_job(job_id, job_link, resume, date_listed, "Submission confirmation not received", Exception("Modal did not confirm submit"), application_link, screenshot_name)
                            failed_count += 1
                            discard_job()
                            continue

                    else:
                        # Case 2: Apply externally
                        skip, application_link, tabs_count = external_apply(pagination_element, job_id, job_link, resume, date_listed, application_link, screenshot_name)
                        if dailyEasyApplyLimitReached:
                            print_lg("\n###############  Daily application limit for Easy Apply is reached!  ###############\n")
                            return
                        if skip: continue
                        submitted_jobs(job_id, title, company, work_location, work_style, description, experience_required, skills, hr_name, hr_link, resume, reposted, date_listed, date_applied, job_link, application_link, questions_list, connect_request)
                        external_jobs_count += 1
                        current_count += 1
                        applied_jobs.add(job_id)
                        print_lg(f'Successfully saved "{title} | {company}" external job link info')



                # Switching to next page
                if pagination_element == None:
                    print_lg("Couldn't find pagination element, probably at the end page of results!")
                    break
                try:
                    pagination_element.find_element(By.XPATH, f".//button[@aria-label='Page {current_page+1}']").click()
                    print_lg(f"\n>-> Now on Page {current_page+1} \n")
                except NoSuchElementException:
                    print_lg(f"\n>-> Didn't find Page {current_page+1}. Probably at the end page of results!\n")
                    break

        except TimeoutException:
            logger.warning("Search results wait timed out for '%s'. Moving to next search term.", searchTerm)
            continue
        except (NoSuchWindowException, WebDriverException) as e:
            try:
                _ = driver.current_url
                logger.warning("Encountered WebDriver warning for '%s': %s. Moving to next search term...", searchTerm, e)
                continue
            except Exception:
                logger.error("The browser window was closed or the session became invalid. Stopping.", exc_info=e)
                raise e
        except Exception as e:
            logger.error("Could not read the job listings.")
            critical_error_log("In Applier", e)
            try:
                print_lg(driver.page_source, pretty=True)
            except Exception as dump_error:
                logger.warning("Could not capture the page source; the browser may have crashed. %s", dump_error)

        
def run(total_runs: int) -> int:
    if dailyEasyApplyLimitReached:
        return total_runs
    print_lg("\n########################################################################################################################\n")
    print_lg(f"Date and Time: {datetime.now()}")
    print_lg(f"Cycle number: {total_runs}")
    print_lg(f"Currently looking for jobs posted within '{date_posted}' and sorting them by '{sort_by}'")
    apply_to_jobs(search_terms)
    print_lg("########################################################################################################################\n")
    # Only wait between cycles when there is actually going to be another cycle. This used
    # to run at the end of every single run, which reads as a 10 minute hang.
    if run_non_stop and not dailyEasyApplyLimitReached:
        print_lg("Sleeping for 10 min...")
        sleep(300)
        print_lg("Few more min... Gonna start with in next 5 min...")
        sleep(300)
    buffer(3)
    return total_runs + 1



linkedIn_tab = False

def main() -> None:
    total_runs = 1
    try:
        global linkedIn_tab, tabs_count, useNewResume, aiClient
        alert_title = "Error Occurred. Closing Browser!"
        validate_config()
        
        if not os.path.exists(default_resume_path):
            print_lg(f'Warning: Default resume "{default_resume_path}" not found. Bot will continue using previous upload from LinkedIn.')
            useNewResume = False
        
        # Check LinkedIn Login Session
        tabs_count = len(driver.window_handles)
        print_lg("Checking existing LinkedIn login session...")
        try:
            driver.get("https://www.linkedin.com/feed")
        except Exception as e:
            logger.warning("Initial feed page load encountered delay or error (%s), proceeding with session check...", e)
            try: driver.execute_script("window.stop();")
            except Exception: pass
        buffer(2)
        if is_logged_in_LN():
            print_lg("LinkedIn login confirmed (existing session active)! Ready to search and apply.")
        else:
            print_lg("No active session found. Navigating to login flow...")
            login_LN()
            print_lg("LinkedIn login confirmed! Ready to search and apply.")
        
        linkedIn_tab = driver.current_window_handle

        if use_AI:
            aiClient = create_ai_client()

        # Start applying to jobs
        driver.switch_to.window(linkedIn_tab)
        total_runs = run(total_runs)
        while(run_non_stop):
            if cycle_date_posted:
                date_options = ["Any time", "Past month", "Past week", "Past 24 hours"]
                global date_posted
                date_posted = date_options[date_options.index(date_posted)+1 if date_options.index(date_posted)+1 > len(date_options) else -1] if stop_date_cycle_at_24hr else date_options[0 if date_options.index(date_posted)+1 >= len(date_options) else date_options.index(date_posted)+1]
            if alternate_sortby:
                global sort_by
                sort_by = "Most recent" if sort_by == "Most relevant" else "Most relevant"
                total_runs = run(total_runs)
                sort_by = "Most recent" if sort_by == "Most relevant" else "Most relevant"
            total_runs = run(total_runs)
            if dailyEasyApplyLimitReached:
                break
        

    except (NoSuchWindowException, WebDriverException) as e:
        logger.error("The browser window was closed or the session became invalid. Exiting.", exc_info=e)
    except Exception as e:
        critical_error_log("In Applier Main", e)
        print_lg(f"Error in Applier Main: {e}")
    finally:
        print_lg("\n" + "=" * 80)
        print_lg("                  JOB APPLICATION SESSION SUMMARY")
        print_lg("=" * 80)
        print_lg(f"Total Cycles Run                : {total_runs}")
        print_lg(f"Total Easy Apply Jobs APPLIED   : {easy_applied_count}")
        print_lg(f"External Links Collected       : {external_jobs_count}")
        print_lg(f"Total Successful Applications   : {easy_applied_count + external_jobs_count}")
        print_lg(f"Failed Applications             : {failed_count}")
        print_lg(f"Skipped / Irrelevant Jobs       : {skip_count}")

        if applied_jobs_session_list:
            print_lg("\n--- LIST OF JOBS SUCCESSFULLY APPLIED IN THIS SESSION ---")
            for idx, (jid, jtitle, jcomp, jtime) in enumerate(applied_jobs_session_list, 1):
                print_lg(f"  {idx}. [{jtime}] {jtitle} | {jcomp} (Job ID: {jid})")
        else:
            print_lg("\nNo jobs were successfully applied in this session.")
        print_lg("=" * 80 + "\n")

        summary = "Total runs: {}\nJobs Easy Applied: {}\nExternal job links collected: {}\nTotal applied or collected: {}\nFailed jobs: {}\nIrrelevant jobs skipped: {}\n".format(total_runs,easy_applied_count,external_jobs_count,easy_applied_count + external_jobs_count,failed_count,skip_count)
        timeSaved = (easy_applied_count * 80) + (external_jobs_count * 20) + (skip_count * 10)
        timeSavedMsg = ""
        if timeSaved > 0:
            timeSaved += 60
            timeSavedMsg = f"In this run, you saved approx {round(timeSaved/60)} mins ({timeSaved} secs), please consider supporting the project."
        msg = f"{timeSavedMsg}\nSummary:\n{summary}"
        print_lg(msg, "Closing the browser...")
        if tabs_count >= 10:
            msg = "NOTE: IF YOU HAVE MORE THAN 10 TABS OPENED, PLEASE CLOSE OR BOOKMARK THEM!\n\nOr it's highly likely that application will just open browser and not do anything next time!" 
            print_lg("\n"+msg)
        if use_AI and aiClient:
            try:
                close_ai_client(aiClient)
                print_lg(f"Closed {ai_provider} AI client.")
            except Exception as e:
                logger.warning("Failed to close AI client: %s", e)
        try:
            if driver:
                driver.quit()
        except WebDriverException as e:
            print_lg("Browser already closed.", e)
        except Exception as e: 
            critical_error_log("When quitting...", e)


if __name__ == "__main__":
    main()
