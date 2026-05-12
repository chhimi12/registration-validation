"""
find_contact_form.py
--------------------
1. Finds the highest-scoring contact form on an attorney website (main page + iframes).
2. Runs compliance validation on that form:
     - Consent message content checks
     - Phone field "not required" check
     - Consent checkbox "not pre-checked" check
3. Navigates to Terms of Service page and validates its content.
4. Navigates to Privacy Policy page and validates its content.

Returns a structured JSON result suitable for connecting to a frontend.

Usage:
  pip install selenium
  python find_contact_form.py https://www.example-lawfirm.com/contact
"""

import sys
import time
import re
import json
import logging
import os
from urllib.parse import urlparse
from dataclasses import dataclass, field
from typing import Optional, List

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from validation_rules import (
    ATTORNEY_CTA_WORDS,
    CONSENT_CHECKBOX_FALLBACK,
    CONSENT_CHECKBOX_SELECTORS,
    FIELD_SIGNALS,
    FORM_CONSENT_PHRASE_RULES,
    FORM_IFRAME_SRC_PATTERNS,
    LINK_SELECTORS,
    MULTI_FIELD_SELECTOR,
    NO_MOBILE_SHARING_PATTERN,
    PHONE_SELECTORS_BROAD,
    REQUIRED_PHONE_PLACEHOLDER,
    SMS_KEYWORD_PATTERN,
    SMS_OPT_IN_DISCLAIMER,
    THIRD_PARTY_SHARING_PATTERN,
    TOS_REQUIRED_CHECKS,
)

# ── CONFIG ────────────────────────────────────────────────────────────────────
logger = logging.getLogger(__name__)

DEFAULT_URL   = "https://www.myrightslawgroup.com/contact-us/"
WAIT_SECONDS  = int(os.getenv("SELENIUM_WAIT_SECONDS", "10"))
PAGE_SETTLE   = float(os.getenv("PAGE_SETTLE_SECONDS", "2"))
IFRAME_SETTLE = float(os.getenv("IFRAME_SETTLE_SECONDS", "1"))
PAGE_LOAD_TIMEOUT = int(os.getenv("PAGE_LOAD_TIMEOUT_SECONDS", "45"))
PAGE_LOAD_STRATEGY = os.getenv("PAGE_LOAD_STRATEGY", "eager")
MIN_SCORE     = int(os.getenv("MIN_FORM_SCORE", "2"))
# ─────────────────────────────────────────────────────────────────────────────


# ══════════════════════════════════════════════════════════════════════════════
#  FORM FINDER
# ══════════════════════════════════════════════════════════════════════════════


@dataclass
class ScoredForm:
    element: object
    score: int
    signals_found: list = field(default_factory=list)
    source: str = "unknown"
    outer_html: str = ""


def score_form(form_el, driver) -> ScoredForm:
    total, signals = 0, []
    for name, selector, points in FIELD_SIGNALS:
        try:
            if form_el.find_elements(By.CSS_SELECTOR, selector):
                total += points
                signals.append(f"{name}(+{points})")
        except Exception:
            pass
    try:
        for btn in form_el.find_elements(By.CSS_SELECTOR, "button, input[type='submit'], a[href='#']"):
            text = (btn.text or btn.get_attribute("value") or "").strip()
            if ATTORNEY_CTA_WORDS.search(text):
                total += 2
                signals.append("attorney-cta(+2)")
                break
    except Exception:
        pass
    try:
        all_fields = form_el.find_elements(By.CSS_SELECTOR, MULTI_FIELD_SELECTOR)
        if len(all_fields) >= 3:
            total += 1
            signals.append(f"multi-field({len(all_fields)},+1)")
    except Exception:
        pass
    return ScoredForm(element=form_el, score=total, signals_found=signals)


def best_form_in_frame(driver) -> Optional[ScoredForm]:
    try:
        forms = driver.find_elements(By.TAG_NAME, "form")
    except Exception:
        return None
    best = None
    for form in forms:
        try:
            sf = score_form(form, driver)
            if best is None or sf.score > best.score:
                best = sf
        except Exception:
            continue
    return best if (best and best.score >= MIN_SCORE) else None


def get_outer_html(el, driver) -> str:
    try:
        return driver.execute_script("return arguments[0].outerHTML;", el) or ""
    except Exception:
        return ""


