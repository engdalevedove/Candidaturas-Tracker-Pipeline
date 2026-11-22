import os
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

load_dotenv()

CHROME_PATHS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
]

def _achar_chrome():
    for path in CHROME_PATHS:
        if os.path.exists(path):
            return path
    return None

def salvar_sessao():
    chrome_exe = _achar_chrome()
    with sync_playwright() as p:
        launch_args = {
            "user_data_dir": "./chrome_profile_real",
            "headless": False,
            "args": [
                "--start-maximized",
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
            ],
            "ignore_default_args": ["--enable-automation"],
        }
        if chrome_exe:
            launch_args["executable_path"] = chrome_exe

        context = p.chromium.launch_persistent_context(**launch_args)
        page = context.new_page()

        # Gupy já está via API (GUPY_COOKIE) — pulamos direto para Sólides e Indeed
        plataformas = [
            ("Sólides", "https://perfil.vagas.solides.com.br/applications?status=applied"),
            ("Indeed", "https://myjobs.indeed.com/applied"),
            ("b2hr", "https://b2hr.empregare.com/pt-br/candidato/candidaturas"),
            ("accenture", "https://accenture.wd103.myworkdayjobs.com/pt-BR/AccentureCareers/userHome"),
            ("jacto", "https://jacto.csod.com/ats/careersite/login.aspx?returnurl=%2fATS%2fcareersite%2fds.aspx%3froutename%3dATS%2fCareerSite%2fMyProfile%26c%3djacto%26site%3d1%26lang%3dpt-BR#loaded"),
            ("limkedin", "https://www.linkedin.com/my-items/saved-jobs/?cardType=APPLIED"),
        ]

        for nome, url in plataformas:
            print(f"\nAbrindo {nome}: {url}")
            page.goto(url, wait_until="domcontentloaded")
            input(f"👉 Faça login no(a) {nome} (se necessário) e pressione ENTER aqui quando carregar...")

        context.storage_state(path="auth_state.json")
        print("\n✅ Sessão salva em 'auth_state.json' para Sólides e Indeed!")
        context.close()

if __name__ == "__main__":
    salvar_sessao()