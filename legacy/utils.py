"""
utils.py — Anti-detection, logging, and config helpers.
"""

import logging
import random
import time
from datetime import date
from pathlib import Path

import yaml


def load_config(path: str = "config.yaml") -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def setup_logging(logs_dir: str = "logs") -> logging.Logger:
    Path(logs_dir).mkdir(exist_ok=True)
    log_file = Path(logs_dir) / f"{date.today().isoformat()}.log"

    logger = logging.getLogger("job-bot")
    logger.setLevel(logging.INFO)

    # Avoid duplicate handlers on re-import
    if not logger.handlers:
        fh = logging.FileHandler(log_file)
        fh.setLevel(logging.INFO)
        ch = logging.StreamHandler()
        ch.setLevel(logging.INFO)

        fmt = logging.Formatter(
            "%(asctime)s | %(levelname)-7s | %(message)s", datefmt="%H:%M:%S"
        )
        fh.setFormatter(fmt)
        ch.setFormatter(fmt)

        logger.addHandler(fh)
        logger.addHandler(ch)

    return logger


def human_delay(min_sec: int = 30, max_sec: int = 90):
    """Sleep for a random duration to mimic human behavior."""
    delay = random.uniform(min_sec, max_sec)
    time.sleep(delay)
    return delay


def take_break(pause_minutes: int = 7, variance: int = 3):
    """Take a longer break to avoid detection."""
    actual = random.uniform(
        max(1, pause_minutes - variance), pause_minutes + variance
    )
    time.sleep(actual * 60)
    return actual


def random_scroll(page):
    """Perform human-like scrolling on a Playwright page."""
    scroll_amount = random.randint(200, 600)
    page.mouse.wheel(0, scroll_amount)
    time.sleep(random.uniform(0.5, 1.5))


def random_mouse_move(page):
    """Move mouse to a random position to seem human."""
    x = random.randint(100, 800)
    y = random.randint(100, 500)
    page.mouse.move(x, y)
    time.sleep(random.uniform(0.2, 0.8))


def slow_type(element_or_page, text_or_selector: str, text: str = None):
    """Type text character-by-character with random delays.
    
    Can be called as:
        slow_type(locator, text)          — pass a Playwright Locator directly
        slow_type(page, selector, text)   — pass page + CSS selector
    """
    if text is None:
        # Called as slow_type(locator, text)
        element = element_or_page
        actual_text = text_or_selector
    else:
        # Called as slow_type(page, selector, text)
        element = element_or_page.locator(text_or_selector)
        actual_text = text

    element.click()
    for char in actual_text:
        element.press(char)
        time.sleep(random.uniform(0.05, 0.15))


def is_excluded_title(title: str, excluded_keywords: list[str]) -> bool:
    """Check if a job title contains excluded keywords."""
    title_lower = title.lower()
    for keyword in excluded_keywords:
        if keyword.lower() in title_lower:
            return True
    return False


def normalize_location(location: str) -> str:
    """Normalize location string for matching."""
    return location.strip().lower().replace(",", "").replace("  ", " ")


def matches_location(job_location: str, target_locations: list[str]) -> bool:
    """Check if job location matches any target location."""
    if not job_location:
        return False
    job_loc = normalize_location(job_location)
    for target in target_locations:
        if normalize_location(target) in job_loc:
            return True
    # Also accept "remote" / "work from home" / "wfh"
    remote_keywords = ["remote", "work from home", "wfh", "anywhere"]
    for kw in remote_keywords:
        if kw in job_loc:
            return True
    return False
