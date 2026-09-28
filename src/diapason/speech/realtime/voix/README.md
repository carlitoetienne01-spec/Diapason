# Orion — référence synthétique masculine

Cet extrait a été créé localement le 27 septembre 2026 avec
`mlx-community/Qwen3-TTS-12Hz-1.7B-VoiceDesign-4bit`, via MLX Audio 0.5.6.
Il ne provient d'aucun micro et n'imite aucune personne désignée.
Carlito a ensuite choisi de conserver **uniquement la voix masculine** :
la référence féminine a été retirée, ainsi que le choix classique de Parler.

- `voix-posee-v2.wav` : Orion (ancien profil B), masculine et posée
  (graine 84, température 0,7). Le nom choisi par Carlito ne change ni la
  référence sonore ni l'identifiant technique `qwen3-b`.

24 kHz, mono, PCM16. Le premier essai B a été écarté parce qu'il ajoutait
un mot ; seul le second est inclus. Le texte est `TEXTE_REFERENCE` dans
`ouvrier_voix.py`. Le moteur Base reprend ce timbre sur les nouvelles
phrases ; il ne lance pas une nouvelle conception de voix à chaque tour.

Source du moteur : https://github.com/QwenLM/Qwen3-TTS
