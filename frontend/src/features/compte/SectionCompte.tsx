/**
 * Réglages › Compte et chiffrement (compte-chiffre.md §3.11, « Place dans
 * l'interface »), après Connexion.
 *
 * Blocs `w-full max-w-*`, sans `SettingRow` à largeur fixe : la page s'ouvre
 * aussi dans le mini-panneau (docs/development/mini-panneau-responsive.md,
 * règles 1 et 4). Là, D14 ne laisse que l'état et le déverrouillage : tout
 * le reste porte `compact:hidden` — c'est un MODE, pas une largeur (règle
 * 3), et la page ne lit pas `estCompact` (seule Layout le lit).
 */

import { useCallback, useEffect, useState } from 'react';
import { useLocation } from 'react-router';
import { KeyRound, Laptop, Lock, LogOut, RefreshCw, Trash2 } from 'lucide-react';
import { useTranslation } from '../../i18n/useTranslation';
import type { MessageKey } from '../../i18n/translate';
import { useConfirm } from '../../components/ConfirmDialog';
import {
  aUnCompte,
  actionSection,
  bandeauCompte,
  estEtatAlerte,
  formaterDate,
  formaterJour,
  lectureAffichee,
  libelleEtat,
  libelleSynchro,
  reglesMotDePasse,
  type CleMontree,
  type ErreurLue,
  type Parcours,
  type StatutCompte,
} from '../../lib/compte';
import {
  changerMotDePasse,
  confirmerCle,
  deconnecterAppareil,
  demanderCodeOubliIci,
  estErreurCompte,
  listerAppareils,
  nouvelleCle,
  oubliIci,
  reinitAnnuler,
  retirerCle,
  seDeconnecter,
  supprimerCompte,
  verrouiller,
  type Appareil,
} from './api';
import {
  AvisRotation,
  BlocCle,
  Bouton,
  Champ,
  EcranCompte,
  Encadre,
  FormulaireDeverrouillage,
  LigneSecours,
  MessageErreur,
  NouveauMotDePasse,
  Saisie,
  SaisieMotDePasse,
  useStatutCompte,
} from './EcranCompte';
import { serviParLeTailnet } from '../../lib/tailnet';

type Panneau = 'motDePasse' | 'cle' | 'retirerCle' | 'oubliIci' | 'appareils' | 'supprimer' | null;

function Bloc({ titre, children, compactVisible = false }: { titre: string; children: React.ReactNode; compactVisible?: boolean }) {
  return (
    <div
      className={`w-full min-w-0 flex flex-col gap-3 py-4 ${compactVisible ? '' : 'compact:hidden'}`}
      style={{ borderTop: '1px solid var(--color-border-subtle)' }}
    >
      <h4 className="text-sm font-medium" style={{ color: 'var(--color-text)' }}>
        {titre}
      </h4>
      {children}
    </div>
  );
}

/** Un geste court de la section : occupé, erreur, succès. */
function useGeste() {
  const [occupe, setOccupe] = useState(false);
  const [erreur, setErreur] = useState<ErreurLue | null>(null);
  const agir = useCallback(async (f: () => Promise<void>) => {
    setOccupe(true);
    setErreur(null);
    try {
      await f();
      return true;
    } catch (e) {
      setErreur(estErreurCompte(e) ? e : { code: 'localServerUnreachable' });
      return false;
    } finally {
      setOccupe(false);
    }
  }, []);
  return { occupe, erreur, agir, setErreur };
}

