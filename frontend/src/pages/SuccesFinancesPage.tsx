import { CadreVitre } from '../components/Glass/CadreVitre';
import { useCallback, useEffect, useMemo, useState, type CSSProperties, type ReactNode } from 'react';
import {
  Check,
  ChevronDown,
  CirclePlus,
  Loader2,
  Repeat2,
  Trash2,
  Upload,
  Wallet,
  X,
} from 'lucide-react';
import { toast } from 'sonner';

import {
  createFinanceAccount,
  createFinanceCategory,
  createFinanceGoal,
  createFinanceSubscription,
  createFinanceTransaction,
  deleteFinanceAccount,
  deleteFinanceBudget,
  deleteFinanceCategory,
  deleteFinanceGoal,
  deleteFinanceSubscription,
  deleteFinanceTransaction,
  fetchFinanceOverview,
  importFinanceCsv,
  listFinanceCategories,
  listFinanceSubscriptions,
  listFinanceTransactions,
  materializeFinanceSubscriptions,
  updateFinanceGoal,
  updateFinanceSubscription,
  upsertFinanceBudget,
} from '../features/succes/api';
import {
  CategoryDonutChart,
  IncomeExpenseBarChart,
  NetEvolutionChart,
} from '../features/succes/FinanceCharts';
import { EmojiPicker } from '../features/succes/EmojiPicker';
import { localIsoDate } from '../features/succes/habitCalendar';
import type {
  FinanceAccount,
  FinanceAccountType,
  FinanceBudget,
  FinanceBudgetScope,
  FinanceCategory,
  FinanceCategoryKind,
  FinanceGoal,
  FinanceOverview,
  FinancePeriod,
  FinanceSubCadence,
  FinanceSubscription,
  FinanceTransaction,
  FinanceTxnType,
} from '../features/succes/types';
import { useConfirm } from '../components/ConfirmDialog';
import { useAppStore } from '../lib/store';
import { useRefreshOnFocus } from '../features/succes/useRefreshOnFocus';
import { clesSucces, ecrireCache, lireCache } from '../features/succes/cacheSucces';

type SectionTab =
  | 'transactions'
  | 'subscriptions'
  | 'budgets'
  | 'accounts'
  | 'goals'
  | 'import';

const PERIODS: { id: FinancePeriod; label: string }[] = [
  { id: 'day', label: 'Jour' },
  { id: 'week', label: 'Semaine' },
  { id: 'month', label: 'Mois' },
  { id: 'year', label: 'Année' },
];

const SECTION_TABS: { id: SectionTab; label: string }[] = [
  { id: 'transactions', label: 'Transactions' },
  { id: 'subscriptions', label: 'Abonnements' },
  { id: 'budgets', label: 'Budgets' },
  { id: 'accounts', label: 'Comptes' },
  { id: 'goals', label: 'Objectifs' },
  { id: 'import', label: 'Import CSV' },
];

const ACCOUNT_TYPES: { id: FinanceAccountType; label: string }[] = [
  { id: 'checking', label: 'Chèque' },
  { id: 'savings', label: 'Épargne' },
  { id: 'cash', label: 'Espèces' },
  { id: 'credit', label: 'Crédit' },
  { id: 'other', label: 'Autre' },
];

const CADENCE_LABELS: Record<FinanceSubCadence, string> = {
  weekly: 'Hebdo',
  monthly: 'Mensuel',
  yearly: 'Annuel',
};

function formatCad(value: number, compact = false) {
  return new Intl.NumberFormat('fr-CA', {
    style: 'currency',
    currency: 'CAD',
    maximumFractionDigits: compact ? 0 : 2,
  }).format(value);
}

function deltaLabel(current: number, previous: number) {
  const delta = current - previous;
  if (Math.abs(delta) < 0.005) return 'stable vs période préc.';
  const sign = delta > 0 ? '+' : '';
  return `${sign}${formatCad(delta, true)} vs préc.`;
}

function currentYearMonth() {
  return localIsoDate().slice(0, 7);
}

function fieldStyle(): CSSProperties {
  return {
    border: '1px solid var(--color-border)',
    color: 'var(--color-text)',
    background: 'transparent',
  };
}

function surfaceStyle(extra?: CSSProperties): CSSProperties {
  return {
    background: 'var(--color-surface)',
    border: '1px solid var(--color-border)',
    ...extra,
  };
}

// Sous `sm`, chaque onglet montrait son formulaire (7 champs) AVANT la
// première ligne de sa liste : dans le mini-panneau, ouvrir « Transactions »
// ne montrait aucune transaction. La liste passe devant (`order`) et le
// formulaire se replie derrière le bouton « + » ; ouvert, il remonte en tête
// pour ne pas naître sous 200 lignes. Dès `sm`, l'ordre du DOM (formulaire
// d'abord) reprend : un premier jet gardait `order-2` jusqu'à `lg`, et entre
// 640 et 1023 px — le panneau étiré — le formulaire passait sous 200 lignes
// sans le « + » (lui `sm:hidden`) pour le remonter (revue du 16 sept. 2026).
// Le `order` ne sert donc que sous sm, où le formulaire est soit caché, soit
// remonté en tête. Audit du mini-panneau, 16 sept. 2026.
function formSlotClass(open: boolean) {
  return open ? 'max-sm:order-first' : 'max-sm:hidden';
}

// Sous sm la rangée défile en interne, barre masquée : sans le fondu du bord
// droit, « Objectifs » et « Import CSV » existaient sans que rien ne le dise
// (revue du 16 sept. 2026).
const PILL_ROW_CLASS =
  'flex gap-2 overflow-x-auto flex-nowrap sm:flex-wrap min-w-0 [scrollbar-width:none] max-sm:[mask-image:linear-gradient(to_right,#000_calc(100%-2.5rem),transparent)]';
const PILL_CLASS =
  'shrink-0 whitespace-nowrap px-3 py-1.5 rounded-xl text-sm font-medium cursor-pointer';

function pillStyle(active: boolean): CSSProperties {
  return {
    background: active ? 'var(--color-accent)' : 'var(--color-surface)',
    color: active ? '#fff' : 'var(--color-text-secondary)',
    border: `1px solid ${active ? 'var(--color-accent)' : 'var(--color-border)'}`,
  };
}

