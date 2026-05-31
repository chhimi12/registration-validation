"""Validation rule definitions for compliance checks.

Move selector patterns, phrase rules, and page content checks here so they can be managed
separately from the main scanning logic.
"""

import re

FIELD_SIGNALS = [
    ("phone",   "input[type='tel'], input[name*='phone' i], input[id*='phone' i], "
                "input[placeholder*='phone' i], input[data-q='phone'], .countryphone, "
                "input[aria-label*='phone' i]",                                        4),
    ("name",    "input[name*='name' i], input[id*='name' i], "
                "input[placeholder*='name' i], input[data-q*='name' i]",              2),
    ("email",   "input[type='email'], input[name*='email' i], "
                "input[id*='email' i], input[placeholder*='email' i]",                2),
    ("message", "textarea, input[name*='message' i], input[name*='comment' i], "
                "input[name*='description' i], input[name*='details' i]",             2),
    ("cta",     "button[type='submit'], input[type='submit'], button[type='button']", 1),
]

ATTORNEY_CTA_WORDS = re.compile(
    r"consult|free\s+case|get\s+help|contact\s+us|send\s+message|submit|case\s+review"
    r"|speak\s+to|talk\s+to|schedule|appointment|get\s+started|reach\s+out",
    re.IGNORECASE,
)

MULTI_FIELD_SELECTOR = "input:not([type='hidden']):not([type='submit']), textarea, select"

FORM_IFRAME_SRC_PATTERNS = re.compile(
    r"widget[/\-_]form|typeform|jotform|gravity|wufoo|cognito|123form"
    r"|formstack|paperform|tally\.so|leadconnector|msgsndr|apisystem"
    r"|link\.\w+\.law|go\.chilipiper|hubspot.*form|monday.*form"
    r"|salesforce.*form|zoho.*form|marketo|pardot|infusionsoft",
    re.IGNORECASE,
)

SMS_KEYWORD_PATTERN = re.compile(
    r"\b(SMS|text\s+messages?|texting|msg)\b",
    re.IGNORECASE,
)

REQUIRED_PHONE_PLACEHOLDER = re.compile(r"\*|required|mandatory", re.IGNORECASE)

PHONE_SELECTORS_BROAD = (
    "input[type='tel'], input[name*='phone' i], input[id*='phone' i], "
    "input[placeholder*='phone' i], input[data-q='phone'], .countryphone, "
    "input[aria-label*='phone' i]"
)

CONSENT_CHECKBOX_SELECTORS = (
    "input[type='checkbox'][name*='consent' i], "
    "input[type='checkbox'][name*='sms' i], "
    "input[type='checkbox'][name*='text' i], "
    "input[type='checkbox'][name*='agree' i], "
    "input[type='checkbox'][name*='terms' i], "
    "input[type='checkbox'][id*='consent' i], "
    "input[type='checkbox'][id*='sms' i]"
)

CONSENT_CHECKBOX_FALLBACK = "input[type='checkbox']"

LINK_SELECTORS = {
    "privacy_policy": "a[href*='privacy' i], a[title*='privacy' i]",
    "terms_of_service": (
        "a[href*='terms' i], a[href*='tos' i], a[href*='disclaimer' i], "
        "a[title*='terms' i]"
    ),
}

FORM_CONSENT_PHRASE_RULES = [
    {
        "key": "sms_keyword",
        "description": 'Must include "SMS", "text messages", "text", or "Msg" (interchangeable)',
        "pattern": SMS_KEYWORD_PATTERN,
    },
    {
        "key": "rates_apply",
        "description": 'Must include "Message and data rates may apply"',
        "pattern": re.compile(r"message\s+and\s+data\s+rates\s+may\s+apply", re.IGNORECASE),
    },
    {
        "key": "frequency_varies",
        "description": 'Must include "Message frequency varies"',
        "pattern": re.compile(r"message\s+frequency\s+varies", re.IGNORECASE),
    },
    {
        "key": "opt_out",
        "description": 'Must include "To opt-out, reply STOP. For help, reply HELP"',
        "pattern": re.compile(
            r"to\s+opt.?out.{0,20}reply\s+STOP.{0,40}reply\s+HELP", re.IGNORECASE
        ),
    },
]