function ChangerMotDePasse({ statut, onRotation }: { statut: StatutCompte; onRotation: () => void }) {
  const { t } = useTranslation();
  const [actuel, setActuel] = useState('');
  const [nouveau, setNouveau] = useState('');
  const [confirmation, setConfirmation] = useState('');
  const { occupe, erreur, agir } = useGeste();
  const valide = actuel.length > 0 && reglesMotDePasse(nouveau, statut.email, confirmation).valide;
  return (
    <form
      className="flex flex-col gap-3 w-full max-w-md"
      onSubmit={(e) => {
        e.preventDefault();
        if (!valide) return;
        void agir(async () => {
          await changerMotDePasse(actuel, nouveau);
          setActuel('');
          setNouveau('');
          setConfirmation('');
          onRotation();
        });
      }}
    >
      <Champ libelle={t('compte.mdp.libelleActuel')}>
        <SaisieMotDePasse valeur={actuel} onChange={setActuel} />
      </Champ>
      <NouveauMotDePasse
        motDePasse={nouveau}
        confirmation={confirmation}
        onMotDePasse={setNouveau}
        onConfirmation={setConfirmation}
        courriel={statut.email}
      />
      <MessageErreur erreur={erreur} />
      <Bouton type="submit" variante="principal" occupe={occupe} disabled={!valide}>
        {t('compte.section.changerMdp')}
      </Bouton>
    </form>
  );
}

/** Oubli depuis CET appareil, déverrouillé (P4 chemin 2) : un code courriel, puis le nouveau mot de passe. */
function OubliIci({ statut, onRotation }: { statut: StatutCompte; onRotation: () => void }) {
  const { t } = useTranslation();
  const [codeEnvoye, setCodeEnvoye] = useState(false);
  const [code, setCode] = useState('');
  const [nouveau, setNouveau] = useState('');
  const [confirmation, setConfirmation] = useState('');
  const { occupe, erreur, agir } = useGeste();
  const propre = code.replace(/\s/g, '');
  const valide = /^\d{6}$/.test(propre) && reglesMotDePasse(nouveau, statut.email, confirmation).valide;
  return (
    <form
      className="flex flex-col gap-3 w-full max-w-md"
      onSubmit={(e) => {
        e.preventDefault();
        if (!valide) return;
        void agir(async () => {
          await oubliIci(propre, nouveau);
          setCode('');
          setNouveau('');
          setConfirmation('');
          onRotation();
        });
      }}
    >
      <p className="text-sm leading-6" style={{ color: 'var(--color-text-secondary)' }}>
        {t('compte.section.oubliIciTexte')}
      </p>
      <Bouton occupe={occupe && !codeEnvoye} onClick={() => void agir(async () => { await demanderCodeOubliIci(); setCodeEnvoye(true); })}>
        {codeEnvoye ? t('compte.reinit.renvoyer') : t('compte.reinit.envoyerCode')}
      </Bouton>
      {codeEnvoye && (
        <>
          <Champ libelle={t('compte.code.libelle')}>
            <Saisie
              value={code}
              onChange={(e) => setCode(e.target.value)}
              inputMode="numeric"
              autoComplete="one-time-code"
              maxLength={7}
              style={{ fontFamily: 'var(--font-hud)', letterSpacing: '0.2em' }}
            />
          </Champ>
          <NouveauMotDePasse
            motDePasse={nouveau}
            confirmation={confirmation}
            onMotDePasse={setNouveau}
            onConfirmation={setConfirmation}
            courriel={statut.email}
          />
        </>
      )}
      <MessageErreur erreur={erreur} />
      {codeEnvoye && (
        <Bouton type="submit" variante="principal" occupe={occupe} disabled={!valide}>
          {t('compte.section.oubliIciEnvoyer')}
        </Bouton>
      )}
    </form>
  );
}

/** Créer ou remplacer la clé : le mot de passe, puis la clé montrée, puis sa preuve. */
function ClePreparee({ onFini }: { onFini: (confirmee: boolean) => void }) {
  const { t } = useTranslation();
  const [motDePasse, setMotDePasse] = useState('');
  const [cle, setCle] = useState<CleMontree | null>(null);
  const { occupe, erreur, agir } = useGeste();
  if (cle) {
    return (
      <div className="w-full max-w-md">
        <BlocCle
          cle={cle}
          occupe={occupe}
          erreur={erreur}
          onConfirmer={(extrait) =>
            void agir(async () => {
              await confirmerCle(extrait);
              setCle(null);
              onFini(true);
            })
          }
          onSansCle={() => {
            setCle(null);
            onFini(false);
          }}
          libelleSansCle={t('compte.section.cleAbandonner')}
        />
      </div>
    );
  }
  return (
    <form
      className="flex flex-col gap-3 w-full max-w-md"
      onSubmit={(e) => {
        e.preventDefault();
        if (!motDePasse) return;
        void agir(async () => {
          const rendue = await nouvelleCle(motDePasse);
          setMotDePasse('');
          setCle({ cle: rendue.cle, groupes: rendue.groupes, origine: 'remplacement' });
        });
      }}
    >
      <Champ libelle={t('compte.mdp.libelleActuel')}>
        <SaisieMotDePasse valeur={motDePasse} onChange={setMotDePasse} />
      </Champ>
      <MessageErreur erreur={erreur} />
      <Bouton type="submit" variante="principal" occupe={occupe} disabled={!motDePasse}>
        {t('compte.section.cleAfficher')}
      </Bouton>
    </form>
  );
}

