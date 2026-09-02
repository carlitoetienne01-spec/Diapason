// La Grande Vie — ce que dix ans de tirages disent, et ce qu'ils ne disent pas.
//
// Demandé le 31 août 2026 : « avoir des chiffres fiables à jouer ». Cet écran
// répond non, et le démontre au lieu de l'affirmer. Il ne recommande aucun
// numéro, et n'en recommandera jamais : sur 1 030 tirages, le test du khi-deux
// rend p ≈ 0,79 — un tirage parfaitement équitable, où aucune combinaison n'est
// plus probable qu'une autre.

import { useCallback, useEffect, useState } from 'react';
import {
  AlertTriangle,
  CheckCircle2,
  Dices,
  Download,
  Loader2,
  ShieldCheck,
} from 'lucide-react';

import {
  type EtatLoterie,
  type ResultatSimulation,
  lireEtat,
  moissonner,
  simuler,
} from '../features/loterie/api';
import {
  type Grille,
  lireGrille,
  lireLaValeurP,
  tiragesPourAnnees,
  unSur,
} from '../features/loterie/loterie';

const sous = { color: 'var(--color-text-secondary)' };
const tertiaire = { color: 'var(--color-text-tertiary)' };

function Carte({
  titre,
  soustitre,
  children,
}: {
  titre: string;
  soustitre?: string;
  children: React.ReactNode;
}) {
  return (
    <section
      className="rounded-xl p-4 flex flex-col gap-3"
      style={{
        background: 'var(--color-bg-secondary)',
        border: '1px solid var(--color-border)',
      }}
    >
      <header>
        <h2 className="text-sm font-medium" style={{ color: 'var(--color-text)' }}>
          {titre}
        </h2>
        {soustitre ? (
          <p className="text-[11px] mt-0.5" style={tertiaire}>
            {soustitre}
          </p>
        ) : null}
      </header>
      {children}
    </section>
  );
}

