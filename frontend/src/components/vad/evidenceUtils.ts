const IMAGE_EXT_RE = /\.(jpg|jpeg|png|webp)$/i;
const FRAME_KEY_RE = /(?:^|\/)frames\/frame_(\d+)\.(jpg|jpeg|png|webp)$/i;

export function isImageKey(key: string): boolean {
  return IMAGE_EXT_RE.test(key || "");
}

export function isTubeletFrameKey(key: string): boolean {
  return FRAME_KEY_RE.test(key || "");
}

export function isMetadataKey(key: string): boolean {
  const lower = (key || "").toLowerCase().replace(/^\/+/, "");
  return lower === "event_metadata.json" || lower.endsWith("/event_metadata.json");
}

export function frameIndexFromKey(key: string): number {
  const match = FRAME_KEY_RE.exec(key || "");
  return match ? Number.parseInt(match[1], 10) : Number.MAX_SAFE_INTEGER;
}

export function sortFrameKeys(keys: string[]): string[] {
  return [...keys].sort((a, b) => frameIndexFromKey(a) - frameIndexFromKey(b));
}

export function getEvidenceDisplayName(key: string): string {
  return (key || "").split("/").pop() || key;
}

export function groupEvidenceKeys(keys: string[]) {
  const annotatedKey = keys.find(k => k.includes("annotated_frame"));
  const montageKey = keys.find(k => k.includes("tubelet_montage"));
  const frameKeys = sortFrameKeys(keys.filter(k => isTubeletFrameKey(k)));
  const known = new Set([annotatedKey, montageKey, ...frameKeys].filter(Boolean) as string[]);
  const otherKeys = keys.filter(k => !known.has(k));
  return { annotatedKey, montageKey, frameKeys, otherKeys };
}
