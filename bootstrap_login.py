#!/usr/bin/env python3
"""
PASSO 1 — rode este script UMA VEZ, no seu computador (nao na nuvem).

Ele abre uma janela de verdade do Chrome. Voce faz o login normalmente
na sua conta do Foco Radical / focomarket ali dentro (usuario e senha
digitados por VOCE, na janela do navegador -- isso nunca passa por mim
nem fica salvo em lugar nenhum além dessa janela). O script so espera
voce terminar de logar e salva a "sessao" (os cookies), nao a senha.

Depois de rodar, ele imprime um texto grande no final. Copie ESSE TEXTO
INTEIRO e cole como o secret SESSION_STATE no seu repositorio do GitHub:

    Settings -> Secrets and variables -> Actions -> New repository secret
    Nome: SESSION_STATE  (ou SESSION_STATE_FOTOP, se rodou com "fotop")
    Valor: (cole o texto impresso)

Pre-requisitos (rode no terminal do seu PC, uma vez so):
    pip install playwright
    playwright install chromium

Como rodar:
    python bootstrap_login.py          -> Foco Radical  (secret SESSION_STATE)
    python bootstrap_login.py fotop    -> Fotop         (secret SESSION_STATE_FOTOP)

Na Fotop, marque "Permanecer logado" antes de clicar em Entrar -- assim
a sessao dura bem mais.
"""
import sys
from playwright.sync_api import sync_playwright
import base64
from pathlib import Path

SITES = {
    "foco": {
        "nome": "Foco Radical / focomarket",
        "login_url": "https://www.focomarket.com.br/site/login",
        "login_path": "site/login",
        "out_file": "storage_state.json",
        "secret": "SESSION_STATE",
    },
    "fotop": {
        "nome": "Fotop",
        "login_url": "https://dashboard.fotop.com/login",
        "login_path": "/login",
        "out_file": "storage_state_fotop.json",
        "secret": "SESSION_STATE_FOTOP",
    },
}


def main():
    key = sys.argv[1].lower() if len(sys.argv) > 1 else "foco"
    if key not in SITES:
        print(f"Site desconhecido: {key}. Use um destes: {', '.join(SITES)}")
        return
    site = SITES[key]
    LOGIN_URL = site["login_url"]
    OUT_FILE = Path(site["out_file"])

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()
        page.goto(LOGIN_URL)

        print("\n>>> Uma janela do Chrome abriu.")
        print(">>> Faca login normalmente na sua conta da " + site["nome"] + " ali dentro.")
        print(">>> Quando conseguir ver a lista de eventos, e so aguardar aqui.\n")

        try:
            page.wait_for_url(lambda url: site["login_path"] not in url, timeout=600_000)
        except Exception:
            print("Nao detectei o login em 10 minutos. Feche e rode de novo quando estiver pronto.")
            browser.close()
            return

        # da um tempinho pra pagina terminar de carregar depois do login
        page.wait_for_timeout(2000)
        context.storage_state(path=str(OUT_FILE))
        browser.close()

    encoded = base64.b64encode(OUT_FILE.read_bytes()).decode()

    print("\n" + "=" * 70)
    print("Login capturado com sucesso!")
    print("Copie TODO o texto abaixo (uma linha longa) e cole no secret")
    print(f"{site['secret']} do seu repositorio no GitHub:")
    print("=" * 70 + "\n")
    print(encoded)
    print("\n" + "=" * 70)
    print(f"(Tambem salvei uma copia local em {OUT_FILE.resolve()} -- pode apagar")
    print(" esse arquivo depois de copiar o texto acima, ele tem a mesma sessao.)")


if __name__ == "__main__":
    main()