function RetirerCle({ onRotation }: { onRotation: () => void }) {
  const { t } = useTranslation();
  const confirmer = useConfirm();
  const [motDePasse, setMotDePasse] = useState('');
  const { occupe, erreur, agir } = useGeste();
  return (
    <form
      className="flex flex-col gap-3 w-full max-w-md"
      onSubmit={(e) => {
        e.preventDefault();
        if (!motDePasse) return;
        void (async () => {
          const ok = await confirmer({
            title: t('compte.section.retirerTitre'),
            description: t('compte.section.retirerTexte'),
            confirmLabel: t('compte.section.retirer'),
            keepLabel: t('compte.garder'),
            tone: 'danger',
          });
          if (!ok) return;
          await agir(async () => {
            await retirerCle(motDePasse);
            setMotDePasse('');
            onRotation();
          });
        })();
      }}
    >
      <Champ libelle={t('compte.mdp.libelleActuel')}>
        <SaisieMotDePasse valeur={motDePasse} onChange={setMotDePasse} />
      </Champ>
      <MessageErreur erreur={erreur} />
      <Bouton type="submit" variante="danger" occupe={occupe} disabled={!motDePasse}>
        {t('compte.section.retirer')}
      </Bouton>
    </form>
  );
}

function Appareils({ onRotation }: { onRotation: () => void }) {
  const { t, locale } = useTranslation();
  const confirmer = useConfirm();
  const [appareils, setAppareils] = useState<Appareil[] | null>(null);
  const [cible, setCible] = useState<Appareil | null>(null);
  const [motDePasse, setMotDePasse] = useState('');
  const { occupe, erreur, agir } = useGeste();
  const charger = useCallback(
    () => void agir(async () => setAppareils(await listerAppareils())),
    [agir],
  );
  useEffect(() => {
    charger();
  }, [charger]);
  return (
    <div className="flex flex-col gap-3 w-full max-w-md">
      {appareils === null && !erreur && <p className="text-sm" style={{ color: 'var(--color-text-tertiary)' }}>{t('compte.chargement')}</p>}
      {appareils && (
        <ul className="flex flex-col gap-2">
          {appareils.map((a) => (
            <li
              key={a.sessionId}
              className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-lg px-3 py-2"
              style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)' }}
            >
              <Laptop size={15} className="shrink-0" style={{ color: 'var(--color-text-tertiary)' }} />
              <span className="flex-1 min-w-0 flex flex-col">
                <span className="text-sm truncate" style={{ color: 'var(--color-text)' }}>
                  {a.name ?? t('compte.appareils.sansNom')}
                  {a.current && ` · ${t('compte.appareils.celuiCi')}`}
                </span>
                <span className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
                  {t('compte.appareils.jours', {
                    cree: formaterJour(a.createdDay, locale),
                    vu: formaterJour(a.lastSeenDay, locale),
                  })}
                </span>
              </span>
              {!a.current && (
                <Bouton variante="lien" onClick={() => setCible(a)}>
                  {t('compte.appareils.deconnecter')}
                </Bouton>
              )}
            </li>
          ))}
        </ul>
      )}
      {appareils?.some((a) => a.name === null) && (
        <p className="text-xs leading-5" style={{ color: 'var(--color-text-tertiary)' }}>
          {t('compte.appareils.nomsIllisibles')}
        </p>
      )}
      {cible && (
        <form
          className="flex flex-col gap-3"
          onSubmit={(e) => {
            e.preventDefault();
            if (!motDePasse) return;
            void (async () => {
              const ok = await confirmer({
                title: t('compte.appareils.confirmerTitre', { nom: cible.name ?? t('compte.appareils.sansNom') }),
                description: t('compte.appareils.texte'),
                confirmLabel: t('compte.appareils.deconnecter'),
                keepLabel: t('compte.garder'),
                tone: 'danger',
              });
              if (!ok) return;
              const fait = await agir(async () => {
                await deconnecterAppareil(cible.sessionId, motDePasse);
              });
              if (fait) {
                setMotDePasse('');
                setCible(null);
                onRotation();
              }
            })();
          }}
        >
          <Encadre ton="attente">{t('compte.appareils.texte')}</Encadre>
          <Champ libelle={t('compte.mdp.libelleActuel')}>
            <SaisieMotDePasse valeur={motDePasse} onChange={setMotDePasse} />
          </Champ>
          <div className="flex flex-wrap gap-2">
            <Bouton type="submit" variante="danger" occupe={occupe} disabled={!motDePasse}>
              {t('compte.appareils.deconnecter')}
            </Bouton>
            <Bouton onClick={() => setCible(null)}>{t('compte.garder')}</Bouton>
          </div>
        </form>
      )}
      <MessageErreur erreur={erreur} />
      <Bouton variante="lien" onClick={charger}>
        <RefreshCw size={12} className="inline mr-1" />
        {t('compte.reessayer')}
      </Bouton>
    </div>
  );
}

