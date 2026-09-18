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
    Nome: SESSION_STATE
    Valor: (cole o texto impresso)

Pre-requisitos (rode no terminal do seu PC, uma vez so):
    pip install playwright
    playwright install chromium

Como rodar:
    python bootstrap_login.py
"""
from playwright.sync_api import sync_playwright
import base64
from pathlib import Path

LOGIN_URL = "https://www.focomarket.com.br/site/login"
OUT_FILE = Path("storage_state.json")


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()
        page.goto(LOGIN_URL)

        print("\n>>> Uma janela do Chrome abriu.")
        print(">>> Faca login normalmente na sua conta do Foco Radical ali dentro.")
        print(">>> Quando conseguir ver a lista de eventos, e so aguardar aqui.\n")

        try:
            page.wait_for_url(lambda url: "site/login" not in url, timeout=600_000)
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
    print("SESSION_STATE do seu repositorio no GitHub:")
    print("=" * 70 + "\n")
    print(encoded)
    print("\n" + "=" * 70)
    print(f"(Tambem salvei uma copia local em {OUT_FILE.resolve()} -- pode apagar")
    print(" esse arquivo depois de copiar o texto acima, ele tem a mesma sessao.)")


if __name__ == "__main__":
    main()
