"""Prepare the canonical install scripts in the generated docs site.

Serves the installers at::

    https://carlitoetienne01-spec.github.io/Diapason/install.sh   (Linux / macOS / WSL2)
    https://carlitoetienne01-spec.github.io/Diapason/install.ps1  (native Windows)

These become project-controlled HTTPS install URLs only when GitHub Pages is
actually deployed. The private repository currently publishes no Pages site,
so product documentation must point at the files in an authenticated checkout
until that deployment exists.

Single source of truth: the scripts live under ``scripts/install/`` and
``deploy/windows/`` (also bundled into the wheel as ``_install_scripts/``).
This copies them verbatim into the built site on every ``mkdocs build``,
so the published copies can never drift from the canonical ones.
"""

from pathlib import Path

import mkdocs_gen_files

# (source path, published URL path)
_SCRIPTS = [
    (Path("scripts/install/install.sh"), "install.sh"),
    (Path("deploy/windows/install.ps1"), "install.ps1"),
]

for src, dest in _SCRIPTS:
    with mkdocs_gen_files.open(dest, "wb") as out:
        out.write(src.read_bytes())
