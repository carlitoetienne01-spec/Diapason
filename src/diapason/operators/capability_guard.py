"""What an operator may be asked to do — checked before it is scheduled.

``OperatorManifest.required_capabilities`` has been loaded from TOML since the
field was written and read by nobody: two producers (``operators/loader.py``
and ``recipes/composer.py``), zero consumers. A declaration nobody checks is
what spec §5 forbids — and here it is worse than idle, because an operator
installed by a third party is scheduled to run unattended, on a tick, with
whatever tools it names.

**Why the check lives at activation, and not where it looks like it should.**

- Not at load: ``OperatorManager.discover()`` swallows exceptions, so a refused
  manifest would vanish from ``operators list`` without a word. You must be
  able to *see* an operator you are not allowed to run.
- Not at tick: the manager is not on that path. ``TaskScheduler._execute_task``
  re-reads the task from the store and never consults the manifest — and it
  records ``success = True`` even when every tool call was denied, so the
  refusal would land in a log that says it worked.
- At activation: it is the one bottleneck both doors share
  (``cli/operators_cmd.py`` and ``cli/compose_cmd.py``), and it is the only
  moment where a refusal can honestly say *nothing has been scheduled*.

**Why the policy is the last of three checks, not the only one.**

The roadmap said "connect to the existing RBAC ``CapabilityPolicy``". Taken
literally that refuses every operator on a default install: with no policy
file, ``CapabilityPolicy(default_deny=True).check("operative", ...)`` is
``False``, because the grants an operator really runs under are the ones
``ToolExecutor`` gives *itself* at construction — which has not happened yet
at activation time. Measured, not assumed.

So the policy is consulted only when an administrator actually supplied one.
The two checks that work on every install are the ones above it: the
vocabulary, and consistency with the tools the manifest names.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Iterable, Optional

if TYPE_CHECKING:  # pragma: no cover - typing only
    from diapason.operators.types import OperatorManifest


@dataclass(frozen=True, slots=True)
class CapabilityVerdict:
    """Why an operator was refused — or that it was not.

    Three separate lists rather than one message: the caller formats them for
    a human, and each kind of fault has a different remedy.
    """

    unknown_verbs: tuple[str, ...] = ()
    """Declared verbs that are not operator capabilities at all."""

    undeclared: tuple[tuple[str, str], ...] = field(default_factory=tuple)
    """``(tool, capability)`` the manifest uses without declaring."""

    denied: tuple[str, ...] = ()
    """Declared verbs an administrator's policy refuses to ``operative``."""

    implied: tuple[str, ...] = ()
    """What the named tools require, declared or not — always computed."""

    policy_consulted: bool = False
    """False when no policy file exists, so the caller can say so."""

    silently_implied: tuple[tuple[str, str], ...] = field(default_factory=tuple)
    """``(tool, capability)`` a silent manifest uses without declaring anything.

    Not a refusal — an empty field is still "no requirement". But without
    this, declaring nothing was the way to be checked by nothing, and the
    guard rewarded exactly the silence it exists to end. Naming what a silent
    manifest will actually be able to do is the least it can do.
    """

    @property
    def ok(self) -> bool:
        return not (self.unknown_verbs or self.undeclared or self.denied)


def known_capabilities() -> tuple[str, ...]:
    """The operator vocabulary: exactly the tool one, and no other."""
    from diapason.security.capabilities import Capability

    return tuple(c.value for c in Capability)


def capabilities_of_tool(name: str) -> tuple[str, ...]:
    """What one tool really requires — declared *and* implied.

    Reads through ``ToolExecutor._required_capabilities`` rather than
    ``spec.required_capabilities`` alone, because several built-ins declare
    nothing in their own spec and get their capability from
    ``DEFAULT_TOOL_CAPABILITIES``: ``memory_store`` is the trap — read its
    spec and you conclude it requires nothing at all.

    A tool that cannot be instantiated (an optional dependency is missing on
    this machine) falls back to that same default table. Refusing to activate
    because a tool could not be *imported* would punish the wrong thing.
    """
    from diapason.security.capabilities import DEFAULT_TOOL_CAPABILITIES

    try:
        from diapason.core.registry import ToolRegistry
        from diapason.tools._stubs import ToolExecutor

        tool = ToolRegistry.create(name)
        return tuple(ToolExecutor._required_capabilities(tool))
    except Exception:  # noqa: BLE001 - an absent tool is not a refusal
        return tuple(
            getattr(c, "value", c) for c in DEFAULT_TOOL_CAPABILITIES.get(name, [])
        )


def implied_capabilities(tools: Iterable[str]) -> dict[str, tuple[str, ...]]:
    """Map each named tool to the capabilities it really requires."""
    return {name: capabilities_of_tool(name) for name in tools if name}


