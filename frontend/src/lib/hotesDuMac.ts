// Ce que seule la fenêtre du Mac doit monter.
//
// 26/09/2026 : `<MeshHost />` et `<ContexteVueHost />` étaient montés sans
// condition. Dans le téléphone, MeshHost relevait toutes les 2 s
// `GET /v1/mesh/inbox?drain=true` — une lecture qui VIDE la boîte : une
// navigation, une notification ou un avis de fichier reçu destinés au Mac
// étaient avalés par la WebView du téléphone, qui naviguait à sa place ou
// affichait la carte d'un fichier resté sur le Mac, pendant que l'émetteur
// avait déjà lu « Écran ouvert » (§100). Et ContexteVueHost publiait chaque
// page du téléphone (`POST /v1/context/view`) comme « ce que l'écran
// affiche » : le référent de « ça » devenait l'écran du téléphone.
//
// Le mini-panneau de la réglette (`?compact`) monte le même App : il était
// donc, lui aussi, un second lecteur de la boîte — « exactly one of these
// may be mounted », dit MeshHost. Il ne la relève plus ; il reste sur
// l'écran du Mac, et sa vue en est bien une.

export type HotesDuMac = {
  /** La main qui exécute ce qu'un autre appareil demande au Mac. */
  boiteDuMaillage: boolean;
  /** L'écran courant, publié comme celui du Mac. */
  contexteDeLaVue: boolean;
};

export function hotesDuMac(estMobile: boolean, estCompact: boolean): HotesDuMac {
  return {
    boiteDuMaillage: !estMobile && !estCompact,
    contexteDeLaVue: !estMobile,
  };
}
