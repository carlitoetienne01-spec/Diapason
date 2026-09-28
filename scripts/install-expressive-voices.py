#!/usr/bin/env python3
"""Installation explicite de la voix masculine locale, sans toucher au venv produit."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

MODELE = "mlx-community/Qwen3-TTS-12Hz-1.7B-Base-4bit"
REVISION = "37e955a1deb861c088ae5f3a67043185f3d1a60c"
# 28/09/2026 : ce script tirait 2,3 Go de poids sans en vérifier un octet,
# quand install-mlx-recognition.py vérifie chacun des siens. La révision fixe
# ce qu'on DEMANDE, pas ce qui ARRIVE : un cache ou un miroir altéré aurait été
# chargé tel quel par l'ouvrier, et moteur_installe() l'aurait dit installé.
# Les deux poids viennent du champ lfs.oid de l'API Hugging Face pour REVISION ;
# les dix autres n'y ont qu'un sha1 git, confronté à la copie installée sur le
# Mac de Carlito avant d'en tirer le SHA-256 — les quatorze fichiers
# concordaient. Douze, pas trois : ce sont les motifs que mlx-audio lui-même
# télécharge (*.json, *.safetensors, *.txt). Son chargeur prend TOUT
# *.safetensors du dossier et AutoTokenizer lit vocab.json et merges.txt.
# README.md et .gitattributes, que rien ne lit, ne sont plus téléchargés
# (ni refusés à la racine d'une installation ancienne, voir plus bas).
EMPREINTES = {
    "config.json": "36477d07e2ac89f79c1410a9782ed69860fbfcc871edea1728624389072e25fd",
    "generation_config.json": (
        "f1b90b4513f3b34c62851049e2492d7b4c5940daf1276f89c82b8ef04127f3aa"
    ),
    "merges.txt": "599bab54075088774b1733fde865d5bd747cbcc7a547c5bc12610e874e26f5e3",
    "model.safetensors": (
        "ac973aa38ec79d4b4b52bf858948f0d47dd909aa4bcd383f5b900e277410fdb5"
    ),
    "model.safetensors.index.json": (
        "2b71cbd2c84cb59d0d71383cc55166ad7108180bfd7e47d2e3a6698f3721abfb"
    ),
    "preprocessor_config.json": (
        "efdde1022ea9d76928bf7a9cd53139138f5ba2e466e837f08f6105ab1af1c119"
    ),
    "speech_tokenizer/config.json": (
        "ee65bb901c876664ab8707c487157aa1a6ee57c65969b28fb5ec9dc211e68167"
    ),
    "speech_tokenizer/configuration.json": (
        "6bc26d64eb5024b4d1dab5a52371958b429256d6c9d59787f1f5294a54e0cebd"
    ),
    "speech_tokenizer/model.safetensors": (
        "836b7b357f5ea43e889936a3709af68dfe3751881acefe4ecf0dbd30ba571258"
    ),
    "speech_tokenizer/preprocessor_config.json": (
        "fcb3805e597e786d4067706e602f6688524640f8d3396790e2e09b5942fcbdfb"
    ),
    "tokenizer_config.json": (
        "dc3c31c3bdaedd5016382bb3cbe07323026775ad51f5a4fb564505992ae4a670"
    ),
    "vocab.json": "ca10d7e9fb3ed18575dd1e277a2579c16d108e32f27439684afa0e10b1440910",
}


# Ce que huggingface_hub écrit lui-même dans local_dir (métadonnées de
# révision, verrous, téléchargements partiels) : ni mlx-audio ni transformers
# ne lisent sous .cache/.
TENUE_DU_HUB = ".cache/huggingface/"

# 28/09/2026 : les deux seuls noms hors table que l'ancienne version de ce
# script a posés dans les installations existantes (snapshot_download sans
# allow_patterns, ou copytree d'une copie entière : les quatorze fichiers du
# dépôt). Le modèle installé sur le Mac de Carlito les porte. Les refuser
# rendait Orion indisponible dès la relance, jusqu'à une seconde AVEC réseau,
# pour deux fichiers qu'aucun chargeur n'ouvre : mlx-audio 0.5.6 lit
# config.json, generation_config.json, speech_tokenizer/config.json et globe
# *.safetensors (*.npz à défaut) ; AutoTokenizer (transformers 5.17) ouvre
# ses noms de vocabulaire et ne confronte la liste du dossier qu'à
# tekken.json, tokenizer.model*, tiktoken.model et *.model. Ces deux-là, à
# la racine, et pas d'autres : aucun autre nom hors table n'a d'installation
# à ménager, et une exception par motif (*.md, *.txt) couvrirait tôt ou tard
# un fichier qu'un chargeur lit — merges.txt en est un.
RESTES_DE_L_ANCIEN_SCRIPT = frozenset({"README.md", ".gitattributes"})


def _empreinte(chemin: Path) -> str | None:
    try:
        with chemin.open("rb") as fichier:
            return hashlib.file_digest(fichier, "sha256").hexdigest()
    except OSError:
        # 28/09/2026 : seule FileNotFoundError était captée. Un poids en
        # chmod 000 levait PermissionError hors de verifier(), qui laissait
        # l'ancien témoin dire « installé » sur un fichier illisible.
        return None


def _non_conformes(dossier: Path) -> list[str]:
    return [
        nom
        for nom, attendu in EMPREINTES.items()
        if _empreinte(dossier / nom) != attendu
    ]


def _liens(modele: Path) -> list[str]:
    # 28/09/2026 : rglob ne descend pas dans un lien de dossier (Python 3.13,
    # recurse_symlinks=False), alors que le glob de post_load_hook le suit :
    # un model/speech_tokenizer lié à un dossier extérieur faisait charger tout
    # *.safetensors qui s'y trouvait sans qu'un seul passe par la table. Et
    # c'est à travers lui que verifier() effaçait le vrai fichier de ce
    # dossier. Un lien, de fichier ou de dossier, n'a pas sa place dans
    # model/ : ce qu'on y vérifie doit y être, pas ailleurs.
    if not modele.is_dir():
        return []
    return sorted(
        chemin.relative_to(modele).as_posix()
        for chemin in modele.rglob("*")
        if chemin.is_symlink()
    )


def _hors_table(modele: Path) -> list[str]:
    # 28/09/2026 : seuls les douze noms étaient vérifiés, or mlx-audio charge
    # TOUT *.safetensors de model/ et de speech_tokenizer/ (glob), et
    # AutoTokenizer tout nom qu'il reconnaît dans model/. Un
    # intrus.safetensors posé à côté des poids passait la relance, qui
    # réécrivait le témoin « installé et vérifié ». Le dossier doit donc être
    # la table, à la tenue du hub et aux restes de l'ancien script près. Les
    # liens sont refusés par _liens().
    if not modele.is_dir():
        return []
    return sorted(
        nom
        for chemin in modele.rglob("*")
        if not chemin.is_symlink() and not chemin.is_dir()
        if (nom := chemin.relative_to(modele).as_posix()) not in EMPREINTES
        and nom not in RESTES_DE_L_ANCIEN_SCRIPT
        and not nom.startswith(TENUE_DU_HUB)
    )


def _dans_le_modele(modele: Path, nom: str) -> bool:
    # Un seul dossier lié (ou un « .. ») entre model/ et le fichier, et
    # modele / nom désigne le fichier de quelqu'un d'autre : son dossier,
    # résolu, n'est alors plus le chemin écrit sous model/.
    return (modele / nom).parent.resolve() == modele.resolve() / Path(nom).parent


def _present(modele: Path, nom: str) -> bool:
    return _dans_le_modele(modele, nom) and os.path.lexists(modele / nom)


def _retirer(modele: Path, nom: str) -> None:
    # 28/09/2026 : _retirer(modele / "speech_tokenizer/model.safetensors")
    # effaçait le fichier du dossier extérieur quand speech_tokenizer était un
    # lien. Rien ne se supprime plus à travers un lien : un lien resté en
    # place (dossier en lecture seule) laisse intact ce qu'il y a derrière.
    if not _dans_le_modele(modele, nom):
        return
    chemin = modele / nom
    try:
        if chemin.is_dir() and not chemin.is_symlink():
            shutil.rmtree(chemin)
        else:
            chemin.unlink(missing_ok=True)  # un lien : lui seul, jamais sa cible
    except OSError:
        pass  # verifier() nomme ce qui reste, et demande de le retirer


def _defaire_les_liens(modele: Path, liens: list[str]) -> None:
    for nom in liens:
        _retirer(modele, nom)


def _sans_lien(modele: Path, operation: str) -> None:
    # 28/09/2026 : verifier() et copier() ne passaient plus à travers un
    # lien, mais le téléchargement, si : huggingface_hub retire puis réécrit
    # local_dir/speech_tokenizer/model.safetensors (ou y recopie son cache)
    # à travers un speech_tokenizer lié — dans le dossier de l'utilisateur,
    # avant que la vérification n'ait vu le lien. Tout ce qui écrit dans
    # model/ passe donc d'abord ici : chaque lien part (le lien seul), et s'il
    # en reste un, rien n'est écrit.
    liens = _liens(modele)
    _defaire_les_liens(modele, liens)
    if restes := _liens(modele):
        raise RuntimeError(
            f"Impossible de retirer {', '.join(restes)} (lien symbolique) : "
            "supprimez le lien lui-même, pas sa cible, puis relancez le "
            f"script. Rien n'a été {operation}."
        )
    if liens:
        print(
            "Lien symbolique retiré de model/, sa cible reste intacte : "
            + ", ".join(liens)
        )


def verifier(modele: Path, temoin: Path) -> None:
    liens = _liens(modele)
    refuses = _non_conformes(modele)
    en_trop = _hors_table(modele)
    if not liens and not refuses and not en_trop:
        return
    # Relancer sur une installation existante re-vérifie ses poids.
    # Laisser l'ancien témoin ferait dire « installé » à moteur_installe()
    # sur un fichier qu'on vient de refuser (§5).
    temoin.unlink(missing_ok=True)
    # Les liens tombent avant toute autre suppression, et seuls : une fois
    # speech_tokenizer défait, « speech_tokenizer/model.safetensors » ne
    # désigne plus rien hors de model/.
    _defaire_les_liens(modele, liens)
    # 28/09/2026 : un fichier refusé restait en place, et huggingface_hub le
    # resservait sans rien retélécharger — ses métadonnées de local_dir
    # portent la bonne révision. Chaque relance refusait le même fichier.
    # Le retirer oblige la relance à le retélécharger (ou à le recopier).
    for nom in (*refuses, *en_trop):
        _retirer(modele, nom)
    raisons = []
    if liens:
        raisons.append(
            "lien symbolique, sa cible échapperait à la vérification et n'est "
            "jamais touchée : " + ", ".join(liens)
        )
    if refuses:
        raisons.append(
            "empreinte invalide ou fichier absent/illisible : " + ", ".join(refuses)
        )
    if en_trop:
        raisons.append(
            "hors de la table d'empreintes, le chargeur les lirait sans "
            "vérification : " + ", ".join(en_trop)
        )
    # Derrière un lien resté en place, un nom désigne un fichier d'ailleurs :
    # le nommer ici demanderait à l'utilisateur de l'effacer. Le lien suffit.
    restants = [
        n for n in dict.fromkeys((*liens, *refuses, *en_trop)) if _present(modele, n)
    ]
    suite = (
        f"Impossible de retirer {', '.join(restants)} : supprimez-les, puis "
        "relancez le script."
        if restants
        else "Ces fichiers ont été retirés : relancez le script pour les "
        "retélécharger (ou --model-source avec une copie saine)."
    )
    raise RuntimeError(f"Modèle refusé — {' ; '.join(raisons)}. {suite}")


def copier(source: Path, modele: Path, temoin: Path) -> None:
    # 28/09/2026 : --model-source n'était lu que sans témoin, et réparer une
    # installation refusée demandait deux lancements. Copier par-dessus une
    # installation existante exige alors que la source soit vérifiée AVANT
    # qu'un seul fichier ne soit remplacé : une mauvaise source n'abîme pas
    # des poids sains.
    refuses = _non_conformes(source)
    if refuses:
        raise RuntimeError(
            "Copie source refusée, rien n'a été remplacé — empreinte invalide "
            "ou fichier absent/illisible : " + ", ".join(refuses)
        )
    # Une copie interrompue laisserait un modèle à moitié remplacé sous un
    # témoin qui dirait le contraire.
    temoin.unlink(missing_ok=True)
    # 28/09/2026 : copier par-dessus un model/speech_tokenizer lié effaçait
    # puis réécrivait les fichiers du dossier extérieur.
    _sans_lien(modele, "copié")
    for nom in EMPREINTES:
        cible = modele / nom
        cible.parent.mkdir(parents=True, exist_ok=True)
        # Les poids installés sont en lecture seule (r--r--r--, constaté le
        # 28/09/2026) : copy2 par-dessus lève PermissionError, et un fichier
        # refusé ne pouvait plus être remplacé depuis une copie saine.
        _retirer(modele, nom)
        shutil.copy2(source / nom, cible)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--model-source", type=Path, help="Copie locale déjà téléchargée"
    )
    args = parser.parse_args()
    if platform.system() != "Darwin" or platform.machine() != "arm64":
        parser.error("Ce moteur requiert un Mac Apple Silicon.")
    from diapason.core.paths import get_config_dir

    root = get_config_dir() / "voices/qwen3"
    root.mkdir(parents=True, exist_ok=True)
    python = root / "runtime/bin/python"
    modele = root / "model"
    temoin = root / "installed.json"
    uv = shutil.which("uv")
    if not uv:
        parser.error("uv doit être installé pour préparer le venv séparé.")
    if not python.exists():
        subprocess.run(
            [uv, "venv", "--python", sys.executable, str(root / "runtime")], check=True
        )
    subprocess.run(
        [
            uv,
            "pip",
            "install",
            "--python",
            str(python),
            "mlx-audio==0.5.6",
            "soundfile==0.13.1",
        ],
        check=True,
    )
    if args.model_source:
        copier(args.model_source, modele, temoin)
    elif not temoin.exists():
        _sans_lien(modele, "téléchargé")
        script = (
            "import os; os.environ['HF_HUB_DISABLE_IMPLICIT_TOKEN']='1'; "
            "from huggingface_hub import snapshot_download; "
            f"snapshot_download({MODELE!r}, revision={REVISION!r}, "
            f"local_dir={str(modele)!r}, "
            f"allow_patterns={list(EMPREINTES)!r})"
        )
        subprocess.run([str(python), "-c", script], check=True)
    verifier(modele, temoin)
    temoin.write_text(
        json.dumps({"model": MODELE, "revision": REVISION, "sha256": EMPREINTES}),
        encoding="utf-8",
    )
    print("Moteur installé et vérifié. La voix par défaut n’a pas été modifiée.")


if __name__ == "__main__":
    main()
