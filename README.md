# Curation HAL — Appli Streamlit

## Ce que fait l'appli

Reprend la logique de ton script "Script curation v3" en mode "par date/collection" :
- interroge l'API HAL sur une collection et une période données,
- détecte : DOI manquant, article sans résumé, éditeur scientifique absent (chapitres),
  revue invalide, auteurs sans affiliation, doublons potentiels, langue suspecte,
- affiche les résultats dans un tableau, avec export CSV.

Le mode "upload de fichiers TXT" du script original n'a pas été repris (sur ta demande),
pour garder l'appli simple. On peut le rajouter plus tard si besoin.

## Tester en local

```bash
pip install -r requirements.txt
streamlit run app.py
```

Ça ouvre l'appli dans ton navigateur à l'adresse http://localhost:8501

## Partager l'appli en ligne (gratuit, recommandé) : Streamlit Community Cloud

1. Crée un dépôt GitHub (public ou privé) et mets-y `app.py` et `requirements.txt`.
2. Va sur https://share.streamlit.io et connecte-toi avec ton compte GitHub.
3. Clique sur "New app", choisis ton dépôt, ta branche, et indique `app.py` comme
   fichier principal.
4. Clique sur "Deploy". Au bout de quelques minutes, tu obtiens une URL du type
   `https://ton-app.streamlit.app` que tu peux partager à n'importe qui.

C'est tout — pas de serveur à gérer, et l'appli se redéploie automatiquement à
chaque fois que tu modifies le code sur GitHub.

## Pour aller plus loin (si tu veux)

- Réintégrer le mode "upload de fichiers TXT" (avec `st.file_uploader`).
- Mettre en cache les résultats d'une recherche (`st.cache_data`) pour éviter de
  re-requêter l'API HAL si tu relances la même période.
- Ajouter un filtre par type de document ou par type de problème détecté.
- Protéger l'accès par mot de passe si tu ne veux pas que l'appli soit publique
  (Streamlit Community Cloud permet de la rendre privée, visible seulement par
  les comptes que tu autorises).
