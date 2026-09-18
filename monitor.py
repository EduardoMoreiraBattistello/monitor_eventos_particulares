#!/usr/bin/env python3
"""
Monitor de vagas -- Foco Radical / focomarket.com.br (Rio Grande do Sul)

Roda periodicamente (via GitHub Actions) e avisa por e-mail quando:
  - aparece um evento novo na lista; ou
  - um evento que estava com "Vagas Esgotadas" volta a ficar disponivel.

Nao faz login a cada execucao: reaproveita uma sessao ja autenticada,
salva previamente pelo bootstrap_login.py e guardada no secret
SESSION_STATE. Isso e so um "refresh de pagina" com um cookie valido,
nao um login repetido.

Se a sessao expirar (o site manda pra tela de login), o script avisa
por e-mail e para -- ele NAO tenta logar sozinho de novo, porque nao
tem (e nao deve ter) a sua senha guardada em lugar nenhum.
"""
import os
import sys
import json
import base64
import smtplib
import ssl
from email.mime.text import MIMEText
from pathlib import Path
from datetime import datetime, timezone

from playwright.sync_api import sync_playwright

TARGET_URL = (
    "https://www.focomarket.com.br/competition/future"
    "?CompetitionSearch%5Bis_social%5D="
    "&CompetitionSearch%5Bis_official_coverage%5D=0"
    "&CompetitionSearch%5Blocation_priority%5D=0"
    "&CompetitionSearch%5Bis_spot%5D="
    "&CompetitionSearch%5Bname%5D="
    "&CompetitionSearch%5Bsport_id%5D="
    "&CompetitionSearch%5Bfuture_list_date_from%5D=18%2F09%2F2026"
    "&CompetitionSearch%5Bfuture_list_date_to%5D=31%2F12%2F2027"
    "&CompetitionSearch%5Bstate_id%5D=21"
    "&CompetitionSearch%5Bplace%5D="
    "&page=0"
)

STATE_FILE = Path("events.json")
STORAGE_STATE_FILE = Path("storage_state.json")

# extrai os eventos da pagina atual (mesma logica validada manualmente
# no dashboard original -- ver historico do projeto)
EXTRACT_JS = """
() => {
  const cards = Array.from(document.querySelectorAll('.card-event-widget'));
  return cards.map(card => {
    const idEl = card.querySelector('a.link-event');
    const id = idEl ? idEl.id.replace('link-event-', '') : null;
    const link = idEl ? idEl.href : null;
    const name = card.querySelector('.event-title-fc')?.textContent.trim() || '';
    const btn = card.querySelector('.event-button-fc');
    const btnText = btn ? btn.textContent.trim() : '';
    const btnClasses = btn ? btn.className : '';
    let status = 'aberta';
    if (btnClasses.includes('slots-sold-out')) status = 'esgotada';
    else if (btnClasses.includes('already-signed')) status = 'inscrito';
    else if (/espera/i.test(btnText)) status = 'lista_espera';
    const leftIcons = card.querySelectorAll('.left-card-column .icon-text-card');
    let sport = '';
    if (leftIcons[0]) sport = leftIcons[0].querySelector('.event-text-fc')?.textContent.trim() || '';
    const locEl = card.querySelector('.icon-text-card-location-fc');
    let city = '', state = '';
    if (locEl) {
      city = locEl.querySelector('.event-city-fc')?.textContent.trim() || '';
      state = (locEl.querySelector('.event-state-fc')?.textContent || '').replace('/', '').trim();
    }
    let date = '';
    const rightIcons = card.querySelectorAll('.right-card-column .icon-text-card');
    rightIcons.forEach(ic => {
      if (ic.querySelector('.fa-calendar-alt')) {
        date = ic.querySelector('.event-text-fc')?.textContent.trim() || '';
      }
    });
    return {id, name, date, city, state, sport, status, btnText, link};
  });
}
"""