def categorise_iframes(driver):
    priority, fallback = [], []
    try:
        iframes = driver.find_elements(By.TAG_NAME, "iframe")
    except Exception:
        return [], []
    for i, iframe in enumerate(iframes):
        src   = iframe.get_attribute("src") or ""
        iid   = iframe.get_attribute("id") or ""
        cls   = iframe.get_attribute("class") or ""
        label = f"iframe #{i+1} id='{iid}' class='{cls}' src={src[:80]}"
        (priority if FORM_IFRAME_SRC_PATTERNS.search(src) else fallback).append(
            (iframe, label, src)
        )
    return priority, fallback


def check_iframe(driver, iframe, label) -> Optional[ScoredForm]:
    try:
        driver.switch_to.frame(iframe)
        WebDriverWait(driver, WAIT_SECONDS).until(
            EC.presence_of_element_located((By.TAG_NAME, "body"))
        )
        time.sleep(IFRAME_SETTLE)
        sf = best_form_in_frame(driver)
        if sf:
            sf.source = label
            sf.outer_html = get_outer_html(sf.element, driver)
        return sf
    except Exception as e:
        logger.warning("Could not inspect %s: %s", label, e)
        return None
    finally:
        try:
            driver.switch_to.default_content()
        except Exception:
            pass


def find_contact_form(driver) -> Optional[ScoredForm]:
    """Main entry: find and return the best contact form across the page."""
    driver.implicitly_wait(0)

    logger.info("Scoring forms on main page")
    sf = best_form_in_frame(driver)
    if sf:
        sf.source = "main page"
        sf.outer_html = get_outer_html(sf.element, driver)
        logger.info("Found form on main page with score %s", sf.score)
        return sf
    logger.info("No qualifying form on main page")

    priority, fallback = categorise_iframes(driver)
    logger.info("Iframes: %s priority, %s fallback", len(priority), len(fallback))

    for iframe, label, _ in priority:
        sf = check_iframe(driver, iframe, label)
        if sf:
            logger.info("Found form in %s with score %s", label, sf.score)
            return sf

    for iframe, label, _ in fallback:
        sf = check_iframe(driver, iframe, label)
        if sf:
            logger.info("Found form in %s with score %s", label, sf.score)
            return sf

    return None


# ══════════════════════════════════════════════════════════════════════════════
#  FIRM NAME EXTRACTION
# ══════════════════════════════════════════════════════════════════════════════

def extract_firm_name(driver, page_url: str) -> str:
    """
    Try several heuristics to get the firm name, in order of reliability:
      1. og:site_name meta
      2. <title> tag
      3. First <h1> on the page
      4. Hostname cleaned up (last resort)
    """
    candidates = []

    # 1. og:site_name
    try:
        og = driver.find_element(By.CSS_SELECTOR, "meta[property='og:site_name']")
        val = og.get_attribute("content")
        if val and len(val.strip()) > 2:
            candidates.append(val.strip())
    except Exception:
        pass

    # 2. <title> — strip common suffixes
    try:
        title = driver.title or ""
        title = re.sub(r"\s*[-|–—]\s*.*$", "", title).strip()
        if title and len(title) > 2:
            candidates.append(title)
    except Exception:
        pass

    # 3. First meaningful h1
    try:
        h1s = driver.find_elements(By.TAG_NAME, "h1")
        for h1 in h1s:
            text = (h1.text or "").strip()
            if 3 < len(text) < 80:
                candidates.append(text)
                break
    except Exception:
        pass

    # 4. Hostname as last resort
    try:
        hostname = urlparse(page_url).hostname or ""
        hostname = re.sub(r"^www\.", "", hostname)
        hostname = hostname.split(".")[0]
        hostname = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", hostname)
        hostname = hostname.replace("-", " ").replace("_", " ").title()
        candidates.append(hostname)
    except Exception:
        pass

    return candidates[0] if candidates else "Unknown Firm"


# ══════════════════════════════════════════════════════════════════════════════
#  COMPLIANCE VALIDATOR — CONTACT FORM
# ══════════════════════════════════════════════════════════════════════════════