export function SuccesFinancesPage() {
  const confirm = useConfirm();
  const today = localIsoDate();
  const [period, setPeriod] = useState<FinancePeriod>('month');
  const [section, setSection] = useState<SectionTab>('transactions');
  // L'état initial vient du cache — la dernière réponse du serveur pour la
  // période d'ouverture (le mois). Chaque montage repartait de panneaux
  // vides qui disaient « Aucune transaction » avant la première réponse
  // (Carlito, 18 sept. 2026).
  const [overview, setOverview] = useState<FinanceOverview | null>(
    () => lireCache<FinanceOverview>(clesSucces.financesApercu('month', today)),
  );
  const [transactions, setTransactions] = useState<FinanceTransaction[]>(() => {
    const apercu = lireCache<FinanceOverview>(clesSucces.financesApercu('month', today));
    return (apercu && lireCache<FinanceTransaction[]>(clesSucces.financesTransactions(apercu.from, apercu.to))) ?? [];
  });
  const [categories, setCategories] = useState<FinanceCategory[]>(
    () => lireCache<FinanceCategory[]>(clesSucces.financesCategories()) ?? [],
  );
  const [subscriptions, setSubscriptions] = useState<FinanceSubscription[]>(
    () => lireCache<FinanceSubscription[]>(clesSucces.financesAbonnements()) ?? [],
  );
  // `loading` : le premier chargement sans cache seulement — les lignes
  // « Aucun… » se taisent tant qu'il dure. `rafraichit` tient le voyant
  // discret de l'en-tête pendant les relectures.
  const [loading, setLoading] = useState(() => lireCache(clesSucces.financesApercu('month', today)) === null);
  const [rafraichit, setRafraichit] = useState(false);
  const [saving, setSaving] = useState(false);
  // Trois états de MODE, pas de largeur : le CSS décide seul ce qui se voit à
  // quelle taille (règle 2 de docs/development/mini-panneau-responsive.md).
  const [formOpen, setFormOpen] = useState(false);
  const [moreCharts, setMoreCharts] = useState(false);
  // « Ajuster » passait par window.prompt, qui rend `null` sans dialogue dans
  // la WKWebView du panneau : le bouton semblait mort. Saisie en place.
  const [goalEdit, setGoalEdit] = useState<{ id: string; value: string } | null>(null);

  const [txnDraft, setTxnDraft] = useState({
    type: 'expense' as FinanceTxnType,
    amount: '',
    accountId: '',
    categoryId: '',
    transferAccountId: '',
    date: today,
    payee: '',
    notes: '',
  });
  const [subDraft, setSubDraft] = useState({
    name: '',
    amount: '',
    cadence: 'monthly' as FinanceSubCadence,
    nextDueDate: today,
    accountId: '',
    categoryId: '',
    reminderDays: '3',
    notes: '',
  });
  const [budgetDraft, setBudgetDraft] = useState({
    scope: 'global' as FinanceBudgetScope,
    categoryId: '',
    yearMonth: currentYearMonth(),
    limit: '',
  });
  const [accountDraft, setAccountDraft] = useState({
    name: '',
    type: 'checking' as FinanceAccountType,
    openingBalance: '0',
    color: '#6366f1',
    icon: '🏦',
  });
  const [goalDraft, setGoalDraft] = useState({
    name: '',
    target: '',
    current: '0',
    accountId: '',
    deadline: '',
    color: '#6366f1',
    icon: '🎯',
  });
  const [categoryDraft, setCategoryDraft] = useState({
    name: '',
    kind: 'expense' as FinanceCategoryKind,
    color: '#94a3b8',
    icon: '📦',
  });
  const [csvText, setCsvText] = useState('');
  const [csvAccountId, setCsvAccountId] = useState('');

  const accounts = overview?.accounts ?? [];
  const goals = overview?.goals ?? [];
  const budgets = overview?.budgets ?? [];

  const categoryById = useMemo(() => {
    const map = new Map<string, FinanceCategory>();
    for (const cat of categories) map.set(cat.id, cat);
    return map;
  }, [categories]);

  const accountById = useMemo(() => {
    const map = new Map<string, FinanceAccount>();
    for (const account of accounts) map.set(account.id, account);
    return map;
  }, [accounts]);

  const expenseCategories = useMemo(
    () => categories.filter((cat) => cat.kind === 'expense'),
    [categories],
  );
  const incomeCategories = useMemo(
    () => categories.filter((cat) => cat.kind === 'income'),
    [categories],
  );

  const load = useCallback(async () => {
    setRafraichit(true);
    try {
      const [nextOverview, nextCategories, nextSubs] = await Promise.all([
        fetchFinanceOverview(period, today),
        listFinanceCategories(),
        listFinanceSubscriptions(),
      ]);
      const nextTxns = await listFinanceTransactions({
        from: nextOverview.from,
        to: nextOverview.to,
        limit: 200,
      });
      // Une seule entrée persistée par ressource datée (aperçu, transactions) :
      // une par jour et par période s'accumulaient sans que rien ne les
      // relise ni ne les retire (revue du cache, 18 sept. 2026).
      // Le mois courant est ce que le montage relit : « Semaine » ou
      // « Année » ne doivent pas l'évincer du disque (contre-revue,
      // 18 sept. 2026).
      const moisEnCache = lireCache<FinanceOverview>(clesSucces.financesApercu('month', today));
      ecrireCache(clesSucces.financesApercu(period, today), nextOverview, {
        uniqueParRessource: true,
        conserver: [clesSucces.financesApercu('month', today)],
      });
      ecrireCache(clesSucces.financesCategories(), nextCategories);
      ecrireCache(clesSucces.financesAbonnements(), nextSubs);
      ecrireCache(clesSucces.financesTransactions(nextOverview.from, nextOverview.to), nextTxns, {
        uniqueParRessource: true,
        conserver: moisEnCache ? [clesSucces.financesTransactions(moisEnCache.from, moisEnCache.to)] : [],
      });
      setOverview(nextOverview);
      setCategories(nextCategories);
      setSubscriptions(nextSubs);
      setTransactions(nextTxns);

      const defaultAccount = nextOverview.accounts[0]?.id ?? '';
      setTxnDraft((prev) => ({
        ...prev,
        accountId: prev.accountId || defaultAccount,
        transferAccountId: prev.transferAccountId || defaultAccount,
      }));
      setSubDraft((prev) => ({ ...prev, accountId: prev.accountId || defaultAccount }));
      setGoalDraft((prev) => ({ ...prev, accountId: prev.accountId || defaultAccount }));
      setCsvAccountId((prev) => prev || defaultAccount);
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      useAppStore.getState().addLogEntry({
        timestamp: Date.now(),
        level: 'error',
        category: 'succes',
        message: `Finances : ${message}`,
      });
      toast.error('Les finances ne peuvent pas être chargées.', { description: message });
    } finally {
      setLoading(false);
      setRafraichit(false);
    }
  }, [period, today]);

  useEffect(() => {
    void load();
  }, [load]);

  // Une page ouverte gardait son état indéfiniment : ce qui change
  // ailleurs — téléphone, autre fenêtre, assistant — n'apparaissait
  // jamais. On relit au retour du focus.
  useRefreshOnFocus(() => void load());

  const runSave = async (action: () => Promise<void>, success: string) => {
    setSaving(true);
    try {
      await action();
      toast.success(success, { description: 'Enregistré localement sur ce Mac.' });
      await load();
    } catch (error) {
      toast.error("L'opération a échoué.", {
        description: error instanceof Error ? error.message : String(error),
      });
    } finally {
      setSaving(false);
    }
  };

  const saveTransaction = () => {
    const amount = Number(txnDraft.amount.replace(',', '.'));
    if (!txnDraft.accountId || !(amount > 0)) {
      toast.warning('Compte et montant sont obligatoires.');
      return;
    }
    if (txnDraft.type === 'transfer' && !txnDraft.transferAccountId) {
      toast.warning('Choisissez le compte destinataire.');
      return;
    }
    void runSave(async () => {
      await createFinanceTransaction({
        accountId: txnDraft.accountId,
        type: txnDraft.type,
        amount,
        date: txnDraft.date || today,
        categoryId: txnDraft.type === 'transfer' ? '' : txnDraft.categoryId,
        payee: txnDraft.payee,
        notes: txnDraft.notes,
        transferAccountId: txnDraft.type === 'transfer' ? txnDraft.transferAccountId : '',
      });
      setTxnDraft((prev) => ({
        ...prev,
        amount: '',
        payee: '',
        notes: '',
        date: today,
      }));
      setFormOpen(false);
    }, 'Transaction ajoutée');
  };

  const saveSubscription = () => {
    const amount = Number(subDraft.amount.replace(',', '.'));
    if (!subDraft.name.trim() || !(amount > 0)) {
      toast.warning('Nom et montant sont obligatoires.');
      return;
    }
    void runSave(async () => {
      await createFinanceSubscription({
        name: subDraft.name.trim(),
        amount,
        cadence: subDraft.cadence,
        nextDueDate: subDraft.nextDueDate || today,
        accountId: subDraft.accountId,
        categoryId: subDraft.categoryId,
        reminderDays: Number(subDraft.reminderDays) || 3,
        notes: subDraft.notes,
      });
      setSubDraft((prev) => ({
        ...prev,
        name: '',
        amount: '',
        notes: '',
        nextDueDate: today,
      }));
      setFormOpen(false);
    }, 'Abonnement créé');
  };

  const saveBudget = () => {
    const limit = Number(budgetDraft.limit.replace(',', '.'));
    if (!(limit > 0)) {
      toast.warning('La limite doit être positive.');
      return;
    }
    if (budgetDraft.scope === 'category' && !budgetDraft.categoryId) {
      toast.warning('Choisissez une catégorie.');
      return;
    }
    void runSave(async () => {
      await upsertFinanceBudget({
        scope: budgetDraft.scope,
        categoryId: budgetDraft.scope === 'category' ? budgetDraft.categoryId : '',
        yearMonth: budgetDraft.yearMonth || currentYearMonth(),
        limit,
      });
      setBudgetDraft((prev) => ({ ...prev, limit: '' }));
      setFormOpen(false);
    }, 'Budget enregistré');
  };

  const saveAccount = () => {
    if (!accountDraft.name.trim()) {
      toast.warning('Le nom du compte est obligatoire.');
      return;
    }
    void runSave(async () => {
      await createFinanceAccount({
        name: accountDraft.name.trim(),
        type: accountDraft.type,
        openingBalance: Number(accountDraft.openingBalance.replace(',', '.')) || 0,
        color: accountDraft.color,
        icon: accountDraft.icon,
      });
      setAccountDraft({
        name: '',
        type: 'checking',
        openingBalance: '0',
        color: '#6366f1',
        icon: '🏦',
      });
      setFormOpen(false);
    }, 'Compte créé');
  };

  const saveGoal = () => {
    const target = Number(goalDraft.target.replace(',', '.'));
    if (!goalDraft.name.trim() || !(target > 0)) {
      toast.warning('Nom et cible sont obligatoires.');
      return;
    }
    void runSave(async () => {
      await createFinanceGoal({
        name: goalDraft.name.trim(),
        target,
        current: Number(goalDraft.current.replace(',', '.')) || 0,
        accountId: goalDraft.accountId,
        deadline: goalDraft.deadline,
        color: goalDraft.color,
        icon: goalDraft.icon,
      });
      setGoalDraft({
        name: '',
        target: '',
        current: '0',
        accountId: accounts[0]?.id ?? '',
        deadline: '',
        color: '#6366f1',
        icon: '🎯',
      });
      setFormOpen(false);
    }, 'Objectif créé');
  };

  const saveCategory = () => {
    if (!categoryDraft.name.trim()) {
      toast.warning('Le nom de la catégorie est obligatoire.');
      return;
    }
    void runSave(async () => {
      await createFinanceCategory({
        name: categoryDraft.name.trim(),
        kind: categoryDraft.kind,
        color: categoryDraft.color,
        icon: categoryDraft.icon,
      });
      setCategoryDraft({ name: '', kind: 'expense', color: '#94a3b8', icon: '📦' });
      setFormOpen(false);
    }, 'Catégorie créée');
  };

  const removeTransaction = async (txn: FinanceTransaction) => {
    const confirmed = await confirm({
      title: 'Supprimer cette transaction ?',
      description: `${txn.payee || txn.type} — ${formatCad(txn.amount)}`,
      confirmLabel: 'Supprimer',
      keepLabel: 'Garder',
      tone: 'danger',
    });
    if (!confirmed) return;
    void runSave(async () => {
      await deleteFinanceTransaction(txn.id);
    }, 'Transaction supprimée');
  };

  const removeSubscription = async (sub: FinanceSubscription) => {
    const confirmed = await confirm({
      title: `Supprimer l’abonnement « ${sub.name} » ?`,
      description: 'Les transactions déjà créées restent en place.',
      confirmLabel: 'Supprimer',
      keepLabel: 'Garder',
      tone: 'danger',
    });
    if (!confirmed) return;
    void runSave(async () => {
      await deleteFinanceSubscription(sub.id);
    }, 'Abonnement supprimé');
  };

  const removeBudget = async (budget: FinanceBudget) => {
    const label =
      budget.scope === 'global'
        ? 'Budget global'
        : categoryById.get(budget.categoryId)?.name || 'Budget catégorie';
    const confirmed = await confirm({
      title: `Supprimer « ${label} » ?`,
      description: `${budget.yearMonth} — limite ${formatCad(budget.limit)}`,
      confirmLabel: 'Supprimer',
      keepLabel: 'Garder',
      tone: 'danger',
    });
    if (!confirmed) return;
    void runSave(async () => {
      await deleteFinanceBudget(budget.id);
    }, 'Budget supprimé');
  };

  const removeAccount = async (account: FinanceAccount) => {
    const confirmed = await confirm({
      title: `Supprimer le compte « ${account.name} » ?`,
      description: 'Impossible s’il contient encore des transactions.',
      confirmLabel: 'Supprimer',
      keepLabel: 'Garder',
      tone: 'danger',
    });
    if (!confirmed) return;
    void runSave(async () => {
      await deleteFinanceAccount(account.id);
    }, 'Compte supprimé');
  };

  const removeGoal = async (goal: FinanceGoal) => {
    const confirmed = await confirm({
      title: `Supprimer l’objectif « ${goal.name} » ?`,
      description: 'La progression enregistrée sera perdue.',
      confirmLabel: 'Supprimer',
      keepLabel: 'Garder',
      tone: 'danger',
    });
    if (!confirmed) return;
    void runSave(async () => {
      await deleteFinanceGoal(goal.id);
    }, 'Objectif supprimé');
  };

  const commitGoalEdit = (goal: FinanceGoal) => {
    if (!goalEdit || goalEdit.id !== goal.id) return;
    const current = Number(goalEdit.value.replace(',', '.'));
    if (!(current >= 0)) {
      toast.warning('Montant invalide.');
      return;
    }
    setGoalEdit(null);
    void runSave(async () => {
      await updateFinanceGoal(goal.id, { current });
    }, 'Progression mise à jour');
  };

  const removeCategory = async (category: FinanceCategory) => {
    if (category.system) {
      toast.info('Les catégories système ne peuvent pas être supprimées.');
      return;
    }
    const confirmed = await confirm({
      title: `Supprimer « ${category.name} » ?`,
      description: 'Les transactions existantes garderont un lien vide.',
      confirmLabel: 'Supprimer',
      keepLabel: 'Garder',
      tone: 'danger',
    });
    if (!confirmed) return;
    void runSave(async () => {
      await deleteFinanceCategory(category.id);
    }, 'Catégorie supprimée');
  };

  const materializeSubs = async () => {
    setSaving(true);
    try {
      const result = await materializeFinanceSubscriptions();
      if (result.count) {
        toast.success(
          `${result.count} abonnement${result.count > 1 ? 's' : ''} matérialisé${result.count > 1 ? 's' : ''}`,
          { description: 'Transactions créées localement sur ce Mac.' },
        );
        await load();
      } else {
        toast.message('Aucun abonnement dû pour aujourd’hui');
      }
    } catch (error) {
      toast.error("L'opération a échoué.", {
        description: error instanceof Error ? error.message : String(error),
      });
    } finally {
      setSaving(false);
    }
  };

  const runCsvImport = () => {
    if (!csvText.trim() || !csvAccountId) {
      toast.warning('Collez un CSV et choisissez un compte.');
      return;
    }
    void runSave(async () => {
      const summary = await importFinanceCsv({
        csvText,
        accountId: csvAccountId,
      });
      if (summary.errors.length) {
        toast.message(`${summary.created} importée(s), ${summary.skipped} ignorée(s)`, {
          description: summary.errors.slice(0, 3).join(' · '),
        });
      }
      setCsvText('');
    }, 'Import terminé');
  };

  const txnCategoryOptions =
    txnDraft.type === 'income' ? incomeCategories : expenseCategories;

  return (
    <div data-verre-defilement className="flex-1 overflow-y-auto px-3 py-4 sm:px-5 sm:py-8 md:px-8 md:py-10">
      <main className="max-w-6xl mx-auto w-full">
        {/* À 460 px, ~1 400 px de décor précédaient la première donnée
            actionnable (audit du 16 sept. 2026). Sous sm l'en-tête tient sur
            une rangée : sous-titre tu, bouton réduit à son icône. */}
        <header className="flex flex-row items-end justify-between gap-3 mb-4 sm:mb-7">
          <div className="min-w-0">
            <div className="flex items-center gap-2 mb-1 sm:mb-2">
              <span
                className="text-xs font-medium tracking-[0.16em] uppercase"
                style={{ color: 'var(--color-accent)' }}
              >
                Succès
              </span>
              {(loading || rafraichit || saving) && (
                <Loader2 size={13} className="animate-spin" style={{ color: 'var(--color-accent)' }} />
              )}
            </div>
            <h1 className="text-2xl font-semibold" style={{ color: 'var(--color-text)' }}>
              Finances
            </h1>
            <p className="hidden sm:block text-sm mt-2" style={{ color: 'var(--color-text-secondary)' }}>
              Budget CAD local — revenus, dépenses, abonnements et objectifs sur ce Mac.
            </p>
          </div>
          <button
            type="button"
            onClick={() => void materializeSubs()}
            aria-label="Matérialiser les abonnements dus"
            title="Matérialiser les abonnements dus"
            className="flex items-center gap-2 px-3 py-2 rounded-xl text-sm font-medium cursor-pointer shrink-0"
            style={{
              background: 'var(--color-bg-secondary)',
              color: 'var(--color-text-secondary)',
              border: '1px solid var(--color-border)',
            }}
          >
            <Repeat2 size={16} />
            <span className="hidden sm:inline">Matérialiser les dus</span>
          </button>
        </header>

        <div className={`${PILL_ROW_CLASS} mb-4 sm:mb-5`}>
          {PERIODS.map((item) => {
            const active = period === item.id;
            return (
              <button
                key={item.id}
                type="button"
                onClick={() => setPeriod(item.id)}
                aria-pressed={active}
                className={PILL_CLASS}
                style={pillStyle(active)}
              >
                {item.label}
              </button>
            );
          })}
        </div>

        {/* Deux colonnes dès 340 px : cinq cartes empilées coûtaient ~480 px.
            La cinquième (le compte de transactions) n'apparaît qu'à partir
            de sm — la liste en dessous porte déjà ce nombre dans son titre. */}
        <section className="grid grid-cols-2 gap-2 sm:gap-3 lg:grid-cols-5 mb-4 sm:mb-5">
          <KpiCard
            icon="↑"
            label="Revenus"
            value={overview ? formatCad(overview.income) : '—'}
            hint={overview ? deltaLabel(overview.income, overview.prevIncome) : ''}
            tone="success"
          />
          <KpiCard
            icon="↓"
            label="Dépenses"
            value={overview ? formatCad(overview.expense) : '—'}
            hint={overview ? deltaLabel(overview.expense, overview.prevExpense) : ''}
            tone="error"
          />
          <KpiCard
            icon="Σ"
            label="Net"
            value={overview ? formatCad(overview.net) : '—'}
            hint={overview ? deltaLabel(overview.net, overview.prevNet) : ''}
          />
          <KpiCard
            icon="⏳"
            label="Reste prévu"
            value={overview ? formatCad(overview.forecastRemaining) : '—'}
            hint={
              overview
                ? `Prévision dépenses ${formatCad(overview.forecastExpense, true)}`
                : ''
            }
          />
          <KpiCard
            icon={<Wallet size={18} />}
            label="Transactions"
            value={overview ? String(overview.transactionCount) : '—'}
            hint={
              overview
                ? `${overview.from.slice(5)} → ${overview.to.slice(5)}`
                : ''
            }
            secondary
          />
        </section>

        {/* Trois graphiques de 260 px empilés = ~780 px dans un panneau de
            620 : sous sm, seule la répartition reste visible, les deux autres
            se déplient à la demande (`contents` les rend enfants de la grille
            une fois révélés, sans wrapper qui casserait les colonnes). */}
        <section className="grid gap-3 lg:grid-cols-3 mb-4 sm:mb-5">
          <CategoryDonutChart data={overview?.categoryBreakdown ?? []} />
          <div className={moreCharts ? 'contents' : 'hidden sm:contents'}>
            <IncomeExpenseBarChart data={overview?.series ?? []} />
            <NetEvolutionChart data={overview?.series ?? []} />
          </div>
          <button
            type="button"
            onClick={() => setMoreCharts((prev) => !prev)}
            aria-expanded={moreCharts}
            className="sm:hidden flex items-center justify-center gap-1.5 py-1.5 rounded-xl text-xs font-medium cursor-pointer"
            style={{
              color: 'var(--color-text-secondary)',
              border: '1px dashed var(--color-border)',
            }}
          >
            <ChevronDown
              size={14}
              className="transition-transform"
              style={{ transform: moreCharts ? 'rotate(180deg)' : undefined }}
            />
            {moreCharts ? 'Masquer les deux autres graphiques' : 'Revenus vs dépenses, solde net'}
          </button>
        </section>

        <section className="grid gap-3 lg:grid-cols-3 mb-4 sm:mb-6">
          <Panel title="Alertes budget">
            {!budgets.length && (
              <EmptyLine attente={loading} text="Aucun budget pour ce mois." />
            )}
            {budgets.map((budget) => {
              const name =
                budget.scope === 'global'
                  ? 'Budget global'
                  : categoryById.get(budget.categoryId)?.name || 'Catégorie';
              const pct = Math.min(100, budget.pct ?? 0);
              return (
                <div key={budget.id} className="mb-3 last:mb-0">
                  <div className="flex items-center justify-between gap-2 mb-1">
                    <span
                      className="text-sm font-medium"
                      style={{ color: budget.over ? 'var(--color-error)' : 'var(--color-text)' }}
                    >
                      {name}
                      {budget.over ? ' · dépassé' : ''}
                    </span>
                    <span className="text-xs tabular-nums" style={{ color: 'var(--color-text-tertiary)' }}>
                      {formatCad(budget.spent ?? 0)} / {formatCad(budget.limit)}
                    </span>
                  </div>
                  <div
                    className="h-2 rounded-full overflow-hidden"
                    style={{ background: 'var(--color-bg-secondary)' }}
                  >
                    <div
                      className="h-full rounded-full"
                      style={{
                        width: `${pct}%`,
                        background: budget.over ? 'var(--color-error)' : 'var(--color-accent)',
                      }}
                    />
                  </div>
                </div>
              );
            })}
          </Panel>

          <Panel title="Abonnements à venir">
            {!(overview?.upcomingSubscriptions.length) && (
              <EmptyLine attente={loading} text="Rien d’imminent sur 14 jours." />
            )}
            {(overview?.upcomingSubscriptions ?? []).map((sub) => (
              <div
                key={sub.id}
                className="flex items-center justify-between gap-2 py-2 border-b last:border-b-0"
                style={{ borderColor: 'var(--color-border)' }}
              >
                <div>
                  <p className="text-sm font-medium" style={{ color: 'var(--color-text)' }}>
                    {sub.name}
                  </p>
                  <p className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
                    {sub.nextDueDate} · {CADENCE_LABELS[sub.cadence]}
                  </p>
                </div>
                <span className="text-sm tabular-nums" style={{ color: 'var(--color-text)' }}>
                  {formatCad(sub.amount)}
                </span>
              </div>
            ))}
          </Panel>

          <Panel title="Objectifs d’épargne">
            {!goals.length && <EmptyLine attente={loading} text="Aucun objectif pour l’instant." />}
            {goals.map((goal) => {
              const pct = goal.target > 0 ? Math.min(100, (goal.current / goal.target) * 100) : 0;
              return (
                <div key={goal.id} className="mb-3 last:mb-0">
                  <div className="flex items-center justify-between gap-2 mb-1">
                    <span className="text-sm font-medium" style={{ color: 'var(--color-text)' }}>
                      {goal.icon} {goal.name}
                    </span>
                    <span className="text-xs tabular-nums" style={{ color: 'var(--color-text-tertiary)' }}>
                      {formatCad(goal.current)} / {formatCad(goal.target)}
                    </span>
                  </div>
                  <div
                    className="h-2 rounded-full overflow-hidden"
                    style={{ background: 'var(--color-bg-secondary)' }}
                  >
                    <div
                      className="h-full rounded-full"
                      style={{ width: `${pct}%`, background: goal.color || 'var(--color-accent)' }}
                    />
                  </div>
                </div>
              );
            })}
          </Panel>
        </section>

        {/* Six onglets qui pliaient sur trois rangées : une seule rangée qui
            défile en interne (jamais la page), et le « + » qui déplie le
            formulaire de l'onglet courant, ancré à droite, sous sm seulement —
            à partir de sm les formulaires sont toujours visibles. */}
        <div className="flex items-center gap-2 mb-4">
          <div className={`${PILL_ROW_CLASS} flex-1`} role="tablist" aria-label="Sections">
            {SECTION_TABS.map((tab) => {
              const active = section === tab.id;
              return (
                <button
                  key={tab.id}
                  type="button"
                  role="tab"
                  aria-selected={active}
                  onClick={() => {
                    setSection(tab.id);
                    setFormOpen(false);
                  }}
                  className={PILL_CLASS}
                  style={pillStyle(active)}
                >
                  {tab.label}
                </button>
              );
            })}
          </div>
          {section !== 'import' && (
            <button
              type="button"
              onClick={() => setFormOpen((prev) => !prev)}
              aria-expanded={formOpen}
              aria-label={formOpen ? 'Replier le formulaire' : 'Ajouter'}
              title={formOpen ? 'Replier le formulaire' : 'Ajouter'}
              className="sm:hidden size-8 shrink-0 rounded-xl flex items-center justify-center cursor-pointer"
              style={{
                background: formOpen ? 'var(--color-bg-secondary)' : 'var(--color-accent)',
                color: formOpen ? 'var(--color-text-secondary)' : '#fff',
                border: `1px solid ${formOpen ? 'var(--color-border)' : 'var(--color-accent)'}`,
              }}
            >
              {formOpen ? <X size={16} /> : <CirclePlus size={16} />}
            </button>
          )}
        </div>

        {section === 'transactions' && (
          <section className="grid gap-4 lg:grid-cols-[340px_1fr]">
            <FormCard title="Ajouter une transaction" className={formSlotClass(formOpen)}>
              <select
                value={txnDraft.type}
                onChange={(event) =>
                  setTxnDraft({
                    ...txnDraft,
                    type: event.target.value as FinanceTxnType,
                    categoryId: '',
                  })
                }
                className="rounded-xl px-3 py-2 text-sm outline-none"
                style={fieldStyle()}
              >
                <option value="expense">Dépense</option>
                <option value="income">Revenu</option>
                <option value="transfer">Virement</option>
              </select>
              <input
                type="number"
                min="0"
                step="0.01"
                placeholder="Montant ($)"
                value={txnDraft.amount}
                onChange={(event) => setTxnDraft({ ...txnDraft, amount: event.target.value })}
                className="rounded-xl px-3 py-2 text-sm outline-none"
                style={fieldStyle()}
              />
              <select
                value={txnDraft.accountId}
                onChange={(event) => setTxnDraft({ ...txnDraft, accountId: event.target.value })}
                className="rounded-xl px-3 py-2 text-sm outline-none"
                style={fieldStyle()}
              >
                <option value="">Compte</option>
                {accounts.map((account) => (
                  <option key={account.id} value={account.id}>
                    {account.icon} {account.name}
                  </option>
                ))}
              </select>
              {txnDraft.type === 'transfer' ? (
                <select
                  value={txnDraft.transferAccountId}
                  onChange={(event) =>
                    setTxnDraft({ ...txnDraft, transferAccountId: event.target.value })
                  }
                  className="rounded-xl px-3 py-2 text-sm outline-none"
                  style={fieldStyle()}
                >
                  <option value="">Vers le compte</option>
                  {accounts.map((account) => (
                    <option key={account.id} value={account.id}>
                      {account.icon} {account.name}
                    </option>
                  ))}
                </select>
              ) : (
                <select
                  value={txnDraft.categoryId}
                  onChange={(event) => setTxnDraft({ ...txnDraft, categoryId: event.target.value })}
                  className="rounded-xl px-3 py-2 text-sm outline-none"
                  style={fieldStyle()}
                >
                  <option value="">Catégorie</option>
                  {txnCategoryOptions.map((cat) => (
                    <option key={cat.id} value={cat.id}>
                      {cat.icon} {cat.name}
                    </option>
                  ))}
                </select>
              )}
              <input
                type="date"
                value={txnDraft.date}
                onChange={(event) => setTxnDraft({ ...txnDraft, date: event.target.value })}
                className="rounded-xl px-3 py-2 text-sm outline-none"
                style={fieldStyle()}
              />
              <input
                value={txnDraft.payee}
                onChange={(event) => setTxnDraft({ ...txnDraft, payee: event.target.value })}
                placeholder="Bénéficiaire / libellé"
                className="rounded-xl px-3 py-2 text-sm outline-none"
                style={fieldStyle()}
              />
              <textarea
                value={txnDraft.notes}
                onChange={(event) => setTxnDraft({ ...txnDraft, notes: event.target.value })}
                placeholder="Notes"
                rows={2}
                className="rounded-xl px-3 py-2 text-sm outline-none resize-none"
                style={fieldStyle()}
              />
              <PrimaryButton onClick={saveTransaction} disabled={saving}>
                <CirclePlus size={16} /> Ajouter
              </PrimaryButton>
            </FormCard>

            <Panel title={`Liste (${transactions.length})`}>
              {!transactions.length && <EmptyLine attente={loading} text="Aucune transaction sur cette période." />}
              {transactions.map((txn) => {
                const cat = categoryById.get(txn.categoryId);
                const account = accountById.get(txn.accountId);
                const sign = txn.type === 'income' ? '+' : txn.type === 'expense' ? '−' : '↔';
                return (
                  <div
                    key={txn.id}
                    className="flex items-start justify-between gap-3 py-2.5 border-b last:border-b-0"
                    style={{ borderColor: 'var(--color-border)' }}
                  >
                    <div className="min-w-0">
                      <p className="text-sm font-medium truncate" style={{ color: 'var(--color-text)' }}>
                        {txn.payee || cat?.name || txn.type}
                      </p>
                      <p className="text-xs mt-0.5" style={{ color: 'var(--color-text-tertiary)' }}>
                        {txn.date} · {account?.name || 'Compte'}
                        {cat ? ` · ${cat.icon} ${cat.name}` : ''}
                      </p>
                    </div>
                    <div className="flex items-center gap-2 shrink-0">
                      <span
                        className="text-sm tabular-nums font-medium"
                        style={{
                          color:
                            txn.type === 'income'
                              ? 'var(--color-success)'
                              : txn.type === 'expense'
                                ? 'var(--color-error)'
                                : 'var(--color-text)',
                        }}
                      >
                        {sign}
                        {formatCad(txn.amount)}
                      </span>
                      <IconButton label="Supprimer" onClick={() => void removeTransaction(txn)}>
                        <Trash2 size={14} />
                      </IconButton>
                    </div>
                  </div>
                );
              })}
            </Panel>
          </section>
        )}

        {section === 'subscriptions' && (
          <section className="grid gap-4 lg:grid-cols-[340px_1fr]">
            <FormCard title="Nouvel abonnement" className={formSlotClass(formOpen)}>
              <input
                value={subDraft.name}
                onChange={(event) => setSubDraft({ ...subDraft, name: event.target.value })}
                placeholder="Nom (Netflix, gym…)"
                className="rounded-xl px-3 py-2 text-sm outline-none"
                style={fieldStyle()}
              />
              <input
                type="number"
                min="0"
                step="0.01"
                value={subDraft.amount}
                onChange={(event) => setSubDraft({ ...subDraft, amount: event.target.value })}
                placeholder="Montant ($)"
                className="rounded-xl px-3 py-2 text-sm outline-none"
                style={fieldStyle()}
              />
              <select
                value={subDraft.cadence}
                onChange={(event) =>
                  setSubDraft({ ...subDraft, cadence: event.target.value as FinanceSubCadence })
                }
                className="rounded-xl px-3 py-2 text-sm outline-none"
                style={fieldStyle()}
              >
                <option value="weekly">Hebdomadaire</option>
                <option value="monthly">Mensuel</option>
                <option value="yearly">Annuel</option>
              </select>
              <input
                type="date"
                value={subDraft.nextDueDate}
                onChange={(event) => setSubDraft({ ...subDraft, nextDueDate: event.target.value })}
                className="rounded-xl px-3 py-2 text-sm outline-none"
                style={fieldStyle()}
              />
              <select
                value={subDraft.accountId}
                onChange={(event) => setSubDraft({ ...subDraft, accountId: event.target.value })}
                className="rounded-xl px-3 py-2 text-sm outline-none"
                style={fieldStyle()}
              >
                <option value="">Compte (optionnel)</option>
                {accounts.map((account) => (
                  <option key={account.id} value={account.id}>
                    {account.icon} {account.name}
                  </option>
                ))}
              </select>
              <select
                value={subDraft.categoryId}
                onChange={(event) => setSubDraft({ ...subDraft, categoryId: event.target.value })}
                className="rounded-xl px-3 py-2 text-sm outline-none"
                style={fieldStyle()}
              >
                <option value="">Catégorie</option>
                {expenseCategories.map((cat) => (
                  <option key={cat.id} value={cat.id}>
                    {cat.icon} {cat.name}
                  </option>
                ))}
              </select>
              <PrimaryButton onClick={saveSubscription} disabled={saving}>
                <CirclePlus size={16} /> Créer
              </PrimaryButton>
            </FormCard>

            <Panel title={`Abonnements (${subscriptions.length})`}>
              {!subscriptions.length && <EmptyLine attente={loading} text="Aucun abonnement enregistré." />}
              {subscriptions.map((sub) => (
                <div
                  key={sub.id}
                  className="flex items-start justify-between gap-3 py-2.5 border-b last:border-b-0"
                  style={{ borderColor: 'var(--color-border)' }}
                >
                  <div className="min-w-0">
                    <p className="text-sm font-medium truncate" style={{ color: 'var(--color-text)' }}>
                      {sub.name}
                      {!sub.active && (
                        <span className="ml-2 text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
                          pause
                        </span>
                      )}
                    </p>
                    <p className="text-xs mt-0.5" style={{ color: 'var(--color-text-tertiary)' }}>
                      {formatCad(sub.amount)} · {CADENCE_LABELS[sub.cadence]} · prochain {sub.nextDueDate}
                    </p>
                  </div>
                  <div className="flex items-center gap-1 shrink-0">
                    <button
                      type="button"
                      onClick={() =>
                        void runSave(async () => {
                          await updateFinanceSubscription(sub.id, { active: !sub.active });
                        }, sub.active ? 'Abonnement en pause' : 'Abonnement réactivé')
                      }
                      className="px-2 py-1 rounded-lg text-xs cursor-pointer"
                      style={{
                        background: 'var(--color-bg-secondary)',
                        color: 'var(--color-text-secondary)',
                        border: '1px solid var(--color-border)',
                      }}
                    >
                      {sub.active ? 'Pause' : 'Activer'}
                    </button>
                    <IconButton label="Supprimer" onClick={() => void removeSubscription(sub)}>
                      <Trash2 size={14} />
                    </IconButton>
                  </div>
                </div>
              ))}
            </Panel>
          </section>
        )}

        {section === 'budgets' && (
          <section className="grid gap-4 lg:grid-cols-[340px_1fr]">
            <FormCard title="Définir un budget" className={formSlotClass(formOpen)}>
              <select
                value={budgetDraft.scope}
                onChange={(event) =>
                  setBudgetDraft({
                    ...budgetDraft,
                    scope: event.target.value as FinanceBudgetScope,
                  })
                }
                className="rounded-xl px-3 py-2 text-sm outline-none"
                style={fieldStyle()}
              >
                <option value="global">Global (toutes dépenses)</option>
                <option value="category">Par catégorie</option>
              </select>
              {budgetDraft.scope === 'category' && (
                <select
                  value={budgetDraft.categoryId}
                  onChange={(event) =>
                    setBudgetDraft({ ...budgetDraft, categoryId: event.target.value })
                  }
                  className="rounded-xl px-3 py-2 text-sm outline-none"
                  style={fieldStyle()}
                >
                  <option value="">Catégorie</option>
                  {expenseCategories.map((cat) => (
                    <option key={cat.id} value={cat.id}>
                      {cat.icon} {cat.name}
                    </option>
                  ))}
                </select>
              )}
              <input
                type="month"
                value={budgetDraft.yearMonth}
                onChange={(event) =>
                  setBudgetDraft({ ...budgetDraft, yearMonth: event.target.value })
                }
                className="rounded-xl px-3 py-2 text-sm outline-none"
                style={fieldStyle()}
              />
              <input
                type="number"
                min="0"
                step="0.01"
                value={budgetDraft.limit}
                onChange={(event) => setBudgetDraft({ ...budgetDraft, limit: event.target.value })}
                placeholder="Limite ($)"
                className="rounded-xl px-3 py-2 text-sm outline-none"
                style={fieldStyle()}
              />
              <PrimaryButton onClick={saveBudget} disabled={saving}>
                <CirclePlus size={16} /> Enregistrer
              </PrimaryButton>
            </FormCard>

            <Panel title="Budgets du mois">
              {!budgets.length && <EmptyLine attente={loading} text="Aucun budget défini." />}
              {budgets.map((budget) => {
                const name =
                  budget.scope === 'global'
                    ? 'Budget global'
                    : categoryById.get(budget.categoryId)?.name || 'Catégorie';
                return (
                  <div
                    key={budget.id}
                    className="flex items-center justify-between gap-3 py-2.5 border-b last:border-b-0"
                    style={{ borderColor: 'var(--color-border)' }}
                  >
                    <div className="min-w-0">
                      <p
                        className="text-sm font-medium truncate"
                        style={{ color: budget.over ? 'var(--color-error)' : 'var(--color-text)' }}
                      >
                        {name}
                      </p>
                      <p className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
                        {budget.yearMonth} · {formatCad(budget.spent ?? 0)} / {formatCad(budget.limit)}
                        {budget.over ? ' · dépassé' : ''}
                      </p>
                    </div>
                    <IconButton label="Supprimer" onClick={() => void removeBudget(budget)}>
                      <Trash2 size={14} />
                    </IconButton>
                  </div>
                );
              })}
            </Panel>
          </section>
        )}

        {section === 'accounts' && (
          <section className="grid gap-4 lg:grid-cols-[340px_1fr]">
            <div className={`space-y-4 ${formSlotClass(formOpen)}`}>
              <FormCard title="Nouveau compte">
                <div className="grid grid-cols-[56px_1fr] gap-2">
                  <EmojiPicker
                    value={accountDraft.icon}
                    onChange={(icon) => setAccountDraft({ ...accountDraft, icon })}
                    aria-label="Icône du compte"
                  />
                  <input
                    value={accountDraft.name}
                    onChange={(event) => setAccountDraft({ ...accountDraft, name: event.target.value })}
                    placeholder="Nom du compte"
                    className="rounded-xl px-3 py-2 text-sm outline-none"
                    style={fieldStyle()}
                  />
                </div>
                <select
                  value={accountDraft.type}
                  onChange={(event) =>
                    setAccountDraft({
                      ...accountDraft,
                      type: event.target.value as FinanceAccountType,
                    })
                  }
                  className="rounded-xl px-3 py-2 text-sm outline-none"
                  style={fieldStyle()}
                >
                  {ACCOUNT_TYPES.map((type) => (
                    <option key={type.id} value={type.id}>
                      {type.label}
                    </option>
                  ))}
                </select>
                <input
                  type="number"
                  step="0.01"
                  value={accountDraft.openingBalance}
                  onChange={(event) =>
                    setAccountDraft({ ...accountDraft, openingBalance: event.target.value })
                  }
                  placeholder="Solde d’ouverture"
                  className="rounded-xl px-3 py-2 text-sm outline-none"
                  style={fieldStyle()}
                />
                <input
                  type="color"
                  value={accountDraft.color}
                  onChange={(event) => setAccountDraft({ ...accountDraft, color: event.target.value })}
                  className="h-10 w-full rounded-xl cursor-pointer bg-transparent"
                />
                <PrimaryButton onClick={saveAccount} disabled={saving}>
                  <CirclePlus size={16} /> Créer le compte
                </PrimaryButton>
              </FormCard>

              <FormCard title="Catégorie personnalisée">
                <div className="grid grid-cols-[56px_1fr] gap-2">
                  <EmojiPicker
                    value={categoryDraft.icon}
                    onChange={(icon) => setCategoryDraft({ ...categoryDraft, icon })}
                    aria-label="Icône catégorie"
                  />
                  <input
                    value={categoryDraft.name}
                    onChange={(event) =>
                      setCategoryDraft({ ...categoryDraft, name: event.target.value })
                    }
                    placeholder="Nom"
                    className="rounded-xl px-3 py-2 text-sm outline-none"
                    style={fieldStyle()}
                  />
                </div>
                <select
                  value={categoryDraft.kind}
                  onChange={(event) =>
                    setCategoryDraft({
                      ...categoryDraft,
                      kind: event.target.value as FinanceCategoryKind,
                    })
                  }
                  className="rounded-xl px-3 py-2 text-sm outline-none"
                  style={fieldStyle()}
                >
                  <option value="expense">Dépense</option>
                  <option value="income">Revenu</option>
                </select>
                <PrimaryButton onClick={saveCategory} disabled={saving}>
                  <CirclePlus size={16} /> Ajouter la catégorie
                </PrimaryButton>
              </FormCard>
            </div>

            <div className="space-y-4">
              <Panel title={`Comptes (${accounts.length})`}>
                {!accounts.length && <EmptyLine attente={loading} text="Aucun compte." />}
                {accounts.map((account) => (
                  <div
                    key={account.id}
                    className="flex items-center justify-between gap-3 py-2.5 border-b last:border-b-0"
                    style={{ borderColor: 'var(--color-border)' }}
                  >
                    <div className="flex items-center gap-3 min-w-0">
                      <span
                        className="size-9 rounded-xl flex items-center justify-center text-lg shrink-0"
                        style={{ background: account.color }}
                      >
                        {account.icon}
                      </span>
                      <div className="min-w-0">
                        <p className="text-sm font-medium truncate" style={{ color: 'var(--color-text)' }}>
                          {account.name}
                        </p>
                        <p className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
                          {ACCOUNT_TYPES.find((item) => item.id === account.type)?.label || account.type}
                        </p>
                      </div>
                    </div>
                    <div className="flex items-center gap-2">
                      <span className="text-sm tabular-nums font-medium" style={{ color: 'var(--color-text)' }}>
                        {formatCad(account.balance ?? account.openingBalance)}
                      </span>
                      <IconButton label="Supprimer" onClick={() => void removeAccount(account)}>
                        <Trash2 size={14} />
                      </IconButton>
                    </div>
                  </div>
                ))}
              </Panel>

              <Panel title="Catégories custom">
                {categories.filter((cat) => !cat.system).length === 0 && (
                  <EmptyLine attente={loading} text="Pas encore de catégorie personnalisée." />
                )}
                {categories
                  .filter((cat) => !cat.system)
                  .map((cat) => (
                    <div
                      key={cat.id}
                      className="flex items-center justify-between gap-3 py-2 border-b last:border-b-0"
                      style={{ borderColor: 'var(--color-border)' }}
                    >
                      <span className="text-sm" style={{ color: 'var(--color-text)' }}>
                        {cat.icon} {cat.name}
                        <span className="ml-2 text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
                          {cat.kind === 'income' ? 'revenu' : 'dépense'}
                        </span>
                      </span>
                      <IconButton label="Supprimer" onClick={() => void removeCategory(cat)}>
                        <Trash2 size={14} />
                      </IconButton>
                    </div>
                  ))}
              </Panel>
            </div>
          </section>
        )}

        {section === 'goals' && (
          <section className="grid gap-4 lg:grid-cols-[340px_1fr]">
            <FormCard title="Nouvel objectif" className={formSlotClass(formOpen)}>
              <div className="grid grid-cols-[56px_1fr] gap-2">
                <EmojiPicker
                  value={goalDraft.icon}
                  onChange={(icon) => setGoalDraft({ ...goalDraft, icon })}
                  aria-label="Icône objectif"
                />
                <input
                  value={goalDraft.name}
                  onChange={(event) => setGoalDraft({ ...goalDraft, name: event.target.value })}
                  placeholder="Nom (voyage, fonds…)"
                  className="rounded-xl px-3 py-2 text-sm outline-none"
                  style={fieldStyle()}
                />
              </div>
              <input
                type="number"
                min="0"
                step="0.01"
                value={goalDraft.target}
                onChange={(event) => setGoalDraft({ ...goalDraft, target: event.target.value })}
                placeholder="Cible ($)"
                className="rounded-xl px-3 py-2 text-sm outline-none"
                style={fieldStyle()}
              />
              <input
                type="number"
                min="0"
                step="0.01"
                value={goalDraft.current}
                onChange={(event) => setGoalDraft({ ...goalDraft, current: event.target.value })}
                placeholder="Déjà épargné ($)"
                className="rounded-xl px-3 py-2 text-sm outline-none"
                style={fieldStyle()}
              />
              <input
                type="date"
                value={goalDraft.deadline}
                onChange={(event) => setGoalDraft({ ...goalDraft, deadline: event.target.value })}
                className="rounded-xl px-3 py-2 text-sm outline-none"
                style={fieldStyle()}
              />
              <select
                value={goalDraft.accountId}
                onChange={(event) => setGoalDraft({ ...goalDraft, accountId: event.target.value })}
                className="rounded-xl px-3 py-2 text-sm outline-none"
                style={fieldStyle()}
              >
                <option value="">Compte lié (optionnel)</option>
                {accounts.map((account) => (
                  <option key={account.id} value={account.id}>
                    {account.icon} {account.name}
                  </option>
                ))}
              </select>
              <input
                type="color"
                value={goalDraft.color}
                onChange={(event) => setGoalDraft({ ...goalDraft, color: event.target.value })}
                className="h-10 w-full rounded-xl cursor-pointer bg-transparent"
              />
              <PrimaryButton onClick={saveGoal} disabled={saving}>
                <CirclePlus size={16} /> Créer
              </PrimaryButton>
            </FormCard>

            <Panel title={`Objectifs (${goals.length})`}>
              {!goals.length && <EmptyLine attente={loading} text="Aucun objectif d’épargne." />}
              {goals.map((goal) => {
                const pct = goal.target > 0 ? Math.min(100, (goal.current / goal.target) * 100) : 0;
                return (
                  <div
                    key={goal.id}
                    className="py-3 border-b last:border-b-0"
                    style={{ borderColor: 'var(--color-border)' }}
                  >
                    <div className="flex items-start justify-between gap-3 mb-2">
                      <div className="min-w-0">
                        <p className="text-sm font-medium truncate" style={{ color: 'var(--color-text)' }}>
                          {goal.icon} {goal.name}
                        </p>
                        <p className="text-xs mt-0.5" style={{ color: 'var(--color-text-tertiary)' }}>
                          {formatCad(goal.current)} / {formatCad(goal.target)}
                          {goal.deadline ? ` · échéance ${goal.deadline}` : ''}
                        </p>
                      </div>
                      <IconButton label="Supprimer" onClick={() => void removeGoal(goal)}>
                        <Trash2 size={14} />
                      </IconButton>
                    </div>
                    <div
                      className="h-2 rounded-full overflow-hidden mb-2"
                      style={{ background: 'var(--color-bg-secondary)' }}
                    >
                      <div
                        className="h-full rounded-full"
                        style={{ width: `${pct}%`, background: goal.color || 'var(--color-accent)' }}
                      />
                    </div>
                    {goalEdit?.id === goal.id ? (
                      <form
                        className="flex items-center gap-2"
                        onSubmit={(event) => {
                          event.preventDefault();
                          commitGoalEdit(goal);
                        }}
                      >
                        <input
                          type="number"
                          min="0"
                          step="0.01"
                          autoFocus
                          value={goalEdit.value}
                          onChange={(event) => setGoalEdit({ id: goal.id, value: event.target.value })}
                          onKeyDown={(event) => {
                            if (event.key === 'Escape') {
                              // Consommé : le mini-panneau ne se ferme qu'au second Échap (contrat du 17 sept. 2026, lib.rs lit `defaultPrevented`).
                              event.preventDefault();
                              setGoalEdit(null);
                            }
                          }}
                          aria-label={`Montant épargné pour ${goal.name} ($)`}
                          placeholder="Montant épargné ($)"
                          className="min-w-0 flex-1 rounded-lg px-2 py-1 text-xs outline-none"
                          style={fieldStyle()}
                        />
                        <button
                          type="submit"
                          aria-label="Valider le montant"
                          className="size-7 shrink-0 rounded-lg flex items-center justify-center cursor-pointer"
                          style={{ background: 'var(--color-accent)', color: '#fff' }}
                        >
                          <Check size={14} />
                        </button>
                        <IconButton label="Annuler" onClick={() => setGoalEdit(null)}>
                          <X size={14} />
                        </IconButton>
                      </form>
                    ) : (
                      <div className="flex flex-wrap gap-2">
                        <button
                          type="button"
                          className="px-2 py-1 rounded-lg text-xs cursor-pointer"
                          style={{
                            background: 'var(--color-bg-secondary)',
                            color: 'var(--color-text-secondary)',
                            border: '1px solid var(--color-border)',
                          }}
                          onClick={() => setGoalEdit({ id: goal.id, value: String(goal.current) })}
                        >
                          Ajuster
                        </button>
                        <button
                          type="button"
                          className="px-2 py-1 rounded-lg text-xs cursor-pointer"
                          style={{
                            background: 'var(--color-bg-secondary)',
                            color: 'var(--color-text-secondary)',
                            border: '1px solid var(--color-border)',
                          }}
                          onClick={() => {
                            const next = Math.round((goal.current + 50) * 100) / 100;
                            void runSave(async () => {
                              await updateFinanceGoal(goal.id, { current: next });
                            }, '+50 $ ajoutés');
                          }}
                        >
                          +50 $
                        </button>
                      </div>
                    )}
                  </div>
                );
              })}
            </Panel>
          </section>
        )}

        {section === 'import' && (
          <section className="grid gap-4 lg:grid-cols-[1fr_320px]">
            <FormCard title="Importer un relevé CSV">
              <p className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
                Colonnes attendues : date, amount, description (ou payee), type, category, notes.
                Formats de date : AAAA-MM-JJ ou JJ/MM/AAAA.
              </p>
              <select
                value={csvAccountId}
                onChange={(event) => setCsvAccountId(event.target.value)}
                className="rounded-xl px-3 py-2 text-sm outline-none"
                style={fieldStyle()}
              >
                <option value="">Compte cible</option>
                {accounts.map((account) => (
                  <option key={account.id} value={account.id}>
                    {account.icon} {account.name}
                  </option>
                ))}
              </select>
              <textarea
                value={csvText}
                onChange={(event) => setCsvText(event.target.value)}
                rows={12}
                placeholder={'date,amount,description\n2026-08-01,-42.50,Épicerie'}
                className="rounded-xl px-3 py-2 text-sm outline-none font-mono resize-y"
                style={fieldStyle()}
              />
              <PrimaryButton onClick={runCsvImport} disabled={saving}>
                <Upload size={16} /> Importer
              </PrimaryButton>
            </FormCard>
            {/* Purement documentaire : sous sm il précédait le bouton
                « Importer » de trois paragraphes. */}
            <Panel title="Conseils" className="hidden sm:block">
              <ul className="text-sm space-y-2" style={{ color: 'var(--color-text-secondary)' }}>
                <li>Les doublons (même date + montant + libellé) sont ignorés.</li>
                <li>Un montant négatif est traité comme une dépense si le type est absent.</li>
                <li>Les catégories sont reliées par nom exact (insensible à la casse).</li>
              </ul>
            </Panel>
          </section>
        )}
      </main>
    </div>
  );
}