function Supprimer({ statut }: { statut: StatutCompte }) {
  const { t } = useTranslation();
  const confirmer = useConfirm();
  const [motDePasse, setMotDePasse] = useState('');
  const { occupe, erreur, agir } = useGeste();
  return (
    <form
      className="flex flex-col gap-3 w-full max-w-md"
      onSubmit={(e) => {
        e.preventDefault();
        if (!motDePasse) return;
        void (async () => {
          const ok = await confirmer({
            title: t('compte.supprimer.confirmerTitre', { courriel: statut.email ?? '' }),
            description: t('compte.supprimer.confirmer'),
            confirmLabel: t('compte.supprimer.bouton'),
            keepLabel: t('compte.garder'),
            tone: 'danger',
          });
          if (!ok) return;
          await agir(async () => {
            await supprimerCompte(motDePasse);
            setMotDePasse('');
          });
        })();
      }}
    >
      <Encadre ton="danger" titre={t('compte.supprimer.efface')}>
        {t('compte.supprimer.effaceListe')}
      </Encadre>
      <Encadre ton="neutre" titre={t('compte.supprimer.reste')}>
        {t('compte.supprimer.resteListe')}
      </Encadre>
      <Champ libelle={t('compte.mdp.libelleActuel')}>
        <SaisieMotDePasse valeur={motDePasse} onChange={setMotDePasse} />
      </Champ>
      <MessageErreur erreur={erreur} />
      <Bouton type="submit" variante="danger" occupe={occupe} disabled={!motDePasse}>
        <Trash2 size={14} />
        {t('compte.supprimer.bouton')}
      </Bouton>
    </form>
  );
}

