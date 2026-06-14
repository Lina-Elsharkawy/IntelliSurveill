import { VadEvent, VadStatus } from "@/services/vad_api";
import { EventFilters } from "@/components/vad/EventToolbar";

export function getEventScoreRatio(event: VadEvent): number {
  return event.threshold_value > 0 ? event.peak_score / event.threshold_value : 0;
}

export function isStreamOffline(status: VadStatus | null): boolean {
  return Boolean(status?.running && (!status?.actual_sample_fps || status.actual_sample_fps === 0));
}

export function filterAndSortVadEvents(events: VadEvent[], filters: EventFilters): VadEvent[] {
  return events
    .filter(event => filters.gate === "all" || event.gate_name === filters.gate)
    .sort((a, b) => {
      if (filters.sortBy === "newest") {
        return new Date(b.start_ts).getTime() - new Date(a.start_ts).getTime();
      }
      if (filters.sortBy === "highest_score") {
        return b.peak_score - a.peak_score;
      }
      if (filters.sortBy === "highest_ratio") {
        return getEventScoreRatio(b) - getEventScoreRatio(a);
      }
      return 0;
    });
}
