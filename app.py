# -*- coding: utf-8 -*-
"""
Application Streamlit — Repérage de problèmes potentiels sur des notices HAL

Reprend la logique du script "Script curation v3" (mode "par date/collection"),
avec une interface web à la place des widgets Colab.
"""

import re
import time
import datetime

import requests
import pandas as pd
import streamlit as st

# ============================================================================
# CONFIGURATION DE LA PAGE
# ============================================================================

st.set_page_config(
    page_title="Curation HAL",
    page_icon="🔎",
    layout="wide",
)

# ============================================================================
# DICTIONNAIRES (inchangés par rapport au script original)
# ============================================================================

DOCTYPE_LABELS = {
    'ART': 'Article',
    'COUV': 'Chapitre',
    'OUV': 'Ouvrage',
    'NOTICE': 'Notice de dictionnaire',
    'COMM': 'Communication',
    'UNDEFINED': 'Working Paper',
    'IMG': 'Image',
    'THESE': 'Thèse',
    'HDR': 'HDR',
    'POSTER': 'Poster',
    'REPORT': 'Rapport',
}

LANG_FLAGS = {
    'fr': '🇫🇷',
    'en': '🇬🇧',
    'de': '🇩🇪',
    'es': '🇪🇸',
    'it': '🇮🇹',
    'pt': '🇵🇹',
    'nl': '🇳🇱',
    'ru': '🇷🇺',
    'zh': '🇨🇳',
    'ja': '🇯🇵',
    'ar': '🇸🇦',
}

# ============================================================================
# PARTIE 1 : RÉCUPÉRATION DES NOTICES DEPUIS L'API HAL (PAR DATE)
# ============================================================================

def fetch_notices_by_date(date_from, date_to, collection, progress_callback=None):
    """
    Récupère toutes les notices soumises entre date_from et date_to
    dans la collection donnée.
    """
    date_str_from = date_from.strftime("%Y-%m-%dT00:00:00Z")
    date_str_to = date_to.strftime("%Y-%m-%dT23:59:59Z")
    query = f"releasedDate_tdate:[{date_str_from} TO {date_str_to}]"
    fq = f"collCode_s:{collection}"

    notices = []
    rows = 100
    start = 0
    total = None

    while True:
        url = (
            f"https://api.archives-ouvertes.fr/search"
            f"?q={requests.utils.quote(query)}"
            f"&fq={requests.utils.quote(fq)}"
            f"&fl=*&wt=json&rows={rows}&start={start}"
        )

        try:
            response = requests.get(url, timeout=15)
            response.raise_for_status()
            data = response.json()
        except Exception as e:
            st.error(f"⚠️ Erreur lors de la récupération : {e}")
            break

        docs = data.get('response', {}).get('docs', [])
        total = data.get('response', {}).get('numFound', 0)

        for doc in docs:
            hal_id = doc.get('halId_s', '')
            notices.append({
                'numero': str(len(notices) + 1),
                'hal_id': hal_id,
                'docid': str(doc.get('docid', '')),
                'url': f"https://hal.science/{hal_id}",
                'raw': '',
                '_prefetched_metadata': doc,
            })

        if progress_callback and total:
            progress_callback(min(len(notices) / total, 1.0), f"Récupération : {len(notices)}/{total} notices")

        start += rows
        if total is None or start >= total:
            break

        time.sleep(0.2)

    return notices, (total or 0)


# ============================================================================
# PARTIE 2 : REQUÊTES API HAL POUR LES MÉTADONNÉES
# ============================================================================

def fetch_hal_metadata(notice):
    """Les notices issues du mode date ont déjà leurs métadonnées préchargées."""
    if notice.get('_prefetched_metadata'):
        return notice['_prefetched_metadata']
    return None


def count_authors_without_affiliation(metadata):
    if not metadata:
        return None, None

    all_authors = metadata.get('authIdFormPerson_s', [])
    struct_with_auth = metadata.get('structHasAlphaAuthId_fs', [])

    authors_with_affiliation = set()
    for entry in struct_with_auth:
        match = re.search(r'_JoinSep_([^_]+)_FacetSep_', entry)
        if match:
            authors_with_affiliation.add(match.group(1))

    authors_without_affiliation = [a for a in all_authors if a not in authors_with_affiliation]

    return len(authors_without_affiliation), len(all_authors)