function Gerer({ statut, ouvrir }: { statut: StatutCompte; ouvrir: (p: Parcours) => void }) {
  const { t, locale } = useTranslation();
  const confirmer = useConfirm();
  const [panneau, setPanneau] = useState<Panneau>(null);
  const [rotation, setRotation] = useState<MessageKey | null>(null);
  const [avisDeconnexion, setAvisDeconnexion] = useState(false);
  const { occupe, erreur, agir } = useGeste();
  const basculer = (p: Panneau) => {
    setRotation(null);
    setPanneau((actuel) => (actuel === p ? null : p));
  };
  // P5 a son propre texte (le mot de passe a changé) ; les autres
  // rotations reprennent celui du §2.8.
  const apresRotation = (cle: MessageKey = 'compte.rotation.texte') => {
    setPanneau(null);
    setRotation(cle);
  };
  const ouvert = statut.unlocked;

  const deconnecter = async () => {
    const ok = await confirmer({
      title: t('compte.deconnexion.titre'),
      description:
        statut.sync.pendingCount !== null && statut.sync.pendingCount > 0
          ? `${t('compte.deconnexion.texte')}\n\n${t('compte.deconnexion.enAttente', { count: statut.sync.pendingCount })}`
          : t('compte.deconnexion.texte'),
      confirmLabel: t('compte.deconnexion.bouton'),
      keepLabel: t('compte.garder'),
      tone: 'warning',
    });
    if (!ok) return;
    await agir(async () => {
      const fermee = await seDeconnecter();
      setAvisDeconnexion(!fermee);
    });
  };

  return (
    <>
      {rotation && (
        <div className="w-full max-w-md compact:hidden">
          <AvisRotation cle={rotation} />
        </div>
      )}

      {ouvert && (
        <Bloc titre={t('compte.section.memorisation')}>
          <p className="text-sm leading-6 max-w-md" style={{ color: 'var(--color-text-secondary)' }}>
            {statut.remembered ? t('compte.section.memoriseOui') : t('compte.section.memoriseNon')}
          </p>
          <div className="flex flex-wrap gap-2">
            <Bouton occupe={occupe} onClick={() => void agir(async () => void (await verrouiller()))}>
              <Lock size={14} />
              {t('compte.section.verrouiller')}
            </Bouton>
          </div>
        </Bloc>
      )}

      {ouvert && (
        <Bloc titre={t('compte.section.motDePasse')}>
          <div className="flex flex-wrap gap-2">
            <Bouton onClick={() => basculer('motDePasse')}>{t('compte.section.changerMdp')}</Bouton>
            <Bouton variante="lien" onClick={() => basculer('oubliIci')}>
              {t('compte.section.oubliIci')}
            </Bouton>
          </div>
          {panneau === 'motDePasse' && (
            <ChangerMotDePasse statut={statut} onRotation={() => apresRotation('compte.rotation.motDePasse')} />
          )}
          {panneau === 'oubliIci' && (
            <OubliIci statut={statut} onRotation={() => apresRotation('compte.rotation.motDePasse')} />
          )}
        </Bloc>
      )}

      {ouvert && (
        <Bloc titre={t('compte.section.cle')}>
          <p className="text-sm leading-6 max-w-md" style={{ color: 'var(--color-text-secondary)' }}>
            {statut.recoveryConfigured ? t('compte.section.cleOui') : t('compte.section.cleNon')}
          </p>
          <div className="flex flex-wrap gap-2">
            <Bouton onClick={() => basculer('cle')}>
              <KeyRound size={14} />
              {statut.recoveryConfigured ? t('compte.section.cleRemplacer') : t('compte.section.cleCreer')}
            </Bouton>
            {statut.recoveryConfigured && (
              <Bouton variante="lien" onClick={() => basculer('retirerCle')}>
                {t('compte.section.retirer')}
              </Bouton>
            )}
          </div>
          {panneau === 'cle' && <ClePreparee onFini={(confirmee) => (confirmee ? apresRotation() : setPanneau(null))} />}
          {panneau === 'retirerCle' && <RetirerCle onRotation={() => apresRotation()} />}
        </Bloc>
      )}

      {ouvert && (
        <Bloc titre={t('compte.section.appareils')}>
          <p className="text-sm leading-6 max-w-md" style={{ color: 'var(--color-text-secondary)' }}>
            {t('compte.section.appareilsTexte')}
          </p>
          <div>
            <Bouton onClick={() => basculer('appareils')}>
              <Laptop size={14} />
              {panneau === 'appareils' ? t('compte.section.masquer') : t('compte.section.appareilsVoir')}
            </Bouton>
          </div>
          {panneau === 'appareils' && <Appareils onRotation={() => apresRotation()} />}
        </Bloc>
      )}

      {!ouvert && (
        <Bloc titre={t('compte.section.motDePasse')}>
          <Bouton variante="lien" onClick={() => ouvrir('oubli')}>
            {t('compte.oubli.lien')}
          </Bouton>
        </Bloc>
      )}

      {statut.lastKeyChangeAt !== null && (
        <p className="text-xs compact:hidden" style={{ color: 'var(--color-text-tertiary)' }}>
          {t('compte.section.derniereRotation', { date: formaterDate(statut.lastKeyChangeAt, locale) })}
        </p>
      )}

      <Bloc titre={t('compte.section.quitter')}>
        <div className="flex flex-wrap gap-2">
          <Bouton occupe={occupe} onClick={() => void deconnecter()}>
            <LogOut size={14} />
            {t('compte.deconnexion.bouton')}
          </Bouton>
          <Bouton variante="lien" onClick={() => basculer('supprimer')}>
            {t('compte.supprimer.lien')}
          </Bouton>
        </div>
        {panneau === 'supprimer' && <Supprimer statut={statut} />}
      </Bloc>
      {avisDeconnexion && (
        <div className="w-full max-w-md">
          <Encadre ton="attente">{t('compte.deconnexion.sessionRestee')}</Encadre>
        </div>
      )}
      <div className="w-full max-w-md">
        <MessageErreur erreur={erreur} />
      </div>
    </>
  );
}