TOS_REQUIRED_CHECKS = [
    {
        "key": "rates_apply",
        "description": 'Must include "Message and data rates may apply"',
        "pattern": re.compile(r"message\s+and\s+data\s+rates\s+may\s+apply", re.IGNORECASE),
    },
    {
        "key": "frequency_varies",
        "description": 'Must include "Message frequency varies"',
        "pattern": re.compile(r"message\s+frequency", re.IGNORECASE),
    },
    {
        "key": "client_intake_scheduling",
        "description": 'Must include "scheduling an initial call"',
        "pattern": re.compile(r"scheduling\s+an\s+initial\s+call", re.IGNORECASE),
    },
    {
        "key": "appointment_reminders",
        "description": 'Must include "appointment reminders"',
        "pattern": re.compile(r"appointment\s+reminders?", re.IGNORECASE),
    },
    {
        "key": "intake_followups",
        "description": 'Must include "intake follow-ups"',
        "pattern": re.compile(r"intake\s+follow.?ups?", re.IGNORECASE),
    },
    {
        "key": "esigning",
        "description": 'Must include "secure links for e-signing documents"',
        "pattern": re.compile(r"(secure\s+links?\s+for\s+e.?sign|e.?sign\w*\s+documents?)", re.IGNORECASE),
    },
    {
        "key": "cancel_anytime",
        "description": 'Must include "You can cancel the SMS service at any time"',
        "pattern": re.compile(r"(you\s+can\s+cancel|cancel\s+the\s+SMS\s+service).{0,30}any\s+time", re.IGNORECASE),
    },
    {
        "key": "stop_keyword",
        "description": 'Must include "STOP" (opt-out keyword)',
        "pattern": re.compile(r"\bSTOP\b"),
    },
    {
        "key": "confirm_unsubscribe",
        "description": 'Must include confirmation of unsubscription ("confirm")',
        "pattern": re.compile(r"\bconfirm\b", re.IGNORECASE),
    },
    {
        "key": "help_keyword",
        "description": 'Must include "HELP" (support keyword)',
        "pattern": re.compile(r"\bHELP\b"),
    },
    {
        "key": "carriers_not_liable",
        "description": 'Must include "Carriers are not liable for delayed or undelivered messages"',
        "pattern": re.compile(
            r"carriers?\s+are\s+not\s+liable\s+for\s+delayed\s+or\s+undelivered\s+messages?",
            re.IGNORECASE,
        ),
    },
    {
        "key": "privacy_policy_link",
        "description": "Must include a link to the Privacy Policy",
        "pattern": None,
    },
]

SMS_OPT_IN_DISCLAIMER = re.compile(
    r"text\s+messaging\s+originator\s+opt.in\s+data\s+and\s+consent"
    r"|opt.in\s+data\s+and\s+consent.{0,100}not\s+be\s+shared",
    re.IGNORECASE,
)

THIRD_PARTY_SHARING_PATTERN = re.compile(
    r"(share|disclose|sell|transfer|provide).{0,60}(third.part|affiliate|partner|vendor)",
    re.IGNORECASE,
)

NO_MOBILE_SHARING_PATTERN = re.compile(
    r"no\s+mobile\s+information\s+will\s+be\s+shared\s+with\s+third.part",
    re.IGNORECASE,
)

# ── Firm name extraction helpers ──────────────────────────────────────────────

# Patterns that strongly indicate a law firm name in structured markup
FIRM_NAME_SCHEMA_TYPES = re.compile(
    r"LegalService|LawFirm|Attorney|Lawyer|Organization",
    re.IGNORECASE,
)

# Common noise words to strip when cleaning a candidate firm name
FIRM_NAME_NOISE = re.compile(
    r"\b(LLC|LLP|PC|PLLC|PA|APC|Esq\.?|Attorney|Attorneys|Law\s+Firm|"
    r"Law\s+Office|Law\s+Group|Lawyers?|Legal|Group|Associates?|"
    r"Injury\s+Lawyers?|Trial\s+Lawyers?|Accident\s+Lawyers?)\b",
    re.IGNORECASE,
)

# Footer / about selectors that often contain the canonical firm name
FIRM_NAME_FOOTER_SELECTORS = [
    "footer [class*='logo' i]",
    "footer [class*='firm' i]",
    "footer [class*='brand' i]",
    "footer [class*='copyright' i]",
    "footer p",
    "[class*='footer-logo' i]",
    "[class*='site-logo' i] img",          # alt text
    "[class*='navbar-brand' i]",
    "[class*='site-title' i]",
    "[rel='author']",
]

# Copyright line pattern — captures the firm name after © YYYY
COPYRIGHT_FIRM_PATTERN = re.compile(
    r"©\s*\d{4}[\s\-–]+(.+?)(?:\.|,|All\s+Rights|LLC|LLP|PC|PLLC|\n|$)",
    re.IGNORECASE,
)