def search_duplicates(metadata, hal_id_base):
    if not metadata:
        return []

    titles = metadata.get('title_s', [])
    if not isinstance(titles, list):
        titles = [titles] if titles else []

    doi = metadata.get('doiId_s')
    if isinstance(doi, list):
        doi = doi[0] if doi else None

    qParts = []
    if doi:
        qParts.append(f'doiId_s:"{doi}"')

    for title in titles:
        if title:
            mots = re.sub(r'[()":!?,;\'\'-]', '', title)
            mots = ' '.join(mots.split()[:12])
            if mots:
                qParts.append(f'title_t:({mots})')

    if not qParts:
        return []

    query = ' OR '.join(qParts)
    url = f"https://api.archives-ouvertes.fr/search?q={requests.utils.quote(query)}&fl=halId_s,title_s,doiId_s&wt=json&rows=50"

    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()

        if not data.get('response', {}).get('docs'):
            return []

        duplicates = []
        for doc in data['response']['docs']:
            doc_halid = doc.get('halId_s', '')
            doc_halid_base = re.sub(r'v\d+$', '', doc_halid)
            doc_doi = doc.get('doiId_s')
            if isinstance(doc_doi, list):
                doc_doi = doc_doi[0] if doc_doi else None

            if doc_halid_base == hal_id_base:
                continue
            if doi and doc_doi and doc_doi != doi:
                continue

            duplicates.append({
                'halId': doc_halid,
                'title': doc.get('title_s', [''])[0] if isinstance(doc.get('title_s'), list) else doc.get('title_s', ''),
                'doi': doc_doi,
            })

        return duplicates

    except Exception:
        return []


# ============================================================================
# PARTIE 3 : FLAGGING
# ============================================================================

def flag_notice(metadata, notice):
    if not metadata:
        return ['❌ Notice non trouvée dans l\'API'], {'doc_type': 'UNKNOWN'}

    flags = []
    info = {}

    doc_type = metadata.get('docType_s', 'UNKNOWN')
    doc_type_label = DOCTYPE_LABELS.get(doc_type, doc_type)
    info['doc_type'] = doc_type_label
    doc_type_code = doc_type

    if doc_type_code == 'ART':
        doi = metadata.get('doiId_s')
        in_press = metadata.get('inPress_bool', False)
        domains = metadata.get('domain_s', [])
        journal = metadata.get('journalTitle_s', [])

        is_law = False
        if isinstance(domains, list):
            is_law = any('shs.droit' in domain for domain in domains)
        elif isinstance(domains, str):
            is_law = 'shs.droit' in domains

        info['doi'] = doi if doi else 'ABSENT'

        if not doi and not in_press and not is_law:
            flags.append(f"⚠️ Article sans DOI ({journal if journal else 'Journal inconnu'})")
        if doi and not metadata.get('abstract_s'):
            flags.append('⚠️ Article sans résumé (DOI disponible)')

    if doc_type_code == 'COUV':
        scientific_editor = metadata.get('scientificEditor_s')
        if scientific_editor:
            editor_text = scientific_editor
            if isinstance(editor_text, list):
                editor_text = ', '.join(editor_text)
            flags.append(f'✒️ Éditeur scientifique : {editor_text}')
        else:
            flags.append('❌ Éditeur scientifique absent')

    journal_valid = metadata.get('journalValid_s')
    if journal_valid == 'INCOMING':
        flags.append('⚠️ Revue invalide (INCOMING)')

    nb_without, total = count_authors_without_affiliation(metadata)
    if nb_without and nb_without > 0:
        flags.append(f'⚠️ {nb_without} auteur(s) sans affiliation sur {total}')

    hal_id_base = re.sub(r'v\d+$', '', notice['hal_id'])
    duplicates = search_duplicates(metadata, hal_id_base)

    display_title = ""
    titles_from_metadata = metadata.get('title_s')
    if isinstance(titles_from_metadata, list) and titles_from_metadata:
        display_title = titles_from_metadata[0]
    elif isinstance(titles_from_metadata, str):
        display_title = titles_from_metadata

    if duplicates:
        info['titre_notice'] = display_title
        flags.append(f'⚠️ {len(duplicates)} doublon(s) potentiel(s)')

    from langdetect import detect, LangDetectException

    declared_lang = metadata.get('language_s')
    if isinstance(declared_lang, list):
        declared_lang = declared_lang[0] if declared_lang else None
    title = metadata.get('title_s')
    if isinstance(title, list):
        title = title[0] if title else None

    if declared_lang and title and len(title) > 20:
        try:
            detected = detect(title)
            if detected != declared_lang:
                declared_flag = LANG_FLAGS.get(declared_lang, declared_lang)
                detected_flag = LANG_FLAGS.get(detected, detected)
                flags.append(f'⚠️ Langue suspecte : déclarée {declared_flag}, titre détecté {detected_flag}')
        except LangDetectException:
            pass

    return flags, info


def get_title(metadata):
    if not metadata:
        return ""
    title = metadata.get('title_s')
    if isinstance(title, list):
        return title[0] if title else ""
    return title or ""


# ============================================================================
# PARTIE 4 : ANALYSE COMPLÈTE
# ============================================================================