function KpiCard({
  icon,
  label,
  value,
  hint,
  tone,
  secondary = false,
}: {
  icon: ReactNode;
  label: string;
  value: string;
  hint?: string;
  tone?: 'success' | 'error';
  /** Carte absente sous `sm` : le panneau n'a pas la place d'un chiffre redondant. */
  secondary?: boolean;
}) {
  const valueColor =
    tone === 'success'
      ? 'var(--color-success)'
      : tone === 'error'
        ? 'var(--color-error)'
        : 'var(--color-text)';
  return (
    <CadreVitre
      className={`rounded-2xl px-3 py-2.5 sm:px-4 sm:py-3 min-w-0 ${secondary ? 'hidden sm:block' : ''}`}
      style={surfaceStyle()}
    >
      <div className="flex items-center gap-2 mb-1">
        <span className="text-base" aria-hidden style={{ color: 'var(--color-accent)' }}>
          {icon}
        </span>
        <span className="text-xs truncate" style={{ color: 'var(--color-text-tertiary)' }}>
          {label}
        </span>
      </div>
      <p className="text-base sm:text-lg font-semibold tabular-nums truncate" style={{ color: valueColor }}>
        {value}
      </p>
      {hint ? (
        <p className="hidden sm:block text-[11px] mt-1" style={{ color: 'var(--color-text-tertiary)' }}>
          {hint}
        </p>
      ) : null}
    </CadreVitre>
  );
}