def load_storage_state():
    encoded = os.environ.get("SESSION_STATE")
    if not encoded:
        print("ERRO: variavel SESSION_STATE nao definida (configure o secret no GitHub).", file=sys.stderr)
        sys.exit(1)
    STORAGE_STATE_FILE.write_bytes(base64.b64decode(encoded))


def click_next(page):
    next_li = page.query_selector("ul.pagination li.next")
    if not next_li:
        return False
    classes = next_li.get_attribute("class") or ""
    if "disabled" in classes:
        return False
    link = next_li.query_selector("a")
    if not link:
        return False
    link.click()
    page.wait_for_load_state("networkidle")
    return True


def scrape_all_events(page):
    page.goto(TARGET_URL, wait_until="networkidle")
    if "site/login" in page.url:
        return None  # sessao expirada

    all_events = []
    pages_seen = 0
    while True:
        all_events.extend(page.evaluate(EXTRACT_JS))
        pages_seen += 1
        if pages_seen > 20:  # trava de seguranca
            break
        if not click_next(page):
            break
    return all_events


def load_previous_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {}


def save_state(events_by_id):
    STATE_FILE.write_text(
        json.dumps(events_by_id, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def send_email(subject, body):
    host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    port = int(os.environ.get("SMTP_PORT", "465"))
    user = os.environ["SMTP_USER"]
    password = os.environ["SMTP_PASS"]
    to_addr = os.environ.get("SMTP_TO", user)

    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = user
    msg["To"] = to_addr

    context = ssl.create_default_context()
    with smtplib.SMTP_SSL(host, port, context=context) as server:
        server.login(user, password)
        server.sendmail(user, [to_addr], msg.as_string())


def main():
    load_storage_state()
    prev = load_previous_state()
    is_first_run = len(prev) == 0

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(storage_state=str(STORAGE_STATE_FILE))
        page = context.new_page()
        events = scrape_all_events(page)
        browser.close()

    if events is None:
        send_email(
            "Monitor Foco Radical: sessao expirou",
            "A sessao salva expirou e o monitor nao consegue mais acessar a lista de eventos.\n\n"
            "Rode o bootstrap_login.py de novo no seu computador e atualize o secret "
            "SESSION_STATE no GitHub (Settings > Secrets and variables > Actions).",
        )
        print("Sessao expirada. E-mail de aviso enviado.")
        return

    if not events:
        print("Nenhum evento encontrado na pagina -- pode ser falha de carregamento. Nao mexi no estado salvo.")
        return

    now = datetime.now(timezone.utc).isoformat()
    current = {}
    alerts = []

    for ev in events:
        eid = ev["id"]
        current[eid] = {**ev, "last_seen": now}
        prev_ev = prev.get(eid)
        if prev_ev is None:
            current[eid]["first_seen"] = now
            if not is_first_run:
                alerts.append(
                    f"NOVO EVENTO: {ev['name']} -- {ev['city']}/{ev['state']} -- {ev['date']}\n{ev['link']}"
                )
        else:
            current[eid]["first_seen"] = prev_ev.get("first_seen", now)
            if prev_ev.get("status") == "esgotada" and ev["status"] != "esgotada":
                alerts.append(
                    f"VAGA LIBERADA: {ev['name']} -- {ev['city']}/{ev['state']} -- {ev['date']}\n{ev['link']}"
                )

    save_state(current)

    if is_first_run:
        print(f"Primeira execucao: {len(current)} eventos salvos como estado inicial (sem alertas).")
    elif alerts:
        body = (
            f"Encontrei {len(alerts)} novidade(s) na lista de eventos do Foco Radical (RS):\n\n"
            + "\n\n".join(alerts)
        )
        send_email(f"Foco Radical: {len(alerts)} novidade(s)", body)
        print(f"Enviado e-mail com {len(alerts)} alerta(s).")
    else:
        print("Nenhuma novidade.")


if __name__ == "__main__":
    main()