def analyze_notices(notices, progress_callback=None):
    rows = []
    total = len(notices)

    for i, notice in enumerate(notices, 1):
        metadata = fetch_hal_metadata(notice)
        flags, info = flag_notice(metadata, notice)

        rows.append({
            'N°': notice['numero'],
            'HAL ID': notice['hal_id'],
            'Type': info.get('doc_type', 'UNKNOWN'),
            'Titre': get_title(metadata),
            'Flags': flags,  # liste de chaînes, une par problème détecté
            'Nb problèmes': len(flags),
            'URL': notice['url'],
        })

        if progress_callback:
            progress_callback(i / total, f"Analyse : {i}/{total} notices")

        if not notice.get('_prefetched_metadata'):
            time.sleep(0.3)

    return pd.DataFrame(rows)


# ============================================================================
# INTERFACE STREAMLIT
# ============================================================================

st.title("🔎 Curation des notices HAL")
st.caption(
    "Repère automatiquement des problèmes potentiels sur les notices déposées "
    "dans une collection HAL (DOI manquant, éditeur scientifique absent, "
    "auteurs sans affiliation, doublons potentiels, langue suspecte...)."
)

with st.sidebar:
    st.header("Paramètres")

    collection = st.text_input(
        "Code de collection HAL",
        value="UNIV-PARIS1",
        help="Exemple : UNIV-PARIS1, CRHXIX...",
    )

    hier = datetime.date.today() - datetime.timedelta(days=1)
    date_from = st.date_input("Depuis le", value=hier)
    date_to = st.date_input("Jusqu'au", value=datetime.date.today())

    lancer = st.button("▶️ Lancer l'analyse", type="primary", use_container_width=True)

# On stocke les résultats dans session_state pour qu'ils survivent aux
# interactions suivantes (cocher une case, etc.), qui relancent le script
# mais ne doivent pas effacer la dernière analyse effectuée.
if "df" not in st.session_state:
    st.session_state.df = None
    st.session_state.total_found = None
    st.session_state.collection_label = None
    st.session_state.dates_label = None

if lancer:
    if date_from > date_to:
        st.error("La date de début doit être antérieure (ou égale) à la date de fin.")
    elif not collection.strip():
        st.error("Merci d'indiquer un code de collection.")
    else:
        progress_bar = st.progress(0.0, text="Démarrage...")

        def update_progress(fraction, text):
            progress_bar.progress(fraction, text=text)

        with st.spinner("Récupération des notices..."):
            notices, total_found = fetch_notices_by_date(
                date_from, date_to, collection.strip(), progress_callback=update_progress
            )

        if not notices:
            progress_bar.empty()
            st.info("ℹ️ Aucune notice trouvée pour cette période et cette collection.")
            st.session_state.df = None
        else:
            st.success(f"📋 {total_found} notice(s) trouvée(s). Analyse en cours...")
            df = analyze_notices(notices, progress_callback=update_progress)
            progress_bar.empty()

            # On sauvegarde le résultat pour qu'il reste affiché après ce rerun
            st.session_state.df = df
            st.session_state.total_found = total_found
            st.session_state.collection_label = collection.strip()
            st.session_state.dates_label = f"{date_from}_{date_to}"

# Affichage des résultats (issus soit de l'analyse qui vient de tourner,
# soit d'une analyse précédente toujours stockée en session)
if st.session_state.df is not None:
    df = st.session_state.df

    nb_problemes = (df['Nb problèmes'] > 0).sum()
    col1, col2, col3 = st.columns(3)
    col1.metric("Notices analysées", len(df))
    col2.metric("Avec problème(s)", int(nb_problemes))
    col3.metric("Sans problème", len(df) - int(nb_problemes))

    st.divider()

    only_flagged = st.checkbox("N'afficher que les notices avec un problème", value=True)
    display_df = df[df['Nb problèmes'] > 0] if only_flagged else df

    st.caption(f"{len(display_df)} notice(s) affichée(s)")

    for _, row in display_df.iterrows():
        with st.container(border=True):
            col_titre, col_lien = st.columns([5, 1])
            with col_titre:
                st.markdown(f"**[#{row['N°']}] {row['HAL ID']}** — *{row['Type']}*")
                if row['Titre']:
                    st.markdown(f"📄 {row['Titre']}")
            with col_lien:
                st.link_button("🔗 Voir la notice", row['URL'], use_container_width=True)

            if row['Flags']:
                for flag in row['Flags']:
                    st.markdown(f"- {flag}")
            else:
                st.markdown("✅ Aucun problème détecté")

    st.divider()

    csv_df = df.copy()
    csv_df['Problèmes détectés'] = csv_df['Flags'].apply(
        lambda fl: '\n'.join(fl) if fl else 'Aucun problème détecté'
    )
    csv = csv_df.drop(columns=['Flags', 'Nb problèmes']).to_csv(index=False).encode('utf-8-sig')
    st.download_button(
        "⬇️ Télécharger le rapport (CSV)",
        data=csv,
        file_name=f"curation_hal_{st.session_state.collection_label}_{st.session_state.dates_label}.csv",
        mime="text/csv",
    )
elif not lancer:
    st.info("Renseigne une collection et une période dans la barre latérale, puis clique sur **Lancer l'analyse**.")