def find_consent_block(form_el, driver) -> dict:
    """
    Locate the consent / SMS disclosure inside the form.
    Returns { "text": str, "element": el | None, "links": {privacy: url, terms: url} }
    """
    result = {
        "text": "",
        "element": None,
        "links": {"privacy_policy": None, "terms_of_service": None},
    }

    # Strategy 1: checkbox label that contains SMS / consent text
    try:
        checkboxes = form_el.find_elements(By.CSS_SELECTOR, "input[type='checkbox']")
        for cb in checkboxes:
            cb_id = cb.get_attribute("id") or ""
            if cb_id:
                try:
                    lbl = form_el.find_element(By.CSS_SELECTOR, f"label[for='{cb_id}']")
                    label_text = lbl.text or ""
                    if SMS_KEYWORD_PATTERN.search(label_text) or "consent" in label_text.lower() or len(label_text) > 60:
                        result["text"] = label_text.strip()
                        result["element"] = lbl
                        for link_key, link_sel in LINK_SELECTORS.items():
                            try:
                                link_el = lbl.find_element(By.CSS_SELECTOR, link_sel)
                                result["links"][link_key] = link_el.get_attribute("href")
                            except Exception:
                                pass
                        if result["text"]:
                            return result
                except Exception:
                    pass
            val = cb.get_attribute("value") or ""
            if SMS_KEYWORD_PATTERN.search(val) or len(val) > 60:
                result["text"] = val.strip()
                result["element"] = cb
    except Exception:
        pass

    # Strategy 2: any <p> / <div> / <span> / <label> / <li> containing SMS-related or consent text
    CONSENT_TEXT_SELECTOR = "p, div, span, label, li"
    try:
        candidates = form_el.find_elements(By.CSS_SELECTOR, CONSENT_TEXT_SELECTOR)
        best_candidate = None
        best_len = 0
        for el in candidates:
            try:
                text = (el.text or "").strip()
                if (
                    SMS_KEYWORD_PATTERN.search(text)
                    or "consent" in text.lower()
                    or "opt-out" in text.lower()
                ) and len(text) > best_len:
                    best_candidate = el
                    best_len = len(text)
            except Exception:
                pass
        if best_candidate:
            result["text"] = best_candidate.text.strip()
            result["element"] = best_candidate
            for link_key, link_sel in LINK_SELECTORS.items():
                try:
                    link_el = best_candidate.find_element(By.CSS_SELECTOR, link_sel)
                    result["links"][link_key] = link_el.get_attribute("href")
                except Exception:
                    pass
    except Exception:
        pass

    return result