function Panel({
  title,
  children,
  className = '',
}: {
  title: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <CadreVitre className={`rounded-2xl p-3 sm:p-4 min-w-0 ${className}`} style={surfaceStyle()}>
      <h3 className="text-sm font-medium mb-3" style={{ color: 'var(--color-text-secondary)' }}>
        {title}
      </h3>
      {children}
    </CadreVitre>
  );
}

function FormCard({
  title,
  children,
  className = '',
}: {
  title: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <CadreVitre
      className={`rounded-2xl p-3 sm:p-4 grid gap-3 h-fit min-w-0 ${className}`}
      style={surfaceStyle({ borderColor: 'var(--color-accent)' })}
    >
      <h3 className="text-sm font-medium" style={{ color: 'var(--color-text)' }}>
        {title}
      </h3>
      {children}
    </CadreVitre>
  );
}

/**
 * `attente` : le premier chargement sans cache est en cours — « Aucune
 * transaction sur cette période » s'affichait AVANT la première réponse,
 * et se lisait comme un fait (18 sept. 2026, §100).
 */
function EmptyLine({ text, attente = false }: { text: string; attente?: boolean }) {
  if (attente) return null;
  return (
    <p className="text-sm py-2" style={{ color: 'var(--color-text-tertiary)' }}>
      {text}
    </p>
  );
}

function PrimaryButton({
  children,
  onClick,
  disabled,
}: {
  children: ReactNode;
  onClick: () => void;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className="flex items-center justify-center gap-2 px-3 py-2.5 rounded-xl text-sm font-medium cursor-pointer disabled:opacity-60"
      style={{ background: 'var(--color-accent)', color: '#fff' }}
    >
      {children}
    </button>
  );
}

function IconButton({
  children,
  onClick,
  label,
}: {
  children: ReactNode;
  onClick: () => void;
  label: string;
}) {
  return (
    <button
      type="button"
      aria-label={label}
      onClick={onClick}
      className="size-8 rounded-lg flex items-center justify-center cursor-pointer"
      style={{
        color: 'var(--color-text-tertiary)',
        background: 'var(--color-bg-secondary)',
        border: '1px solid var(--color-border)',
      }}
    >
      {children}
    </button>
  );
}
