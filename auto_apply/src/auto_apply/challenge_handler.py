"""Detect active challenges; never solve, hide, or bypass them."""
def _any_visible(locator):
    return any(locator.nth(i).is_visible() for i in range(locator.count()))

def detect_challenge(page):
    title = page.title().lower()
    if "just a moment" in title or "verify you are human" in title:
        return True
    selectors = (
        "#challenge-running",
        "iframe[src*='recaptcha/api2/bframe']",
        "iframe[src*='recaptcha/enterprise/bframe']",
        "text='Please verify you are a human'",
        "#email-verification",
    )
    if any(_any_visible(page.locator(selector)) for selector in selectors):
        return True
    turnstile = page.locator("div[class*='cf-turnstile'], iframe[src*='challenges.cloudflare.com']")
    if _any_visible(turnstile):
        # A visible widget may remain after success. A nonempty standard response
        # token is evidence of completion, not a reason to bypass the platform.
        tokens = page.locator("input[name='cf-turnstile-response']")
        if not any(tokens.nth(i).input_value().strip() for i in range(tokens.count())):
            return True
    return False

def handle_challenge(page, unattended=False):
    if not detect_challenge(page):
        return None
    if unattended:
        return "paused"
    while detect_challenge(page):
        print("Resolve the challenge in this browser window yourself.")
        if input("Press Enter to recheck, or type skip: ").strip().lower() == "skip":
            return "skipped"
        page.wait_for_timeout(250)
    return None
