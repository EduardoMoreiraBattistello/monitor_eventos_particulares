#!/usr/bin/env python3
"""
Monitor de vagas -- Fotop (dashboard.fotop.com), Rio Grande do Sul

Mesmo esquema do monitor.py (Foco Radical): roda no GitHub Actions,
reaproveita uma sessao ja logada (secret SESSION_STATE_FOTOP, gerado com
`python bootstrap_login.py fotop`) e avisa por e-mail quando:
  - aparece um evento novo na lista de proximos eventos do RS; ou
  - um evento que estava Esgotado / Em breve / sob analise passa a
    aceitar inscricao (botao "Participar").

Os alertas vao so pro e-mail principal (SMTP_TO). Diferente do monitor da
Foco Radical, aqui NAO tem copia atrasada pro SMTP_TO_ATRASADO.

A lista da Fotop vem pronta no HTML, sem paginacao, e o filtro de estado
vai direto na URL -- entao uma unica carga de pagina basta.

Se a sessao expirar (o site manda pra /login), avisa por e-mail e para.
Nunca tenta logar sozinho.
"""
import os
import sys
import json
import base64
from pathlib import Path
from datetime import datetime, timezone

from playwright.sync_api import sync_playwright

# reaproveita o envio de e-mail do monitor da Foco Radical
from monitor import send_email

BASE_URL = "https://dashboard.fotop.com"
TARGET_URL = (
    f"{BASE_URL}/eventos/proximos/"
    "?busca="
    "&pais=31"                    # Brasil
    "&ufs_selecionadas=RS"
    "&internacional=nao"
    "&cidades_selecionadas="
    "&categoria=Categoria"        # todas as categorias
    "&marketplace=todos"          # Marketplace Fotop + eventos de parceiros
    "&vagas=todos"                # inclui esgotados, pra detectar quando liberam
)

STATE_FILE = Path("events_fotop.json")
STORAGE_STATE_FILE = Path("storage_state_fotop.json")

# status considerados "da pra se inscrever"
STATUS_ABERTOS = {"aberta"}

EXTRACT_JS = """
() => {
  const items = Array.from(document.querySelectorAll('.item-evento'));
  return items.map(it => {
    const id = it.querySelector('a[name]')?.getAttribute('name') || null;

    // "344581 - Nome do evento" (eventos exclusivos vem com um "E" na frente)
    let rawName = (it.querySelector('.nome-evento-painel')?.textContent || '')
      .replace(/\\s+/g, ' ').trim();
    let name = rawName.replace(/^E\\s+(?=\\d)/, '');
    if (id) name = name.replace(new RegExp('^' + id + '\\\\s*-\\\\s*'), '');

    // "31/10   Passo Fundo, Passo Fundo - Passo Fundo / RS"
    const localData = (it.querySelector('.local-data-evento')?.textContent || '')
      .replace(/\\s+/g, ' ').trim();
    const m = localData.match(/^(\\d{2}\\/\\d{2})\\s*(.*)$/);
    const dayMonth = m ? m[1] : '';
    const place = m ? m[2] : localData;

    // ano vem do cabecalho do mes ("Novembro 2026")
    const monthHeader = (it.closest('.panel')?.querySelector('.panel-heading')?.textContent || '')
      .replace(/\\s+/g, ' ').trim();
    const year = (monthHeader.match(/(\\d{4})/) || [])[1] || '';
    const date = dayMonth && year ? dayMonth + '/' + year : dayMonth;

    const fullText = it.textContent.replace(/\\s+/g, ' ');
    const abertura = (fullText.match(/Abertura das vagas:\\s*([\\d\\/]+\\s+[\\d:]+)/) || [])[1] || '';

    const btn = it.querySelector('button.btn-acao-evento');
    const btnText = btn ? btn.textContent.replace(/\\s+/g, ' ').trim() : '';
    const btnClasses = btn ? btn.className : '';
    let status;
    if (!btn) status = 'sob_analise';
    else if (btnClasses.includes('btn-esgotado')) status = 'esgotada';
    else if (btnClasses.includes('btn-abandonar')) status = 'inscrito';
    else if (btnClasses.includes('btn-evt-breve')) status = 'em_breve';
    else if (btnClasses.includes('btn-participar')) status = 'aberta';
    else status = 'outro';

    return {id, name, date, place, abertura, status, btnText};
  });
}
"""


def load_storage_state():
    encoded = os.environ.get("SESSION_STATE_FOTOP")
    if not encoded:
        # sai com sucesso pra nao ficar falhando (e mandando e-mail do
        # GitHub) enquanto o secret ainda nao foi configurado
        print("SESSION_STATE_FOTOP nao definido -- configure o secret no GitHub. Nada a fazer.")
        sys.exit(0)
    STORAGE_STATE_FILE.write_bytes(base64.b64decode(encoded))


def scrape_events(page):
    page.goto(TARGET_URL, wait_until="networkidle")
    if "/login" in page.url:
        return None  # sessao expirada
    return page.evaluate(EXTRACT_JS)


def load_previous_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {}


def save_state(events_by_id):
    STATE_FILE.write_text(
        json.dumps(events_by_id, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def describe(ev):
    line = f"{ev['name']} -- {ev['place']} -- {ev['date']}"
    if ev.get("abertura") and ev["status"] != "aberta":
        line += f"\nAbertura das vagas: {ev['abertura']}"
    line += f"\nStatus: {ev['btnText'] or ev['status']}"
    line += f"\n{BASE_URL}/eventos/proximos#{ev['id']}"
    return line


def main():
    load_storage_state()
    prev = load_previous_state()
    is_first_run = len(prev) == 0

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(storage_state=str(STORAGE_STATE_FILE))
        page = context.new_page()
        events = scrape_events(page)
        browser.close()

    if events is None:
        send_email(
            "Monitor Fotop: sessao expirou",
            "A sessao salva da Fotop expirou e o monitor nao consegue mais acessar a lista de eventos.\n\n"
            "Rode `python bootstrap_login.py fotop` de novo no seu computador e atualize o secret "
            "SESSION_STATE_FOTOP no GitHub (Settings > Secrets and variables > Actions).",
        )
        print("Sessao expirada. E-mail de aviso enviado.")
        return

    events = [e for e in events if e.get("id")]
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
                alerts.append("NOVO EVENTO: " + describe(ev))
        else:
            current[eid]["first_seen"] = prev_ev.get("first_seen", now)
            was_open = prev_ev.get("status") in STATUS_ABERTOS | {"inscrito"}
            if not was_open and ev["status"] in STATUS_ABERTOS:
                alerts.append("VAGA LIBERADA: " + describe(ev))

    save_state(current)

    if is_first_run:
        print(f"Primeira execucao: {len(current)} eventos salvos como estado inicial (sem alertas).")
    elif alerts:
        body = (
            f"Encontrei {len(alerts)} novidade(s) na lista de proximos eventos da Fotop (RS):\n\n"
            + "\n\n".join(alerts)
        )
        subject = f"Fotop: {len(alerts)} novidade(s)"
        # so pro e-mail principal (SMTP_TO) -- sem copia atrasada na Fotop
        send_email(subject, body)
        print(f"Enviado e-mail com {len(alerts)} alerta(s).")
    else:
        print("Nenhuma novidade.")


if __name__ == "__main__":
    main()