def check_manifest(
    manifest: "OperatorManifest",
    *,
    policy: Optional[Any] = None,
) -> CapabilityVerdict:
    """Decide whether *manifest* may be scheduled.

    An empty ``required_capabilities`` means "no requirement", not "refuse" —
    the twelve bundled operators and recipes declare nothing, so fail-closed
    would refuse all of them on day one. Making them declare is a decision
    that belongs to whoever maintains them, not to this function.

    The earlier version of this docstring justified that leniency by claiming
    "the real authorisation is not lost — ``ToolExecutor`` still filters every
    single tool call and fails closed without a policy". **That is false, and
    it was measured on 26 August 2026.** Without a policy file,
    ``ToolExecutor._grant_selected_tools_when_unmanaged`` grants each selected
    tool exactly the capabilities it declares, scoped to its own name — so a
    tool is authorised by having been selected. And a tool that declares *no*
    capability is filtered by nothing at all, anywhere. Invoking a protection
    that does not exist to excuse the absence of another is precisely the
    defect this guard was written to close.

    So the leniency stands, but it is now named for what it is: a silent
    manifest is not verified, and ``silently_implied`` says so out loud rather
    than letting the caller believe a check happened.

    Fail-closed *does* apply to the vocabulary. ``mesh/capabilities.py`` drops
    an unknown verb silently, and that tolerance is right there — a client can
    be newer than the server. It is wrong here: the manifest and the policy
    ship in the same package, so an unknown verb is a typo, and ignoring it
    would rebuild the very defect this guard exists to close.
    """
    declared = [str(c).strip() for c in (manifest.required_capabilities or []) if c]
    vocabulary = set(known_capabilities())
    unknown = tuple(c for c in declared if c not in vocabulary)

    par_outil = implied_capabilities(manifest.tools or [])
    implied = tuple(sorted({c for caps in par_outil.values() for c in caps}))

    # Only meaningful when the manifest declares something: an empty field is
    # "no requirement", and comparing it to the tools would refuse everything.
    undeclared: tuple[tuple[str, str], ...] = ()
    silently_implied: tuple[tuple[str, str], ...] = ()
    manquantes = tuple(
        (outil, cap)
        for outil, caps in sorted(par_outil.items())
        for cap in caps
        if cap not in declared
    )
    if declared:
        undeclared = manquantes
    else:
        # Le même calcul, mais il ne refuse pas : il NOMME. Déclarer un champ
        # vide restait le moyen de n'être contrôlé par rien.
        silently_implied = manquantes

    denied: tuple[str, ...] = ()
    consulted = policy is not None and bool(
        getattr(policy, "has_explicit_policy", False)
    )
    if consulted and declared:
        denied = tuple(c for c in declared if not policy.check("operative", c, ""))

    return CapabilityVerdict(
        unknown_verbs=unknown,
        undeclared=undeclared,
        denied=denied,
        implied=implied,
        policy_consulted=consulted,
        silently_implied=silently_implied,
    )


def explain(operator_id: str, verdict: CapabilityVerdict) -> str:
    """Say what is wrong, what to change, and that nothing was scheduled.

    "Nothing has been scheduled" is not politeness. It is the whole
    difference between refusing at activation and refusing at tick: without
    it, the user has no way to tell whether a half-installed operator is
    about to wake up in five minutes.
    """
    lignes = [f"Operator '{operator_id}' refused."]

    for verbe in verdict.unknown_verbs:
        lignes.append(
            f"  '{verbe}' is not an operator capability. The vocabulary is the "
            f"tool one: {', '.join(known_capabilities())}."
        )
        if "." in verbe:
            lignes.append(
                "  (Verbs with a dot belong to the device mesh — app.navigate, "
                "tasks.read — and are not checked here.)"
            )
        elif verbe.startswith(("filesystem:", "shell:", "network:listen")):
            lignes.append(
                "  (That one belongs to skills, which use a different "
                "vocabulary from tools.)"
            )

    for outil, capacite in verdict.undeclared:
        lignes.append(
            f"  it uses the tool '{outil}', which requires '{capacite}', but the "
            f"manifest does not declare it. Add '{capacite}' to "
            "required_capabilities, or drop the tool."
        )

    for capacite in verdict.denied:
        lignes.append(
            f"  '{capacite}' is not granted to the 'operative' agent by your "
            "capability policy. The operator stays installed and visible."
        )

    lignes.append("  Nothing has been scheduled; it will not run.")
    return "\n".join(lignes)


def avertissement(operator_id: str, verdict: CapabilityVerdict) -> Optional[str]:
    """Ce qu'un manifeste silencieux pourra faire — ou None s'il n'y a rien.

    Un verdict qui passe n'est pas un verdict qui a vérifié. Un manifeste qui
    ne déclare rien traverse `check_manifest` sans qu'aucune cohérence soit
    contrôlée, et déclarer un champ vide était donc le moyen de n'être
    contrôlé par rien.

    Refuser serait l'autre réponse, et elle reste ouverte : elle suppose de
    renseigner les douze manifestes livrés, ce qui appartient à qui les
    maintient. En attendant, nommer vaut mieux que taire — et surtout mieux
    que d'écrire dans un champ que personne ne lit, ce que ce garde a
    précisément été écrit pour corriger.
    """
    if not verdict.silently_implied:
        return None
    par_outil: dict[str, list[str]] = {}
    for outil, capacite in verdict.silently_implied:
        par_outil.setdefault(outil, []).append(capacite)
    lignes = [
        f"Operator '{operator_id}' declares no required_capabilities, so "
        "nothing was verified against its tools. It will be able to:",
    ]
    for outil, capacites in sorted(par_outil.items()):
        lignes.append(f"  {outil} → {', '.join(sorted(capacites))}")
    lignes.append("  Declare them in required_capabilities to have this checked.")
    return "\n".join(lignes)


class OperatorRefused(RuntimeError):
    """An operator was refused before anything was scheduled.

    The full explanation is the exception's message, so that both activation
    doors — ``operators activate`` and ``compose deploy``, which each print
    ``Error: {exc}`` — say the useful thing without either of them knowing
    anything about capabilities.
    """

    def __init__(self, operator_id: str, verdict: CapabilityVerdict) -> None:
        self.operator_id = operator_id
        self.verdict = verdict
        super().__init__(explain(operator_id, verdict))


__all__ = [
    "CapabilityVerdict",
    "OperatorRefused",
    "capabilities_of_tool",
    "explain",
    "check_manifest",
    "implied_capabilities",
    "known_capabilities",
]