export function SectionCompte() {
  const { t, locale } = useTranslation();
  const { hash } = useLocation();
  const { statut, lu, illisible, erreur, relire } = useStatutCompte(30000);
  const [ecran, setEcran] = useState<Parcours | null>(null);
  // Stable : l'écran du compte s'abonne à Échap avec elle, et une flèche
  // neuve à chaque sonde réinscrivait son écouteur (24/09/2026).
  const fermerEcran = useCallback(() => setEcran(null), []);
  const { occupe, erreur: erreurGeste, agir } = useGeste();
  const lecture = lectureAffichee(statut, lu, erreur);

  // Le bandeau renvoie ici par « /settings#compte ».
  useEffect(() => {
    if (hash !== '#compte') return;
    const minuteur = window.setTimeout(
      () => document.getElementById('compte')?.scrollIntoView({ behavior: 'smooth', block: 'start' }),
      50,
    );
    return () => window.clearTimeout(minuteur);
  }, [hash]);

  let contenu: React.ReactNode;
  if (serviParLeTailnet()) {
    // Le statut n'est pas lu au téléphone (useStatutCompte) : sans cette
    // branche, la section restait sur « Chargement… » pour toujours.
    contenu = (
      <p className="text-sm leading-6" style={{ color: 'var(--color-text-secondary)' }}>
        {t('tailnet.compte')}
      </p>
    );
  } else if (!statut) {
    contenu = !lu ? (
      <p className="text-sm" style={{ color: 'var(--color-text-tertiary)' }}>{t('compte.chargement')}</p>
    ) : (
      <div className="flex flex-col gap-3 w-full max-w-md">
        <MessageErreur erreur={erreur ?? (illisible ? { code: 'responseUnreadable' } : null)} />
        <div>
          <Bouton onClick={relire}>{t('compte.reessayer')}</Bouton>
        </div>
      </div>
    );
  } else if (!aUnCompte(statut) && !statut.accountsOpen) {
    // 24/09/2026 : ni « Créer un compte » ni « Se connecter » tant que les
    // comptes ne sont pas ouverts — deux boutons qui mèneraient chacun à une
    // erreur réseau (§5).
    contenu = (
      <div className="flex flex-col gap-2 w-full max-w-md">
        <p className="text-sm font-medium" style={{ color: 'var(--color-text)' }}>
          {t('compte.fermee.titre')}
        </p>
        <p className="text-sm leading-6" style={{ color: 'var(--color-text-secondary)' }}>
          {t('compte.fermee.texte')}
        </p>
      </div>
    );
  } else if (!aUnCompte(statut)) {
    contenu = (
      <div className="flex flex-col gap-3 w-full max-w-md">
        <p className="text-sm leading-6" style={{ color: 'var(--color-text-secondary)' }}>
          {t('compte.accueil.texte')}
        </p>
        <p className="text-xs leading-5 compact:hidden" style={{ color: 'var(--color-text-tertiary)' }}>
          {t('compte.accueil.serveurVoit')}
        </p>
        <div className="flex flex-wrap gap-2 compact:hidden">
          <Bouton variante="principal" onClick={() => setEcran('inscription')}>
            {statut.state === 'signupInProgress' ? t('compte.section.reprendre') : t('compte.accueil.creer')}
          </Bouton>
          <Bouton onClick={() => setEcran('connexion')}>{t('compte.accueil.connecter')}</Bouton>
        </div>
        <p className="hidden compact:block text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
          {t('compte.section.fenetre')}
        </p>
      </div>
    );
  } else {
    const synchro = libelleSynchro(statut.sync, Date.now(), locale);
    const bandeau = bandeauCompte(statut, locale);
    const action = actionSection(statut);
    const perime = lecture === 'perime';
    contenu = (
      <div className="flex flex-col gap-3 w-full min-w-0">
        <div className="flex flex-col gap-1 min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span
              className="w-2 h-2 rounded-full shrink-0"
              style={{
                background: perime
                  ? 'var(--color-text-tertiary)'
                  : statut.unlocked
                    ? 'var(--color-success)'
                    : estEtatAlerte(statut.state)
                      ? 'var(--color-error)'
                      : 'var(--color-warning)',
              }}
            />
            <span className="text-sm font-medium" style={{ color: 'var(--color-text)' }}>
              {t(libelleEtat(statut.state))}
            </span>
            {statut.email && (
              <span className="text-sm min-w-0 truncate" style={{ color: 'var(--color-text-secondary)' }}>
                {statut.email}
              </span>
            )}
          </div>
          <span className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
            {t(synchro.cle, synchro.vars)}
          </span>
          {/* 24/09/2026 : le dernier état connu s'affichait comme frais —
              « Déverrouillé », pastille verte — serveur local arrêté. */}
          {perime && (
            <span role="status" className="text-xs" style={{ color: 'var(--color-text-secondary)' }}>
              {t('compte.statutPerime')}
            </span>
          )}
        </div>

        {statut.state === 'locked' && (
          <div className="w-full max-w-md">
            <FormulaireDeverrouillage statut={statut} onConnexion={() => setEcran('connexion')} />
          </div>
        )}

        {statut.state === 'resetPending' && (
          <div className="w-full max-w-md flex flex-col gap-2">
            <Encadre ton="danger">
              {statut.pendingResetAt !== null
                ? t('compte.reinit.prevue', { date: formaterDate(statut.pendingResetAt, locale) })
                : t('compte.bandeau.reinitPrevueSansDate')}
            </Encadre>
            <div className="compact:hidden">
              <Bouton variante="principal" occupe={occupe} onClick={() => void agir(async () => void (await reinitAnnuler()))}>
                {t('compte.reinit.annuler')}
              </Bouton>
            </div>
            <MessageErreur erreur={erreurGeste} />
            {!statut.unlocked && <FormulaireDeverrouillage statut={statut} />}
          </div>
        )}

        {action === 'consentir' && (
          <div className="w-full max-w-md compact:hidden">
            <Bouton variante="principal" onClick={() => setEcran('accueil')}>
              {t('compte.section.consentir')}
            </Bouton>
          </div>
        )}

        {action === 'resoudre' && (
          <div className="w-full max-w-md flex flex-col gap-2">
            {bandeau && <Encadre ton="alerte">{t(bandeau.cle, bandeau.vars)}</Encadre>}
            <div className="compact:hidden">
              <Bouton variante="principal" onClick={() => setEcran('accueil')}>
                {t('compte.section.resoudre')}
              </Bouton>
            </div>
            <p className="hidden compact:block text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
              {t('compte.section.fenetre')}
            </p>
          </div>
        )}

        <div className="w-full max-w-md">
          <LigneSecours statut={statut} />
        </div>

        <Gerer statut={statut} ouvrir={(p) => setEcran(p)} />
      </div>
    );
  }

  return (
    <div
      id="compte"
      className="rounded-xl p-5 scroll-mt-4"
      style={{ background: 'var(--color-surface)', border: '1px solid var(--color-border)' }}
    >
      <h3 className="text-sm font-semibold mb-4" style={{ color: 'var(--color-text)' }}>
        {t('compte.section.titre')}
      </h3>
      {contenu}
      {ecran && <EcranCompte contexte="reglages" parcoursInitial={ecran} onFermer={fermerEcran} />}
    </div>
  );
}
