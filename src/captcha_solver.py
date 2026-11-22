import os
from urllib.parse import urlparse, parse_qs
from twocaptcha import TwoCaptcha

class CaptchaManager:
    def __init__(self):
        api_key = os.getenv("TWOCAPTCHA_API_KEY")
        self.solver = TwoCaptcha(api_key) if api_key else None

    def resolver_se_necessario(self, page) -> bool:
        if not self.solver:
            return False

        url_atual = page.url

        # Cloudflare Turnstile (Indeed)
        turnstile = page.locator("[data-sitekey], .cf-turnstile").first
        if turnstile.count() > 0:
            sitekey = turnstile.get_attribute("data-sitekey")
            if sitekey:
                res = self.solver.turnstile(sitekey=sitekey, url=url_atual)
                token = res["code"]
                page.evaluate(f"""
                    document.querySelectorAll('[name="cf-turnstile-response"], [name="g-recaptcha-response"]')
                        .forEach(el => el.value = '{token}');
                """)
                page.wait_for_timeout(2000)
                return True

        # Google reCAPTCHA v2 (Gupy / Sólides)
        recaptcha = page.locator("iframe[src*='recaptcha']").first
        if recaptcha.count() > 0:
            src = recaptcha.get_attribute("src")
            sitekey = parse_qs(urlparse(src).query).get("k", [None])[0]
            if sitekey:
                res = self.solver.recaptcha(sitekey=sitekey, url=url_atual)
                token = res["code"]
                page.evaluate(f"""
                    const el = document.getElementById('g-recaptcha-response');
                    if (el) {{
                        el.style.display = 'block';
                        el.value = '{token}';
                    }}
                """)
                page.wait_for_timeout(2000)
                return True

        return False