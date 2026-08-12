/** The ONE list of cloud-model id prefixes.
 *
 * Three hand-maintained copies had already drifted apart (api.ts was
 * missing 'MiniMax-' and 'chatgpt-', so those models were treated as
 * local Ollama models and preloaded into a POST that could only fail).
 */
export const CLOUD_MODEL_PREFIXES = [
  'gpt-',
  'o1-',
  'o3-',
  'o4-',
  'claude-',
  'gemini-',
  'openrouter/',
  'MiniMax-',
  'chatgpt-',
] as const;

export function isCloudModel(id: string): boolean {
  return CLOUD_MODEL_PREFIXES.some((p) => id.startsWith(p));
}