def validate_form(sf: ScoredForm, driver, firm_name: str, page_url: str) -> dict:
    """
    Run all compliance checks on the identified form.
    Returns a structured dict ready for JSON serialisation / frontend rendering.
    """
    result = {
        "url": page_url,
        "firm_name_detected": firm_name,
        "form_score": sf.score,
        "form_source": sf.source,
        "overall_pass": False,
        "checks": {},
    }

    form_el = sf.element

    # ── 1. Locate consent block ───────────────────────────────────────────────
    consent = find_consent_block(form_el, driver)
    consent_text = consent["text"]
    result["consent_text_found"] = consent_text or None

    # ── 2. Consent message content checks (short blurb on the form) ──────────
    consent_checks = {}

    # Firm name check — build pattern dynamically
    firm_pattern = re.compile(re.escape(firm_name), re.IGNORECASE) if firm_name else None
    firm_rule = {
        "key": "firm_name",
        "description": "Firm name must appear in the consent message",
        "pattern": firm_pattern,
    }
    all_phrase_rules = [firm_rule] + FORM_CONSENT_PHRASE_RULES

    for rule in all_phrase_rules:
        key  = rule["key"]
        desc = rule["description"]
        pat  = rule["pattern"]
        if pat is None:
            consent_checks[key] = {
                "pass": False,
                "description": desc,
                "detail": "Could not build pattern (firm name unknown).",
            }
            continue
        matched = bool(pat.search(consent_text)) if consent_text else False
        consent_checks[key] = {
            "pass": matched,
            "description": desc,
            "detail": (
                "✓ Found in consent text."
                if matched
                else "✗ Not found in consent text."
            ),
        }

    # Link checks (from the consent block on the form)
    for link_key, friendly in [
        ("privacy_policy", "Privacy Policy"),
        ("terms_of_service", "Terms of Service"),
    ]:
        href = consent["links"].get(link_key)
        consent_checks[link_key] = {
            "pass": bool(href),
            "description": f"Must include a link to {friendly}",
            "detail": f"✓ Link found: {href}" if href else f"✗ No {friendly} link found.",
            "href": href,
        }

    result["checks"]["consent_message"] = consent_checks

    # ── 3. Phone field checks ─────────────────────────────────────────────────
    phone_checks = {}

    phone_els = []
    try:
        phone_els = form_el.find_elements(By.CSS_SELECTOR, PHONE_SELECTORS_BROAD)
    except Exception:
        pass

    if not phone_els:
        phone_checks["phone_field_exists"] = {
            "pass": False,
            "description": "A phone input field must exist in the form",
            "detail": "✗ No phone field found.",
        }
    else:
        phone_el = phone_els[0]

        is_required_attr = False
        try:
            required_attr = phone_el.get_attribute("required")
            data_required = phone_el.get_attribute("data-required")
            is_required_attr = (
                (required_attr is not None and required_attr != "false")
                or (data_required and data_required.lower() == "true")
            )
        except Exception:
            pass

        phone_checks["not_required_attribute"] = {
            "pass": not is_required_attr,
            "description": "Phone field must NOT be marked required (required / data-required attribute)",
            "detail": (
                "✓ Phone field is not required by attribute."
                if not is_required_attr
                else "✗ Phone field has required or data-required='true' attribute."
            ),
        }

        placeholder = ""
        try:
            placeholder = phone_el.get_attribute("placeholder") or ""
        except Exception:
            pass

        placeholder_implies_required = bool(REQUIRED_PHONE_PLACEHOLDER.search(placeholder))
        phone_checks["placeholder_not_required"] = {
            "pass": not placeholder_implies_required,
            "description": "Phone placeholder must NOT suggest the field is required (no *, 'required', 'mandatory')",
            "detail": (
                f"✓ Placeholder '{placeholder}' does not imply required."
                if not placeholder_implies_required
                else f"✗ Placeholder '{placeholder}' implies the field is required."
            ),
            "placeholder_value": placeholder,
        }

    result["checks"]["phone_field"] = phone_checks

    # ── 4. Consent checkbox pre-checked check ─────────────────────────────────
    checkbox_checks = {}

    consent_cbs = []
    try:
        consent_cbs = form_el.find_elements(By.CSS_SELECTOR, CONSENT_CHECKBOX_SELECTORS)
        if not consent_cbs:
            consent_cbs = form_el.find_elements(By.CSS_SELECTOR, CONSENT_CHECKBOX_FALLBACK)
    except Exception:
        pass

    if not consent_cbs:
        checkbox_checks["checkbox_exists"] = {
            "pass": None,
            "description": "Consent checkbox presence",
            "detail": "ℹ No consent checkbox found — check may not be applicable.",
        }
    else:
        for i, cb in enumerate(consent_cbs):
            try:
                is_checked = cb.is_selected()
                cb_name = cb.get_attribute("name") or cb.get_attribute("id") or f"checkbox_{i}"
                checkbox_checks[f"not_prechecked_{i}"] = {
                    "pass": not is_checked,
                    "description": f"Consent checkbox '{cb_name}' must NOT be pre-checked by default",
                    "detail": (
                        f"✓ Checkbox '{cb_name}' is unchecked by default."
                        if not is_checked
                        else f"✗ Checkbox '{cb_name}' is pre-checked — user has not given active consent."
                    ),
                    "checkbox_name": cb_name,
                }
            except Exception as e:
                checkbox_checks[f"checkbox_{i}_error"] = {
                    "pass": False,
                    "description": f"Could not inspect checkbox {i}",
                    "detail": str(e),
                }

    result["checks"]["consent_checkbox"] = checkbox_checks

    return result


# ══════════════════════════════════════════════════════════════════════════════
#  TERMS OF SERVICE PAGE VALIDATOR
# ══════════════════════════════════════════════════════════════════════════════


