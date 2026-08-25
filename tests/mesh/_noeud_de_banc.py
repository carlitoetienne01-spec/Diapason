"""Un nœud de maillage réel, dans SON processus, sur SON port.

Spatial Mesh, 25 août 2026. Ce fichier est lancé en sous-processus par
``test_banc_deux_processus.py``. Il ne peut pas être une fixture : deux
identités de maillage exigent deux ``$DIAPASON_HOME`` vivants en même
temps, et cette variable appartient au processus. Le contrôle 4 de
``verify_command`` refuse d'ailleurs une commande venant de soi-même —
deux nœuds dans un processus partageraient la même clé, donc le même
identifiant, et se refuseraient avant même la signature.

Usage : python _noeud_de_banc.py <foyer> <port> <cle_api>
Écrit « PRÊT <deviceId> » sur la sortie standard quand il écoute.
"""

from __future__ import annotations

import os
import sys


def main() -> None:
    foyer, port, cle = sys.argv[1], int(sys.argv[2]), sys.argv[3]
    os.environ["DIAPASON_HOME"] = foyer

    from fastapi import FastAPI

    from diapason.mesh.beacon import set_local_endpoint
    from diapason.mesh.identity import device_identity
    from diapason.mesh.routes import router
    from diapason.server.auth_middleware import AuthMiddleware

    # AVANT de servir : sinon l'adresse annoncée dans la réponse du
    # jumelage retombe sur le port de config.toml et l'autre nœud écrit
    # au mauvais endroit.
    set_local_endpoint("127.0.0.1", port)

    app = FastAPI()
    app.add_middleware(AuthMiddleware, api_key=cle)
    app.include_router(router)

    moi = device_identity()
    print(f"PRÊT {moi.device_id}", flush=True)

    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=port, log_level="error")


if __name__ == "__main__":
    main()
