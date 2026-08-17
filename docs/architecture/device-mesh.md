# Device Mesh

The Device Mesh lets a user's own devices act on each other's behalf: *« ouvre mes tâches sur mon PC »* typed on a laptop opens a screen on the desktop, and a reminder created on a Mac appears on a phone.

It is a **fleet of one owner**. There is no server, no account, and no notion of sharing between people. Every device holds the same private data and the same authority; the mesh only carries intent between them.

---

## Trust model

A device is in the fleet or it is not. There is no partial membership.

| Concept | Meaning |
|---|---|
| **Owner id** | Names the fleet. Minted once, propagated by pairing. A command carrying a different owner id is refused without further examination. |
| **Device id** | `sha256(public_key)[:24]`, prefixed `dev_`. Derived, never asserted — a device cannot choose its own name in the protocol sense. |
| **Trust level** | `TRUSTED` after redeeming an invitation; `REVOKED` after the user removes it. Revocation is terminal: the only way back is to forget the device entirely and pair it again. |
| **Capabilities** | What the device may be asked to do. Always the **intersection** of what it declares and what its platform ceiling allows (`capabilities.py`), never the union. |

Pairing is mutual and short-lived. The host mints a single-use invitation (10 minutes); the joining device redeems it with its public key, and receives the host's identity and address in the same response. Both sides now hold each other's public key, which is the only credential the mesh ever uses afterwards.

### The platform ceiling

`PLATFORM_CAPABILITIES` in `capabilities.py` is the answer to "what could this class of device honour even in principle". iOS and iPadOS exclude arbitrary automation and filesystem writes; `WEB` is client-only; an unrecognised platform falls to a read-only floor.

This is enforced at every point a device could try to widen its own grant — pairing, an explicit declaration, a presence beacon, a poll — because a check that exists at only one of those is a check that will eventually be bypassed by the others.

---

## What can be commanded

The remote catalogue is closed and small (`tools.py`):

| Tool | Effect | Offline policy |
|---|---|---|
| `app.navigate` | Open a screen named by a `success://` route | `REQUIRE_ONLINE` |
| `app.show_resource` | Show one task, project, note or habit | `QUEUE_UNTIL_EXPIRATION` |
| `app.open` | Bring the app to the front | `REQUIRE_ONLINE` |
| `notifications.show` | Display a notification | `QUEUE_UNTIL_EXPIRATION` |

Each tool declares typed parameters, and a structural guard refuses any tool whose parameters include a passthrough name — `command`, `path`, `url`, `sql`, `script`, `eval` and the rest:

```python
FORBIDDEN_PARAMETER_NAMES = frozenset({
    "action", "command", "method", "code", "script",
    "sql", "query", "exec", "eval", "path", "url", "shell",
})
```

The point is not that today's four tools are safe. It is that the *next* tool cannot quietly be a shell wearing a costume.

---

## The command envelope

Every command is an Ed25519-signed envelope. `verify_command()` runs eleven checks in a deliberate order:

1. protocol version
2. owner — same fleet
3. destination — addressed to us
4. origin — a device we know, trust, and hold a key for
5. expiry, with bounded clock tolerance in both directions
6. signature, over the envelope minus itself
7. the tool exists in the catalogue
8. arguments match the tool's declared shape
9. capabilities — what *this* device can honour
10. confirmation — an impactful tool may not run unconfirmed
11. **nonce spent, last**

The order carries meaning. Cheap structural checks come first so a misaddressed command never reaches the cryptography. The nonce is spent **last** so a command rejected for any other reason does not burn a nonce the legitimate sender still needs.

`NonceStore.spend()` uses a `PRIMARY KEY` insert as its atomic test — two racing deliveries of the same command cannot both succeed, because only one insert can win.

---

## Two transports

The mesh has to reach two very different kinds of device, and one shape does not fit both.

### Push — computers

A machine with a reachable address is dialled directly: the sender POSTs the signed envelope to `POST /v1/mesh/commands/deliver`. Lowest latency, and the sender learns the outcome in the same round trip.

The address is learned from the device itself and is a promise: `local_address()` reports where the process is *actually* listening, never a guess from configuration. A server bound to loopback advertises loopback, even though a LAN address would look more useful — peers off that machine genuinely cannot reach it, and telling them otherwise sends commands into the void and has them reported as delivered.

### Pull — phones and tablets

Succès Flutter runs on devices that cannot be dialled: no stable address, a carrier NAT in the way, and an operating system that suspends the app whenever the user looks away. The direction flips. The device asks:

```
POST /v1/mesh/commands/poll   → { commands: [...signed envelopes...] }
POST /v1/mesh/commands/ack    → what it did with them
```

Two consequences fall out of this rather than being designed in:

- **The poll is the heartbeat.** A device asking for its commands has proved it is awake more convincingly than any beacon could, so the same request records presence.
- **A queued command is not a failed one.** A phone polling every few seconds collects within seconds, so `« elle n'a pas été effectuée »` would be a lie.

