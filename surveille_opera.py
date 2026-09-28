#!/usr/bin/env python3
"""
Vérifie UNE fois la bourse de revente de l'Opéra de Paris (L'Histoire de Manon)
et envoie un mail si un nouveau billet est mis en vente pour la date choisie.
Conçu pour être lancé toutes les 5 min par GitHub Actions.

Variables d'environnement (à définir dans les Secrets du dépôt) :
  GMAIL_EXPEDITEUR    ton adresse Gmail
  GMAIL_APP_PASSWORD  mot de passe d'application Gmail (16 caractères)
  DESTINATAIRES       adresse(s) à prévenir, séparées par des virgules

Test local sans mail :  python3 surveille_opera.py --essai --date 01.10.2026
"""
import argparse
import html
import json
import os
import re
import smtplib
import ssl
from datetime import datetime, date as date_cls
from email.message import EmailMessage
from pathlib import Path
from urllib.request import Request, urlopen

DATE_CIBLE = "15.10.2026"  # format JJ.MM.AAAA, comme sur le site
URL = ("https://bourse.operadeparis.fr/selection/event/date"
       "?productId=10229120931474&lang=en")
SITE = "https://bourse.operadeparis.fr"
FICHIER_ETAT = Path(__file__).with_name("etat_opera.json")
ECHECS_AVANT_ALERTE = 6  # ~30 min d'erreurs d'affilée -> mail d'alerte à l'expéditeur

DATE_RE = re.compile(r"\b\d{2}\.\d{2}\.\d{4}\b")


def log(msg):
    print(f"[{datetime.now():%d/%m %H:%M:%S}] {msg}", flush=True)


def lire_page():
    req = Request(URL, headers={
        "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/128.0 Safari/537.36"),
        "Accept-Language": "en,fr;q=0.8",
    })
    with urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", errors="replace")


def analyser(page, date):
    """Renvoie (nb_billets, lien) pour la date, ou None si la date est introuvable."""
    debut = page.find(date)
    if debut == -1:
        return None
    fin = next((m.start() for m in DATE_RE.finditer(page, debut)
                if m.group() != date), len(page))
    bloc = page[debut:fin]

    texte = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", bloc)))
    m = re.search(r"(\d+)\s*(?:tickets?|billets?)\b", texte, re.I)
    nb = int(m.group(1)) if m else 0

    lien = None
    m_lien = re.search(r'href="([^"]*resale/item\?[^"]*)"', bloc)
    if m_lien:
        lien = html.unescape(m_lien.group(1))
        if lien.startswith("/"):
            lien = SITE + lien
        nb = max(nb, 1)
    return nb, lien


def envoyer_mail(sujet, corps, destinataires):
    expediteur = os.environ["GMAIL_EXPEDITEUR"]
    msg = EmailMessage()
    msg["From"] = expediteur
    msg["To"] = ", ".join(destinataires)
    msg["Subject"] = sujet
    msg.set_content(corps)
    with smtplib.SMTP_SSL("smtp.gmail.com", 465,
                          context=ssl.create_default_context()) as s:
        s.login(expediteur, os.environ["GMAIL_APP_PASSWORD"].replace(" ", ""))
        s.send_message(msg)


def destinataires():
    return [a.strip() for a in os.environ["DESTINATAIRES"].split(",") if a.strip()]


def charger_etat():
    try:
        return json.loads(FICHIER_ETAT.read_text())
    except Exception:
        return {}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--date", default=DATE_CIBLE)
    p.add_argument("--essai", action="store_true", help="sans mail ni sauvegarde")
    p.add_argument("--test-mail", action="store_true", help="envoie un mail de test")
    args = p.parse_args()

    if args.test_mail:
        envoyer_mail("Test surveillance Opéra",
                     "Si tu lis ceci, les alertes fonctionnent 🎉", destinataires())
        log("Mail de test envoyé.")
        return

    j, m, a = map(int, args.date.split("."))
    if date_cls.today() > date_cls(a, m, j):
        log("La représentation est passée : surveillance terminée.")
        return

    etat = charger_etat() if not args.essai else {}
    try:
        resultat = analyser(lire_page(), args.date)
        if resultat is None:
            raise ValueError(f"date {args.date} introuvable sur la page")
        nb, lien = resultat
        avant = etat.get(args.date, 0)
        log(f"{args.date} : {nb} billet(s) en vente (avant : {avant})")

        if nb > avant:
            sujet = f"🎭 Billet dispo pour L'Histoire de Manon le {args.date[:5].replace('.', '/')} !"
            corps = (f"{nb} billet(s) en revente pour la représentation du {args.date}.\n\n"
                     f"Voir les billets : {lien or URL}\n\n"
                     f"Page de la bourse : {URL}\n\n"
                     "Fais vite, ils partent en général rapidement !")
            if args.essai:
                log(f"[ESSAI] Mail qui serait envoyé :\n{sujet}\n{corps}")
            else:
                envoyer_mail(sujet, corps, destinataires())
                log("✅ Mail envoyé !")
        etat[args.date] = nb
        etat["echecs"] = 0
    except Exception as e:
        if args.essai:
            raise
        etat["echecs"] = etat.get("echecs", 0) + 1
        log(f"⚠️ Erreur ({etat['echecs']}) : {e}")
        if etat["echecs"] == ECHECS_AVANT_ALERTE:
            envoyer_mail("⚠️ Surveillance Opéra : problème",
                         f"La page n'est plus lisible depuis ~30 min : {e}\n{URL}",
                         [os.environ["GMAIL_EXPEDITEUR"]])

    if not args.essai:
        FICHIER_ETAT.write_text(json.dumps(etat, indent=2) + "\n")


if __name__ == "__main__":
    main()