export function LoteriePage() {
  const [etat, setEtat] = useState<EtatLoterie | null>(null);
  const [chargement, setChargement] = useState(true);
  const [erreur, setErreur] = useState('');
  const [moissonEnCours, setMoissonEnCours] = useState(false);
  const [journalMoisson, setJournalMoisson] = useState('');

  const [saisie, setSaisie] = useState('6 23 28 34 37 4');
  const [annees, setAnnees] = useState(50);
  const [simulation, setSimulation] = useState<ResultatSimulation | null>(null);
  const [simulationEnCours, setSimulationEnCours] = useState(false);

  const recharger = useCallback(async () => {
    try {
      setEtat(await lireEtat());
      setErreur('');
    } catch (e) {
      setErreur(e instanceof Error ? e.message : String(e));
    } finally {
      setChargement(false);
    }
  }, []);

  useEffect(() => {
    void recharger();
  }, [recharger]);

  const lancerLaMoisson = async () => {
    setMoissonEnCours(true);
    setJournalMoisson('');
    try {
      const r = await moissonner();
      setJournalMoisson(
        `${r.pagesRead} pages lues, ${r.drawsRead} tirages, ${r.drawsNew} nouveaux — ${r.stoppedBecause}`,
      );
      await recharger();
    } catch (e) {
      setJournalMoisson(e instanceof Error ? e.message : String(e));
    } finally {
      setMoissonEnCours(false);
    }
  };

  const { grille, erreur: erreurGrille } = lireGrille(saisie);

  const lancerLaSimulation = async (g: Grille) => {
    setSimulationEnCours(true);
    try {
      setSimulation(await simuler(g.numeros, g.grandNumero, tiragesPourAnnees(annees)));
    } catch (e) {
      setErreur(e instanceof Error ? e.message : String(e));
    } finally {
      setSimulationEnCours(false);
    }
  };

  if (chargement) {
    return (
      <div className="p-6 flex items-center gap-2 text-sm" style={sous}>
        <Loader2 size={15} className="animate-spin" /> Lecture de l’historique…
      </div>
    );
  }

  const jeu = etat?.game;
  const validation = etat?.validation;
  const equite = etat?.fairness;

  return (
    <div className="p-4 md:p-6 flex flex-col gap-4 max-w-4xl">
      <header>
        <h1 className="text-lg font-medium" style={{ color: 'var(--color-text)' }}>
          Grande Vie
        </h1>
        <p className="text-xs mt-1" style={sous}>
          {jeu
            ? `${jeu.pick} numéros parmi ${jeu.from}, plus un Grand Numéro parmi ${jeu.grandNumberFrom} — ${unSur(jeu.combinations)} combinaisons. Aussi appelée ${jeu.alsoKnownAs} hors du Québec : c’est le même tirage.`
            : null}
        </p>
      </header>

      {erreur ? (
        <div
          className="rounded-lg px-3 py-2 text-xs flex items-start gap-2"
          style={{ background: 'var(--color-bg-tertiary)', color: 'var(--color-danger, #f87171)' }}
        >
          <AlertTriangle size={13} className="mt-0.5 shrink-0" />
          {erreur}
        </div>
      ) : null}

      {/* ─── 1. LA MOISSON ─────────────────────────────────────────────── */}
      <Carte
        titre="L’historique"
        soustitre="Une seconde de repos entre deux pages — on ne martèle pas la source."
      >
        <div className="flex flex-wrap items-center gap-3 text-xs" style={sous}>
          <span className="tabular-nums">
            <strong style={{ color: 'var(--color-text)' }}>{etat?.drawCount ?? 0}</strong>{' '}
            tirages
          </span>
          {etat?.firstDraw ? (
            <span className="tabular-nums">
              du {etat.firstDraw} au {etat.lastDraw}
            </span>
          ) : (
            <span style={tertiaire}>rien encore — lancez la moisson</span>
          )}
          <button
            type="button"
            onClick={() => void lancerLaMoisson()}
            disabled={moissonEnCours}
            className="ml-auto h-8 px-3 rounded-lg text-xs flex items-center gap-1.5 cursor-pointer"
            style={{ background: 'var(--color-accent)', color: 'var(--color-bg)' }}
          >
            {moissonEnCours ? (
              <Loader2 size={13} className="animate-spin" />
            ) : (
              <Download size={13} />
            )}
            {moissonEnCours ? 'Moisson en cours…' : 'Moissonner'}
          </button>
        </div>
        {journalMoisson ? (
          <p className="text-[11px]" style={tertiaire}>
            {journalMoisson}
          </p>
        ) : null}
      </Carte>

      {/* ─── 2. LA VALIDATION CROISÉE ──────────────────────────────────── */}
      <Carte
        titre="Contrôle croisé"
        soustitre="L’archive est un tiers. On ne la croit pas : on la confronte aux fréquences publiées par Loto-Québec."
      >
        {validation ? (
          <>
            <div
              className="flex items-start gap-2 text-xs"
              style={{
                color: validation.agrees
                  ? 'var(--color-accent)'
                  : 'var(--color-danger, #f87171)',
              }}
            >
              {validation.agrees ? (
                <ShieldCheck size={14} className="mt-0.5 shrink-0" />
              ) : (
                <AlertTriangle size={14} className="mt-0.5 shrink-0" />
              )}
              <span>
                {validation.agrees
                  ? `Les 49 numéros concordent — ${validation.harvested} tirages, ${validation.sum} sorties.`
                  : validation.reason}
              </span>
            </div>
            <p className="text-[11px]" style={tertiaire}>
              Référence : {validation.reference.source}, relevée le{' '}
              {validation.reference.takenOn} — {validation.reference.draws} tirages du{' '}
              {validation.reference.from} au {validation.reference.to}.
            </p>
            {Object.keys(validation.mismatches).length > 0 ? (
              <p className="text-[11px]" style={{ color: 'var(--color-danger, #f87171)' }}>
                Divergences :{' '}
                {Object.entries(validation.mismatches)
                  .slice(0, 8)
                  .map(([n, v]) => `n°${n} (${v.harvested} ≠ ${v.official})`)
                  .join(', ')}
              </p>
            ) : null}
          </>
        ) : null}
      </Carte>

      {/* ─── 3. LE TEST D'ÉQUITÉ ───────────────────────────────────────── */}
      <Carte
        titre="Le tirage est-il équitable ?"
        soustitre="Test du khi-deux sur la fréquence des 49 numéros. C’est ce test qui répond à « existe-t-il des chiffres fiables ? »."
      >
        {!validation?.agrees ? (
          <p className="text-xs" style={tertiaire}>
            Rien n’est calculé tant que le contrôle croisé n’a pas accordé les données.
            Un test bâti sur des chiffres non vérifiés donnerait une assurance qu’il ne
            mérite pas.
          </p>
        ) : equite ? (
          <>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-xs">
              {[
                ['χ²', equite.chiSquare.toFixed(2)],
                ['degrés', String(equite.degreesOfFreedom)],
                ['valeur p', equite.pValue.toFixed(3)],
                ['attendu / numéro', equite.expectedPerNumber.toFixed(1)],
              ].map(([k, v]) => (
                <div key={k}>
                  <div className="tabular-nums text-sm" style={{ color: 'var(--color-text)' }}>
                    {v}
                  </div>
                  <div className="text-[10px]" style={tertiaire}>
                    {k}
                  </div>
                </div>
              ))}
            </div>
            <p
              className="text-xs flex items-start gap-2"
              style={{ color: equite.fair ? 'var(--color-accent)' : 'var(--color-danger, #f87171)' }}
            >
              <CheckCircle2 size={14} className="mt-0.5 shrink-0" />
              {lireLaValeurP(equite.pValue)}
            </p>
            {/* Le chiffre qui désarme l'idée de « numéro chaud ». */}
            <p className="text-[11px] leading-relaxed" style={sous}>
              Le plus sorti est le <strong>n° {equite.hottest.number}</strong> (
              {equite.hottest.count} fois, {equite.hottest.sigma.toFixed(2)} écart-type)
              et le moins sorti le <strong>n° {equite.coldest.number}</strong> (
              {equite.coldest.count} fois, {equite.coldest.sigma.toFixed(2)}). Sur 49
              numéros parfaitement équitables, le plus extrême l’est déjà d’environ{' '}
              {equite.expectedExtremeSigma.toFixed(2)} écart-type <em>par pur hasard</em>.
              Voir un numéro « chaud » ne prouve donc rien.
            </p>
          </>
        ) : (
          <p className="text-xs" style={tertiaire}>
            Moins de cent tirages : le test existerait, mais il ne saurait rien
            distinguer.
          </p>
        )}
      </Carte>

      {/* ─── 4. LE SIMULATEUR ──────────────────────────────────────────── */}
      <Carte
        titre="Simulateur"
        soustitre="Une vie de jeu en quelques secondes. Le tirage simulé est équitable — c’est le résultat du test ci-dessus, pas une hypothèse de confort."
      >
        <div className="flex flex-wrap items-end gap-3">
          <label className="flex flex-col gap-1 flex-1 min-w-[220px]">
            <span className="text-[11px]" style={tertiaire}>
              Votre grille — 5 numéros puis le Grand Numéro
            </span>
            <input
              value={saisie}
              onChange={(e) => setSaisie(e.target.value)}
              className="h-9 rounded-lg px-2.5 text-sm tabular-nums"
              style={{
                background: 'var(--color-bg)',
                color: 'var(--color-text)',
                border: `1px solid ${erreurGrille ? 'var(--color-danger, #f87171)' : 'var(--color-border)'}`,
              }}
            />
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-[11px]" style={tertiaire}>
              Années de jeu
            </span>
            <input
              type="number"
              min={1}
              max={200}
              value={annees}
              onChange={(e) => setAnnees(Math.max(1, Number(e.target.value) || 1))}
              className="h-9 w-24 rounded-lg px-2.5 text-sm tabular-nums"
              style={{
                background: 'var(--color-bg)',
                color: 'var(--color-text)',
                border: '1px solid var(--color-border)',
              }}
            />
          </label>
          <button
            type="button"
            disabled={!grille || simulationEnCours}
            onClick={() => grille && void lancerLaSimulation(grille)}
            className="h-9 px-3 rounded-lg text-xs flex items-center gap-1.5 cursor-pointer"
            style={{
              background: grille ? 'var(--color-accent)' : 'var(--color-bg-tertiary)',
              color: grille ? 'var(--color-bg)' : 'var(--color-text-tertiary)',
            }}
          >
            {simulationEnCours ? (
              <Loader2 size={13} className="animate-spin" />
            ) : (
              <Dices size={13} />
            )}
            Jouer {tiragesPourAnnees(annees).toLocaleString('fr-CA')} tirages
          </button>
        </div>
        {erreurGrille ? (
          <p className="text-[11px]" style={{ color: 'var(--color-danger, #f87171)' }}>
            {erreurGrille}
          </p>
        ) : null}

        {simulation ? (
          <div className="flex flex-col gap-2">
            <div className="grid grid-cols-3 gap-3 text-xs">
              {[
                ['misé', `${simulation.spent.toLocaleString('fr-CA')} $`],
                ['gagné', `${simulation.won.toLocaleString('fr-CA')} $`],
                ['solde', `${simulation.balance.toLocaleString('fr-CA')} $`],
              ].map(([k, v], i) => (
                <div key={k}>
                  <div
                    className="tabular-nums text-sm"
                    style={{
                      color:
                        i === 2
                          ? simulation.balance < 0
                            ? 'var(--color-danger, #f87171)'
                            : 'var(--color-accent)'
                          : 'var(--color-text)',
                    }}
                  >
                    {v}
                  </div>
                  <div className="text-[10px]" style={tertiaire}>
                    {k}
                  </div>
                </div>
              ))}
            </div>
            {Object.keys(simulation.byPrize).length > 0 ? (
              <ul className="text-[11px] flex flex-col gap-0.5" style={sous}>
                {Object.entries(simulation.byPrize)
                  .sort((a, b) => b[1] - a[1])
                  .map(([lot, fois]) => (
                    <li key={lot} className="tabular-nums">
                      {fois} × {lot}
                    </li>
                  ))}
              </ul>
            ) : (
              <p className="text-[11px]" style={tertiaire}>
                Aucun lot. Pas une seule fois.
              </p>
            )}
            <p className="text-[11px] leading-relaxed" style={tertiaire}>
              Ceci est <em>une</em> vie de jeu, pas la moyenne. Le retour moyen d’un
              billet vaut {simulation.expectedPerTicket.toFixed(2)} $ pour{' '}
              {simulation.ticketPrice} $ misés — et c’est un plafond, les deux plus gros
              lots étant comptés à leur valeur forfaitaire plutôt qu’en rente.
            </p>
          </div>
        ) : null}
      </Carte>

      {jeu ? (
        <Carte titre="Table des lots" soustitre="Cotes recalculées, pas recopiées.">
          <div className="overflow-x-auto">
            <table className="w-full text-[11px]" style={sous}>
              <thead>
                <tr style={tertiaire}>
                  <th className="text-left font-normal pb-1">Combinaison</th>
                  <th className="text-left font-normal pb-1">Lot</th>
                  <th className="text-right font-normal pb-1">Probabilité</th>
                </tr>
              </thead>
              <tbody>
                {jeu.prizes.map((lot) => (
                  <tr key={`${lot.matched}-${lot.grandNumber}`}>
                    <td className="py-0.5 tabular-nums">
                      {lot.matched} numéro{lot.matched > 1 ? 's' : ''}
                      {lot.grandNumber ? ' + Grand Numéro' : ''}
                    </td>
                    <td className="py-0.5">{lot.label}</td>
                    <td className="py-0.5 text-right tabular-nums">{unSur(lot.oneIn)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="text-[11px]" style={tertiaire}>
            Gagner quelque chose, si petit soit-il : {unSur(jeu.anyPrizeOdds)}.
          </p>
        </Carte>
      ) : null}
    </div>
  );
}