def validate_tos_page(driver, tos_url: str, firm_name: str) -> dict:
    """
    Navigate to the Terms of Service URL, validate its title and required content.
    Returns a structured dict with all check results.
    """
    result = {
        "url": tos_url,
        "checks": {},
        "page_text_snapshot": "",
    }

    logger.info("Navigating to Terms of Service page: %s", tos_url)
    try:
        driver.get(tos_url)
        time.sleep(PAGE_SETTLE)
    except Exception as e:
        result["error"] = f"Could not load ToS page: {e}"
        return result

    # ── Title check ───────────────────────────────────────────────────────────
    try:
        page_title = driver.title or ""
        # Also check the first visible h1
        h1_text = ""
        try:
            h1s = driver.find_elements(By.TAG_NAME, "h1")
            if h1s:
                h1_text = h1s[0].text.strip()
        except Exception:
            pass

        EXPECTED_TOS_TITLE = re.compile(
            r"messaging\s+terms\s+of\s+service|terms\s+of\s+service|terms\s+&\s+conditions",
            re.IGNORECASE,
        )
        title_pass = bool(
            EXPECTED_TOS_TITLE.search(page_title) or EXPECTED_TOS_TITLE.search(h1_text)
        )
        result["checks"]["page_title"] = {
            "pass": title_pass,
            "description": 'Page must be titled "Terms of Service" (or "[Firm Name]\'s Messaging Terms of Service")',
            "detail": (
                f"✓ Title '{page_title}' / H1 '{h1_text}' matches expected."
                if title_pass
                else f"✗ Title '{page_title}' / H1 '{h1_text}' does not match expected 'Terms of Service'."
            ),
            "page_title": page_title,
            "h1_text": h1_text,
        }
    except Exception as e:
        result["checks"]["page_title"] = {"pass": False, "detail": str(e)}

    # ── Get full visible page text ─────────────────────────────────────────────
    page_text = ""
    try:
        body = driver.find_element(By.TAG_NAME, "body")
        page_text = body.text or ""
        result["page_text_snapshot"] = page_text[:500]  # first 500 chars for debugging
    except Exception:
        pass

    # ── Firm name check ───────────────────────────────────────────────────────
    if firm_name:
        firm_pattern = re.compile(re.escape(firm_name), re.IGNORECASE)
        matched = bool(firm_pattern.search(page_text))
        result["checks"]["firm_name"] = {
            "pass": matched,
            "description": "Firm name must appear in the Terms of Service page",
            "detail": (
                f"✓ Firm name '{firm_name}' found."
                if matched
                else f"✗ Firm name '{firm_name}' not found."
            ),
        }

    # ── Required phrase checks ────────────────────────────────────────────────
    privacy_link_href = None
    try:
        privacy_links = driver.find_elements(
            By.CSS_SELECTOR, "a[href*='privacy' i], a[title*='privacy' i]"
        )
        if privacy_links:
            privacy_link_href = privacy_links[0].get_attribute("href")
    except Exception:
        pass

    for rule in TOS_REQUIRED_CHECKS:
        key  = rule["key"]
        desc = rule["description"]
        pat  = rule["pattern"]

        if key == "privacy_policy_link":
            passed = bool(privacy_link_href)
            result["checks"][key] = {
                "pass": passed,
                "description": desc,
                "detail": (
                    f"✓ Privacy Policy link found: {privacy_link_href}"
                    if passed
                    else "✗ No Privacy Policy link found on the ToS page."
                ),
                "href": privacy_link_href,
            }
            continue

        if pat is None:
            continue

        matched = bool(pat.search(page_text))
        result["checks"][key] = {
            "pass": matched,
            "description": desc,
            "detail": (
                "✓ Found on page."
                if matched
                else f"✗ Not found on page."
            ),
        }

    # ── SMS / text keyword check ──────────────────────────────────────────────
    sms_matched = bool(SMS_KEYWORD_PATTERN.search(page_text))
    result["checks"]["sms_keyword"] = {
        "pass": sms_matched,
        "description": 'Must include "SMS", "text messages", "text", or "Msg" (any are acceptable)',
        "detail": (
            "✓ SMS-related keyword found."
            if sms_matched
            else "✗ No SMS/text/Msg keyword found on the ToS page."
        ),
    }

    return result


# ══════════════════════════════════════════════════════════════════════════════
#  PRIVACY POLICY PAGE VALIDATOR
# ══════════════════════════════════════════════════════════════════════════════


