import type { Evidence } from "../types";

/** Keep the two most direct, distinct source ranges supplied for a finding. */
export function keyEvidence(ids: string[], evidence: Evidence[], limit = 2) {
  const lookup = new Map(evidence.map((item) => [item.id, item]));
  const chosen: Evidence[] = [];
  for (const id of ids) {
    const candidate = lookup.get(id);
    if (!candidate || candidate.source_end_s <= candidate.source_start_s)
      continue;
    const duplicate = chosen.some((item) => {
      if (item.asset_id !== candidate.asset_id) return false;
      if (
        item.id === candidate.id ||
        (item.shot_id && item.shot_id === candidate.shot_id)
      )
        return true;
      const overlap = Math.max(
        0,
        Math.min(item.source_end_s, candidate.source_end_s) -
          Math.max(item.source_start_s, candidate.source_start_s),
      );
      const shorter = Math.min(
        item.source_end_s - item.source_start_s,
        candidate.source_end_s - candidate.source_start_s,
      );
      return overlap / shorter >= 0.5;
    });
    if (!duplicate) chosen.push(candidate);
    if (chosen.length >= limit) break;
  }
  return chosen;
}

export const preciseTime = (seconds: number) => {
  const tenths = Math.round(Math.max(0, seconds) * 10);
  return `${Math.floor(tenths / 600)
    .toString()
    .padStart(
      2,
      "0",
    )}:${(Math.floor(tenths / 10) % 60).toString().padStart(2, "0")}.${tenths % 10}`;
};