A device is treated as pull-mode when it has *told us so* by polling (`transport == "pull"`), never inferred from the absence of an address — a desktop that has simply not announced yet also has no address and will never come to fetch.

---

## Presence

Presence is **derived, never stored as a state**. `presence_of()` reads the last-seen timestamp and returns one of four states:

| State | Age of last contact |
|---|---|
| `ONLINE` | ≤ 45 s |
| `IDLE` | ≤ 5 min |
| `BACKGROUND` | ≤ 30 min |
| `OFFLINE` | beyond, or revoked |

A revoked device is `OFFLINE` regardless of how recently it was seen.

Devices announce themselves with the same credential they use to command — an Ed25519 signature — because a joining device never holds this machine's API key. Replay is stopped by **monotonicity** rather than nonces: a beacon must be strictly newer than the last accepted one. A heartbeat every fifteen seconds would mint 5 760 nonces per device per day to protect a message whose entire content is "still here"; one integer per device refuses the same attack for nothing.

---

## The honesty contract

The rule the whole system exists to keep:

> A command that was merely queued must never be reported as done.

Every terminal status carries a French sentence true of that status and no other, and `dispatch.py` is deliberately the only place that decides what the user is told.

| Situation | What the user reads |
|---|---|
| Delivered and executed | *« C'est fait. »* |
| Device asleep, tool needs it awake | *« … est hors ligne : cette action demande un appareil actif, elle n'a pas été effectuée. »* |
| Device awake but unreachable on the network | *« … n'a pas pu être joint : … »* |
| Device asleep, tool can wait | *« … est hors ligne : la commande est en attente et partira dès son retour. »* |
| Polling device, awake | *« C'est prêt pour … : l'appareil le récupérera dans quelques secondes. »* |
| Polling device, asleep | *« … : l'appareil le récupérera à son réveil. »* |

The distinctions are not decoration. "Offline" and "unreachable" call for different things from the user — waiting versus checking the network — and being told the wrong one wastes their time on the wrong machine.

---

## Security boundary

### Routes outside the API key wall

Five routes are reachable without the local API key, because the device calling them has never had it:

| Route | Credential |
|---|---|
| `POST /v1/mesh/pairings/redeem` | the one-time invitation |
| `POST /v1/mesh/commands/deliver` | Ed25519 signature over the envelope |
| `POST /v1/mesh/presence` | Ed25519 signature over the beacon |
| `POST /v1/mesh/commands/poll` | Ed25519 signature over the poll |
| `POST /v1/mesh/commands/ack` | Ed25519 signature over the results |

A signature proves more than a shared secret would: it says *which* device, and it binds the exact contents. The seven checks common to the last four live in one place (`signed.py`) so there is exactly one copy to get right.

### The local-only exemption

Diapason's `local_only` mode is fail-closed: nothing leaves the machine. The mesh holds one documented exemption, and both halves are required:

```python
if (device or {}).get("trustLevel") != "TRUSTED":
    raise LocalOnlyError(...)
if not address_is_private(address):
    raise LocalOnlyError(...)
```

A paired, trusted device at a private address is the user's own other computer, not "elsewhere". Anything failing either half is refused exactly as before. `mesh/transport.py` and `mesh/beacon.py` are listed in `tests/privacy/outbound_manifest.txt`, and the ratchet test fails in both directions if that stops being true.

### What the assistant can do

The LLM sees two tools, split deliberately: `mesh_devices` only looks, `mesh_send` acts. The model can answer *« quels appareils sont allumés ? »* without ever entering the code path that sends something.

`mesh_send` declares `risk: "outward_action"`. It is **not** in the live-voice allow-list (`speech/realtime/tools.py`), because that path runs its tools directly rather than through `ToolExecutor`, where the approval system lives. A tripwire test enforces this and says when to delete itself.

---

## Known limits

- **The server binds `127.0.0.1` by default**, so the mesh does not yet cross machines without the user opening the network interface. That is a security decision that belongs to them.
- **`execute_voice_tool` bypasses `ToolExecutor`**, and therefore approvals. This must be fixed before any `remote.*` tool is exposed to the voice path.
- **The inbox queue is in-process memory**, capped at 16 entries. A backend restart loses whatever was waiting for the desktop shell to collect.

---

## Files

| Module | Responsibility |
|---|---|
| `identity.py` | keys, device id, canonical bytes, envelope signing |
| `registry.py` | paired devices, invitations, trust, revocation |
| `capabilities.py` | the platform ceiling |
| `presence.py` | derived presence |
| `commands.py` | the envelope, its eleven checks, nonces |
| `tools.py` | the closed remote catalogue |
| `queue.py` | durable command queue |
| `transport.py` | LAN delivery and the local-only exemption |
| `beacon.py` | outgoing and incoming presence |
| `pull.py` | poll and acknowledgement, for devices that fetch |
| `signed.py` | the seven checks shared by device-signed requests |
| `dispatch.py` | sending, and what the user is told |
| `executor.py` | running a verified command here |
| `resolver.py` | *« sur mon PC »* → a device id, or a question |
| `routes.py` | the HTTP surface |
