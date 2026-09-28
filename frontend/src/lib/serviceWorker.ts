// Le service worker de la PWA — réservé au navigateur, pas au mini-panneau.
//
// 26/09/2026, décision de la phase 3 (plan mobile, étape 7) : pour l'origine
// du téléphone, le service worker est DÉSINSCRIT — le bundle doit toujours
// être exactement celui que le Mac sert. Or le plugin PWA injectait
// `registerSW.js` dans index.html, qui l'inscrivait à chaque chargement,
// sans condition : ce que la coquille aurait désinscrit revenait au
// chargement suivant, précachait ses 12 Mo et servait ensuite l'index.html
// EN CACHE — un bundle d'hier chargé hors de portée du Mac, qui échoue
// action par action au lieu que la coquille dise « Mac injoignable ».
//
// L'inscription passe donc ici, après la même attente (`load`) et avec les
// mêmes arguments que `registerSW.js` pour le navigateur du Mac.

export type IssueDuServiceWorker = 'absent' | 'inscrit' | 'desinscrit' | 'rien';

type Inscription = { unregister(): Promise<boolean> };

export type ConteneurSW = {
  register(url: string, options: { scope: string }): Promise<unknown>;
  getRegistrations(): Promise<readonly Inscription[]>;
};

export type CachesSW = {
  keys(): Promise<string[]>;
  delete(nom: string): Promise<boolean>;
};

/** Les caches que Workbox a créés — seuls ceux-là sont à nous de vider. */
const PREFIXE_WORKBOX = 'workbox-';

export async function gererLeServiceWorker(options: {
  conteneur: ConteneurSW | null | undefined;
  caches?: CachesSW | null;
  /** Servi par le tailnet (lib/tailnet.ts) : désinscrire, ne rien inscrire. */
  servi: boolean;
  /** Le mini-panneau doit suivre le bundle du serveur, comme le téléphone. */
  compact?: boolean;
  /** Construction qui publie un service worker (ni Tauri, ni le serveur de dev). */
  actif: boolean;
}): Promise<IssueDuServiceWorker> {
  const { conteneur, caches, servi, actif, compact = false } = options;
  if (!conteneur) return 'absent';
  // 28/09/2026 : le mini-panneau gardait les anciennes routes /succes et
  // l'ancien compositeur. Une construction Tauri ne publie plus sw.js,
  // mais cela ne désinscrit PAS un worker installé par un build précédent.
  if (servi || compact || !actif) {
    const inscriptions = await conteneur.getRegistrations();
    await Promise.all(inscriptions.map((i) => i.unregister().catch(() => false)));
    // Le précache (12 Mo) ne sert plus à rien sans service worker pour le
    // servir ; le garder, c'est garder la place d'un bundle périmé.
    if (caches) {
      try {
        const noms = await caches.keys();
        await Promise.all(
          noms.filter((nom) => nom.startsWith(PREFIXE_WORKBOX)).map((nom) => caches.delete(nom)),
        );
      } catch {
        // Un cache illisible ne ramène pas le service worker.
      }
    }
    return 'desinscrit';
  }
  await conteneur.register('/sw.js', { scope: '/' });
  return 'inscrit';
}
