import os
from playwright.sync_api import sync_playwright

PORTAIS = [
    ("Sólides", "https://perfil.vagas.solides.com.br/applications?status=applied"),
    ("B2HR", "https://b2hr.empregare.com/pt-br/candidato/candidaturas"),
    ("Workday", "https://accenture.wd103.myworkdayjobs.com/pt-BR/AccentureCareers/userHome"),
    ("Cornerstone", "https://jacto.csod.com/ATS/careersite/ds.aspx?routename=ATS/CareerSite/MyProfile&c=jacto&site=1&lang=pt-BR"),
    ("LinkedIn", "https://www.linkedin.com/jobs-tracker/?stage=in-progress"),
]


def salvar_sessao():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(
            storage_state="auth_state.json" if os.path.exists("auth_state.json") else None
        )
        page = context.new_page()

        for nome, url in PORTAIS:
            print(f"\nAbrindo {nome}: {url}")
            page.goto(url, wait_until="domcontentloaded")
            input(f"👉 Faça login no(a) {nome} (se necessário) e pressione ENTER aqui quando carregar...")
            context.storage_state(path="auth_state.json")

        print("\n✅ Sessão de todos os portais salva com sucesso em 'auth_state.json'!")
        browser.close()


if __name__ == "__main__":
    salvar_sessao()
