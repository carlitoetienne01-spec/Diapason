import type { MessageKey } from './translate';

/**
 * Server errors, translated on the way to the screen.
 *
 * The API answers in English — it is a machine interface, and changing that
 * would break every other client. But an English sentence surfacing inside a
 * French interface reads as a bug, so the known ones are mapped here.
 *
 * The mapping is exact and small on purpose. Guessing with a fuzzy match would
 * eventually mistranslate a message that merely resembles a known one, and a
 * wrong explanation of a failure is worse than an untranslated one — hence the
 * fallback returns the server's own words rather than anything invented.
 */
const KNOWN: Record<string, MessageKey> = {
  'Action not found': 'server.actionNotFound',
  'Agent is already running': 'server.agentAlreadyRunning',
  'Agent is archived': 'server.agentArchived',
  'Agent not found': 'server.agentNotFound',
  'Agent tools not available': 'server.agentToolsUnavailable',
  'Audio not available': 'server.audioUnavailable',
  'Channel bridge not configured': 'server.channelNotConfigured',
  'Content is empty': 'server.contentEmpty',
  'Engine not available for streaming': 'server.engineNoStreaming',
  'Engine unhealthy': 'server.engineUnhealthy',
  'Failed to send message': 'server.sendFailed',
  'Invalid SendBlue credentials': 'server.invalidCredentials',
  'Memory is not configured': 'server.memoryNotConfigured',
  'Model pulling is only supported with the Ollama engine':
    'server.pullNeedsOllama',
  'No digest for today': 'server.noDigest',
  'No trace database': 'server.noTraceDatabase',
  'Only supported with Ollama engine': 'server.onlyOllama',
  'Path is outside the allowed workspace directories.': 'server.pathOutside',
  'Refusing to index a sensitive file.': 'server.sensitiveFile',
  'Session not found': 'server.sessionNotFound',
  'Speech backend not configured': 'server.speechNotConfigured',
  'Task not found': 'server.taskNotFound',
  'Trace not found': 'server.traceNotFound',
};

/** The catalogue key for a server message, or null when it is unknown. */
export function serverMessageKey(message: string): MessageKey | null {
  return KNOWN[message.trim()] ?? null;
}

/**
 * Translate a server message if it is one we know, otherwise hand back exactly
 * what the server said.
 */
export function translateServerMessage(
  message: string,
  t: (key: MessageKey) => string,
): string {
  const key = serverMessageKey(message);
  return key ? t(key) : message;
}