def validate_privacy_page(driver, privacy_url: str) -> dict:
    """
    Navigate to the Privacy Policy URL, validate its title and required content.
    Returns a structured dict with all check results.
    """
    result = {
        "url": privacy_url,
        "checks": {},
        "page_text_snapshot": "",
    }

    logger.info("Navigating to Privacy Policy page: %s", privacy_url)
    try:
        driver.get(privacy_url)
        time.sleep(PAGE_SETTLE)
    except Exception as e:
        result["error"] = f"Could not load Privacy Policy page: {e}"
        return result

    # ── Title check ───────────────────────────────────────────────────────────
    try:
        page_title = driver.title or ""
        h1_text = ""
        try:
            h1s = driver.find_elements(By.TAG_NAME, "h1")
            if h1s:
                h1_text = h1s[0].text.strip()
        except Exception:
            pass

        EXPECTED_PRIVACY_TITLE = re.compile(r"privacy\s+policy", re.IGNORECASE)
        title_pass = bool(
            EXPECTED_PRIVACY_TITLE.search(page_title) or EXPECTED_PRIVACY_TITLE.search(h1_text)
        )
        result["checks"]["page_title"] = {
            "pass": title_pass,
            "description": 'Page must be titled "Privacy Policy"',
            "detail": (
                f"✓ Title '{page_title}' / H1 '{h1_text}' matches 'Privacy Policy'."
                if title_pass
                else f"✗ Title '{page_title}' / H1 '{h1_text}' does not match 'Privacy Policy'."
            ),
            "page_title": page_title,
            "h1_text": h1_text,
        }
    except Exception as e:
        result["checks"]["page_title"] = {"pass": False, "detail": str(e)}

    # ── Get full visible page text ─────────────────────────────────────────────
    page_text = ""
    try:
        body = driver.find_element(By.TAG_NAME, "body")
        page_text = body.text or ""
        result["page_text_snapshot"] = page_text[:500]
    except Exception:
        pass

    # ── No mobile info shared with third parties ──────────────────────────────
    no_mobile_sharing = bool(NO_MOBILE_SHARING_PATTERN.search(page_text))
    result["checks"]["no_mobile_info_shared"] = {
        "pass": no_mobile_sharing,
        "description": (
            'Must state "no mobile information will be shared with third parties/affiliates '
            'for marketing/promotional purposes"'
        ),
        "detail": (
            "✓ Statement found."
            if no_mobile_sharing
            else "✗ Statement not found. Required: no mobile information will be shared with third parties."
        ),
    }

    # ── Third-party sharing section — check for SMS opt-in disclaimer if needed ──
    mentions_third_party_sharing = bool(THIRD_PARTY_SHARING_PATTERN.search(page_text))
    has_sms_disclaimer = bool(SMS_OPT_IN_DISCLAIMER.search(page_text))

    if mentions_third_party_sharing:
        result["checks"]["sms_opt_in_disclaimer"] = {
            "pass": has_sms_disclaimer,
            "description": (
                "Since the policy mentions sharing data with third parties, it must include the "
                "SMS opt-in disclaimer: "
                '"All the above categories exclude text messaging originator opt-in data and consent; '
                "this information will not be shared with any third parties, excluding aggregators "
                'and providers of the Text Message services."'
            ),
            "detail": (
                "✓ SMS opt-in disclaimer found."
                if has_sms_disclaimer
                else (
                    "✗ Policy mentions third-party sharing but is missing the required SMS opt-in "
                    "data disclaimer. Add: 'All the above categories exclude text messaging originator "
                    "opt-in data and consent; this information will not be shared with any third "
                    "parties, excluding aggregators and providers of the Text Message services.'"
                )
            ),
            "third_party_sharing_detected": True,
        }
    else:
        result["checks"]["sms_opt_in_disclaimer"] = {
            "pass": True,  # Not required if no third-party sharing mentioned
            "description": "SMS opt-in disclaimer (only required if policy mentions third-party sharing)",
            "detail": "ℹ No third-party sharing language detected — disclaimer not required.",
            "third_party_sharing_detected": False,
        }

    return result


# ══════════════════════════════════════════════════════════════════════════════
#  OVERALL PASS CALCULATION
# ══════════════════════════════════════════════════════════════════════════════

def compute_overall_pass(result: dict) -> bool:
    """Walk all 'pass' values in all check sections and return True only if all pass."""
    all_checks = []

    def collect(obj):
        if isinstance(obj, dict):
            if "pass" in obj and not isinstance(obj["pass"], dict):
                p = obj["pass"]
                if p is not None:
                    all_checks.append(bool(p))
            for v in obj.values():
                collect(v)
        elif isinstance(obj, list):
            for item in obj:
                collect(item)

    collect(result.get("checks", {}))
    if result.get("tos_page"):
        collect(result["tos_page"].get("checks", {}))
    if result.get("privacy_page"):
        collect(result["privacy_page"].get("checks", {}))

    return all(all_checks) if all_checks else False


# ══════════════════════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════════════════════

def create_driver() -> webdriver.Chrome:
    options = webdriver.ChromeOptions()
    options.page_load_strategy = PAGE_LOAD_STRATEGY
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--disable-extensions")
    options.add_argument("--remote-debugging-pipe")
    options.add_argument("--window-size=1920,1080")

    chrome_binary = os.getenv("CHROME_BINARY")
    if chrome_binary:
        options.binary_location = chrome_binary

    chromedriver_path = os.getenv("CHROMEDRIVER_PATH")
    service = Service(executable_path=chromedriver_path) if chromedriver_path else Service()
    driver = webdriver.Chrome(service=service, options=options)
    driver.set_page_load_timeout(PAGE_LOAD_TIMEOUT)
    return driver


def scan_url(url: str) -> dict:
    """Scan a URL and return the structured compliance result."""
    try:
        driver = create_driver()
    except Exception as exc:
        return {
            "url": url,
            "firm_name_detected": None,
            "overall_pass": False,
            "error": f"Failed to start Chrome scanner: {exc}",
            "checks": {},
        }

    try:
        logger.info("Opening scan URL: %s", url)
        driver.get(url)
        time.sleep(PAGE_SETTLE)

        firm_name = extract_firm_name(driver, url)
        logger.info("Firm name detected: %s", firm_name)

        sf = find_contact_form(driver)

        if not sf:
            output = {
                "url": url,
                "firm_name_detected": firm_name,
                "overall_pass": False,
                "error": "No contact form found on this page.",
                "checks": {},
            }
        else:
            if sf.source != "main page":
                try:
                    all_iframes = driver.find_elements(By.TAG_NAME, "iframe")
                    for iframe in all_iframes:
                        src = iframe.get_attribute("src") or ""
                        if src and src[:80] in sf.source:
                            driver.switch_to.frame(iframe)
                            time.sleep(IFRAME_SETTLE)
                            forms = driver.find_elements(By.TAG_NAME, "form")
                            if forms:
                                best = max(
                                    (score_form(f, driver) for f in forms),
                                    key=lambda x: x.score,
                                    default=None,
                                )
                                if best:
                                    sf.element = best.element
                            break
                except Exception:
                    pass

            output = validate_form(sf, driver, firm_name, url)

            driver.switch_to.default_content()
            driver.get(url)
            time.sleep(PAGE_SETTLE)
            consent_links = {"privacy_policy": None, "terms_of_service": None}
            try:
                forms = driver.find_elements(By.TAG_NAME, "form")
                if forms:
                    best_sf = max(
                        (score_form(f, driver) for f in forms),
                        key=lambda x: x.score,
                        default=None,
                    )
                    if best_sf and best_sf.score >= MIN_SCORE:
                        cb = find_consent_block(best_sf.element, driver)
                        consent_links = cb["links"]
            except Exception:
                pass

            tos_url = consent_links.get("terms_of_service")
            privacy_url = consent_links.get("privacy_policy")

            if tos_url:
                logger.info("Terms of Service URL: %s", tos_url)
                output["tos_page"] = validate_tos_page(driver, tos_url, firm_name)
            else:
                output["tos_page"] = {
                    "url": None,
                    "error": "No Terms of Service link found in the consent block.",
                    "checks": {
                        "page_reachable": {
                            "pass": False,
                            "description": "Terms of Service page must be linked and reachable",
                            "detail": "✗ No Terms of Service URL found in the form consent block.",
                        }
                    },
                }

            if privacy_url:
                logger.info("Privacy Policy URL: %s", privacy_url)
                output["privacy_page"] = validate_privacy_page(driver, privacy_url)
            else:
                output["privacy_page"] = {
                    "url": None,
                    "error": "No Privacy Policy link found in the consent block.",
                    "checks": {
                        "page_reachable": {
                            "pass": False,
                            "description": "Privacy Policy page must be linked and reachable",
                            "detail": "✗ No Privacy Policy URL found in the form consent block.",
                        }
                    },
                }

        output["overall_pass"] = compute_overall_pass(output)
        return output

    finally:
        try:
            driver.quit()
        except Exception:
            pass


def main():
    url = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_URL
    output = scan_url(url)
    sys.stdout.buffer.write(json.dumps(output, indent=2, ensure_ascii=False).encode("utf-8"))
    sys.stdout.buffer.write(b"\n")


if __name__ == "__main__":
    main()
